from __future__ import annotations

import csv
import gzip
import io
import sqlite3
from pathlib import Path
from typing import cast

import pandas as pd
import pytest

from marimo_mmp import (
    EvidenceThresholds,
    EvidenceTier,
    TransformDataset,
    TransformValidationError,
)

ROOT = Path(__file__).resolve().parents[1]
TRANSFORMS = ROOT / "data" / "processed" / "bilastine_transforms.tsv"
DATABASE = ROOT / "data" / "processed" / "h1_ic50.mmpdb"
ORIGINAL = "CCOCCn1c(C2CCN(CCc3ccc(C(C)(C)C(=O)O)cc3)CC2)nc2ccccc21"


def transform_text() -> str:
    return TRANSFORMS.read_text(encoding="utf-8")


def first_row_text() -> str:
    return "\n".join(transform_text().splitlines()[:2]) + "\n"


def mutate_first_row(**changes: str) -> bytes:
    reader = csv.DictReader(io.StringIO(first_row_text()), delimiter="\t")
    row = next(reader)
    row.update(changes)
    output = io.StringIO()
    assert reader.fieldnames is not None
    writer = csv.DictWriter(
        output, fieldnames=reader.fieldnames, delimiter="\t", lineterminator="\n"
    )
    writer.writeheader()
    writer.writerow(row)
    return output.getvalue().encode()


def test_bilastine_acceptance_counts_and_warnings():
    dataset = TransformDataset.from_tsv(TRANSFORMS)
    assert len(dataset.records) == 94
    assert dataset.properties == ("pIC50",)
    assert len(dataset.view(filters={"min_support": 2}).records) == 27
    assert any("std" in warning for warning in dataset.warnings)


def test_path_bytes_filelike_csv_and_gzip_modalities():
    raw = transform_text()
    from_bytes = TransformDataset.from_tsv(raw.encode())
    from_file = TransformDataset.from_tsv(io.BytesIO(raw.encode()))
    from_gzip = TransformDataset.from_tsv(gzip.compress(raw.encode()))

    rows = list(csv.reader(io.StringIO(raw), delimiter="\t"))
    csv_buffer = io.StringIO()
    csv.writer(csv_buffer).writerows(rows)
    from_csv = TransformDataset.from_tsv(csv_buffer.getvalue().encode())

    assert [
        len(item.records) for item in (from_bytes, from_file, from_gzip, from_csv)
    ] == [94] * 4


def test_from_df_matches_from_tsv_and_keeps_query_smiles():
    reference = TransformDataset.from_tsv(TRANSFORMS)
    frame = pd.read_csv(TRANSFORMS, sep="\t", dtype=str, keep_default_na=False)

    loaded = TransformDataset.from_df(frame, original_smiles=ORIGINAL)

    assert loaded.records == reference.records
    assert loaded.properties == reference.properties
    assert loaded.warnings == reference.warnings
    assert loaded.original_smiles == ORIGINAL


def test_unsupported_transform_sources_are_rejected():
    with pytest.raises(TypeError, match="expects a pandas DataFrame"):
        TransformDataset.from_df(cast(pd.DataFrame, object()))
    with pytest.raises(TypeError, match="path, bytes, or a readable file-like"):
        TransformDataset.from_tsv(cast("str", object()))


def test_from_tsv_preserves_source_names_and_gzip_parity():
    from_path = TransformDataset.from_tsv(TRANSFORMS)
    from_gzip = TransformDataset.from_tsv(gzip.compress(TRANSFORMS.read_bytes()))

    assert from_path.records == from_gzip.records


def test_from_tsv_rejects_empty_input_and_from_df_takes_numeric_cells():
    with pytest.raises(TransformValidationError, match="is empty"):
        TransformDataset.from_tsv(io.StringIO(""))

    numeric = pd.read_csv(TRANSFORMS, sep="\t")
    assert numeric["pIC50_radius"].dtype != object
    assert (
        TransformDataset.from_df(numeric).records
        == TransformDataset.from_tsv(TRANSFORMS).records
    )


def test_multiple_property_families_are_detected():
    lines = first_row_text().splitlines()
    header = lines[0].split("\t")
    values = lines[1].split("\t")
    extra_header = [column.replace("pIC50_", "logD_") for column in header[2:]]
    dataset = TransformDataset.from_tsv(
        (
            "\t".join(header + extra_header)
            + "\n"
            + "\t".join(values + values[2:])
            + "\n"
        ).encode()
    )
    assert dataset.properties == ("pIC50", "logD")
    assert set(dataset.records[0].properties) == {"pIC50", "logD"}


@pytest.mark.parametrize(
    "payload, message",
    [
        (
            lambda: (
                first_row_text() + first_row_text().splitlines()[1] + "\n"
            ).encode(),
            "duplicate ID",
        ),
        (lambda: mutate_first_row(SMILES="not-a-smiles"), "invalid product SMILES"),
        (lambda: mutate_first_row(pIC50_count="1.5"), "must be an integer"),
        (lambda: mutate_first_row(pIC50_median="nan"), "must be finite"),
        (lambda: mutate_first_row(pIC50_median=""), "is required"),
    ],
)
def test_invalid_rows_are_rejected(payload, message):
    with pytest.raises(TransformValidationError, match=message):
        TransformDataset.from_tsv(payload())


def test_invalid_original_smiles_is_rejected():
    with pytest.raises(TransformValidationError, match="original_smiles"):
        TransformDataset.from_tsv(first_row_text().encode(), original_smiles="bad[")


def test_evidence_tier_boundaries():
    assert EvidenceTier.from_count(1) is EvidenceTier.EXPLORATORY
    assert EvidenceTier.from_count(2) is EvidenceTier.MODERATE
    assert EvidenceTier.from_count(4) is EvidenceTier.MODERATE
    assert EvidenceTier.from_count(5) is EvidenceTier.STRONG


def test_evidence_thresholds_are_customizable_per_dataset():
    thresholds = EvidenceThresholds(moderate=3, strong=8)
    dataset = TransformDataset.from_tsv(TRANSFORMS, evidence_thresholds=thresholds)

    assert dataset.evidence_thresholds is thresholds
    assert EvidenceTier.from_count(2, thresholds) is EvidenceTier.EXPLORATORY
    assert EvidenceTier.from_count(3, thresholds) is EvidenceTier.MODERATE
    assert EvidenceTier.from_count(7, thresholds) is EvidenceTier.MODERATE
    assert EvidenceTier.from_count(8, thresholds) is EvidenceTier.STRONG
    assert all(
        stats.evidence
        is (
            EvidenceTier.STRONG
            if stats.count >= 8
            else EvidenceTier.MODERATE
            if stats.count >= 3
            else EvidenceTier.EXPLORATORY
        )
        for record in dataset.records
        for stats in record.properties.values()
    )
    assert all(
        record.properties["pIC50"].count >= 8
        for record in dataset.view(filters={"quality": ["Strong"]}).records
    )


@pytest.mark.parametrize(
    "thresholds, error",
    [
        ({"moderate": 1, "strong": 5}, "at least 2"),
        ({"moderate": 5, "strong": 5}, "must exceed"),
        ({"moderate": 2, "strong": True}, "must be an integer"),
        ({"moderate": 2, "strong": 5, "unknown": 7}, "unknown evidence thresholds"),
    ],
)
def test_invalid_evidence_thresholds_are_rejected(thresholds, error):
    with pytest.raises((TypeError, ValueError), match=error):
        TransformDataset.from_tsv(
            first_row_text().encode(), evidence_thresholds=thresholds
        )


def test_filtering_ranking_truncation_and_fold_change():
    dataset = TransformDataset.from_tsv(TRANSFORMS)
    view = dataset.view(
        filters={
            "direction": "gain",
            "min_support": 2,
            "quality": ["Strong", "Moderate"],
            "text": "[*:1]",
        },
        max_nodes=5,
    )
    assert len(view.records) == 5
    assert view.total_matching > len(view.records)
    assert view.truncated
    keys = [
        (
            {"Strong": 0, "Moderate": 1, "Exploratory": 2}[
                record.properties[view.property].evidence.value
            ],
            -record.properties[view.property].count,
        )
        for record in view.records
    ]
    assert keys == sorted(keys)
    assert all(record.properties[view.property].median > 0 for record in view.records)
    stats = view.records[0].properties[view.property]
    assert stats.min is not None
    assert stats.max is not None


def test_view_direction_orients_gain_and_loss_filters():
    dataset = TransformDataset.from_tsv(TRANSFORMS)
    gains = dataset.view(filters={"direction": "gain"}, max_nodes=100)
    gains_when_lower = dataset.view(
        filters={"direction": "loss"}, max_nodes=100, direction="lower"
    )
    losses_when_lower = dataset.view(
        filters={"direction": "gain"}, max_nodes=100, direction="lower"
    )

    assert gains.records
    assert {record.id for record in gains.records} == {
        record.id for record in gains_when_lower.records
    }
    assert all(record.properties["pIC50"].median > 0 for record in gains.records)
    assert losses_when_lower.records
    assert all(
        record.properties["pIC50"].median < 0 for record in losses_when_lower.records
    )


def test_view_direction_validates_orientation_and_filter():
    dataset = TransformDataset.from_tsv(TRANSFORMS)

    with pytest.raises(ValueError, match="direction must be higher or lower"):
        dataset.view(direction="sideways")
    with pytest.raises(
        ValueError, match="direction must be all, gain, loss, or neutral"
    ):
        dataset.view(filters={"direction": "up"})


def test_mmpdb_provenance_is_eager_directional_and_read_only(tmp_path):
    readonly = tmp_path / "copy.mmpdb"
    readonly.write_bytes(DATABASE.read_bytes())
    readonly.chmod(0o444)
    dataset = TransformDataset.from_tsv(
        TRANSFORMS, original_smiles=ORIGINAL, mmpdb=readonly
    )
    assert dataset.mmpdb_path == readonly
    readonly.unlink()
    record = next(
        item
        for item in dataset.records
        if item.properties["pIC50"].rule_environment_id == 1973
    )
    pairs = dataset.source_pairs(record.id, "pIC50")
    assert len(pairs) == 2
    assert pairs[0].to_value is not None
    assert pairs[0].from_value is not None
    assert pairs[0].delta == pytest.approx(pairs[0].to_value - pairs[0].from_value)


@pytest.mark.parametrize("loader", ["from_tsv", "from_df"])
def test_all_source_pairs_remain_available_after_database_cleanup(tmp_path, loader):
    reference = TransformDataset.from_tsv(TRANSFORMS, mmpdb=DATABASE)
    database = tmp_path / "uploaded.mmpdb"
    database.write_bytes(DATABASE.read_bytes())
    if loader == "from_df":
        dataset = TransformDataset.from_df(
            pd.read_csv(TRANSFORMS, sep="\t"), mmpdb=database
        )
    else:
        dataset = TransformDataset.from_tsv(TRANSFORMS, mmpdb=database)
    database.unlink()

    for record in dataset.records:
        for property in record.properties:
            for include_missing in (False, True):
                assert dataset.source_pairs(
                    record.id, property, include_missing=include_missing
                ) == reference.source_pairs(
                    record.id, property, include_missing=include_missing
                )
    assert dataset.view().rows() == reference.view().rows()
    with pytest.raises(KeyError, match="unknown transform ID/property"):
        dataset.source_pairs("missing")
    with pytest.raises(KeyError, match="unknown transform ID/property"):
        dataset.source_pairs(dataset.records[0].id, "missing")


def test_source_pairs_filter_missing_selected_property_values_by_default(tmp_path):
    source = TransformDataset.from_tsv(TRANSFORMS, mmpdb=DATABASE)
    record = next(
        item
        for item in source.records
        if item.properties["pIC50"].rule_environment_id == 1973
    )
    structural_pairs = source.source_pairs(record.id, "pIC50", include_missing=True)
    assert len(structural_pairs) == 2

    compound_counts: dict[str, int] = {}
    for pair in structural_pairs:
        for public_id in (pair.from_id, pair.to_id):
            compound_counts[public_id] = compound_counts.get(public_id, 0) + 1
    missing_public_id = next(
        public_id for public_id, count in compound_counts.items() if count == 1
    )

    database = tmp_path / "partial-coverage.mmpdb"
    database.write_bytes(DATABASE.read_bytes())
    with sqlite3.connect(database) as connection:
        property_id = connection.execute(
            "SELECT id FROM property_name WHERE name = ?", ("pIC50",)
        ).fetchone()[0]
        compound_id = connection.execute(
            "SELECT id FROM compound WHERE public_id = ?", (missing_public_id,)
        ).fetchone()[0]
        connection.execute(
            "DELETE FROM compound_property WHERE compound_id = ? AND property_name_id = ?",
            (compound_id, property_id),
        )

    dataset = TransformDataset.from_tsv(TRANSFORMS, mmpdb=database)
    database.unlink()
    measured_pairs = dataset.source_pairs(record.id, "pIC50")
    all_pairs = dataset.source_pairs(record.id, "pIC50", include_missing=True)

    assert len(measured_pairs) == len(structural_pairs) - 1
    assert all(
        pair.from_value is not None and pair.to_value is not None
        for pair in measured_pairs
    )
    assert len(all_pairs) == len(structural_pairs)
    assert any(pair.from_value is None or pair.to_value is None for pair in all_pairs)

    view = dataset.view(max_nodes=100)
    assert view.source_pairs(record.id) == measured_pairs
    assert view.source_pairs(record.id, include_missing=True) == all_pairs


def test_source_pairs_cache_every_property_after_database_cleanup(tmp_path):
    database = tmp_path / "two-properties.mmpdb"
    database.write_bytes(DATABASE.read_bytes())
    with sqlite3.connect(database) as connection:
        original_id = connection.execute(
            "SELECT id FROM property_name WHERE name = 'pIC50'"
        ).fetchone()[0]
        extra_id = connection.execute(
            "INSERT INTO property_name (name) VALUES ('logD')"
        ).lastrowid
        connection.execute(
            """INSERT INTO compound_property (compound_id, property_name_id, value)
               SELECT compound_id, ?, value * 2 FROM compound_property
               WHERE property_name_id = ?""",
            (extra_id, original_id),
        )

    frame = pd.read_csv(TRANSFORMS, sep="\t").head(1)
    for column in list(frame.columns):
        if column.startswith("pIC50_"):
            frame[column.replace("pIC50_", "logD_")] = frame[column]
    dataset = TransformDataset.from_df(frame, mmpdb=database)
    database.unlink()

    record = dataset.records[0]
    original_pairs = dataset.source_pairs(record.id, "pIC50")
    extra_pairs = dataset.view(property="logD").source_pairs(record.id)
    assert original_pairs
    assert len(extra_pairs) == len(original_pairs)
    for original, extra in zip(original_pairs, extra_pairs, strict=True):
        assert (extra.from_id, extra.to_id) == (original.from_id, original.to_id)
        assert original.from_value is not None and original.to_value is not None
        assert original.delta is not None
        assert extra.from_value == pytest.approx(original.from_value * 2)
        assert extra.to_value == pytest.approx(original.to_value * 2)
        assert extra.delta == pytest.approx(original.delta * 2)


def test_reversed_rule_swaps_source_pair_direction(tmp_path):
    database = tmp_path / "reversed.mmpdb"
    database.write_bytes(DATABASE.read_bytes())
    direct = TransformDataset.from_tsv(first_row_text().encode(), mmpdb=DATABASE)
    row = direct.records[0].properties["pIC50"]
    reversed_data = mutate_first_row(
        pIC50_from_smiles=row.to_smiles,
        pIC50_to_smiles=row.from_smiles,
        pIC50_median=str(-row.median),
    )
    reversed_dataset = TransformDataset.from_tsv(reversed_data, mmpdb=database)
    database.unlink()
    direct_pair = direct.source_pairs("1")[0]
    reversed_pair = reversed_dataset.source_pairs("1")[0]
    assert (reversed_pair.from_id, reversed_pair.to_id) == (
        direct_pair.to_id,
        direct_pair.from_id,
    )
    assert direct_pair.delta is not None
    assert reversed_pair.delta == pytest.approx(-direct_pair.delta)


def test_mismatched_database_reference_and_missing_property_are_rejected():
    with pytest.raises(TransformValidationError, match="not found"):
        TransformDataset.from_tsv(
            mutate_first_row(pIC50_rule_environment_id="999999"), mmpdb=DATABASE
        )

    lines = first_row_text().splitlines()
    header = lines[0].split("\t")
    values = lines[1].split("\t")
    extra_header = [column.replace("pIC50_", "logD_") for column in header[2:]]
    data = (
        "\t".join(header + extra_header) + "\n" + "\t".join(values + values[2:]) + "\n"
    )
    with pytest.raises(TransformValidationError, match="absent from MMPDB"):
        TransformDataset.from_tsv(data.encode(), mmpdb=DATABASE)


def test_500_product_view_is_stable():
    lines = first_row_text().splitlines()
    header, template = lines
    fields = template.split("\t")
    rows = []
    for index in range(500):
        row = fields.copy()
        row[0] = str(index + 1)
        rows.append("\t".join(row))
    dataset = TransformDataset.from_tsv(
        (header + "\n" + "\n".join(rows) + "\n").encode()
    )
    first = [record.id for record in dataset.view(max_nodes=100).records]
    second = [record.id for record in dataset.view(max_nodes=100).records]
    assert len(first) == 100
    assert first == second
