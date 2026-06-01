"""Unit tests for the preflight / `make doctor` checks.

All I/O (ArangoDB, Redis, provider SDKs) is patched at the ``_ping_*`` seam, so
these tests run offline and deterministically while still exercising the
status-classification and hint logic that makes the tool useful.
"""

from __future__ import annotations

import app.preflight as pf
from app.preflight import CheckStatus


class _FakeProviderError(Exception):
    """Mirrors the Anthropic/OpenAI SDK error shape (HTTP ``status_code``)."""

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


# ---------------------------------------------------------------------------
# _provider_error_hint
# ---------------------------------------------------------------------------


class TestProviderErrorHint:
    def test_404_points_at_model_access_and_offers_openai(self) -> None:
        hint = pf._provider_error_hint(
            _FakeProviderError("model: x does not exist", 404),
            model="claude-sonnet-4-6",
            key_env="ANTHROPIC_API_KEY",
        )
        assert "no access" in hint.lower() or "does not exist" in hint.lower()
        assert "gpt-4o" in hint

    def test_401_points_at_bad_key(self) -> None:
        hint = pf._provider_error_hint(
            _FakeProviderError("unauthorized", 401), model="m", key_env="OPENAI_API_KEY"
        )
        assert "OPENAI_API_KEY" in hint and "revoked" in hint

    def test_400_credit_balance_points_at_billing(self) -> None:
        hint = pf._provider_error_hint(
            _FakeProviderError("Your credit balance is too low", 400),
            model="m",
            key_env="ANTHROPIC_API_KEY",
        )
        assert "billing" in hint.lower() or "credit" in hint.lower()

    def test_429_says_key_works(self) -> None:
        hint = pf._provider_error_hint(
            _FakeProviderError("rate limit", 429), model="m", key_env="OPENAI_API_KEY"
        )
        assert "key works" in hint.lower()

    def test_unknown_error_is_reported_verbatim(self) -> None:
        hint = pf._provider_error_hint(
            RuntimeError("connection reset"), model="m", key_env="OPENAI_API_KEY"
        )
        assert "connection reset" in hint


# ---------------------------------------------------------------------------
# check_config
# ---------------------------------------------------------------------------


class TestCheckConfig:
    def test_ok_in_development(self, monkeypatch) -> None:
        monkeypatch.setattr(pf.settings, "app_env", "development")
        assert pf.check_config().status is CheckStatus.OK

    def test_fail_in_production_with_placeholder_secret(self, monkeypatch) -> None:
        monkeypatch.setattr(pf.settings, "app_env", "production")
        monkeypatch.setattr(pf.settings, "app_secret_key", "change-this")
        result = pf.check_config()
        assert result.status is CheckStatus.FAIL
        assert "APP_SECRET_KEY" in result.hint


# ---------------------------------------------------------------------------
# check_arangodb
# ---------------------------------------------------------------------------


class TestCheckArangodb:
    def test_ok_when_reachable(self, monkeypatch) -> None:
        monkeypatch.setattr(pf, "_ping_arango", lambda: "3.12.0")
        assert pf.check_arangodb().status is CheckStatus.OK

    def test_fail_when_unreachable(self, monkeypatch) -> None:
        def _boom() -> str:
            raise ConnectionError("connection refused")

        monkeypatch.setattr(pf, "_ping_arango", _boom)
        result = pf.check_arangodb()
        assert result.status is CheckStatus.FAIL
        assert "make infra" in result.hint

    def test_skip_when_offline(self, monkeypatch) -> None:
        # Even if the ping would fail, offline must short-circuit before I/O.
        monkeypatch.setattr(pf, "_ping_arango", lambda: (_ for _ in ()).throw(AssertionError()))
        assert pf.check_arangodb(offline=True).status is CheckStatus.SKIP


# ---------------------------------------------------------------------------
# check_redis
# ---------------------------------------------------------------------------


class TestCheckRedis:
    def test_skip_when_rate_limiting_disabled(self, monkeypatch) -> None:
        monkeypatch.setattr(pf.settings, "rate_limit_enabled", False)
        assert pf.check_redis().status is CheckStatus.SKIP

    def test_warn_when_url_empty(self, monkeypatch) -> None:
        monkeypatch.setattr(pf.settings, "rate_limit_enabled", True)
        monkeypatch.setattr(pf.settings, "redis_url", "")
        assert pf.check_redis().status is CheckStatus.WARN

    def test_warn_not_fail_when_unreachable(self, monkeypatch) -> None:
        # Redis degrades to pass-through, so an outage is a WARN, never a FAIL.
        monkeypatch.setattr(pf.settings, "rate_limit_enabled", True)
        monkeypatch.setattr(pf.settings, "redis_url", "redis://localhost:6379/0")

        def _boom(url: str) -> None:
            raise ConnectionError("refused")

        monkeypatch.setattr(pf, "_ping_redis", _boom)
        assert pf.check_redis().status is CheckStatus.WARN

    def test_ok_when_reachable(self, monkeypatch) -> None:
        monkeypatch.setattr(pf.settings, "rate_limit_enabled", True)
        monkeypatch.setattr(pf.settings, "redis_url", "redis://localhost:6379/0")
        monkeypatch.setattr(pf, "_ping_redis", lambda url: None)
        assert pf.check_redis().status is CheckStatus.OK


# ---------------------------------------------------------------------------
# check_extraction_llm
# ---------------------------------------------------------------------------


class TestCheckExtractionLlm:
    def test_routes_to_anthropic_for_claude(self, monkeypatch) -> None:
        monkeypatch.setattr(pf.settings, "llm_extraction_model", "claude-sonnet-4-6")
        monkeypatch.setattr(pf.settings, "anthropic_api_key", "sk-ant-x")
        called: dict[str, str] = {}
        monkeypatch.setattr(
            pf, "_ping_anthropic", lambda model, key: called.update(model=model, key=key)
        )
        monkeypatch.setattr(
            pf,
            "_ping_openai_chat",
            lambda *a, **k: (_ for _ in ()).throw(AssertionError("wrong provider")),
        )
        assert pf.check_extraction_llm().status is CheckStatus.OK
        assert called["model"] == "claude-sonnet-4-6"

    def test_routes_to_openai_for_gpt(self, monkeypatch) -> None:
        monkeypatch.setattr(pf.settings, "llm_extraction_model", "gpt-4o")
        monkeypatch.setattr(pf.settings, "openai_api_key", "sk-x")
        monkeypatch.setattr(pf.settings, "openai_base_url", "")
        monkeypatch.setattr(pf, "_ping_openai_chat", lambda model, key, base_url: None)
        assert pf.check_extraction_llm().status is CheckStatus.OK

    def test_fail_when_anthropic_key_missing(self, monkeypatch) -> None:
        monkeypatch.setattr(pf.settings, "llm_extraction_model", "claude-sonnet-4-6")
        monkeypatch.setattr(pf.settings, "anthropic_api_key", "")
        result = pf.check_extraction_llm()
        assert result.status is CheckStatus.FAIL
        assert "ANTHROPIC_API_KEY" in result.detail

    def test_fail_on_provider_404_with_actionable_hint(self, monkeypatch) -> None:
        monkeypatch.setattr(pf.settings, "llm_extraction_model", "claude-sonnet-4-20250514")
        monkeypatch.setattr(pf.settings, "anthropic_api_key", "sk-ant-x")

        def _boom(model: str, key: str) -> None:
            raise _FakeProviderError("model does not exist or you do not have access", 404)

        monkeypatch.setattr(pf, "_ping_anthropic", _boom)
        result = pf.check_extraction_llm()
        assert result.status is CheckStatus.FAIL
        assert "gpt-4o" in result.hint

    def test_skip_when_offline_but_key_present(self, monkeypatch) -> None:
        monkeypatch.setattr(pf.settings, "llm_extraction_model", "gpt-4o")
        monkeypatch.setattr(pf.settings, "openai_api_key", "sk-x")
        assert pf.check_extraction_llm(offline=True).status is CheckStatus.SKIP

    def test_offline_still_fails_on_missing_key(self, monkeypatch) -> None:
        # Key-presence is a config check, not a network check -- it must FAIL
        # even offline so `make doctor OFFLINE=1` still catches an empty key.
        monkeypatch.setattr(pf.settings, "llm_extraction_model", "gpt-4o")
        monkeypatch.setattr(pf.settings, "openai_api_key", "")
        assert pf.check_extraction_llm(offline=True).status is CheckStatus.FAIL


# ---------------------------------------------------------------------------
# check_embeddings
# ---------------------------------------------------------------------------


class TestCheckEmbeddings:
    def test_fail_when_openai_key_missing(self, monkeypatch) -> None:
        monkeypatch.setattr(pf.settings, "openai_api_key", "")
        assert pf.check_embeddings().status is CheckStatus.FAIL

    def test_ok_when_reachable(self, monkeypatch) -> None:
        monkeypatch.setattr(pf.settings, "openai_api_key", "sk-x")
        monkeypatch.setattr(pf.settings, "openai_base_url", "")
        monkeypatch.setattr(pf, "_ping_openai_embeddings", lambda model, key, base_url: None)
        assert pf.check_embeddings().status is CheckStatus.OK

    def test_fail_on_401(self, monkeypatch) -> None:
        monkeypatch.setattr(pf.settings, "openai_api_key", "sk-bad")
        monkeypatch.setattr(pf.settings, "openai_base_url", "")

        def _boom(model: str, key: str, base_url: str) -> None:
            raise _FakeProviderError("incorrect api key", 401)

        monkeypatch.setattr(pf, "_ping_openai_embeddings", _boom)
        assert pf.check_embeddings().status is CheckStatus.FAIL


# ---------------------------------------------------------------------------
# run_checks / main
# ---------------------------------------------------------------------------


def _all_ok(monkeypatch) -> None:
    monkeypatch.setattr(pf.settings, "app_env", "development")
    monkeypatch.setattr(pf.settings, "rate_limit_enabled", False)
    monkeypatch.setattr(pf.settings, "llm_extraction_model", "gpt-4o")
    monkeypatch.setattr(pf.settings, "openai_api_key", "sk-x")
    monkeypatch.setattr(pf.settings, "openai_base_url", "")
    monkeypatch.setattr(pf, "_ping_arango", lambda: "3.12.0")
    monkeypatch.setattr(pf, "_ping_openai_chat", lambda model, key, base_url: None)
    monkeypatch.setattr(pf, "_ping_openai_embeddings", lambda model, key, base_url: None)


class TestRunnerAndMain:
    def test_run_checks_all_ok_not_failed(self, monkeypatch) -> None:
        _all_ok(monkeypatch)
        report = pf.run_checks()
        assert not report.failed
        assert len(report.results) == 5

    def test_main_exit_zero_when_healthy(self, monkeypatch, capsys) -> None:
        _all_ok(monkeypatch)
        assert pf.main([]) == 0
        assert "Result: OK" in capsys.readouterr().out

    def test_main_exit_one_when_a_check_fails(self, monkeypatch, capsys) -> None:
        _all_ok(monkeypatch)
        monkeypatch.setattr(pf.settings, "openai_api_key", "")  # breaks LLM + embeddings
        assert pf.main([]) == 1
        assert "FAIL" in capsys.readouterr().out

    def test_main_json_output_is_parseable(self, monkeypatch, capsys) -> None:
        import json

        _all_ok(monkeypatch)
        assert pf.main(["--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["failed"] is False
        assert {r["name"] for r in payload["results"]} >= {"ArangoDB", "Extraction LLM"}

    def test_main_offline_skips_network_without_io(self, monkeypatch, capsys) -> None:
        monkeypatch.setattr(pf.settings, "app_env", "development")
        monkeypatch.setattr(pf.settings, "rate_limit_enabled", False)
        monkeypatch.setattr(pf.settings, "llm_extraction_model", "gpt-4o")
        monkeypatch.setattr(pf.settings, "openai_api_key", "sk-x")
        # Any real ping would raise; offline must not call them.
        monkeypatch.setattr(pf, "_ping_arango", lambda: (_ for _ in ()).throw(AssertionError()))
        assert pf.main(["--offline"]) == 0
        assert "[SKIP]" in capsys.readouterr().out
