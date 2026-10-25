"""UUIDv7 identifiers (RFC 9562): time-ordered, so primary-key indexes stay compact.

Python 3.12 has no `uuid.uuid7`, so it is implemented here. IDs from this process are
strictly increasing, even within the same millisecond.
"""

import secrets
import threading
import time
from datetime import datetime
from uuid import UUID

_VERSION = 0x7
_VARIANT = 0b10
_RAND_BITS = 74  # 12 bits rand_a + 62 bits rand_b
_RAND_MASK = (1 << _RAND_BITS) - 1

_lock = threading.Lock()
_last_ms = -1
_last_rand = 0


def _pack(unix_ms: int, rand: int) -> UUID:
    rand_a = rand >> 62
    rand_b = rand & ((1 << 62) - 1)
    value = (unix_ms << 80) | (_VERSION << 76) | (rand_a << 64) | (_VARIANT << 62) | rand_b
    return UUID(int=value)


def new_id(at: datetime | None = None) -> UUID:
    """Return a new UUIDv7.

    `at` sets the embedded timestamp (for tests and backfills); IDs created with an explicit
    `at` are not part of the monotonic sequence.
    """
    if at is not None:
        return _pack(int(at.timestamp() * 1000), secrets.randbits(_RAND_BITS))

    global _last_ms, _last_rand
    with _lock:
        unix_ms = time.time_ns() // 1_000_000
        if unix_ms > _last_ms:
            rand = secrets.randbits(_RAND_BITS)
        else:
            # Same millisecond (or the wall clock stepped back): keep ordering by counting
            # up from the previous value, carrying into the timestamp on overflow.
            unix_ms = _last_ms
            rand = _last_rand + 1
            if rand > _RAND_MASK:
                unix_ms += 1
                rand = secrets.randbits(_RAND_BITS)
        _last_ms, _last_rand = unix_ms, rand
    return _pack(unix_ms, rand)


def id_timestamp_ms(value: UUID) -> int:
    """Unix milliseconds embedded in a UUIDv7."""
    return value.int >> 80
