"""Redis stub — Redis was stripped from the bundled core.

Every consumer in the original we-mp-rss already falls back to local
files / in-process globals when Redis is unavailable, so this stub simply
reports ``is_connected=False`` and the fallback paths take over.
"""


class _RedisClientStub:
    is_connected = False
    _client = None


redis_client = _RedisClientStub()
