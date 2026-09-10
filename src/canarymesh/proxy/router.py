"""Routing decision engine for traffic splitting between stable and canary."""

import hashlib
import re
import uuid
from dataclasses import dataclass

from canarymesh.config import CanaryMeshConfig, UpstreamConfig


@dataclass
class RouteDecision:
    """Outcome of a traffic routing evaluation."""
    target: UpstreamConfig
    upstream_name: str
    reason: str
    session_id: str | None = None
    is_new_session: bool = False


class TrafficRouter:
    """Evaluates incoming request attributes to select upstream target."""

    def __init__(self, config: CanaryMeshConfig):
        self.config = config
        self._canary_weight = float(config.initial_canary_weight)
        self._compiled_rules: list[tuple[str, re.Pattern, str]] = []
        for rule in config.header_rules:
            self._compiled_rules.append(
                (rule.header_name.lower(), re.compile(rule.header_pattern), rule.target)
            )

    @property
    def canary_weight(self) -> float:
        """Current canary weight percentage (0.0 to 100.0)."""
        return self._canary_weight

    def set_weight(self, weight: float) -> None:
        """Update the canary traffic percentage."""
        self._canary_weight = max(0.0, min(100.0, float(weight)))

    def route(
        self,
        headers: dict[str, str],
        cookies: dict[str, str],
        query_params: dict[str, str],
    ) -> RouteDecision:
        """Determine upstream destination for an incoming request."""
        # 1. Query parameter override (?canary=true / ?canary=false)
        query_canary = query_params.get("canary", "").lower()
        if query_canary in ("true", "1", "yes"):
            return RouteDecision(
                target=self.config.canary,
                upstream_name="canary",
                reason="query_param_override",
            )
        if query_canary in ("false", "0", "no"):
            return RouteDecision(
                target=self.config.stable,
                upstream_name="stable",
                reason="query_param_override",
            )

        # 2. Direct X-Canary header override
        header_canary = headers.get("x-canary", "").lower()
        if header_canary in ("true", "1", "yes"):
            return RouteDecision(
                target=self.config.canary,
                upstream_name="canary",
                reason="header_canary_override",
            )
        if header_canary in ("false", "0", "no"):
            return RouteDecision(
                target=self.config.stable,
                upstream_name="stable",
                reason="header_canary_override",
            )

        # 3. Custom configured header rules (e.g. X-User-Group: beta-*)
        for header_key, pattern, target_name in self._compiled_rules:
            val = headers.get(header_key, "")
            if val and pattern.search(val):
                target = self.config.canary if target_name == "canary" else self.config.stable
                return RouteDecision(
                    target=target,
                    upstream_name=target_name,
                    reason=f"header_rule:{header_key}",
                )

        # 4. Sticky session cookie
        cookie_name = self.config.sticky_cookie_name
        session_id = cookies.get(cookie_name)
        is_new_session = False

        if not session_id:
            session_id = uuid.uuid4().hex
            is_new_session = True

        # Calculate consistent deterministic hash bucket (0 - 99)
        bucket = int(hashlib.md5(session_id.encode("utf-8")).hexdigest(), 16) % 100

        if self._canary_weight > 0 and bucket < self._canary_weight:
            return RouteDecision(
                target=self.config.canary,
                upstream_name="canary",
                reason="sticky_cookie_bucket" if not is_new_session else "weighted_split",
                session_id=session_id,
                is_new_session=is_new_session,
            )

        return RouteDecision(
            target=self.config.stable,
            upstream_name="stable",
            reason="sticky_cookie_bucket" if not is_new_session else "weighted_split",
            session_id=session_id,
            is_new_session=is_new_session,
        )
