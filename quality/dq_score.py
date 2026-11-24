"""
Data Quality Score computation and Circuit Breaker for Silver -> Gold gating.

Dimensions & documented default weights (sum = 1.00):
  - completeness (0.30): non-null rate across required fields
  - validity     (0.25): contract & semantic rule pass rate
  - uniqueness   (0.20): 1 - duplicate rate
  - timeliness   (0.15): fraction arriving within freshness SLA
  - consistency  (0.10): cross-field & format consistency rate
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

DEFAULT_WEIGHTS: dict[str, float] = {
    "completeness": 0.30,
    "validity": 0.25,
    "uniqueness": 0.20,
    "timeliness": 0.15,
    "consistency": 0.10,
}


class DQCircuitBreakerError(RuntimeError):
    """Raised when batch DQ score falls below contract threshold."""


@dataclass
class DQScore:
    source: str
    batch_date: str
    completeness: float
    validity: float
    uniqueness: float
    timeliness: float
    consistency: float
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))

    def __post_init__(self) -> None:
        for dim in ("completeness", "validity", "uniqueness", "timeliness", "consistency"):
            val = getattr(self, dim)
            if not 0.0 <= val <= 1.0:
                raise ValueError(f"DQ dimension '{dim}' must be in [0, 1], got {val}")
        total_w = sum(self.weights.values())
        if abs(total_w - 1.0) > 1e-6:
            raise ValueError(f"DQ weights must sum to 1.0, got {total_w}")

    @property
    def overall(self) -> float:
        return round(
            self.completeness * self.weights["completeness"]
            + self.validity * self.weights["validity"]
            + self.uniqueness * self.weights["uniqueness"]
            + self.timeliness * self.weights["timeliness"]
            + self.consistency * self.weights["consistency"],
            6,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "batch_date": self.batch_date,
            "completeness": round(self.completeness, 4),
            "validity": round(self.validity, 4),
            "uniqueness": round(self.uniqueness, 4),
            "timeliness": round(self.timeliness, 4),
            "consistency": round(self.consistency, 4),
            "overall_score": self.overall,
        }


class DQCircuitBreaker:
    """Evaluates DQScore against contract threshold and halts Gold promotion on breach."""

    def __init__(self, threshold: float = 0.90) -> None:
        self.threshold = threshold

    def evaluate(self, score: DQScore) -> bool:
        """Return True if gate passes; raise DQCircuitBreakerError if halted."""
        if score.overall < self.threshold:
            logging.error(
                "DQ circuit breaker triggered: source=%s batch_date=%s score=%.4f threshold=%.4f",
                score.source,
                score.batch_date,
                score.overall,
                self.threshold,
            )
            raise DQCircuitBreakerError(
                f"DQ score {score.overall:.4f} below threshold {self.threshold:.4f} "
                f"for {score.source} on {score.batch_date}"
            )
        return True
