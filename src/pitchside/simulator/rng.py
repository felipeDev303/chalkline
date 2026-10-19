"""Seeded randomness for the simulator.

Everything is built on `random.Random.random()` (Mersenne Twister, stable across
Python versions and platforms) plus plain arithmetic. We deliberately avoid
`random.gauss`, `random.choices` and anything that calls `math.log`/`math.cos`,
whose last bits may differ between C maths libraries.
"""

from __future__ import annotations

import random
from collections.abc import Sequence


class Rng:
    def __init__(self, seed: int) -> None:
        self._r = random.Random(seed)

    def random(self) -> float:
        return self._r.random()

    def uniform(self, lo: float, hi: float) -> float:
        return lo + (hi - lo) * self._r.random()

    def chance(self, p: float) -> bool:
        return self._r.random() < p

    def index(self, n: int) -> int:
        return min(int(self._r.random() * n), n - 1)

    def choice[T](self, items: Sequence[T]) -> T:
        return items[self.index(len(items))]

    def weighted_index(self, weights: Sequence[float]) -> int:
        total = 0.0
        for w in weights:
            total += w
        r = self._r.random() * total
        acc = 0.0
        for i, w in enumerate(weights):
            acc += w
            if r < acc:
                return i
        return max(i for i, w in enumerate(weights) if w > 0)

    def normal(self, mu: float, sd: float) -> float:
        """Approximate normal draw (Irwin-Hall: sum of 12 uniforms)."""
        s = 0.0
        for _ in range(12):
            s += self._r.random()
        return mu + sd * (s - 6.0)
