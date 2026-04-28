from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import field_validator
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
    redis_url: str = "redis://localhost:6379/0"

    # -- LLM ---------------------------------------------------------------
    openai_api_key: str = ""
    openai_base_url: str = ""
    anthropic_api_key: str = ""
    llm_extraction_model: str = "claude-sonnet-4-20250514"
    embedding_model: str = "text-embedding-3-small"

    # -- Extraction --------------------------------------------------------
    extraction_passes: int = 3
    extraction_consistency_threshold: int = 2
    extraction_confidence_min: float = 0.6

    # -- Entity Resolution -------------------------------------------------
    er_vector_similarity_threshold: float = 0.85
    er_vector_weight: float = 0.6
    er_topo_weight: float = 0.4

    # -- Ontology Defaults ---------------------------------------------------
    default_ontology_uri: str = "http://example.org/ontology#"

    # -- CORS ---------------------------------------------------------------
    cors_origins: str = "http://localhost:3000"

    # -- Public URL (reverse proxy / Container Manager) --------------------
    #: External path prefix before routes, e.g.
    #: ``/_service/uds/_db/ontoextract/arango-ontoextract`` — no trailing slash.
    service_url_path_prefix: str = ""

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
            raise ValueError(
                "APP_SECRET_KEY must be set to a strong random value in production"
            )
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
