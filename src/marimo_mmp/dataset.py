"""Filtering, ranking, and provenance lookup for transform results."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from os import PathLike
from pathlib import Path
from typing import Any, BinaryIO, TextIO

import pandas as pd

from .models import (
    EvidenceThresholds,
    EvidenceTier,
    PropertyStats,
    SourcePair,
    TransformFilters,
    TransformRecord,
    TransformValidationError,
)
from .parsing import _frame_from_text, _mol_from_smiles, _read_text, records_from_frame
from .provenance import load_source_pairs

__all__ = [
    "EvidenceThresholds",
    "EvidenceTier",
    "PropertyStats",
    "SourcePair",
    "TransformDataset",
    "TransformFilters",
    "TransformRecord",
    "TransformValidationError",
    "TransformView",
]


@dataclass(frozen=True, slots=True, repr=False)
class TransformView:
    dataset: TransformDataset = field(repr=False)
    property_name: str
    records: tuple[TransformRecord, ...]
    matching_count: int
    max_nodes: int
    filters: TransformFilters

    def __repr__(self) -> str:
        return (
            f"TransformView(property_name={self.property_name!r}, "
            f"records={len(self.records)}/{self.matching_count}, "
            f"max_nodes={self.max_nodes}, filters={self.filters!r})"
        )

    @property
    def truncated(self) -> bool:
        return self.matching_count > len(self.records)

    def record(self, record_id: str) -> TransformRecord | None:
        return next(
            (record for record in self.records if record.id == str(record_id)), None
        )

    def source_pairs(
        self, record_id: str, *, include_missing: bool = False
    ) -> tuple[SourcePair, ...]:
        """Return provenance pairs for a shown transform.

        By default, pairs without a value for this view's selected property
        are omitted. Set ``include_missing=True`` to inspect every structural
        pair in the rule environment, including pairs with null values.
        """
        record = self.record(record_id)
        if record is None:
            raise KeyError(f"transform ID {record_id!r} is not in this view")
        return self.dataset.source_pairs(
            record.id, self.property_name, include_missing=include_missing
        )

    def rows(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for record in self.records:
            stats = record.properties[self.property_name]
            result.append(
                {
                    "ID": record.id,
                    "SMILES": record.smiles,
                    "property": self.property_name,
                    "median": stats.median,
                    "count": stats.count,
                    "evidence": stats.evidence.value,
                    "radius": stats.radius,
                    "std": stats.std,
                    "min": stats.min,
                    "q1": stats.q1,
                    "q3": stats.q3,
                    "max": stats.max,
                    "p_value": stats.p_value,
                    "from_smiles": stats.from_smiles,
                    "to_smiles": stats.to_smiles,
                    "rule_environment_id": stats.rule_environment_id,
                    "warnings": ", ".join(stats.missing_statistics),
                }
            )
        return result


@dataclass(frozen=True, slots=True, repr=False)
class TransformDataset:
    """Transform results with optional in-memory source-pair provenance.

    Prefer the ``from_df`` and ``from_tsv`` loaders, which parse and validate
    mmpdb output. Direct construction validates record consistency and, when
    ``mmpdb_path`` is given, eagerly loads source pairs from that database.
    Datasets do not need the database file after construction completes.
    """

    records: tuple[TransformRecord, ...]
    properties: tuple[str, ...]
    original_smiles: str | None = None
    mmpdb_path: Path | None = None
    warnings: tuple[str, ...] = ()
    evidence_thresholds: EvidenceThresholds = field(default_factory=EvidenceThresholds)
    _source_pairs: dict[tuple[str, str], tuple[SourcePair, ...]] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )

    def __repr__(self) -> str:
        return (
            f"TransformDataset(records={len(self.records)}, "
            f"properties={self.properties!r}, "
            f"mmpdb_path={None if self.mmpdb_path is None else str(self.mmpdb_path)!r}, "
            f"warnings={len(self.warnings)})"
        )

    @property
    def has_mmpdb(self) -> bool:
        """Whether source-pair provenance was loaded from an MMPDB."""
        return self.mmpdb_path is not None

    def __post_init__(self) -> None:
        records = tuple(self.records)
        if not records:
            raise TransformValidationError("dataset must contain at least one record")
        if not all(isinstance(record, TransformRecord) for record in records):
            raise TypeError("records must be TransformRecord instances")
        duplicate_ids = sorted(
            record_id
            for record_id, count in Counter(record.id for record in records).items()
            if count > 1
        )
        if duplicate_ids:
            raise TransformValidationError(
                f"duplicate transform IDs: {', '.join(duplicate_ids)}"
            )
        properties = tuple(self.properties)
        if not properties or not all(isinstance(name, str) for name in properties):
            raise TypeError("properties must be a non-empty sequence of strings")
        if len(set(properties)) != len(properties):
            raise TransformValidationError("properties must be unique")
        known = set(properties)
        for record in records:
            unknown = sorted(set(record.properties) - known)
            if unknown:
                raise TransformValidationError(
                    f"transform {record.id}: unknown properties {', '.join(unknown)}"
                )
        if self.original_smiles is not None and not isinstance(
            self.original_smiles, str
        ):
            raise TypeError("original_smiles must be a string or None")
        warnings = tuple(self.warnings)
        if not all(isinstance(warning, str) for warning in warnings):
            raise TypeError("warnings must be strings")
        object.__setattr__(self, "records", records)
        object.__setattr__(self, "properties", properties)
        object.__setattr__(self, "warnings", warnings)
        object.__setattr__(
            self,
            "evidence_thresholds",
            EvidenceThresholds.coerce(self.evidence_thresholds),
        )
        if self.mmpdb_path is not None:
            object.__setattr__(self, "mmpdb_path", Path(self.mmpdb_path))
            self._source_pairs.update(
                load_source_pairs(self.mmpdb_path, records, properties)
            )

    @classmethod
    def from_df(
        cls,
        frame: pd.DataFrame,
        *,
        original_smiles: str | None = None,
        mmpdb_path: str | PathLike[str] | None = None,
        evidence_thresholds: EvidenceThresholds | Mapping[str, Any] | None = None,
    ) -> TransformDataset:
        """Load validated transform results from a pandas DataFrame.

        Property families are discovered from mmpdb-style column suffixes
        such as ``_median``, ``_count``, and ``_rule_environment_id``.
        Non-text cells are stringified; missing values count as blank.

        Parameters
        ----------
        frame : pandas.DataFrame
            Transform table with ``ID`` and ``SMILES`` columns plus
            per-property statistic families.
        original_smiles : str, optional
            Query-compound SMILES used for graph context and depiction. When
            supplied, it must describe a valid RDKit molecule.
        mmpdb_path : str or PathLike, optional
            MMPDB SQLite database used to load source-pair provenance. The
            database is opened read-only and checked against every property
            and rule environment in the transform table. Relevant source
            pairs are stored in memory, including pairs with missing values;
            the database can be removed after this method returns.
        evidence_thresholds : EvidenceThresholds or mapping, optional
            Inclusive pair-count minima for Moderate and Strong evidence. The
            default is ``{"moderate": 2, "strong": 5}``.

        Returns
        -------
        TransformDataset
            Validated records, discovered properties, optional query
            structure and source-pair provenance, and warnings for missing
            optional statistics.

        Raises
        ------
        TypeError
            If ``frame`` is not a pandas DataFrame, or an evidence threshold
            is not an integer.
        ValueError
            If evidence thresholds do not preserve distinct Exploratory,
            Moderate, and Strong ranges.
        TransformValidationError
            If the table is empty, lacks required columns, contains invalid
            values or SMILES, or conflicts with the attached MMPDB.

        Notes
        -----
        Required columns are ``ID`` and ``SMILES`` plus, for each property,
        ``from_smiles``, ``to_smiles``, ``radius``, ``rule_environment_id``,
        ``count``, and ``median``. Blank optional statistics are retained as
        ``None`` and summarized in ``TransformDataset.warnings``. Column names
        must be unique after conversion to strings, and rule SMILES must contain
        atoms. Standard deviations must be nonnegative, p-values must be in
        ``[0, 1]``, and available min/quartile/median/max values must be ordered.
        """
        if not isinstance(frame, pd.DataFrame):
            raise TypeError("from_df expects a pandas DataFrame")
        selected_evidence_thresholds = EvidenceThresholds.coerce(evidence_thresholds)
        records, properties, warnings = records_from_frame(
            frame, selected_evidence_thresholds
        )
        if original_smiles is not None:
            original_smiles = original_smiles.strip()
            if not original_smiles or _mol_from_smiles(original_smiles) is None:
                raise TransformValidationError(
                    "original_smiles is not a valid SMILES structure"
                )
        return cls(
            records=records,
            properties=properties,
            original_smiles=original_smiles,
            mmpdb_path=Path(mmpdb_path) if mmpdb_path is not None else None,
            warnings=warnings,
            evidence_thresholds=selected_evidence_thresholds,
        )

    @classmethod
    def from_tsv(
        cls,
        transform_file: str | PathLike[str] | bytes | bytearray | BinaryIO | TextIO,
        *,
        original_smiles: str | None = None,
        mmpdb_path: str | PathLike[str] | None = None,
        evidence_thresholds: EvidenceThresholds | Mapping[str, Any] | None = None,
    ) -> TransformDataset:
        """Load validated transform results from TSV or CSV input.

        The source may be a filesystem path, an in-memory payload, or a
        readable stream, optionally gzip-compressed. UTF-8 text is expected;
        gzip is detected by its magic bytes or a ``.gz`` filename, and the
        delimiter is inferred from the first nonblank line. The payload is
        parsed into a pandas DataFrame and validated by :meth:`from_df`,
        which also documents the required columns and failure modes.
        """
        text, name = _read_text(transform_file)
        return cls.from_df(
            _frame_from_text(text, name),
            original_smiles=original_smiles,
            mmpdb_path=mmpdb_path,
            evidence_thresholds=evidence_thresholds,
        )

    def view(
        self,
        property_name: str | None = None,
        filters: TransformFilters | Mapping[str, Any] | None = None,
        max_nodes: int = 100,
        direction: str = "higher",
    ) -> TransformView:
        property_name = property_name or self.properties[0]
        if property_name not in self.properties:
            raise KeyError(
                f"unknown property {property_name!r}; choose from {', '.join(self.properties)}"
            )
        if isinstance(max_nodes, bool) or not isinstance(max_nodes, int):
            raise TypeError("max_nodes must be an integer")
        if max_nodes < 1:
            raise ValueError("max_nodes must be at least 1")
        selected_filters = TransformFilters.coerce(filters)
        effect_filter = selected_filters.effect
        orientation = direction.lower() if isinstance(direction, str) else ""
        if orientation not in {"higher", "lower"}:
            raise ValueError("direction must be higher or lower")
        quality = {item.lower() for item in selected_filters.quality or ()}
        quality_is_filtered = selected_filters.quality is not None
        radii = set(selected_filters.radii or ())
        radii_are_filtered = selected_filters.radii is not None
        text = selected_filters.text.casefold().strip()

        def favorable(median: float) -> bool:
            return median > 0 if orientation == "higher" else median < 0

        def include(record: TransformRecord) -> bool:
            stats = record.properties.get(property_name)
            if stats is None or stats.count < selected_filters.min_support:
                return False
            if abs(stats.median) < selected_filters.min_abs_effect:
                return False
            if effect_filter == "gain" and not favorable(stats.median):
                return False
            if effect_filter == "loss" and (
                stats.median == 0 or favorable(stats.median)
            ):
                return False
            if effect_filter == "neutral" and stats.median != 0:
                return False
            if radii_are_filtered and stats.radius not in radii:
                return False
            if quality_is_filtered and stats.evidence.value.lower() not in quality:
                return False
            if selected_filters.max_std is not None and (
                stats.std is None or stats.std > selected_filters.max_std
            ):
                return False
            if selected_filters.max_p_value is not None and (
                stats.p_value is None or stats.p_value > selected_filters.max_p_value
            ):
                return False
            haystack = " ".join(
                (
                    record.id,
                    record.smiles,
                    stats.from_smiles,
                    stats.to_smiles,
                    stats.smarts,
                )
            ).casefold()
            return not text or text in haystack

        tier_rank = {
            EvidenceTier.STRONG: 0,
            EvidenceTier.MODERATE: 1,
            EvidenceTier.EXPLORATORY: 2,
        }

        def stable_id(value: str) -> tuple[int, int | str]:
            try:
                return (0, int(value))
            except ValueError:
                return (1, value)

        matches = [record for record in self.records if include(record)]
        matches.sort(
            key=lambda record: (
                tier_rank[record.properties[property_name].evidence],
                -record.properties[property_name].count,
                -record.properties[property_name].radius,
                -abs(record.properties[property_name].median),
                stable_id(record.id),
            )
        )
        return TransformView(
            self,
            property_name,
            tuple(matches[:max_nodes]),
            len(matches),
            max_nodes,
            selected_filters,
        )

    def source_pairs(
        self,
        record_id: str,
        property: str | None = None,
        *,
        include_missing: bool = False,
    ) -> tuple[SourcePair, ...]:
        """Return in-memory source pairs for one transform/property combination.

        The default returns only pairs for which both compounds have a value
        for the selected property. This keeps provenance aligned with the
        property-specific transform statistics. Set ``include_missing=True``
        to inspect every structural pair in the rule environment instead.
        """
        property = property or self.properties[0]
        record = next(
            (item for item in self.records if item.id == str(record_id)), None
        )
        if record is None or property not in record.properties:
            raise KeyError(f"unknown transform ID/property: {record_id!r}/{property!r}")
        if self.mmpdb_path is None:
            return ()
        pairs = self._source_pairs[(record.id, property)]
        if include_missing:
            return pairs
        return tuple(
            pair
            for pair in pairs
            if pair.from_value is not None and pair.to_value is not None
        )
