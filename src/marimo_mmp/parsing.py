"""TSV/CSV decoding and validated parsing of mmpdb transform tables."""

from __future__ import annotations

import csv
import gzip
import io
import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from os import PathLike
from pathlib import Path
from typing import Any, BinaryIO, TextIO

import pandas as pd
from rdkit import Chem, rdBase

from .models import (
    EvidenceThresholds,
    PropertyStats,
    TransformRecord,
    TransformValidationError,
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


def records_from_frame(
    frame: pd.DataFrame, selected_evidence_thresholds: EvidenceThresholds
) -> tuple[tuple[TransformRecord, ...], tuple[str, ...], tuple[str, ...]]:
    """Parse and validate a transform table into records, properties, and warnings."""
    name = str(frame.attrs.get("name", "dataframe"))
    fields = tuple(str(column) for column in frame.columns)
    _validate_columns(fields, name)
    if "ID" not in fields or "SMILES" not in fields:
        raise TransformValidationError(f"{name}: expected ID and SMILES columns")
    property_columns = _property_columns(fields)
    if not property_columns:
        raise TransformValidationError(f"{name}: no property statistic families found")
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
        if not smiles or _mol_from_smiles(smiles) is None:
            raise TransformValidationError(f"row {row_number}: invalid product SMILES")
        stats_by_property: dict[str, PropertyStats] = {}
        for property, columns in property_columns.items():

            def get(
                suffix: str,
                cells: Sequence[Any] = cells,
                columns: Mapping[str, str] = columns,
            ) -> str:
                return cell(cells, columns.get(suffix, ""))

            from_smiles, to_smiles = get("from_smiles"), get("to_smiles")
            if not _valid_rule_smiles(from_smiles) or not _valid_rule_smiles(to_smiles):
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
    return tuple(records), tuple(property_columns), tuple(sorted(warning_set))


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


def _mol_from_smiles(smiles: str) -> Chem.Mol | None:
    # Rule SMILES contain dummy atoms; RDKit logs noisy hydrogen warnings.
    with rdBase.BlockLogs():
        return Chem.MolFromSmiles(smiles)


def _valid_rule_smiles(smiles: str) -> bool:
    if not smiles:
        return False
    molecule = _mol_from_smiles(smiles)
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
