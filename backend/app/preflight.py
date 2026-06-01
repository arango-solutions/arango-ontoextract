"""First-run / deploy preflight checks (``make doctor`` / ``python -m app.preflight``).

Every blocker a fresh install hits in practice is a *configuration* problem,
not a code bug: an unreachable ArangoDB, a missing/typo'd API key, a deprecated
or inaccessible LLM model, no billing on the provider account. CI never catches
these (they're environment-specific), and at runtime they surface deep in the
extraction pipeline -- often masked (a provider HTTP 404 showed up only as
"extractor parse error ... Pass N failed after 5 retries").

This module validates that environment up front and prints an actionable
report, so the operator sees ``[FAIL] Extraction LLM -- model 'X' not available
to this key`` at the door instead of a silent empty ontology an hour later.

Usage::

    python -m app.preflight              # full check, incl. tiny live LLM calls
    python -m app.preflight --offline    # skip all network/API calls
    python -m app.preflight --json       # machine-readable output

Exit code is non-zero iff any check FAILs (WARN / SKIP do not fail the run), so
it composes into CI and container entrypoints.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from app.config import settings

# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------


class CheckStatus(StrEnum):
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"
    SKIP = "skip"


@dataclass
class CheckResult:
    name: str
    status: CheckStatus
    detail: str
    hint: str = ""


# ASCII markers (no color codes -- safe for CI logs, file redirects, k8s).
_MARKER = {
    CheckStatus.OK: "[ OK ]",
    CheckStatus.WARN: "[WARN]",
    CheckStatus.FAIL: "[FAIL]",
    CheckStatus.SKIP: "[SKIP]",
}


# ---------------------------------------------------------------------------
# Provider-error -> actionable hint
# ---------------------------------------------------------------------------


def _provider_error_hint(exc: Exception, *, model: str, key_env: str) -> str:
    """Translate a provider SDK exception into a one-line fix instruction.

    Both the Anthropic and OpenAI SDK errors expose the HTTP status on
    ``status_code``; we branch on it to turn an opaque failure into a concrete
    next step (wrong key vs. no model access vs. no billing vs. rate limit).
    """
    status = getattr(exc, "status_code", None)
    message = str(exc).lower()
    if status == 404:
        return (
            f"Model '{model}' does not exist or this key has no access to it. "
            "Use a current model id, or switch providers "
            "(LLM_EXTRACTION_MODEL=gpt-4o with OPENAI_API_KEY)."
        )
    if status == 401:
        return f"{key_env} is invalid, mistyped, or revoked. Regenerate it and re-copy."
    if status == 403:
        return f"{key_env} is valid but lacks permission for model '{model}'."
    if status == 400:
        if "credit" in message or "billing" in message or "quota" in message:
            return "Account has no billing/credits. Add a payment method in the provider console."
        return f"Provider rejected the request for model '{model}': {exc}"
    if status == 429:
        return "Rate limited right now -- the key works; retry later or raise your tier."
    return f"Could not validate the key/model (network or provider error): {exc}"


# ---------------------------------------------------------------------------
# Low-level pings (isolated so tests can patch them without real I/O)
# ---------------------------------------------------------------------------


def _ping_arango() -> str:
    """Return the ArangoDB server version, raising on connectivity failure."""
    from app.db.client import get_db

    return str(get_db().version())


def _ping_redis(url: str) -> None:
    """Raise if Redis at ``url`` is unreachable."""
    import redis

    client: Any = redis.Redis.from_url(url, socket_connect_timeout=3, socket_timeout=3)
    try:
        client.ping()
    finally:
        with contextlib.suppress(Exception):
            client.close()


def _ping_anthropic(model: str, api_key: str) -> None:
    """Smallest possible Messages call -- raises the SDK error on failure."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key, timeout=15.0)
    client.messages.create(
        model=model,
        max_tokens=1,
        messages=[{"role": "user", "content": "ping"}],
    )


def _ping_openai_chat(model: str, api_key: str, base_url: str) -> None:
    """Smallest possible chat-completions call -- raises the SDK error on failure."""
    from openai import OpenAI

    kwargs: dict[str, object] = {"api_key": api_key, "timeout": 15.0}
    if base_url:
        kwargs["base_url"] = base_url
    client = OpenAI(**kwargs)  # type: ignore[arg-type]
    client.chat.completions.create(
        model=model,
        max_tokens=1,
        messages=[{"role": "user", "content": "ping"}],
    )


def _ping_openai_embeddings(model: str, api_key: str, base_url: str) -> None:
    """Smallest possible embeddings call -- raises the SDK error on failure."""
    from openai import OpenAI

    kwargs: dict[str, object] = {"api_key": api_key, "timeout": 15.0}
    if base_url:
        kwargs["base_url"] = base_url
    client = OpenAI(**kwargs)  # type: ignore[arg-type]
    client.embeddings.create(model=model, input="ping")


def _model_uses_anthropic(model: str) -> bool:
    name = model.lower()
    return "claude" in name or "anthropic" in name


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def check_config() -> CheckResult:
    """Settings loaded; flag dev placeholders that are unsafe in production."""
    if settings.is_production and settings.app_secret_key in ("change-this", ""):
        return CheckResult(
            "Configuration",
            CheckStatus.FAIL,
            "APP_ENV=production but APP_SECRET_KEY is still the default placeholder.",
            hint="Set APP_SECRET_KEY to a strong random value.",
        )
    return CheckResult(
        "Configuration",
        CheckStatus.OK,
        f"app_env={settings.app_env}, model={settings.llm_extraction_model}",
    )


def check_arangodb(offline: bool = False) -> CheckResult:
    if offline:
        return CheckResult("ArangoDB", CheckStatus.SKIP, "skipped (--offline)")
    try:
        version = _ping_arango()
    except Exception as exc:
        return CheckResult(
            "ArangoDB",
            CheckStatus.FAIL,
            f"cannot reach {settings.effective_arango_host}: {exc}",
            hint=(
                "Is the DB running? For local dev: `make infra` (Docker), then "
                "`make migrate`. Check ARANGO_HOST / ARANGO_USER / ARANGO_PASSWORD in .env."
            ),
        )
    return CheckResult(
        "ArangoDB",
        CheckStatus.OK,
        f"connected to {settings.effective_arango_host} "
        f"(server {version}), db={settings.arango_db}",
    )


def check_redis(offline: bool = False) -> CheckResult:
    if not settings.rate_limit_enabled:
        return CheckResult(
            "Redis", CheckStatus.SKIP, "rate limiting disabled (RATE_LIMIT_ENABLED=false)"
        )
    if not settings.redis_url:
        return CheckResult(
            "Redis",
            CheckStatus.WARN,
            "REDIS_URL is empty; rate limiting degrades to pass-through.",
            hint="Set REDIS_URL, or set RATE_LIMIT_ENABLED=false to silence this.",
        )
    if offline:
        return CheckResult("Redis", CheckStatus.SKIP, "skipped (--offline)")
    try:
        _ping_redis(settings.redis_url)
    except Exception as exc:
        return CheckResult(
            "Redis",
            CheckStatus.WARN,
            f"cannot reach {settings.redis_url}: {exc}",
            hint=(
                "Rate limiting will pass-through until Redis is reachable. "
                "Start it (`make infra`) or set RATE_LIMIT_ENABLED=false."
            ),
        )
    return CheckResult("Redis", CheckStatus.OK, f"connected to {settings.redis_url}")


def check_extraction_llm(offline: bool = False) -> CheckResult:
    """Validate the *extraction* provider key + model with a tiny live call.

    This is the check that would have caught Tim's deprecated-model 404 before
    it became a silent empty ontology.
    """
    model = settings.llm_extraction_model
    ping: Callable[[], None]
    if _model_uses_anthropic(model):
        provider, key_env, key = "Anthropic", "ANTHROPIC_API_KEY", settings.anthropic_api_key

        def ping() -> None:
            _ping_anthropic(model, key)
    else:
        provider, key_env, key = "OpenAI", "OPENAI_API_KEY", settings.openai_api_key

        def ping() -> None:
            _ping_openai_chat(model, key, settings.openai_base_url)

    if not key:
        return CheckResult(
            "Extraction LLM",
            CheckStatus.FAIL,
            f"{key_env} is not set, but LLM_EXTRACTION_MODEL='{model}' needs {provider}.",
            hint=(
                f"Set {key_env} in .env (and restart). "
                "Alternatively set LLM_EXTRACTION_MODEL=gpt-4o to use OpenAI."
            ),
        )
    if offline:
        return CheckResult(
            "Extraction LLM", CheckStatus.SKIP, f"skipped (--offline); {provider} model '{model}'"
        )
    try:
        ping()
    except Exception as exc:
        return CheckResult(
            "Extraction LLM",
            CheckStatus.FAIL,
            f"{provider} model '{model}' is not usable with the configured key.",
            hint=_provider_error_hint(exc, model=model, key_env=key_env),
        )
    return CheckResult(
        "Extraction LLM", CheckStatus.OK, f"{provider} model '{model}' reachable and callable"
    )


def check_embeddings(offline: bool = False) -> CheckResult:
    """Embeddings always run through OpenAI regardless of the extraction provider."""
    model = settings.embedding_model
    key = settings.openai_api_key
    if not key:
        return CheckResult(
            "Embeddings (OpenAI)",
            CheckStatus.FAIL,
            "OPENAI_API_KEY is not set; document embedding will fail on upload.",
            hint="Set OPENAI_API_KEY in .env (required even when extraction uses Anthropic).",
        )
    if offline:
        return CheckResult(
            "Embeddings (OpenAI)", CheckStatus.SKIP, f"skipped (--offline); model '{model}'"
        )
    try:
        _ping_openai_embeddings(model, key, settings.openai_base_url)
    except Exception as exc:
        return CheckResult(
            "Embeddings (OpenAI)",
            CheckStatus.FAIL,
            f"embedding model '{model}' is not usable with OPENAI_API_KEY.",
            hint=_provider_error_hint(exc, model=model, key_env="OPENAI_API_KEY"),
        )
    return CheckResult(
        "Embeddings (OpenAI)", CheckStatus.OK, f"model '{model}' reachable and callable"
    )


# ---------------------------------------------------------------------------
# Runner / CLI
# ---------------------------------------------------------------------------


@dataclass
class PreflightReport:
    results: list[CheckResult] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return any(r.status is CheckStatus.FAIL for r in self.results)

    @property
    def warned(self) -> bool:
        return any(r.status is CheckStatus.WARN for r in self.results)


def run_checks(offline: bool = False) -> PreflightReport:
    """Run every check and collect results (never raises)."""
    return PreflightReport(
        results=[
            check_config(),
            check_arangodb(offline),
            check_redis(offline),
            check_extraction_llm(offline),
            check_embeddings(offline),
        ]
    )


def format_report(report: PreflightReport) -> str:
    lines = ["", "AOE preflight (`make doctor`)", "=" * 60]
    for r in report.results:
        lines.append(f"{_MARKER[r.status]} {r.name}: {r.detail}")
        if r.hint and r.status in (CheckStatus.FAIL, CheckStatus.WARN):
            lines.append(f"        ↳ {r.hint}")
    lines.append("=" * 60)
    if report.failed:
        lines.append("Result: FAIL — fix the [FAIL] items above, then re-run `make doctor`.")
    elif report.warned:
        lines.append("Result: OK with warnings — the system can run; review [WARN] items.")
    else:
        lines.append("Result: OK — environment looks healthy.")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.preflight",
        description="Validate the AOE runtime environment (config, DB, Redis, LLM keys).",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Skip all network/API calls (config + key-presence checks only).",
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON instead of a report."
    )
    args = parser.parse_args(argv)

    report = run_checks(offline=args.offline)

    if args.json:
        payload = {
            "failed": report.failed,
            "results": [{**asdict(r), "status": r.status.value} for r in report.results],
        }
        print(json.dumps(payload, indent=2))
    else:
        print(format_report(report))

    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
