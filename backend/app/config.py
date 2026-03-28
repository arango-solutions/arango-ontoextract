from enum import Enum

from pydantic import field_validator
from pydantic_settings import BaseSettings


class DeploymentMode(str, Enum):
    LOCAL_DOCKER = "local_docker"
    SELF_MANAGED_PLATFORM = "self_managed_platform"
    MANAGED_PLATFORM = "managed_platform"


class Settings(BaseSettings):
    model_config = {"env_file": "../.env", "env_file_encoding": "utf-8", "extra": "ignore"}

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
    arango_db: str = "ontology_generator"
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

    @field_validator("test_deployment_mode", mode="before")
    @classmethod
    def _normalize_deployment_mode(cls, v: str) -> str:
        if isinstance(v, str):
            return v.strip().lower()
        return v

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
