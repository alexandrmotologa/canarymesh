"""Unit tests for URL path prefix routing and dynamic rule management."""

from canarymesh.config import CanaryMeshConfig, PathRoutingRule, UpstreamConfig
from canarymesh.proxy.router import TrafficRouter


def test_path_prefix_routing():
    cfg = CanaryMeshConfig(
        stable=UpstreamConfig(name="stable", url="http://127.0.0.1:8081"),
        canary=UpstreamConfig(name="canary", url="http://127.0.0.1:8082"),
        initial_canary_weight=0.0,
        path_rules=[
            PathRoutingRule(path_prefix="/api/v2/", target="canary"),
            PathRoutingRule(path_prefix="/checkout", target="canary"),
        ],
    )
    router = TrafficRouter(cfg)

    # Paths matching prefix should route to canary
    decision_v2 = router.route(headers={}, cookies={}, query_params={}, path="/api/v2/users")
    assert decision_v2.upstream_name == "canary"
    assert decision_v2.reason == "path_rule:/api/v2/"

    decision_checkout = router.route(headers={}, cookies={}, query_params={}, path="/checkout")
    assert decision_checkout.upstream_name == "canary"

    # Other paths route to stable (0% weight)
    decision_v1 = router.route(headers={}, cookies={}, query_params={}, path="/api/v1/users")
    assert decision_v1.upstream_name == "stable"


def test_dynamic_rule_registration():
    cfg = CanaryMeshConfig(
        stable=UpstreamConfig(name="stable", url="http://127.0.0.1:8081"),
        canary=UpstreamConfig(name="canary", url="http://127.0.0.1:8082"),
        initial_canary_weight=0.0,
    )
    router = TrafficRouter(cfg)

    # Initial check: no path rules
    decision = router.route(headers={}, cookies={}, query_params={}, path="/experimental")
    assert decision.upstream_name == "stable"

    # Add dynamic path rule
    rule_id = router.add_path_rule(PathRoutingRule(path_prefix="/experimental", target="canary"))
    decision_after = router.route(headers={}, cookies={}, query_params={}, path="/experimental/test")
    assert decision_after.upstream_name == "canary"

    # Remove dynamic path rule
    removed = router.remove_path_rule(rule_id)
    assert removed is True

    decision_reverted = router.route(headers={}, cookies={}, query_params={}, path="/experimental/test")
    assert decision_reverted.upstream_name == "stable"
