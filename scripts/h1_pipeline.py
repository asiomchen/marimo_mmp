"""Build an IC50-focused matched molecular pair database for human HRH1.

The public source is the ChEMBL REST API. Records are restricted to direct
human H1 binding assays and exact, standardized IC50 measurements reported in
nanomolar units. pIC50 is calculated from those IC50 values without requiring
a ChEMBL pChEMBL field, then aggregated by median per parent compound.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import shutil
import sqlite3
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rdkit import Chem
from rdkit.Chem.MolStandardize import rdMolStandardize

CHEMBL_API = "https://www.ebi.ac.uk/chembl/api/data"
TARGET_CHEMBL_ID = "CHEMBL231"
TARGET_NAME = "Histamine H1 receptor"
TARGET_ORGANISM = "Homo sapiens"
TARGET_UNIPROT = "P35367"
PRIMARY_PROPERTY = "pIC50"
USER_AGENT = "marimo-mmp/0.1 (public ChEMBL data; reproducible research)"


@dataclass(frozen=True)
class BuildReport:
    retrieved_at_utc: str
    chembl_version: str
    raw_assays: int
    direct_binding_assays: int
    raw_ic50_activities: int
    retained_activity_records: int
    compounds: int
    fragmentations: int
    database_compounds: int
    rules: int
    pairs: int
    environments: int
    output_database: str


def _request_json(url: str, retries: int = 4) -> dict[str, Any]:
    """Retrieve JSON with bounded retries for transient server failures."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                return json.load(response)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            if attempt == retries - 1:
                raise
            time.sleep(2**attempt)
    raise RuntimeError("unreachable")


def _endpoint(resource: str, **filters: object) -> str:
    params = {key: str(value) for key, value in filters.items()}
    return f"{CHEMBL_API}/{resource}.json?{urllib.parse.urlencode(params)}"


def fetch_all(
    resource: str, collection_key: str, **filters: object
) -> list[dict[str, Any]]:
    """Fetch every page from a ChEMBL collection endpoint."""
    url: str | None = _endpoint(resource, limit=1000, **filters)
    rows: list[dict[str, Any]] = []
    while url:
        payload = _request_json(url)
        rows.extend(payload[collection_key])
        next_path = payload["page_meta"]["next"]
        url = urllib.parse.urljoin(CHEMBL_API + "/", next_path) if next_path else None
    return rows


def _standardize_smiles(smiles: str) -> str | None:
    """Clean a structure, keep its largest covalent fragment, and canonicalize."""
    molecule = Chem.MolFromSmiles(smiles)
    if molecule is None:
        return None
    try:
        molecule = rdMolStandardize.Cleanup(molecule)
        molecule = rdMolStandardize.FragmentParent(molecule)
        if molecule.GetNumHeavyAtoms() < 2:
            return None
        return Chem.MolToSmiles(molecule, canonical=True, isomericSmiles=True)
    except (ValueError, RuntimeError):
        return None


def _write_json_gz(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _aggregate_compounds(
    activities: list[dict[str, Any]], direct_assay_ids: set[str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Validate IC50 records and aggregate calculated pIC50 by parent ID."""
    accepted: list[dict[str, Any]] = []
    values_by_compound: dict[str, list[float]] = defaultdict(list)
    smiles_by_compound: dict[str, Counter[str]] = defaultdict(Counter)

    for row in activities:
        if row.get("assay_chembl_id") not in direct_assay_ids:
            continue
        if row.get("standard_type") != "IC50" or row.get("standard_relation") != "=":
            continue
        if row.get("standard_flag") != 1 or row.get("potential_duplicate") != 0:
            continue
        if row.get("data_validity_comment") not in (None, ""):
            continue
        if row.get("target_organism") != TARGET_ORGANISM:
            continue
        if row.get("standard_units") != "nM":
            continue
        try:
            ic50_nm = float(row["standard_value"])
        except (KeyError, TypeError, ValueError):
            continue
        if ic50_nm <= 0:
            continue
        p_ic50 = 9.0 - math.log10(ic50_nm)
        canonical_smiles = _standardize_smiles(row.get("canonical_smiles") or "")
        if canonical_smiles is None:
            continue
        compound_id = row.get("parent_molecule_chembl_id") or row.get(
            "molecule_chembl_id"
        )
        if not compound_id:
            continue
        cleaned = dict(row)
        cleaned["standardized_smiles"] = canonical_smiles
        cleaned["IC50_nM"] = ic50_nm
        cleaned["pIC50"] = p_ic50
        accepted.append(cleaned)
        values_by_compound[compound_id].append(p_ic50)
        smiles_by_compound[compound_id][canonical_smiles] += 1

    compounds: list[dict[str, Any]] = []
    for compound_id in sorted(values_by_compound):
        # Prefer the most frequent standardized representation; sort resolves ties.
        selected_smiles = sorted(
            smiles_by_compound[compound_id].items(),
            key=lambda item: (-item[1], item[0]),
        )[0][0]
        values = values_by_compound[compound_id]
        compounds.append(
            {
                "compound_id": compound_id,
                "smiles": selected_smiles,
                "pIC50": statistics.median(values),
                "n_measurements": len(values),
                "pIC50_min": min(values),
                "pIC50_max": max(values),
            }
        )
    return accepted, compounds


def _write_processed_files(
    processed_dir: Path, compounds: list[dict[str, Any]]
) -> None:
    table_path = processed_dir / "h1_ic50_compounds.csv"
    with table_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(compounds[0]))
        writer.writeheader()
        writer.writerows(compounds)

    with (processed_dir / "h1_ic50.smi").open("w", encoding="utf-8") as handle:
        for row in compounds:
            handle.write(f"{row['smiles']}\t{row['compound_id']}\n")

    with (processed_dir / "h1_ic50_properties.tsv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(["ID", PRIMARY_PROPERTY])
        for row in compounds:
            writer.writerow([row["compound_id"], f"{row['pIC50']:.6f}"])


def _mmpdb_executable() -> str:
    adjacent = Path(sys.executable).with_name("mmpdb")
    executable = str(adjacent) if adjacent.exists() else shutil.which("mmpdb")
    if not executable:
        raise RuntimeError("mmpdb executable not found in the active environment")
    return executable


def _sqlite_counts(database: Path) -> dict[str, int]:
    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        mapping = {
            "database_compounds": "compound",
            "rules": "rule",
            "pairs": "pair",
            "environments": "rule_environment",
        }
        return {
            key: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            if table in tables
            else 0
            for key, table in mapping.items()
        }


def _fragdb_count(path: Path) -> int:
    with sqlite3.connect(path) as connection:
        return connection.execute("SELECT COUNT(*) FROM fragmentation").fetchone()[0]


def build_h1_database(root: Path | str = ".") -> BuildReport:
    """Download, curate, fragment, and index the public H1 IC50 dataset."""
    root = Path(root).resolve()
    raw_dir = root / "data" / "raw"
    processed_dir = root / "data" / "processed"
    raw_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)

    retrieved_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    status = _request_json(f"{CHEMBL_API}/status.json")
    target = _request_json(f"{CHEMBL_API}/target/{TARGET_CHEMBL_ID}.json")
    if (
        target.get("organism") != TARGET_ORGANISM
        or target.get("target_type") != "SINGLE PROTEIN"
    ):
        raise RuntimeError(
            "ChEMBL target metadata no longer matches the expected human single protein"
        )

    assays = fetch_all(
        "assay",
        "assays",
        target_chembl_id=TARGET_CHEMBL_ID,
        assay_type="B",
    )
    direct_assays = [row for row in assays if row.get("relationship_type") == "D"]
    direct_assay_ids = {row["assay_chembl_id"] for row in direct_assays}

    activities = fetch_all(
        "activity",
        "activities",
        target_chembl_id=TARGET_CHEMBL_ID,
        target_organism=TARGET_ORGANISM,
        assay_type="B",
        standard_type="IC50",
        standard_relation="=",
        standard_flag=1,
        potential_duplicate=0,
        standard_value__isnull="false",
        standard_units="nM",
    )
    accepted, compounds = _aggregate_compounds(activities, direct_assay_ids)
    if len(compounds) < 2:
        raise RuntimeError(
            "Too few curated compounds to create matched molecular pairs"
        )

    (raw_dir / "chembl_status.json").write_text(
        json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (raw_dir / "h1_target.json").write_text(
        json.dumps(target, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _write_json_gz(raw_dir / "h1_direct_binding_assays.jsonl.gz", direct_assays)
    _write_json_gz(raw_dir / "h1_ic50_activities.jsonl.gz", activities)
    _write_json_gz(raw_dir / "h1_ic50_accepted_records.jsonl.gz", accepted)
    _write_processed_files(processed_dir, compounds)

    fragdb = processed_dir / "h1_ic50.fragdb"
    database = processed_dir / "h1_ic50.mmpdb"
    for generated in (fragdb, database):
        if generated.exists():
            generated.unlink()

    executable = _mmpdb_executable()
    subprocess.run(
        [
            executable,
            "fragment",
            str(processed_dir / "h1_ic50.smi"),
            "--delimiter",
            "tab",
            "--num-jobs",
            "1",
            "--output",
            str(fragdb),
        ],
        check=True,
    )
    subprocess.run(
        [
            executable,
            "index",
            str(fragdb),
            "--properties",
            str(processed_dir / "h1_ic50_properties.tsv"),
            "--title",
            "ChEMBL human histamine H1 receptor pIC50 derived from exact IC50",
            "--output",
            str(database),
        ],
        check=True,
    )

    counts = _sqlite_counts(database)
    report = BuildReport(
        retrieved_at_utc=retrieved_at,
        chembl_version=str(status.get("chembl_db_version", "unknown")),
        raw_assays=len(assays),
        direct_binding_assays=len(direct_assays),
        raw_ic50_activities=len(activities),
        retained_activity_records=len(accepted),
        compounds=len(compounds),
        fragmentations=_fragdb_count(fragdb),
        output_database=str(database.relative_to(root)),
        **counts,
    )
    (processed_dir / "build_report.json").write_text(
        json.dumps(asdict(report), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="project root")
    args = parser.parse_args()
    report = build_h1_database(args.root)
    print(json.dumps(asdict(report), indent=2))


if __name__ == "__main__":
    main()
