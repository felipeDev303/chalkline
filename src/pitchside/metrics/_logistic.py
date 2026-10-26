"""A fitted logistic regression: probability and per-feature effects."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Logistic:
    features: tuple[str, ...]
    intercept: float
    coefs: tuple[float, ...]
    means: tuple[float, ...]  # training means: the "average" case effects are measured from
    n_train: int
    positives: int

    def log_odds(self, x: tuple[float, ...]) -> float:
        return self.intercept + sum(c * v for c, v in zip(self.coefs, x, strict=True))

    def prob(self, x: tuple[float, ...]) -> float:
        return 1.0 / (1.0 + math.exp(-self.log_odds(x)))

    def effects(self, x: tuple[float, ...]) -> dict[str, float]:
        """Each feature's push on the log-odds against an average case: coef x (x - mean).

        They add up, with the average case's log-odds, to this case's log-odds.
        """
        return {f: c * (v - m) for f, c, v, m in
                zip(self.features, self.coefs, x, self.means, strict=True)}
