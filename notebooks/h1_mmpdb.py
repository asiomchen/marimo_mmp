import marimo

__generated_with = "0.24.0"
app = marimo.App(width="medium")


@app.cell
def _():
    import json
    import sqlite3
    import sys
    from pathlib import Path

    import marimo as mo

    _project_root = Path(__file__).resolve().parents[1]
    if str(_project_root) not in sys.path:
        sys.path.insert(0, str(_project_root))

    from scripts.h1_pipeline import PRIMARY_PROPERTY, build_h1_database

    return PRIMARY_PROPERTY, Path, build_h1_database, json, mo, sqlite3


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Human histamine H1 matched molecular pairs

    This notebook builds and inspects a matched molecular pair database from
    public ChEMBL data. The target is the human histamine H1 receptor
    (`CHEMBL231`, HRH1, UniProt `P35367`). **IC50 is the only endpoint**, and
    **pIC50** is calculated as `9 - log10(IC50_nM)` and used as the primary
    property. A ChEMBL pChEMBL value is not required.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## Step 1 — identify the target

    The workflow verifies at build time that `CHEMBL231` is still annotated
    as a human single-protein target. This prevents silently building against
    a similarly named receptor from another species.

    ## Step 2 — select assays

    ChEMBL binding assays (`assay_type=B`) are downloaded. Only assays whose
    target relationship is direct (`relationship_type=D`) are retained.

    ## Step 3 — select IC50 measurements

    Activity rows must have an exact, positive standardized IC50 value in nM,
    be marked as standard records, not be potential duplicates, have no
    data-validity warning, and be assigned to *Homo sapiens*.

    ## Step 4 — standardize structures

    RDKit parses and cleans each SMILES, selects the parent fragment, and
    writes canonical isomeric SMILES. Invalid structures are excluded.

    ## Step 5 — aggregate replicates

    Each accepted value is converted with `pIC50 = 9 - log10(IC50_nM)`. Rows
    are grouped by parent ChEMBL molecule ID and median pIC50 is used, while
    replicate count and range remain in the audit table.

    ## Step 6 — fragment structures

    `mmpdb fragment` applies its standard rotatable-bond fragmentation rules.
    The fragment database is an intermediate and can be regenerated.

    ## Step 7 — index matched pairs

    `mmpdb index` stores the transformations it identifies for each compound
    pair and loads calculated pIC50 as the sole property into a SQLite `.mmpdb`
    database.

    ## Step 8 — validate and audit

    Counts for compounds, fragmentations, rules, pairs, and environments are
    written to `build_report.json`. Raw API snapshots and accepted records are
    retained as compressed JSON Lines files.
    """)
    return


@app.cell
def _(Path, mo):
    project_root = Path(__file__).resolve().parents[1]
    build_button = mo.ui.run_button(label="Rebuild database from ChEMBL")
    mo.hstack([build_button, mo.md(f"Project: `{project_root}`")], justify="start")
    return build_button, project_root


@app.cell
def _(build_button, build_h1_database, project_root):
    build_result = build_h1_database(project_root) if build_button.value else None
    return


@app.cell
def _(json, mo, project_root):
    report_path = project_root / "data" / "processed" / "build_report.json"
    saved_report = json.loads(report_path.read_text()) if report_path.exists() else None
    report_view = (
        mo.ui.table([saved_report], selection=None)
        if saved_report
        else mo.callout(
            "No database has been built yet. Use the button above.", kind="warn"
        )
    )
    mo.vstack([mo.md("## Build report"), report_view])
    return (saved_report,)


@app.cell
def _(PRIMARY_PROPERTY, mo, project_root, saved_report, sqlite3):
    database_path = project_root / "data" / "processed" / "h1_ic50.mmpdb"
    if saved_report and database_path.exists():
        with sqlite3.connect(database_path) as _connection:
            _property_row = _connection.execute(
                "SELECT name FROM property_name ORDER BY id LIMIT 1"
            ).fetchone()
        validation_text = (
            f"Database property: `{_property_row[0]}`; expected primary property: "
            f"`{PRIMARY_PROPERTY}`. Database: `{database_path}`."
        )
        validation_view = mo.callout(validation_text, kind="success")
    else:
        validation_view = mo.callout(
            "Build the database to run validation.", kind="info"
        )
    return


if __name__ == "__main__":
    app.run()
