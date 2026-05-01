"""DocMind Agent settings configuration."""

from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    app_name: str = "DocMind Agent"
    app_env: str = "development"
    app_debug: bool = True
    app_secret_key: str = "change-me-to-a-random-secret-key"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_auto_create_tables: bool = True
    app_cors_origins: str = "http://localhost:5173,http://localhost:3000"
    max_upload_size_mb: int = 100
    app_metrics_enabled: bool = True
    bootstrap_demo_admin_enabled: bool = True
    bootstrap_demo_admin_username: str = "admin_demo"
    bootstrap_demo_admin_password: str = "Password123"
    bootstrap_demo_admin_email: str = "admin_demo@docmind.local"
    bootstrap_demo_admin_tenant_id: str = "default"
    bootstrap_demo_admin_department: str = "Platform"
    docmind_reports_dir: Path = Path("reports")
    docmind_shared_datasets_dir: Path = Path("datasets")

    jwt_secret_key: str = "change-me-to-a-random-jwt-secret"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "docmind"
    postgres_password: str = "docmind_password"
    postgres_db: str = "docmind_db"
    postgres_pool_size: int = 80
    postgres_max_overflow: int = 80
    postgres_pool_timeout_seconds: int = 30

    @property
    def postgres_dsn(self) -> str:
        return f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"

    @property
    def postgres_dsn_sync(self) -> str:
        return f"postgresql://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"

    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str = ""
    redis_db: int = 0

    @property
    def redis_url(self) -> str:
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    milvus_host: str = "localhost"
    milvus_port: int = 19530
    milvus_collection: str = "docmind_vectors"

    es_host: str = "localhost"
    es_port: int = 9200
    es_index: str = "docmind_documents"

    @property
    def es_url(self) -> str:
        return f"http://{self.es_host}:{self.es_port}"

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "neo4j_password"

    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "docmind-documents"
    minio_secure: bool = False

    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"
    celery_default_queue: str = "default"
    celery_ingestion_queue: str = "ingestion"
    celery_reindex_queue: str = "reindex"
    celery_maintenance_queue: str = "maintenance"
    celery_task_soft_time_limit_seconds: int = 900
    celery_task_time_limit_seconds: int = 1200

    llm_provider: str = "local"
    llm_api_key: str = ""
    llm_api_base_url: str = "http://localhost:11434/v1"
    llm_model_name: str = "qwen2.5:1.5b"
    llm_canary_percent: int = 10
    llm_canary_seed: str = "docmind-llm"
    llm_enterprise_enabled: bool = False
    llm_enterprise_api_base_url: str = ""
    llm_enterprise_model_name: str = ""
    llm_enterprise_api_key: str = ""
    llm_enterprise_keywords: str = "制度,审批,流程,合规,预算,采购,合同,报销,风控,审计,人事,绩效,会议纪要,管理办法"
    llm_enterprise_force_tenants: str = ""
    llm_enterprise_canary_percent: int = 0
    llm_enterprise_canary_seed: str = "docmind-enterprise-llm"
    llm_enterprise_corpus_min_chars: int = 80
    llm_training_provider: str = "mock"
    llm_training_base_model: str = "qwen2.5:7b"
    llm_training_artifacts_subdir: str = "model_training"
    llm_training_min_train_records: int = 20
    llm_training_auto_activate: bool = True
    llm_training_executor_api_base_url: str = ""
    llm_training_executor_api_key: str = ""
    llm_training_executor_timeout_seconds: int = 1800
    llm_training_executor_poll_interval_seconds: int = 5
    llm_training_executor_script_command: str = ""
    llm_training_executor_script_workdir: str = ""
    llm_training_task_soft_time_limit_seconds: int = 7200
    llm_training_task_time_limit_seconds: int = 7500
    llm_training_progress_heartbeat_seconds: int = 30
    llm_training_runtime_stale_seconds: int = 300
    llm_training_publish_enabled: bool = False
    llm_training_publish_command: str = ""
    llm_training_publish_workdir: str = ""
    llm_training_deploy_fail_rollback: bool = True
    llm_training_deploy_verify_enabled: bool = True
    llm_training_deploy_health_path: str = ""
    llm_training_deploy_verify_timeout_seconds: int = 20

    embedding_provider: str = "local"
    embedding_model_name: str = "BAAI/bge-m3"
    embedding_api_key: str = ""
    embedding_api_base_url: str = ""
    embedding_canary_percent: int = 10
    embedding_canary_seed: str = "docmind-embedding"

    reranker_provider: str = "local"
    reranker_model_name: str = "BAAI/bge-reranker-v2-m3"
    reranker_api_key: str = ""
    reranker_api_base_url: str = ""
    reranker_canary_percent: int = 10
    reranker_canary_seed: str = "docmind-reranker"
    vector_local_fallback_enabled: bool = False
    hybrid_vector_enabled: bool = False

    ocr_provider: str = "paddleocr"

    semantic_cache_enabled: bool = True
    semantic_cache_threshold: float = 0.95
    semantic_cache_ttl_seconds: int = 300
    semantic_cache_collection: str = "docmind_semantic_cache"
    semantic_cache_top_k: int = 3

    pii_masking_enabled: bool = True
    pii_presidio_enabled: bool = False
    guardrails_enabled: bool = True
    guardrails_sidecar_url: str = ""
    guardrails_fail_closed: bool = False
    watermark_enabled: bool = True
    runtime_stage_timeout_seconds: int = 600
    runtime_event_replay_ttl_seconds: int = 1800
    runtime_task_retention_seconds: int = 7200
    runtime_keepalive_seconds: int = 15
    runtime_langgraph_native_checkpoint_enabled: bool = True
    runtime_maintenance_alert_repaired_ttl_threshold: int = 50
    runtime_maintenance_alert_empty_replay_threshold: int = 100
    security_policy_profile: str = "enterprise"  # enterprise | financial
    clamav_enabled: bool = False
    clamav_fail_closed: bool = False
    clamav_host: str = "localhost"
    clamav_port: int = 3310
    auth_allow_public_registration: bool = False
    auth_stateless_jwt_context: bool = True
    auth_allowlist_domains: str = ""
    auth_blocklist_domains: str = "mailinator.com,10minutemail.com,guerrillamail.com,temp-mail.org"
    auth_mobile_oauth_enabled: bool = True
    auth_mobile_oauth_clients: str = "docmind-capacitor,docmind-miniapp"
    auth_mobile_oauth_redirect_uris: str = "docmind://auth/callback,https://servicewechat.com/docmind/callback"
    auth_mobile_authorization_code_expire_minutes: int = 5

    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "http://localhost:3000"
    push_notifications_enabled: bool = True
    push_notification_provider: str = "log"
    push_notification_webhook_url: str = ""
    push_notification_fail_closed: bool = False
    push_auto_deactivate_invalid_tokens: bool = True
    push_fcm_endpoint: str = "https://fcm.googleapis.com/fcm/send"
    push_fcm_server_key: str = ""
    push_fcm_access_token: str = ""
    push_fcm_project_id: str = ""
    push_fcm_service_account_file: str = ""
    push_apns_endpoint: str = "https://api.push.apple.com"
    push_apns_topic: str = ""
    push_apns_auth_token: str = ""
    push_apns_priority: str = "10"
    push_wechat_access_token: str = ""
    push_wechat_template_id: str = ""
    push_wechat_page: str = "pages/docs/index"
    push_wechat_miniprogram_state: str = "developer"
    push_wechat_lang: str = "zh_CN"
    ragas_api_base_url: str = ""
    ragas_api_key: str = ""
    ragas_timeout_seconds: int = 420
    ragas_require_real_mode: bool = False
    ci_gate_min_runtime_samples: int = 1
    ci_gate_max_fallback_rate: float = 0.8
    ci_gate_max_deny_rate: float = 0.8
    ci_gate_require_real_ragas: bool = False
    ci_gate_min_faithfulness: float = 0.85
    ci_gate_min_answer_relevancy: float = 0.8
    ci_gate_min_context_precision: float = 0.8
    ci_gate_min_context_recall: float = 0.8
    ci_gate_eval_sample_limit: int = 3
    ci_gate_min_eval_dataset_size: int = 3

    @property
    def cors_origins(self) -> List[str]:
        return [origin.strip() for origin in self.app_cors_origins.split(",") if origin.strip()]

    @property
    def auth_allowlist_domain_list(self) -> List[str]:
        return [domain.strip().lower() for domain in self.auth_allowlist_domains.split(",") if domain.strip()]

    @property
    def auth_blocklist_domain_list(self) -> List[str]:
        return [domain.strip().lower() for domain in self.auth_blocklist_domains.split(",") if domain.strip()]

    @property
    def auth_mobile_oauth_client_list(self) -> List[str]:
        return [client.strip() for client in self.auth_mobile_oauth_clients.split(",") if client.strip()]

    @property
    def auth_mobile_oauth_redirect_uri_list(self) -> List[str]:
        return [uri.strip() for uri in self.auth_mobile_oauth_redirect_uris.split(",") if uri.strip()]

    @property
    def llm_enterprise_keyword_list(self) -> List[str]:
        return [keyword.strip() for keyword in self.llm_enterprise_keywords.split(",") if keyword.strip()]

    @property
    def llm_enterprise_force_tenant_list(self) -> List[str]:
        return [tenant.strip() for tenant in self.llm_enterprise_force_tenants.split(",") if tenant.strip()]

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore")


settings = Settings()



