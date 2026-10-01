"""Immutable value types for transform records, filters, and provenance."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TransformValidationError(ValueError):
    """Raised when transform input cannot be interpreted safely."""


class EvidenceTier(str, Enum):
    STRONG = "Strong"
    MODERATE = "Moderate"
    EXPLORATORY = "Exploratory"

    @classmethod
    def from_count(
        cls,
        count: int,
        thresholds: EvidenceThresholds | Mapping[str, Any] | None = None,
    ) -> EvidenceTier:
        selected = EvidenceThresholds.coerce(thresholds)
        if count >= selected.strong:
            return cls.STRONG
        if count >= selected.moderate:
            return cls.MODERATE
        return cls.EXPLORATORY


@dataclass(frozen=True, slots=True)
class EvidenceThresholds:
    """Inclusive pair-count minima for Moderate and Strong evidence."""

    moderate: int = 2
    strong: int = 5

    def __post_init__(self) -> None:
        if isinstance(self.moderate, bool) or not isinstance(self.moderate, int):
            raise TypeError("moderate evidence threshold must be an integer")
        if isinstance(self.strong, bool) or not isinstance(self.strong, int):
            raise TypeError("strong evidence threshold must be an integer")
        if self.moderate < 2:
            raise ValueError("moderate evidence threshold must be at least 2")
        if self.strong <= self.moderate:
            raise ValueError(
                "strong evidence threshold must exceed the moderate threshold"
            )

    @classmethod
    def coerce(
        cls,
        value: EvidenceThresholds | Mapping[str, Any] | None,
    ) -> EvidenceThresholds:
        if value is None:
            return cls()
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise TypeError(
                "evidence_thresholds must be EvidenceThresholds, a mapping, or None"
            )
        unknown = sorted(set(value) - {"moderate", "strong"})
        if unknown:
            raise ValueError(f"unknown evidence thresholds: {', '.join(unknown)}")
        return cls(**value)


@dataclass(frozen=True, slots=True)
class PropertyStats:
    property: str
    from_smiles: str
    to_smiles: str
    radius: int
    smarts: str
    pseudosmiles: str
    rule_environment_id: int
    count: int
    avg: float | None
    std: float | None
    kurtosis: float | None
    skewness: float | None
    min: float | None
    q1: float | None
    median: float
    q3: float | None
    max: float | None
    paired_t: float | None
    p_value: float | None
    evidence_thresholds: EvidenceThresholds = field(
        default_factory=EvidenceThresholds, repr=False
    )

    @property
    def evidence(self) -> EvidenceTier:
        return EvidenceTier.from_count(self.count, self.evidence_thresholds)

    @property
    def missing_statistics(self) -> tuple[str, ...]:
        return tuple(
            name
            for name in ("std", "q1", "q3", "p_value")
            if getattr(self, name) is None
        )


class _FrozenDict(dict[str, PropertyStats]):
    """Read-only, hashable dict that copies, pickles, and ``asdict``s like a dict."""

    __slots__ = ()

    def _readonly(self, *args: Any, **kwargs: Any) -> Any:
        raise TypeError("transform record properties are read-only")

    __setitem__ = __delitem__ = __ior__ = _readonly
    clear = pop = popitem = setdefault = update = _readonly

    def __hash__(self) -> int:
        return hash(frozenset(self.items()))

    def __reduce__(self) -> tuple[type[_FrozenDict], tuple[dict[str, PropertyStats]]]:
        # The default dict protocol restores items through blocked __setitem__.
        return (type(self), (dict(self),))


@dataclass(frozen=True, slots=True)
class TransformRecord:
    id: str
    smiles: str
    properties: Mapping[str, PropertyStats]

    def __post_init__(self) -> None:
        # Copy so callers cannot mutate the record through their input dict.
        object.__setattr__(self, "properties", _FrozenDict(self.properties))


@dataclass(frozen=True, slots=True)
class TransformFilters:
    effect: str = "all"
    min_abs_effect: float = 0.0
    min_support: int = 1
    radii: tuple[int, ...] | None = None
    quality: tuple[str, ...] | None = None
    text: str = ""
    max_std: float | None = None
    max_p_value: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.effect, str):
            raise TypeError("effect filter must be a string")
        effect = self.effect.lower()
        if effect not in {"all", "gain", "loss", "neutral"}:
            raise ValueError("effect must be all, gain, loss, or neutral")
        object.__setattr__(self, "effect", effect)
        object.__setattr__(
            self,
            "min_abs_effect",
            _filter_number(self.min_abs_effect, "min_abs_effect"),
        )
        if isinstance(self.min_support, bool) or not isinstance(self.min_support, int):
            raise TypeError("min_support must be an integer")
        if self.min_support < 1:
            raise ValueError("min_support must be at least 1")
        if self.radii is not None:
            radii = (self.radii,) if isinstance(self.radii, int) else self.radii
            if isinstance(radii, (str, bytes)) or not isinstance(radii, Iterable):
                raise TypeError(
                    "radii must be an integer, a sequence of integers, or None"
                )
            radii = tuple(radii)
            if any(
                isinstance(r, bool) or not isinstance(r, int) or r < 0 for r in radii
            ):
                raise ValueError("radii must be non-negative integers")
            object.__setattr__(self, "radii", radii)
        if self.quality is not None:
            quality = (self.quality,) if isinstance(self.quality, str) else self.quality
            if not isinstance(quality, Iterable):
                raise TypeError(
                    "quality must be a string, a sequence of strings, or None"
                )
            tiers: dict[str, str] = {
                tier.value.lower(): tier.value for tier in EvidenceTier
            }
            normalized = []
            for item in quality:
                if not isinstance(item, str) or item.lower() not in tiers:
                    raise ValueError(
                        f"quality must contain only {', '.join(tiers.values())}"
                    )
                normalized.append(tiers[item.lower()])
            object.__setattr__(self, "quality", tuple(normalized))
        if not isinstance(self.text, str):
            raise TypeError("text filter must be a string")
        if self.max_std is not None:
            object.__setattr__(self, "max_std", _filter_number(self.max_std, "max_std"))
        if self.max_p_value is not None:
            max_p_value = _filter_number(self.max_p_value, "max_p_value")
            if max_p_value > 1:
                raise ValueError("max_p_value must be at most 1")
            object.__setattr__(self, "max_p_value", max_p_value)

    @classmethod
    def coerce(
        cls, value: TransformFilters | Mapping[str, Any] | None
    ) -> TransformFilters:
        if value is None:
            return cls()
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise TypeError("filters must be TransformFilters, a mapping, or None")
        allowed = set(cls.__dataclass_fields__)
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise ValueError(f"unknown filters: {', '.join(unknown)}")
        return cls(**value)


def _filter_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite non-negative number")
    return float(value)


@dataclass(frozen=True, slots=True)
class SourcePair:
    from_id: str
    to_id: str
    from_smiles: str
    to_smiles: str
    from_value: float | None
    to_value: float | None
    delta: float | None
    constant_smiles: str | None
