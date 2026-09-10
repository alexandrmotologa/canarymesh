"""Configuration models for CanaryMesh proxy, routing, and rollback guard."""


from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class UpstreamConfig(BaseModel):
    """Configuration for an upstream target service."""
    name: str
    url: str
    timeout_seconds: float = Field(default=10.0, ge=0.1, le=120.0)
    health_path: str = "/healthz"


class SlaThresholds(BaseModel):
    """SLA thresholds evaluated by the automated rollback guard."""
    max_error_rate_percent: float = Field(default=1.0, ge=0.0, le=100.0)
    max_p99_latency_ms: float = Field(default=350.0, ge=1.0)
    min_sample_size: int = Field(default=10, ge=1)
    cooldown_seconds: int = Field(default=30, ge=5)


import uuid


class HeaderRoutingRule(BaseModel):
    """Header-based routing rule."""
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    header_name: str
    header_pattern: str
    target: str = "canary"
    enabled: bool = True


class PathRoutingRule(BaseModel):
    """URL path prefix routing rule."""
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    path_prefix: str
    target: str = "canary"
    enabled: bool = True


class CanaryMeshConfig(BaseSettings):
    """Primary settings for CanaryMesh runtime."""
    model_config = SettingsConfigDict(env_prefix="CANARYMESH_", extra="ignore")

    proxy_host: str = "0.0.0.0"
    proxy_port: int = 8080
    control_host: str = "0.0.0.0"
    control_port: int = 8090

    stable: UpstreamConfig = UpstreamConfig(name="stable", url="http://127.0.0.1:8081")
    canary: UpstreamConfig = UpstreamConfig(name="canary", url="http://127.0.0.1:8082")

    initial_canary_weight: float = Field(default=0.0, ge=0.0, le=100.0)
    sticky_cookie_name: str = "canary_session"
    sticky_cookie_ttl_seconds: int = 86400

    header_rules: list[HeaderRoutingRule] = Field(default_factory=list)
    path_rules: list[PathRoutingRule] = Field(default_factory=list)
    sla: SlaThresholds = Field(default_factory=SlaThresholds)
    alert_webhooks: list[str] = Field(default_factory=list)

    window_size_seconds: int = Field(default=60, ge=5, le=300)
    eval_interval_seconds: float = Field(default=1.0, ge=0.2, le=10.0)
    scenario_path: str | None = None
