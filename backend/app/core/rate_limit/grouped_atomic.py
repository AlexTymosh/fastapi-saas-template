from __future__ import annotations

from dataclasses import dataclass
from typing import Any

GROUPED_REDIS_HASH_TAG = "{rl-grouped-v1}"

GROUPED_FIXED_WINDOW_CONSUME_LUA = """
local n = tonumber(ARGV[1])
for i = 1, n do
  local limit_value = tonumber(ARGV[1 + i])
  local current = tonumber(redis.call('GET', KEYS[i]) or '0')
  if current >= limit_value then
    local ttl_ms = redis.call('PTTL', KEYS[i])
    if ttl_ms < 0 then
      ttl_ms = tonumber(ARGV[1 + n + i])
      redis.call('PEXPIRE', KEYS[i], ttl_ms)
    end
    return {0, i, ttl_ms}
  end
end
for i = 1, n do
  local next_value = redis.call('INCR', KEYS[i])
  local ttl_ms = redis.call('PTTL', KEYS[i])
  if next_value == 1 or ttl_ms < 0 then
    redis.call('PEXPIRE', KEYS[i], tonumber(ARGV[1 + n + i]))
  end
end
return {1, 0, 0}
""".strip()


@dataclass(frozen=True)
class GroupedBucketSpec:
    key: str
    limit: int
    expiry_seconds: int


@dataclass(frozen=True)
class GroupedConsumeResult:
    allowed: bool
    blocked_index: int | None
    retry_after_seconds: int | None


def build_grouped_redis_key(*, namespace: str, bucket_key: str) -> str:
    """Build a grouped rate-limit key that is safe for Redis Cluster Lua.

    Redis Cluster requires all keys touched by one script invocation to live in
    the same hash slot. A shared hash tag preserves the all-or-nothing Lua path
    for grouped checks while keeping the existing HMAC identifier as the only
    per-subject key material.
    """

    return f"{GROUPED_REDIS_HASH_TAG}:{namespace}:{bucket_key}"


_CLUSTER_FALLBACK_PREFIXES = frozenset({"moved", "ask", "tryagain", "clusterdown"})


def is_redis_cluster_fallback_error(exc: Exception) -> bool:
    """Return True for Redis Cluster errors that should degrade to fallback.

    Redis Cluster may reject or redirect a grouped Lua request during normal
    cluster operation and resharding. Some clients expose dedicated exception
    classes, while others surface plain RedisError instances with server error
    text. Detect the stable server error prefixes and same-slot failures without
    importing version-specific redis-py cluster exception classes.
    """

    error_name = exc.__class__.__name__.lower().replace("_", "").replace("-", "")
    error_text = str(exc).strip().lower()
    compact_text = error_text.replace("_", "").replace("-", "")
    first_token = error_text.split(maxsplit=1)[0].lstrip("-") if error_text else ""

    if (
        "crossslot" in error_name
        or "crossslot" in compact_text
        or "cross slot" in error_text
        or "same slot" in error_text
        or "same key slot" in error_text
    ):
        return True

    if first_token in _CLUSTER_FALLBACK_PREFIXES:
        return True

    return any(
        marker in error_name
        for marker in ("moved", "askerror", "tryagain", "clusterdown")
    )


def is_redis_cross_slot_error(exc: Exception) -> bool:
    """Backward-compatible alias for older imports/tests."""

    return is_redis_cluster_fallback_error(exc)


def maybe_get_async_redis_client(storage: Any) -> Any | None:
    """Best-effort fallback discovery for non-standard Redis-backed runtimes.

    Production initialisation now stores an explicit `grouped_redis_client` on
    `RateLimiterRuntime`. This helper remains only as a compatibility fallback
    for tests, custom runtimes, or older initialisation paths.
    """

    return _find_eval_client(storage, seen=set(), depth=0)


def _find_eval_client(
    candidate: Any,
    *,
    seen: set[int],
    depth: int,
) -> Any | None:
    if candidate is None or depth > 4:
        return None

    candidate_id = id(candidate)
    if candidate_id in seen:
        return None
    seen.add(candidate_id)

    if callable(getattr(candidate, "eval", None)):
        return candidate

    for attr in (
        "grouped_redis_client",
        "bridge",
        "storage",
        "_storage",
        "client",
        "_client",
        "redis",
        "_redis",
    ):
        child = getattr(candidate, attr, None)
        found = _find_eval_client(child, seen=seen, depth=depth + 1)
        if found is not None:
            return found

    get_conn = getattr(candidate, "get_connection", None)
    if callable(get_conn):
        try:
            child = get_conn()
        except Exception:
            return None
        return _find_eval_client(child, seen=seen, depth=depth + 1)

    return None


async def atomic_consume_grouped_buckets(
    *, redis_client: Any, buckets: list[GroupedBucketSpec]
) -> GroupedConsumeResult:
    keys = [bucket.key for bucket in buckets]
    argv: list[int] = [len(buckets)]
    argv.extend(bucket.limit for bucket in buckets)
    argv.extend(bucket.expiry_seconds * 1000 for bucket in buckets)
    raw_result = await redis_client.eval(
        GROUPED_FIXED_WINDOW_CONSUME_LUA,
        len(keys),
        *keys,
        *argv,
    )
    allowed = int(raw_result[0]) == 1
    if allowed:
        return GroupedConsumeResult(
            allowed=True, blocked_index=None, retry_after_seconds=None
        )
    blocked_position = int(raw_result[1])
    ttl_ms = int(raw_result[2])
    if ttl_ms < 1:
        bucket = buckets[max(blocked_position - 1, 0)]
        ttl_ms = bucket.expiry_seconds * 1000
    retry_after = max(1, (ttl_ms + 999) // 1000)
    return GroupedConsumeResult(
        allowed=False,
        blocked_index=max(0, blocked_position - 1),
        retry_after_seconds=retry_after,
    )
