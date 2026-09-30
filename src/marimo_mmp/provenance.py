"""Read-only loading of source-pair provenance from an MMPDB SQLite file."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from contextlib import closing
from pathlib import Path

from .models import SourcePair, TransformRecord, TransformValidationError


def load_source_pairs(
    path: Path,
    records: Sequence[TransformRecord],
    properties: Sequence[str],
) -> dict[tuple[str, str], tuple[SourcePair, ...]]:
    """Validate records against an MMPDB and load their source pairs."""
    source_pairs: dict[tuple[str, str], tuple[SourcePair, ...]] = {}
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
            absent_properties = sorted(set(properties) - db_properties)
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
            for record in records:
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
                    source_pairs[(record.id, property)] = loaded_pairs[key]
    except sqlite3.DatabaseError as exc:
        raise TransformValidationError(f"cannot read MMPDB {path}: {exc}") from exc
    return source_pairs


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
