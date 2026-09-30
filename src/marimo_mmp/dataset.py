"""Parsing, validation, filtering, and provenance for transform results."""

from __future__ import annotations

import csv
import gzip
import io
import math
import sqlite3
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from contextlib import closing
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from os import PathLike
from pathlib import Path
from types import MappingProxyType
from typing import Any, BinaryIO, TextIO

import pandas as pd
from rdkit import Chem


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


@dataclass(frozen=True, slots=True)
class TransformRecord:
    id: str
    smiles: str
    properties: Mapping[str, PropertyStats]

    def __post_init__(self) -> None:
        # Copy before wrapping so callers cannot mutate through their input dict.
        object.__setattr__(self, "properties", MappingProxyType(dict(self.properties)))

    def __deepcopy__(self, memo: dict[int, Any]) -> TransformRecord:
        # Mapping proxies cannot be deep-copied directly; rebuild the frozen record.
        clone = TransformRecord(
            self.id, self.smiles, deepcopy(dict(self.properties), memo)
        )
        memo[id(self)] = clone
        return clone

    def __reduce__(self) -> tuple[type[TransformRecord], tuple[Any, ...]]:
        # Mapping proxies cannot be pickled; rebuild from a plain dict.
        return (TransformRecord, (self.id, self.smiles, dict(self.properties)))


@dataclass(frozen=True, slots=True)
class TransformFilters:
    direction: str = "all"
    min_abs_effect: float = 0.0
    min_support: int = 1
    radii: tuple[int, ...] | None = None
    quality: tuple[str, ...] | None = None
    text: str = ""
    max_std: float | None = None
    max_p_value: float | None = None

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
        converted = dict(value)
        for name in ("radii", "quality"):
            if name in converted and converted[name] is not None:
                converted[name] = tuple(converted[name])
        return cls(**converted)


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


@dataclass(frozen=True, slots=True)
class TransformView:
    dataset: TransformDataset
    property: str
    records: tuple[TransformRecord, ...]
    total_matching: int
    max_nodes: int
    filters: TransformFilters

    @property
    def truncated(self) -> bool:
        return self.total_matching > len(self.records)

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
            record.id, self.property, include_missing=include_missing
        )

    def rows(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for record in self.records:
            stats = record.properties[self.property]
            result.append(
                {
                    "ID": record.id,
                    "SMILES": record.smiles,
                    "property": self.property,
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


@dataclass(slots=True)
class TransformDataset:
    """Transform results with optional in-memory source-pair provenance.

    ``mmpdb_path`` records the source database path for provenance only.
    Datasets loaded with ``from_df`` or ``from_tsv`` do not need that file
    after loading completes.
    """

    records: tuple[TransformRecord, ...]
    properties: tuple[str, ...]
    original_smiles: str | None = None
    mmpdb_path: Path | None = None
    warnings: tuple[str, ...] = ()
    evidence_thresholds: EvidenceThresholds = field(default_factory=EvidenceThresholds)
    _source_pairs: dict[tuple[str, str], tuple[SourcePair, ...]] = field(
        default_factory=dict, repr=False
    )

    @classmethod
    def from_df(
        cls,
        frame: pd.DataFrame,
        *,
        original_smiles: str | None = None,
        mmpdb: str | PathLike[str] | None = None,
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
        mmpdb : str or PathLike, optional
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
        name = str(frame.attrs.get("name", "dataframe"))
        fields = tuple(str(column) for column in frame.columns)
        _validate_columns(fields, name)
        if "ID" not in fields or "SMILES" not in fields:
            raise TransformValidationError(f"{name}: expected ID and SMILES columns")
        property_columns = _property_columns(fields)
        if not property_columns:
            raise TransformValidationError(
                f"{name}: no property statistic families found"
            )
        for property, columns in property_columns.items():
            missing = sorted(_REQUIRED_SUFFIXES - set(columns))
            if missing:
                raise TransformValidationError(
                    f"{name}: property {property!r} is missing columns: {', '.join(missing)}"
                )

        column_positions = {column: position for position, column in enumerate(fields)}

        def cell(cells: Sequence[Any], column: str) -> str:
            position = column_positions.get(column, -1)
            value = cells[position] if 0 <= position < len(cells) else None
            return _cell_text(value).strip()

        records: list[TransformRecord] = []
        identifiers: set[str] = set()
        warning_set: set[str] = set()
        for row_number, cells in enumerate(frame.to_dict("split")["data"], start=2):
            if not any(_cell_text(value).strip() for value in cells):
                continue
            identifier = cell(cells, "ID")
            if not identifier:
                raise TransformValidationError(f"row {row_number}: ID is required")
            if identifier in identifiers:
                raise TransformValidationError(
                    f"row {row_number}: duplicate ID {identifier!r}"
                )
            identifiers.add(identifier)
            smiles = cell(cells, "SMILES")
            if not smiles or Chem.MolFromSmiles(smiles) is None:
                raise TransformValidationError(
                    f"row {row_number}: invalid product SMILES"
                )
            stats_by_property: dict[str, PropertyStats] = {}
            for property, columns in property_columns.items():

                def get(
                    suffix: str,
                    cells: Sequence[Any] = cells,
                    columns: Mapping[str, str] = columns,
                ) -> str:
                    return cell(cells, columns.get(suffix, ""))

                from_smiles, to_smiles = get("from_smiles"), get("to_smiles")
                if not _valid_rule_smiles(from_smiles) or not _valid_rule_smiles(
                    to_smiles
                ):
                    raise TransformValidationError(
                        f"row {row_number}: invalid {property} rule SMILES"
                    )
                radius = _parse_int(get("radius"), row_number, columns["radius"])
                environment_id = _parse_int(
                    get("rule_environment_id"),
                    row_number,
                    columns["rule_environment_id"],
                )
                count = _parse_int(get("count"), row_number, columns["count"])
                if radius < 0 or environment_id < 0 or count < 1:
                    raise TransformValidationError(
                        f"row {row_number}: radius/environment/count values are out of range"
                    )
                numbers = {
                    suffix: _parse_float(
                        get(suffix),
                        row_number,
                        columns.get(suffix, f"{property}_{suffix}"),
                        required=suffix == "median",
                    )
                    for suffix in _FLOAT_SUFFIXES
                }
                _validate_statistics(numbers, row_number, property)
                median_value = numbers["median"]
                assert median_value is not None
                property_stats = PropertyStats(
                    property=property,
                    from_smiles=from_smiles,
                    to_smiles=to_smiles,
                    radius=radius,
                    smarts=get("smarts"),
                    pseudosmiles=get("pseudosmiles"),
                    rule_environment_id=environment_id,
                    count=count,
                    evidence_thresholds=selected_evidence_thresholds,
                    avg=numbers["avg"],
                    std=numbers["std"],
                    kurtosis=numbers["kurtosis"],
                    skewness=numbers["skewness"],
                    min=numbers["min"],
                    q1=numbers["q1"],
                    median=median_value,
                    q3=numbers["q3"],
                    max=numbers["max"],
                    paired_t=numbers["paired_t"],
                    p_value=numbers["p_value"],
                )
                for missing_stat in property_stats.missing_statistics:
                    warning_set.add(
                        f"{property}: {missing_stat} is blank for one or more transforms"
                    )
                stats_by_property[property] = property_stats
            records.append(TransformRecord(identifier, smiles, stats_by_property))
        if not records:
            raise TransformValidationError(f"{name}: no transform rows found")
        if original_smiles is not None:
            original_smiles = original_smiles.strip()
            if not original_smiles or Chem.MolFromSmiles(original_smiles) is None:
                raise TransformValidationError(
                    "original_smiles is not a valid SMILES structure"
                )
        dataset = cls(
            records=tuple(records),
            properties=tuple(property_columns),
            original_smiles=original_smiles,
            mmpdb_path=Path(mmpdb) if mmpdb is not None else None,
            warnings=tuple(sorted(warning_set)),
            evidence_thresholds=selected_evidence_thresholds,
        )
        if dataset.mmpdb_path is not None:
            _load_database(dataset)
        return dataset

    @classmethod
    def from_tsv(
        cls,
        transform_file: str | PathLike[str] | bytes | bytearray | BinaryIO | TextIO,
        *,
        original_smiles: str | None = None,
        mmpdb: str | PathLike[str] | None = None,
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
            mmpdb=mmpdb,
            evidence_thresholds=evidence_thresholds,
        )

    def view(
        self,
        property: str | None = None,
        filters: TransformFilters | Mapping[str, Any] | None = None,
        max_nodes: int = 100,
        direction: str = "higher",
    ) -> TransformView:
        property = property or self.properties[0]
        if property not in self.properties:
            raise KeyError(
                f"unknown property {property!r}; choose from {', '.join(self.properties)}"
            )
        if max_nodes < 1:
            raise ValueError("max_nodes must be at least 1")
        selected_filters = TransformFilters.coerce(filters)
        direction_filter = selected_filters.direction.lower()
        if direction_filter not in {"all", "gain", "loss", "neutral"}:
            raise ValueError("direction must be all, gain, loss, or neutral")
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
            stats = record.properties.get(property)
            if stats is None or stats.count < selected_filters.min_support:
                return False
            if abs(stats.median) < selected_filters.min_abs_effect:
                return False
            if direction_filter == "gain" and not favorable(stats.median):
                return False
            if direction_filter == "loss" and (
                stats.median == 0 or favorable(stats.median)
            ):
                return False
            if direction_filter == "neutral" and stats.median != 0:
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
                tier_rank[record.properties[property].evidence],
                -record.properties[property].count,
                -record.properties[property].radius,
                -abs(record.properties[property].median),
                stable_id(record.id),
            )
        )
        return TransformView(
            self,
            property,
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
        if self.mmpdb_path is None:
            return ()
        property = property or self.properties[0]
        record = next(
            (item for item in self.records if item.id == str(record_id)), None
        )
        if record is None or property not in record.properties:
            raise KeyError(f"unknown transform ID/property: {record_id!r}/{property!r}")
        pairs = self._source_pairs[(record.id, property)]
        if include_missing:
            return pairs
        return tuple(
            pair
            for pair in pairs
            if pair.from_value is not None and pair.to_value is not None
        )


_STAT_SUFFIXES = (
    "from_smiles",
    "to_smiles",
    "radius",
    "smarts",
    "pseudosmiles",
    "rule_environment_id",
    "count",
    "avg",
    "std",
    "kurtosis",
    "skewness",
    "min",
    "q1",
    "median",
    "q3",
    "max",
    "paired_t",
    "p_value",
)
_REQUIRED_SUFFIXES = {
    "from_smiles",
    "to_smiles",
    "radius",
    "rule_environment_id",
    "count",
    "median",
}
_FLOAT_SUFFIXES = {
    "avg",
    "std",
    "kurtosis",
    "skewness",
    "min",
    "q1",
    "median",
    "q3",
    "max",
    "paired_t",
    "p_value",
}


def _read_text(
    source: str | PathLike[str] | bytes | bytearray | BinaryIO | TextIO,
) -> tuple[str, str]:
    name = getattr(source, "name", "<memory>")
    if isinstance(source, (str, PathLike)):
        path = Path(source)
        name = path.name
        raw = path.read_bytes()
    elif isinstance(source, (bytes, bytearray)):
        raw = bytes(source)
    elif hasattr(source, "read"):
        payload = source.read()
        raw = payload.encode("utf-8") if isinstance(payload, str) else bytes(payload)
    else:
        raise TypeError(
            "transform source must be a path, bytes, or a readable file-like object"
        )
    if raw.startswith(b"\x1f\x8b") or str(name).lower().endswith(".gz"):
        try:
            raw = gzip.decompress(raw)
        except (gzip.BadGzipFile, EOFError) as exc:
            raise TransformValidationError(f"{name}: invalid gzip stream") from exc
    try:
        return raw.decode("utf-8-sig"), str(name)
    except UnicodeDecodeError as exc:
        raise TransformValidationError(f"{name}: expected UTF-8 text") from exc


def _cell_text(value: Any) -> str:
    if value is None or value is pd.NA:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value)


def _frame_from_text(text: str, name: str) -> pd.DataFrame:
    first_line = next((line for line in text.splitlines() if line.strip()), "")
    if not first_line:
        raise TransformValidationError(f"{name}: transform file is empty")
    delimiter = "\t" if "\t" in first_line else ","
    try:
        # Inspect the original header before pandas renames duplicate columns.
        header = next(
            (
                row
                for row in csv.reader(io.StringIO(text), delimiter=delimiter)
                if any(field.strip() for field in row)
            ),
            [],
        )
        _validate_columns(header, name)
        frame = pd.read_csv(
            io.StringIO(text),
            delimiter=delimiter,
            dtype=str,
            keep_default_na=False,
            skip_blank_lines=False,
        )
    except (csv.Error, pd.errors.ParserError) as exc:
        raise TransformValidationError(f"{name}: {exc}") from exc
    frame.attrs["name"] = name
    return frame


def _validate_columns(fields: Iterable[str], name: str) -> None:
    duplicates = sorted(field for field, count in Counter(fields).items() if count > 1)
    if duplicates:
        raise TransformValidationError(
            f"{name}: duplicate column names: {', '.join(repr(field) for field in duplicates)}"
        )


def _valid_rule_smiles(smiles: str) -> bool:
    if not smiles:
        return False
    molecule = Chem.MolFromSmiles(smiles)
    return molecule is not None and molecule.GetNumAtoms() > 0


def _validate_statistics(
    numbers: Mapping[str, float | None], row_number: int, property: str
) -> None:
    std = numbers["std"]
    if std is not None and std < 0:
        raise TransformValidationError(
            f"row {row_number}: {property}_std must be nonnegative"
        )
    p_value = numbers["p_value"]
    if p_value is not None and not 0 <= p_value <= 1:
        raise TransformValidationError(
            f"row {row_number}: {property}_p_value must be between 0 and 1"
        )
    previous: float | None = None
    for suffix in ("min", "q1", "median", "q3", "max"):
        value = numbers[suffix]
        if value is None:
            continue
        if previous is not None and previous > value:
            raise TransformValidationError(
                f"row {row_number}: {property} statistics must satisfy "
                "min <= q1 <= median <= q3 <= max for available values"
            )
        previous = value


def _parse_float(
    value: str, row_number: int, column: str, required: bool = False
) -> float | None:
    value = value.strip()
    if not value:
        if required:
            raise TransformValidationError(f"row {row_number}: {column} is required")
        return None
    try:
        result = float(value)
    except ValueError as exc:
        raise TransformValidationError(
            f"row {row_number}: {column} must be numeric"
        ) from exc
    if not math.isfinite(result):
        raise TransformValidationError(f"row {row_number}: {column} must be finite")
    return result


def _parse_int(value: str, row_number: int, column: str) -> int:
    parsed = _parse_float(value, row_number, column, required=True)
    assert parsed is not None
    if parsed != int(parsed):
        raise TransformValidationError(f"row {row_number}: {column} must be an integer")
    return int(parsed)


def _property_columns(fieldnames: Iterable[str]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for column in fieldnames:
        for suffix in _STAT_SUFFIXES:
            marker = f"_{suffix}"
            if column.endswith(marker) and len(column) > len(marker):
                result.setdefault(column[: -len(marker)], {})[suffix] = column
                break
    return result


def _load_database(dataset: TransformDataset) -> None:
    assert dataset.mmpdb_path is not None
    path = dataset.mmpdb_path
    if not path.is_file():
        raise TransformValidationError(f"MMPDB file does not exist: {path}")
    uri = f"{path.resolve().as_uri()}?mode=ro"
    try:
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            connection.execute("PRAGMA query_only = ON")
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            required_tables = {
                "rule_environment",
                "rule",
                "rule_smiles",
                "property_name",
                "pair",
                "compound",
                "compound_property",
                "constant_smiles",
            }
            missing = sorted(required_tables - tables)
            if missing:
                raise TransformValidationError(
                    f"MMPDB is missing tables: {', '.join(missing)}"
                )
            db_properties = {
                row[0] for row in connection.execute("SELECT name FROM property_name")
            }
            absent_properties = sorted(set(dataset.properties) - db_properties)
            if absent_properties:
                raise TransformValidationError(
                    "transform properties are absent from MMPDB: "
                    + ", ".join(absent_properties)
                )
            sql = """
                SELECT rf.smiles, rt.smiles, re.radius
                FROM rule_environment re
                JOIN rule r ON r.id = re.rule_id
                JOIN rule_smiles rf ON rf.id = r.from_smiles_id
                JOIN rule_smiles rt ON rt.id = r.to_smiles_id
                WHERE re.id = ?
            """
            # Share tuples when multiple products use the same oriented rule.
            loaded_pairs: dict[tuple[int, str, int], tuple[SourcePair, ...]] = {}
            for record in dataset.records:
                for property, stats in record.properties.items():
                    row = connection.execute(
                        sql, (stats.rule_environment_id,)
                    ).fetchone()
                    if row is None:
                        raise TransformValidationError(
                            f"transform {record.id}/{property}: rule environment {stats.rule_environment_id} not found"
                        )
                    db_from, db_to, db_radius = row
                    if stats.radius != db_radius:
                        raise TransformValidationError(
                            f"transform {record.id}/{property}: rule environment radius does not match MMPDB"
                        )
                    if (stats.from_smiles, stats.to_smiles) == (db_from, db_to):
                        orientation = 1
                    elif (stats.from_smiles, stats.to_smiles) == (db_to, db_from):
                        orientation = -1
                    else:
                        raise TransformValidationError(
                            f"transform {record.id}/{property}: rule does not match MMPDB environment"
                        )
                    key = (stats.rule_environment_id, property, orientation)
                    if key not in loaded_pairs:
                        loaded_pairs[key] = _read_source_pairs(
                            connection, stats.rule_environment_id, property, orientation
                        )
                    dataset._source_pairs[(record.id, property)] = loaded_pairs[key]
    except sqlite3.DatabaseError as exc:
        raise TransformValidationError(f"cannot read MMPDB {path}: {exc}") from exc


def _read_source_pairs(
    connection: sqlite3.Connection,
    rule_environment_id: int,
    property: str,
    orientation: int,
) -> tuple[SourcePair, ...]:
    query = """
        SELECT c1.public_id, c2.public_id, c1.clean_smiles, c2.clean_smiles,
               cp1.value, cp2.value, cs.smiles
        FROM pair AS p
        JOIN compound AS c1 ON c1.id = p.compound1_id
        JOIN compound AS c2 ON c2.id = p.compound2_id
        LEFT JOIN constant_smiles AS cs ON cs.id = p.constant_id
        LEFT JOIN property_name AS pn ON pn.name = ?
        LEFT JOIN compound_property AS cp1 ON cp1.compound_id = c1.id AND cp1.property_name_id = pn.id
        LEFT JOIN compound_property AS cp2 ON cp2.compound_id = c2.id AND cp2.property_name_id = pn.id
        WHERE p.rule_environment_id = ?
        ORDER BY c1.public_id, c2.public_id
    """
    rows = connection.execute(query, (property, rule_environment_id))
    result: list[SourcePair] = []
    for public1, public2, smiles1, smiles2, value1, value2, constant in rows:
        if orientation < 0:
            public1, public2 = public2, public1
            smiles1, smiles2 = smiles2, smiles1
            value1, value2 = value2, value1
        delta = None if value1 is None or value2 is None else value2 - value1
        result.append(
            SourcePair(
                public1, public2, smiles1, smiles2, value1, value2, delta, constant
            )
        )
    return tuple(result)
