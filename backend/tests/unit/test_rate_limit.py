"""Unit tests for the Redis-backed sliding-window rate limiter."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch


class TestCheckRateLimit:
    """Tests for the core sliding-window check_rate_limit function."""

    def _make_redis_mock(self, current_count: int = 1, oldest_score: float | None = None):
        """Build a mock Redis client with a pipeline that returns ``current_count``."""
        mock_redis = MagicMock()
        pipe = MagicMock()
        pipe.execute.return_value = [
            0,              # zremrangebyscore result
            True,           # zadd result
            current_count,  # zcard result
            True,           # expire result
        ]
        mock_redis.pipeline.return_value = pipe

        if oldest_score is not None:
            mock_redis.zrange.return_value = [("entry", oldest_score)]
        else:
            mock_redis.zrange.return_value = []

        return mock_redis

    def test_allows_request_under_limit(self):
        from app.api.rate_limit import check_rate_limit

        redis_mock = self._make_redis_mock(current_count=5)

        allowed, remaining, limit, retry_after = check_rate_limit(
            "org_1", "standard", redis_client=redis_mock, now=1000.0,
        )

        assert allowed is True
        assert remaining == 95
        assert limit == 100
        assert retry_after == 0.0

    def test_blocks_request_over_limit(self):
        from app.api.rate_limit import check_rate_limit

        now = 1000.0
        redis_mock = self._make_redis_mock(
            current_count=101,
            oldest_score=now - 50,
        )

        allowed, remaining, limit, retry_after = check_rate_limit(
            "org_1", "standard", redis_client=redis_mock, now=now,
        )

        assert allowed is False
        assert remaining == 0
        assert limit == 100
        assert retry_after > 0

    def test_premium_tier_has_higher_limit(self):
        from app.api.rate_limit import check_rate_limit

        redis_mock = self._make_redis_mock(current_count=500)

        allowed, remaining, limit, _retry_after = check_rate_limit(
            "org_1", "premium", redis_client=redis_mock, now=1000.0,
        )

        assert allowed is True
        assert limit == 1000
        assert remaining == 500

    def test_premium_tier_blocks_above_1000(self):
        from app.api.rate_limit import check_rate_limit

        redis_mock = self._make_redis_mock(
            current_count=1001,
            oldest_score=950.0,
        )

        allowed, remaining, limit, _retry_after = check_rate_limit(
            "org_1", "premium", redis_client=redis_mock, now=1000.0,
        )

        assert allowed is False
        assert limit == 1000
        assert remaining == 0

    def test_exactly_at_limit_is_allowed(self):
        from app.api.rate_limit import check_rate_limit

        redis_mock = self._make_redis_mock(current_count=100)

        allowed, remaining, *_ = check_rate_limit(
            "org_1", "standard", redis_client=redis_mock, now=1000.0,
        )

        assert allowed is True
        assert remaining == 0

    def test_unknown_tier_uses_default(self):
        from app.api.rate_limit import check_rate_limit

        redis_mock = self._make_redis_mock(current_count=5)

        allowed, _, limit, _ = check_rate_limit(
            "org_1", "unknown_tier", redis_client=redis_mock, now=1000.0,
        )

        assert allowed is True
        assert limit == 100  # default from settings

    def test_retry_after_calculated_from_oldest_entry(self):
        from app.api.rate_limit import check_rate_limit

        now = 1000.0
        oldest = now - 30  # 30 seconds ago -> retry in 30 seconds
        redis_mock = self._make_redis_mock(current_count=101, oldest_score=oldest)

        _, _, _, retry_after = check_rate_limit(
            "org_1", "standard", redis_client=redis_mock, now=now,
        )

        assert 29.0 <= retry_after <= 31.0

    def test_uses_redis_pipeline(self):
        from app.api.rate_limit import check_rate_limit

        redis_mock = self._make_redis_mock(current_count=1)
        pipe = redis_mock.pipeline.return_value

        check_rate_limit("org_1", "standard", redis_client=redis_mock, now=1000.0)

        redis_mock.pipeline.assert_called_once()
        pipe.zremrangebyscore.assert_called_once()
        pipe.zadd.assert_called_once()
        pipe.zcard.assert_called_once()
        pipe.expire.assert_called_once()
        pipe.execute.assert_called_once()

    def test_passes_through_when_redis_pipeline_raises(self):
        """Lazy Redis connects on execute — pod without Redis must not error."""
        from app.api.rate_limit import check_rate_limit

        redis_mock = MagicMock()
        pipe = MagicMock()
        pipe.execute.side_effect = ConnectionRefusedError(111, "Connection refused")
        redis_mock.pipeline.return_value = pipe

        allowed, remaining, limit, retry_after = check_rate_limit(
            "org_1", "standard", redis_client=redis_mock, now=1000.0,
        )

        assert allowed is True
        assert remaining == limit == 100
        assert retry_after == 0.0


class TestGetRedis:
    """``_get_redis`` must not rely on pipeline ``execute`` for first connect (k8s without Redis)."""

    def test_returns_none_when_ping_fails(self):
        from app.api import rate_limit as rl

        rl._redis_client = None
        rl._redis_unavailable_until = 0.0

        with patch("redis.Redis.from_url") as from_url:
            inst = MagicMock()
            inst.ping.side_effect = OSError("Error 111 connecting to localhost:6379")
            from_url.return_value = inst
            assert rl._get_redis() is None
            assert rl._redis_client is None
            assert rl._redis_unavailable_until > 0.0


class TestOrgIdExtraction:
    """Tests for _org_id_from_request helper."""

    def _make_request(self, headers=None, query_params=None, client_host="127.0.0.1"):
        request = MagicMock()
        request.headers = headers or {}
        request.query_params = query_params or {}
        client = MagicMock()
        client.host = client_host
        request.client = client
        return request

    def test_uses_x_org_id_header(self):
        from app.api.rate_limit import _org_id_from_request

        req = self._make_request(headers={"X-Org-Id": "org_42"})
        assert _org_id_from_request(req) == "org_42"

    def test_falls_back_to_query_param(self):
        from app.api.rate_limit import _org_id_from_request

        req = self._make_request(query_params={"org_id": "org_99"})
        assert _org_id_from_request(req) == "org_99"

    def test_falls_back_to_client_ip(self):
        from app.api.rate_limit import _org_id_from_request

        req = self._make_request(client_host="10.0.0.5")
        assert _org_id_from_request(req) == "10.0.0.5"

    def test_header_takes_priority_over_query_param(self):
        from app.api.rate_limit import _org_id_from_request

        req = self._make_request(
            headers={"X-Org-Id": "from_header"},
            query_params={"org_id": "from_query"},
        )
        assert _org_id_from_request(req) == "from_header"


class TestRateLimitMiddleware:
    """Tests for the FastAPI middleware integration."""

    @patch("app.api.rate_limit.check_rate_limit")
    @patch("app.api.rate_limit.settings")
    def test_returns_429_when_limit_exceeded(self, mock_settings, mock_check):
        from app.api.rate_limit import RateLimitMiddleware

        mock_settings.rate_limit_enabled = True
        mock_settings.rate_limit_default_tier = "standard"
        mock_check.return_value = (False, 0, 100, 30.0)

        middleware = RateLimitMiddleware(app=MagicMock())
        request = MagicMock()
        request.url.path = "/api/v1/ontologies"
        request.headers = {}
        request.query_params = {}
        request.client.host = "10.0.0.1"

        import asyncio

        response = asyncio.get_event_loop().run_until_complete(
            middleware.dispatch(request, MagicMock())
        )

        assert response.status_code == 429
        assert response.headers["Retry-After"] == "31"

    @patch("app.api.rate_limit.settings")
    def test_skips_when_disabled(self, mock_settings):
        from app.api.rate_limit import RateLimitMiddleware

        mock_settings.rate_limit_enabled = False

        middleware = RateLimitMiddleware(app=MagicMock())
        request = MagicMock()
        request.url.path = "/api/v1/ontologies"

        MagicMock()  # mock_next unused, dispatch takes call_next directly
        mock_response = MagicMock()

        import asyncio

        async def fake_next(req):
            return mock_response

        response = asyncio.get_event_loop().run_until_complete(
            middleware.dispatch(request, fake_next)
        )

        assert response is mock_response

    @patch("app.api.rate_limit.settings")
    def test_skips_exempt_paths(self, mock_settings):
        from app.api.rate_limit import RateLimitMiddleware

        mock_settings.rate_limit_enabled = True

        middleware = RateLimitMiddleware(app=MagicMock())
        request = MagicMock()
        request.url.path = "/health"

        mock_response = MagicMock()

        import asyncio

        async def fake_next(req):
            return mock_response

        response = asyncio.get_event_loop().run_until_complete(
            middleware.dispatch(request, fake_next)
        )

        assert response is mock_response

    @patch("app.api.rate_limit.check_rate_limit")
    @patch("app.api.rate_limit.settings")
    def test_adds_rate_limit_headers_on_success(self, mock_settings, mock_check):
        from app.api.rate_limit import RateLimitMiddleware

        mock_settings.rate_limit_enabled = True
        mock_settings.rate_limit_default_tier = "standard"
        mock_check.return_value = (True, 95, 100, 0.0)

        middleware = RateLimitMiddleware(app=MagicMock())
        request = MagicMock()
        request.url.path = "/api/v1/ontologies"
        request.headers = {}
        request.query_params = {}
        request.client.host = "10.0.0.1"

        mock_response = MagicMock()
        mock_response.headers = {}

        import asyncio

        async def fake_next(req):
            return mock_response

        response = asyncio.get_event_loop().run_until_complete(
            middleware.dispatch(request, fake_next)
        )

        assert response.headers["X-RateLimit-Limit"] == "100"
        assert response.headers["X-RateLimit-Remaining"] == "95"

    @patch("app.api.rate_limit.check_rate_limit", side_effect=Exception("Redis down"))
    @patch("app.api.rate_limit.settings")
    def test_allows_request_when_redis_fails(self, mock_settings, mock_check):
        """Rate limiter degrades gracefully — if Redis is down, requests pass through."""
        from app.api.rate_limit import RateLimitMiddleware

        mock_settings.rate_limit_enabled = True
        mock_settings.rate_limit_default_tier = "standard"

        middleware = RateLimitMiddleware(app=MagicMock())
        request = MagicMock()
        request.url.path = "/api/v1/ontologies"
        request.headers = {}
        request.query_params = {}
        request.client.host = "10.0.0.1"

        mock_response = MagicMock()

        import asyncio

        async def fake_next(req):
            return mock_response

        response = asyncio.get_event_loop().run_until_complete(
            middleware.dispatch(request, fake_next)
        )

        assert response is mock_response


class TestSnapshotCache:
    """Tests for the materialized snapshot cache on temporal.py."""

    def test_cache_hit_skips_db_query(self):
        from app.services.temporal import (
            _snapshot_cache,
            _snapshot_cache_key,
            _snapshot_cache_put,
            get_snapshot,
        )

        ontology_id = "test_onto"
        ts = 1000.0
        cache_key = _snapshot_cache_key(ontology_id, ts)
        cached_data = {
            "ontology_id": ontology_id,
            "timestamp": ts,
            "classes": [{"_key": "c1"}],
            "properties": [],
            "edges": [],
        }
        _snapshot_cache_put(cache_key, cached_data)

        try:
            result = get_snapshot(ontology_id=ontology_id, timestamp=ts)
            assert result == cached_data
        finally:
            _snapshot_cache.pop(cache_key, None)

    def test_bypass_cache_ignores_cached_entry(self):
        from app.services.temporal import (
            _snapshot_cache,
            _snapshot_cache_key,
            _snapshot_cache_put,
        )

        ontology_id = "test_onto"
        ts = 2000.0
        cache_key = _snapshot_cache_key(ontology_id, ts)
        _snapshot_cache_put(cache_key, {"ontology_id": ontology_id, "stale": True})

        try:
            from app.services.temporal import get_snapshot

            mock_db = MagicMock()
            mock_db.has_collection.return_value = False
            result = get_snapshot(mock_db, ontology_id=ontology_id, timestamp=ts, bypass_cache=True)
            assert result["ontology_id"] == ontology_id
            assert "stale" not in result
        finally:
            _snapshot_cache.pop(cache_key, None)

    def test_invalidation_clears_entries(self):
        from app.services.temporal import (
            _snapshot_cache,
            _snapshot_cache_key,
            _snapshot_cache_put,
            invalidate_snapshot_cache,
        )

        ontology_id = "inv_test"
        for ts in [1000.0, 2000.0, 3000.0]:
            key = _snapshot_cache_key(ontology_id, ts)
            _snapshot_cache_put(key, {"ontology_id": ontology_id, "timestamp": ts})

        try:
            removed = invalidate_snapshot_cache(ontology_id)
            assert removed == 3

            for ts in [1000.0, 2000.0, 3000.0]:
                key = _snapshot_cache_key(ontology_id, ts)
                assert key not in _snapshot_cache
        finally:
            pass

    def test_ttl_expiry(self):
        from app.services.temporal import (
            _snapshot_cache,
            _snapshot_cache_get,
            _snapshot_cache_key,
        )

        ontology_id = "ttl_test"
        ts = 5000.0
        cache_key = _snapshot_cache_key(ontology_id, ts)
        _snapshot_cache[cache_key] = (
            time.time() - 301,
            {"ontology_id": ontology_id},
        )

        try:
            result = _snapshot_cache_get(cache_key)
            assert result is None
        finally:
            _snapshot_cache.pop(cache_key, None)

    def test_cache_key_includes_precise_timestamp(self):
        from app.services.temporal import _snapshot_cache_key

        key_a = _snapshot_cache_key("onto1", 960.0)
        key_b = _snapshot_cache_key("onto1", 975.0)
        key_c = _snapshot_cache_key("onto1", 960.0)

        assert key_a != key_b
        assert key_a == key_c
