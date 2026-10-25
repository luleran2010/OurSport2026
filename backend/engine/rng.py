"""A deterministic random number generator for auditable results (draws, simulations).

Python's `random` does not promise the same shuffle across versions; this generator is a
SHA-256 counter stream, so anyone with the inputs and the published seed can reproduce a
draw exactly, on any platform, years later.
"""

import hashlib
from collections.abc import Sequence

_DOMAIN = b"oursport-rng-v1"
_U64 = 1 << 64


class DeterministicRng:
    def __init__(self, seed: bytes) -> None:
        self._prefix = _DOMAIN + len(seed).to_bytes(4, "big") + seed
        self._counter = 0
        self._buffer = b""

    def _next_u64(self) -> int:
        if len(self._buffer) < 8:
            block = hashlib.sha256(self._prefix + self._counter.to_bytes(8, "big")).digest()
            self._buffer += block
            self._counter += 1
        value, self._buffer = int.from_bytes(self._buffer[:8], "big"), self._buffer[8:]
        return value

    def randbelow(self, n: int) -> int:
        """Uniform integer in [0, n), without modulo bias."""
        if n <= 0:
            raise ValueError("n must be positive")
        limit = _U64 - (_U64 % n)
        while True:
            value = self._next_u64()
            if value < limit:
                return value % n

    def shuffled[T](self, items: Sequence[T]) -> list[T]:
        """A uniformly random permutation (Fisher-Yates)."""
        result = list(items)
        for i in range(len(result) - 1, 0, -1):
            j = self.randbelow(i + 1)
            result[i], result[j] = result[j], result[i]
        return result
