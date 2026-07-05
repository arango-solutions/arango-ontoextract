from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.middleware.strip_service_prefix import normalize_service_url_path_prefix


def _resolved_env_files() -> tuple[str, ...]:
    """Paths to optional `.env` files — stable regardless of process cwd.

    - Monorepo: repo-root ``.env`` (backend/app/config → ../../.env).
    - Flat deploy ``/project``: ``/project/.env`` beside ``app/``.

    A cwd-relative ``../.env`` breaks when cwd is ``/project`` (becomes ``/.env``).
    """
    here = Path(__file__).resolve()
    bundle = here.parents[1] / ".env"
    paths: list[Path] = []
    if len(here.parents) >= 3:
        repo = here.parents[2] / ".env"
        if here.parents[2] != Path("/") and repo.is_file():
            paths.append(repo)
    if bundle.is_file() and bundle.resolve() not in {p.resolve() for p in paths}:
        paths.append(bundle)
    return tuple(str(p) for p in paths)


class DeploymentMode(StrEnum):
    LOCAL_DOCKER = "local_docker"
    SELF_MANAGED_PLATFORM = "self_managed_platform"
    MANAGED_PLATFORM = "managed_platform"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_resolved_env_files() or None,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    app_log_level: str = "INFO"
    app_secret_key: str = "change-this"

    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    backend_workers: int = 1

    # -- Deployment Mode ---------------------------------------------------
    test_deployment_mode: DeploymentMode = DeploymentMode.LOCAL_DOCKER

    # -- ArangoDB (common) -------------------------------------------------
    arango_host: str = "http://localhost:8530"
    arango_db: str = "OntoExtract"
    arango_user: str = "root"
    arango_password: str = "changeme"
    arango_no_auth: bool = False

    # -- ArangoDB (cluster / self-managed) ---------------------------------
    arango_endpoint: str = ""
    arango_verify_ssl: bool = True
    arango_timeout: int = 30

    # -- ArangoDB (AMP / managed platform — future ArangoDB 4.0) -----------
    arango_graph_api_key_id: str = ""
    arango_graph_api_key_secret: str = ""
    gae_deployment_mode: str = ""

    # -- Redis -------------------------------------------------------------
    #: In k8s set ``REDIS_URL`` to your Redis Service (not localhost). If Redis is
    #: unreachable, rate limiting degrades to pass-through (see ``rate_limit.py``).
    #: To disable limits entirely: ``RATE_LIMIT_ENABLED=false``.
    redis_url: str = "redis://localhost:6379/0"

    # -- LLM ---------------------------------------------------------------
    openai_api_key: str = ""
    openai_base_url: str = ""
    anthropic_api_key: str = ""
    #: Default extraction model. Anthropic deprecated the original
    #: ``claude-sonnet-4-20250514`` snapshot (retires 2026-06-15) and the
    #: Messages API already returns HTTP 404 ``not_found_error`` for accounts
    #: without grandfathered access -- which silently failed every extraction
    #: batch (see the "Pass N failed after 5 retries" incident). Pin the
    #: current recommended replacement; override per-deployment via
    #: ``LLM_EXTRACTION_MODEL`` (e.g. ``gpt-4o`` for the OpenAI path).
    llm_extraction_model: str = "claude-sonnet-4-6"
    embedding_model: str = "text-embedding-3-small"
    #: Per-request HTTP timeout for LLM calls, in seconds. Without an
    #: explicit timeout, ``ChatAnthropic`` and ``ChatOpenAI`` inherit
    #: their underlying httpx client default (``None`` = wait forever
    #: in the SDK builds we depend on), so a hung provider connection
    #: ties up the asyncio task indefinitely. With a single uvicorn
    #: worker, enough hung tasks starve the threadpool and the API
    #: stops responding to anything -- exactly the symptom we hit
    #: during the WTW Ontology document load (worker in ``S 0%``,
    #: ``/runs`` healthcheck timing out, REST poll fallbacks failing
    #: into the WS connection storm).
    #:
    #: 60s is a deliberately generous ceiling: the qualitative-eval
    #: map step legitimately needs 30-45s on long chunks under the
    #: GPT-4o tier, while a real outage will trip well inside the
    #: minute. Tune downward in production if your deployment fronts
    #: a cheaper / faster judge model.
    llm_request_timeout_seconds: float = 60.0

    # -- Extraction --------------------------------------------------------
    extraction_passes: int = 3
    extraction_consistency_threshold: int = 2
    extraction_confidence_min: float = 0.6
    #: Maximum simultaneous LLM calls fired by the qualitative-evaluation
    #: map phase. Caps unbounded ``asyncio.gather`` fan-out that, on large
    #: documents, can produce dozens of parallel OpenAI requests, trip
    #: provider rate limits, trigger long retry storms, and saturate the
    #: single uvicorn worker (blocking unrelated API + WebSocket traffic).
    #: A value of 5 keeps us well under typical TPM/RPM ceilings while
    #: preserving most of the speed-up from concurrency.
    qualitative_eval_max_concurrency: int = 5

    # -- Visual extraction (Stream 13) -------------------------------------
    #: Inventory embedded images/charts and emit labeled placeholders when
    #: OCR/vision is not configured. Disabling skips visual asset walks.
    visual_extraction_enabled: bool = True
    #: When True, non-text visuals become ``[Visual omitted: …]`` lines in
    #: chunk text; when False, visuals are counted in metadata only.
    visual_extraction_placeholders: bool = True
    #: Provider id for OCR/vision caption generation. ``"none"`` (default)
    #: produces no captions; ingestion remains text-only with placeholders.
    #: ``"openai_vision"`` activates the OpenAI Vision adapter in
    #: ``app.services.visual_captions_openai`` (requires
    #: ``openai_api_key``). ``"tesseract"`` activates the on-prem OCR
    #: adapter in ``app.services.visual_captions_tesseract`` (requires
    #: ``pip install pytesseract`` + the ``tesseract`` host binary).
    visual_caption_provider: str = "none"
    #: Per-document cap on caption calls so a slide deck cannot run away
    #: with provider cost. Captions beyond this point fall back to
    #: placeholders and are recorded with ``failure_reason="cap_exceeded"``.
    visual_caption_max_assets_per_doc: int = 25
    #: Model id used by ``OpenAIVisionCaptionProvider``. Must be a
    #: vision-capable chat-completions model. ``gpt-4o-mini`` is the
    #: cost/quality sweet spot for short alt-text-style captions; bump
    #: to ``gpt-4o`` when caption fidelity outweighs per-image cost.
    visual_caption_openai_model: str = "gpt-4o-mini"
    #: Visual-heavy + orphan-class warning threshold (IMG.7). Orphan ratio
    #: must exceed this to trigger a non-blocking run warning.
    visual_orphan_warning_orphan_ratio: float = 0.5
    #: Visual-heavy + orphan-class warning threshold (IMG.7). Total visual
    #: asset count across run documents must exceed this to trigger.
    visual_orphan_warning_min_assets: int = 5

    # -- Domain Detection & Multi-Ontology Routing (Stream 16) -------------
    #: Master switch for the pre-extraction domain-segmentation node
    #: (DD.1). Default OFF, mirroring the belief-revision and
    #: structural-gate nodes: every new pipeline node in this codebase
    #: ships behind a default-off flag so existing runs are byte-identical
    #: until an operator opts in. When False the node is a transparent
    #: pass-through (no LLM call, no ``domain_segments``, no
    #: ``detected_domains``, no per-class ``domain_tag``, no warning).
    domain_detection_enabled: bool = False
    #: Model id for the domain-classification call. Empty string (default)
    #: falls back to ``llm_extraction_model`` so a deployment only needs to
    #: override this when it wants a cheaper/faster classifier than the
    #: main extractor model.
    domain_detection_model: str = ""
    #: A chunk's domain assignment below this confidence is treated as
    #: unassigned (folded into the dominant domain) so a single low-signal
    #: chunk does not spuriously create a second domain / multi-domain
    #: warning. Also the floor for a distinct domain to count toward
    #: ``detected_domains``.
    domain_detection_min_confidence: float = 0.6
    #: Upper bound on the number of chunks sent to the classifier in one
    #: call, bounding cost/latency on very large documents. When a document
    #: exceeds this, the node samples evenly across the document; unsampled
    #: chunks inherit the nearest sampled chunk's domain.
    domain_detection_max_chunks: int = 200

    # -- Entity Resolution -------------------------------------------------
    er_vector_similarity_threshold: float = 0.85
    er_vector_weight: float = 0.6
    er_topo_weight: float = 0.4

    # -- Belief Revision (PRD §6.16, Stream 11) ----------------------------
    #: Master kill-switch for the confidence-decay job (IBR.3). Default OFF;
    #: dry-runs (``apply_confidence_decay(..., dry_run=True)``) work even
    #: when this is False, so an admin can preview decay before enabling.
    belief_revision_decay_enabled: bool = False
    #: Half-life for the decay curve. After this many days an
    #: untouched class's confidence has halved (subject to the floor).
    belief_revision_decay_half_life_days: float = 90.0
    #: Hard floor for decayed confidence; we never decay below this so
    #: a long-untouched class is always still ranked above a brand-new
    #: zero-confidence one. Tune per ontology if needed.
    belief_revision_decay_floor: float = 0.05
    #: Master kill-switch for the per-document Belief Revision pipeline
    #: stage (IBR.10/11). Default OFF: every new upload runs the legacy
    #: extract+ER+filter path with no touchpoint discovery, no LLM
    #: revision agent, and no temporal supersedes. Flip to True to
    #: activate the four-phase IBR pipeline. Setting only -- no code
    #: deploy required to roll out or roll back.
    belief_revision_pipeline_enabled: bool = False
    #: Circuit breaker for the LLM revision agent (IBR.18). Maximum
    #: number of revisions allowed within ``circuit_window_seconds``
    #: before the breaker trips and halts the agent until the next
    #: window. Defaults are conservative: 50 / 60s allows realistic
    #: extraction loads while preventing runaway LLM cost. Set
    #: ``max_per_minute`` to 0 to disable the breaker entirely.
    belief_revision_circuit_max_per_minute: int = 50
    belief_revision_circuit_window_seconds: float = 60.0

    # -- Structural gate (Stream 15 SO.1 + SO.2) --------------------------
    #: Master kill-switch for the in-pipeline structural quality gate
    #: (``extraction/agents/structural_gate.py``). Default **ON** as of SO.2:
    #: the node runs *before* the human-in-the-loop curation breakpoint and
    #: applies two deterministic (non-LLM, 100%-reliable) repairs to the
    #: in-memory merged class list -- URI normalization and evidence-based
    #: link recovery -- so broken relationship targets are recovered (or at
    #: least surfaced in the health report) rather than materialized into a
    #: disconnected schema. Inspired by the UPM "Self-Optimizing Ontology"
    #: Pipeline-2 quality loop (``docs/research/Ontologies_3_6 .pdf``;
    #: empirical gains in ``Ontologies_27_05.pdf``).
    #:
    #: Enabling by default is safe because the repairs are provably
    #: faithfulness-neutral: they only ever rewrite relationship *targets*,
    #: never class identity/description/evidence (the inputs the faithfulness
    #: judge reads). See the guardrail test
    #: ``test_repairs_never_touch_faithfulness_inputs``. Set to ``False`` to
    #: roll back to a pass-through with no code deploy. The iterative LLM
    #: "surgeon" loop (SO.3) and A-box layer (SO.4) remain out of scope.
    structural_gate_enabled: bool = True

    # -- Observability (Stream 7 PR 2 -- E.1, OpenTelemetry) ---------------
    #: Master kill-switch for OpenTelemetry tracing. Default OFF so a
    #: fresh ``pip install`` deployment has zero runtime cost and zero
    #: outbound traffic from spans. Flip to ``true`` and point
    #: ``otel_exporter_otlp_endpoint`` at a collector (Jaeger, Tempo,
    #: Honeycomb's OTLP receiver, etc) to start emitting spans.
    #:
    #: When OFF the OpenTelemetry no-op TracerProvider is used, which
    #: means ``trace.get_tracer().start_as_current_span(...)`` calls
    #: scattered through the codebase are effectively free -- no
    #: context propagation, no exporter, no buffering.
    otel_enabled: bool = False

    #: ``service.name`` resource attribute on every emitted span.
    #: Distinguishes this backend in a multi-service Jaeger / Tempo
    #: view. Defaults to a stable identifier; deployments can override
    #: when they run multiple instances side-by-side (eg
    #: ``arango-ontoextract-staging`` vs ``-prod``).
    otel_service_name: str = "arango-ontoextract"

    #: OTLP/gRPC endpoint to ship spans to. Empty string means
    #: "console exporter" (logs span JSON to stdout) when
    #: ``otel_enabled=True`` -- handy for local dev / debugging
    #: instrumentation without standing up a collector. Set to eg
    #: ``http://otel-collector:4317`` in a real deployment.
    otel_exporter_otlp_endpoint: str = ""

    #: Sample rate for the parent-based traceid-ratio sampler.
    #: 1.0 = trace every request (good for dev / low traffic);
    #: drop to eg 0.1 in production to keep collector + storage
    #: cost bounded. Spans inherit the parent's sampling decision,
    #: so a root request that is sampled emits a complete trace.
    otel_trace_sample_rate: float = 1.0

    # -- Temporal Retention (Stream 7 PR 1 -- E.3) -------------------------
    #: Default retention window for expired temporal versions. Every time a
    #: vertex or edge is superseded (``expired`` set to a real timestamp),
    #: we also stamp ``ttlExpireAt = expired + temporal_retention_seconds``.
    #: ArangoDB's sparse TTL index (migration 006 + 026) garbage-collects
    #: rows once their ``ttlExpireAt`` is reached, so the history stays
    #: queryable for this many seconds before disappearing.
    #:
    #: 90 days (7,776,000 s) is the PRD default and matches the original
    #: hardcoded value the temporal service used to carry. Tune downward
    #: for cost-sensitive deployments (eg 30 days = 2,592,000 s) or
    #: upward for compliance regimes that demand longer audit trails.
    #: Setting it to 0 disables the stamp (history accumulates forever
    #: -- only useful for dev / forensic captures).
    temporal_retention_seconds: int = 7_776_000

    # -- Ontology Defaults ---------------------------------------------------
    default_ontology_uri: str = "http://example.org/ontology#"

    # -- CORS ---------------------------------------------------------------
    cors_origins: str = "http://localhost:3000"

    # -- Public URL (reverse proxy / Container Manager) --------------------
    #: External path prefix before routes (env ``SERVICE_URL_PATH_PREFIX``).
    #: Must match the frontend static bundle / Next ``basePath`` (same env in repo ``.env``).
    service_url_path_prefix: str = ""

    #: Next.js static export root (directory containing ``index.html`` and ``_next/``).
    #: Use in k8s when the UI is copied or mounted at a known path. If unset, the app
    #: looks for ``<bundle>/frontend/out``, monorepo ``frontend/out``, or ``/app/static``.
    #: Build the export with ``AOE_STATIC_EXPORT=1`` and ``SERVICE_URL_PATH_PREFIX`` (see
    #: ``scripts/package-arango-manual.sh`` with ``PACKAGE_INCLUDE_FRONTEND=1``).
    frontend_static_root: str = Field(
        default="",
        validation_alias=AliasChoices("AOE_FRONTEND_OUT_DIR", "FRONTEND_STATIC_ROOT"),
    )

    # -- Rate Limiting -----------------------------------------------------
    rate_limit_enabled: bool = True
    rate_limit_default: int = 100
    rate_limit_default_tier: str = "standard"

    # -- Admin -------------------------------------------------------------
    allow_system_reset: bool = False

    @field_validator("app_secret_key", mode="after")
    @classmethod
    def _validate_secret_key(cls, v: str, info: Any) -> str:
        env = info.data.get("app_env", "development")
        if env == "production" and v in ("change-this", ""):
            raise ValueError("APP_SECRET_KEY must be set to a strong random value in production")
        return v

    @field_validator("test_deployment_mode", mode="before")
    @classmethod
    def _normalize_deployment_mode(cls, v: str) -> str:
        if isinstance(v, str):
            return v.strip().lower()
        return v

    @field_validator("service_url_path_prefix", mode="after")
    @classmethod
    def _normalize_service_url_path_prefix_setting(cls, v: str) -> str:
        return normalize_service_url_path_prefix(v)

    # -- Deployment-mode-derived properties --------------------------------

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_local(self) -> bool:
        return self.test_deployment_mode == DeploymentMode.LOCAL_DOCKER

    @property
    def is_cluster(self) -> bool:
        return self.test_deployment_mode in (
            DeploymentMode.SELF_MANAGED_PLATFORM,
            DeploymentMode.MANAGED_PLATFORM,
        )

    @property
    def is_amp(self) -> bool:
        return self.test_deployment_mode == DeploymentMode.MANAGED_PLATFORM

    @property
    def effective_arango_host(self) -> str:
        """Resolve the ArangoDB endpoint based on deployment mode.

        - local_docker: uses ARANGO_HOST (http://localhost:PORT)
        - self_managed_platform / managed_platform: uses ARANGO_ENDPOINT
        """
        if self.is_local:
            return self.arango_host
        if self.arango_endpoint:
            return self.arango_endpoint
        return self.arango_host

    @property
    def has_gae(self) -> bool:
        """Graph Analytics Engine is only available on cluster deployments."""
        return self.is_cluster

    @property
    def has_smart_graphs(self) -> bool:
        """SmartGraphs require a cluster (Enterprise Edition)."""
        return self.is_cluster

    @property
    def can_create_databases(self) -> bool:
        """On managed platforms, DB creation may be restricted.

        Local and self-managed allow _system DB access for auto-creation.
        AMP managed platform may not.
        """
        return not self.is_amp

    @property
    def supports_satellite_collections(self) -> bool:
        """SatelliteCollections are cluster-only (Enterprise Edition)."""
        return self.is_cluster

    @property
    def wcc_backend_preference(self) -> str:
        """Entity resolution WCC clustering backend.

        GAE backend is faster but only available on clusters.
        Falls back to in-memory Python Union-Find on single server.
        """
        if self.has_gae:
            return "gae"
        return "python_union_find"


settings = Settings()
