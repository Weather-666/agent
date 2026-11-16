from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _bundled_codex_adapter_command() -> str:
    return str(Path(__file__).resolve().parents[2] / "runtime" / "codex-acp")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        env_prefix="EXPERT_",
        extra="ignore",
    )

    app_env: str = "development"
    jwt_secret: str = "change-me"
    jwt_issuer: str = "experts-backend"
    jwt_audience: str = "expert-web"
    access_token_ttl_seconds: int = 900
    refresh_token_ttl_seconds: int = 60 * 60 * 24 * 7
    # Allow a small, explicit clock-skew window between the process that issues a JWT and the
    # process that validates it. This is especially important in WSL/Docker after host resume;
    # it does not extend the configured token lifetime by more than this bounded leeway.
    jwt_clock_skew_seconds: int = Field(default=30, ge=0, le=300)
    platform_activation_token_ttl_seconds: int = 60 * 60 * 24 * 7
    password_reset_code_ttl_seconds: int = Field(default=10 * 60, ge=1)
    password_reset_cooldown_seconds: int = Field(default=60, ge=0)
    password_reset_max_attempts: int = Field(default=5, ge=1)
    default_tenant_id: str = "tenant_default"
    credit_tokens_per_credit: int = Field(default=500, gt=0)
    credit_cached_input_weight: Decimal = Field(
        default=Decimal("0.1"), ge=Decimal("0"), le=Decimal("1")
    )

    smtp_server: str | None = None
    smtp_port: int = Field(default=465, ge=1, le=65_535)
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_address: str | None = None
    smtp_from_name: str = "WinWise"
    smtp_use_ssl: bool = True
    smtp_timeout_seconds: float = Field(default=10.0, gt=0)

    cors_origins: list[str] = Field(default_factory=lambda: ["*"])

    database_url: str = "sqlite:///./.data/experts-backend.sqlite3"
    database_auto_migrate: bool = True
    database_schema_dir: str = Field(
        default_factory=lambda: str(Path(__file__).resolve().parents[2] / "infra" / "sql")
    )

    # agent-gateway ACP data plane. The route prefix is the gateway's external path prefix for
    # the ACP route; the client posts to <prefix>/turn and <prefix>/permission and reads history
    # from <prefix>/sessions and <prefix>/sessions/{id}/transcript (all route-scoped and
    # authenticated by acp_auth_token, so no admin plane is needed). acp_default_cwd is reserved
    # for legacy/unbound Chat Sessions (expert_id is null). Bound Expert sessions require
    # acp_cwd_base and use <base>/<tenant_id>/users/<user_id>; both paths must resolve under the ACP
    # service's allowedRoots on the Backend/Gateway shared filesystem.
    acp_gateway_base_url: str | None = None
    acp_route_prefix: str = ""
    acp_search_route_prefix: str | None = None
    acp_auth_token: str | None = None
    acp_client_id: str = "experts-backend"
    acp_default_model: str | None = None
    acp_default_cwd: str | None = None
    acp_cwd_base: str | None = None
    acp_config_base: str | None = None
    acp_gateway_admin_url: str | None = None
    acp_gateway_admin_token: str | None = None
    acp_virtual_key_id: str = "backend-acp"
    acp_codex_adapter_command: str = Field(default_factory=_bundled_codex_adapter_command)
    acp_codex_real_adapter_command: str = "/usr/local/bin/codex-acp"
    agent_gateway_model_base_url: str | None = None
    agent_gateway_model_api_key: str | None = None
    builder_executable: str | None = None
    runtime_operation_timeout_seconds: float = Field(default=120.0, gt=0, le=1_800)
    mcp_model_compat_base_url: str | None = None
    mcp_gateway_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    knowledge_mcp_base_url: str = "http://127.0.0.1:15000/internal/mcp/knowledge"

    codex_home: str = Field(default_factory=lambda: str(Path.home() / ".codex"))
    codex_skills_dir: str | None = None

    object_storage_backend: str = "local"
    object_storage_local_dir: str = Field(
        default_factory=lambda: str(Path.cwd() / ".data" / "objects")
    )
    # Retained for configuration compatibility only. Local browser upload/download URLs are
    # always same-origin relative Backend paths; absolute origins belong to the reverse proxy.
    object_storage_public_base_url: str | None = None
    object_storage_max_upload_bytes: int = 100 * 1024 * 1024
    avatar_max_upload_bytes: int = Field(default=2 * 1024 * 1024, ge=1)
    avatar_max_pixels: int = Field(default=20_000_000, ge=1)
    avatar_max_dimension: int = Field(default=512, ge=1, le=4096)
    avatar_url_ttl_seconds: int = Field(default=900, ge=1)

    minio_endpoint: str | None = None
    minio_access_key: str | None = None
    minio_secret_key: str | None = None
    minio_bucket: str | None = None
    minio_secure: bool = False
    # Explicit browser-facing MinIO host[:port] used for presigned PUT/GET URL signing. It must
    # not be a loopback, private IP or internal service name; there is deliberately no fallback
    # to minio_endpoint because that address belongs to the Backend-to-storage network.
    minio_public_endpoint: str | None = None
    # Local Compose development can explicitly opt out of the browser-public-host guard.
    # Keep this disabled by default so deployed environments cannot accidentally sign URLs for
    # loopback, private addresses, or Docker-only service names.
    minio_allow_local_endpoint: bool = False
    # The public endpoint can terminate TLS independently from the internal MinIO connection.
    # None preserves minio_secure for deployments where both endpoints use the same scheme.
    minio_public_secure: bool | None = None
    # Short-lived presigned URL TTL for document upload/download (seconds). See design section 11.
    presigned_url_ttl_seconds: int = 900
    # Retention window for chat temporary files (seconds). A temporary attachment gets
    # expires_at = now() + this at complete-upload; promotion clears it. Default 1 day.
    chat_attachment_retention_seconds: int = 60 * 60 * 24
    # TTL for the Backend delivery capability sent to the compute engine for a turn attachment.
    # Must outlive the whole turn because the agent may fetch it minutes later. Default 1 hour.
    attachment_delivery_url_ttl_seconds: int = 60 * 60
    # Backend origin reachable by the Agent runtime for request-authorized Library delivery.
    # Browser download/preview routes can remain relative; Agent URLs must be absolute in Compose.
    library_delivery_public_base_url: str | None = None

    # Dynamic provisioning goes through the isolated Controller. There is no static pool fallback:
    # every knowledge base receives a Controller-owned isolated instance.
    lightrag_controller_url: str | None = None
    lightrag_controller_token: str | None = None
    lightrag_controller_timeout_seconds: float = Field(default=180.0, gt=0, le=600)
    lightrag_api_key: str | None = None
    lightrag_timeout_seconds: float = Field(default=40.0, gt=0)
    lightrag_insert_timeout_seconds: float = Field(default=60.0, gt=0)
    lightrag_delete_timeout_seconds: float = Field(default=180.0, gt=0, le=1_800)
    lightrag_poll_initial_seconds: float = Field(default=2.0, gt=0, le=60)
    lightrag_poll_max_seconds: float = Field(default=10.0, gt=0, le=120)
    lightrag_query_mode: str = "hybrid"
    lightrag_query_top_k: int = Field(default=10, ge=1, le=100)
    lightrag_query_chunk_top_k: int = Field(default=8, ge=1, le=100)
    lightrag_query_enable_rerank: bool = False
    lightrag_chunk_token_size: int = Field(default=800, ge=200, le=4_000)
    lightrag_chunk_overlap_token_size: int = Field(default=100, ge=0, le=1_000)

    # External Docling service (docling-serve). The build worker sends original document bytes
    # here and receives markdown for LightRAG ingestion.
    docling_base_url: str | None = None
    docling_timeout_seconds: float = Field(default=600.0, gt=0)
    docling_do_ocr: bool = True
    docling_force_ocr: bool = False
    docling_ocr_languages: list[str] = Field(default_factory=list)
    docling_page_break_placeholder: str = "<!-- expert-source-page-break -->"
    docling_max_concurrency: int = Field(default=1, ge=1, le=8)

    # Automatic per-document sync worker.
    knowledge_index_worker_poll_seconds: float = Field(default=3.0, ge=1)
    knowledge_index_max_attempts: int = Field(default=5, ge=1, le=20)
    knowledge_index_reconcile_batch_size: int = Field(default=100, ge=1, le=1000)
    knowledge_index_retry_base_seconds: float = Field(default=5.0, gt=0, le=300)
    knowledge_index_retry_max_seconds: float = Field(default=300.0, gt=0, le=3_600)
    knowledge_index_pipeline_version: str = "docling-page-ocr-locator-v3"
    knowledge_index_worker_concurrency: int = Field(default=3, ge=1, le=16)

    @field_validator(
        "acp_default_cwd",
        "acp_cwd_base",
        "acp_config_base",
        "acp_gateway_admin_url",
        "acp_gateway_admin_token",
        "agent_gateway_model_base_url",
        "agent_gateway_model_api_key",
        "builder_executable",
        "mcp_model_compat_base_url",
        "lightrag_controller_url",
        "lightrag_controller_token",
        "lightrag_api_key",
        "docling_base_url",
        "minio_public_endpoint",
        mode="before",
    )
    @classmethod
    def empty_string_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("knowledge_mcp_base_url")
    @classmethod
    def require_knowledge_mcp_http_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        parsed = urlsplit(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Knowledge MCP URL must be an HTTP(S) URL")
        return normalized

    @field_validator("lightrag_controller_url")
    @classmethod
    def require_controller_http_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().rstrip("/")
        parsed = urlsplit(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("LightRAG Controller URL must be an HTTP(S) origin")
        return normalized

    @field_validator("credit_cached_input_weight")
    @classmethod
    def validate_credit_cached_input_weight_precision(cls, value: Decimal) -> Decimal:
        scaled = value * Decimal(10_000)
        if scaled != scaled.to_integral_value():
            raise ValueError("Cached input weight supports at most four decimal places")
        return value

    @field_validator("acp_cwd_base", "acp_config_base")
    @classmethod
    def require_absolute_runtime_path(cls, value: str | None) -> str | None:
        if value is not None:
            path = Path(value).expanduser()
            if not path.is_absolute() or path == Path(path.anchor):
                raise ValueError("Expert runtime roots must be absolute non-root paths")
        return value

    @field_validator("acp_codex_adapter_command")
    @classmethod
    def validate_codex_adapter_command(cls, value: str) -> str:
        command = value.strip()
        path = Path(command)
        if path.name != "codex-acp":
            raise ValueError("Codex ACP adapter command must be named codex-acp")
        if command != "codex-acp" and not path.is_absolute():
            raise ValueError("Codex ACP adapter command must be codex-acp or an absolute path")
        return command

    @field_validator("acp_codex_real_adapter_command")
    @classmethod
    def validate_real_codex_adapter_command(cls, value: str) -> str:
        command = value.strip()
        path = Path(command)
        if path.name != "codex-acp" or not path.is_absolute():
            raise ValueError("Real Codex ACP adapter command must be an absolute codex-acp path")
        return command


@lru_cache
def get_settings() -> Settings:
    return Settings()
