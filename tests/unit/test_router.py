"""Unit tests for traffic router."""

from canarymesh.config import CanaryMeshConfig, HeaderRoutingRule, UpstreamConfig
from canarymesh.proxy.router import TrafficRouter


def create_test_router(weight: float = 0.0, rules=None) -> TrafficRouter:
    cfg = CanaryMeshConfig(
        stable=UpstreamConfig(name="stable", url="http://127.0.0.1:8081"),
        canary=UpstreamConfig(name="canary", url="http://127.0.0.1:8082"),
        initial_canary_weight=weight,
        header_rules=rules or [],
    )
    return TrafficRouter(cfg)


def test_router_header_canary_override():
    router = create_test_router(weight=0.0)

    # With X-Canary: true
    decision = router.route(headers={"x-canary": "true"}, cookies={}, query_params={})
    assert decision.upstream_name == "canary"
    assert decision.reason == "header_canary_override"

    # With X-Canary: false
    decision = router.route(headers={"x-canary": "false"}, cookies={}, query_params={})
    assert decision.upstream_name == "stable"


def test_router_query_param_override():
    router = create_test_router(weight=0.0)

    decision = router.route(headers={}, cookies={}, query_params={"canary": "1"})
    assert decision.upstream_name == "canary"
    assert decision.reason == "query_param_override"

    decision = router.route(headers={}, cookies={}, query_params={"canary": "0"})
    assert decision.upstream_name == "stable"


def test_router_custom_header_rule():
    rule = HeaderRoutingRule(
        header_name="X-User-Group",
        header_pattern=r"^beta-.*",
        target="canary",
    )
    router = create_test_router(weight=0.0, rules=[rule])

    decision = router.route(headers={"x-user-group": "beta-testers"}, cookies={}, query_params={})
    assert decision.upstream_name == "canary"
    assert decision.reason == "header_rule:x-user-group"

    decision = router.route(headers={"x-user-group": "standard-user"}, cookies={}, query_params={})
    assert decision.upstream_name == "stable"


def test_router_sticky_cookie_consistency():
    router = create_test_router(weight=50.0)
    session_id = "test-session-token-12345"

    decision1 = router.route(headers={}, cookies={"canary_session": session_id}, query_params={})
    decision2 = router.route(headers={}, cookies={"canary_session": session_id}, query_params={})

    assert decision1.upstream_name == decision2.upstream_name
    assert decision1.reason == "sticky_cookie_bucket"


def test_router_weighted_distribution():
    # Test 0% canary
    router_zero = create_test_router(weight=0.0)
    for i in range(100):
        decision = router_zero.route(headers={}, cookies={"canary_session": f"sess-{i}"}, query_params={})
        assert decision.upstream_name == "stable"

    # Test 100% canary
    router_full = create_test_router(weight=100.0)
    for i in range(100):
        decision = router_full.route(headers={}, cookies={"canary_session": f"sess-{i}"}, query_params={})
        assert decision.upstream_name == "canary"

    # Test 30% canary over 1000 uniform sessions
    router_split = create_test_router(weight=30.0)
    canary_count = 0
    total = 1000
    for i in range(total):
        decision = router_split.route(headers={}, cookies={"canary_session": f"user-{i}"}, query_params={})
        if decision.upstream_name == "canary":
            canary_count += 1

    ratio = canary_count / total
    # Consistent hash distribution across 1000 items should be within 25% - 35%
    assert 0.25 <= ratio <= 0.35
