import marimo

__generated_with = "0.24.0"
app = marimo.App(width="full")


@app.cell
def _():
    import csv
    import io
    from pathlib import Path

    import marimo as mo

    from marimo_mmp import TransformDataset, TransformGraph

    return Path, TransformDataset, TransformGraph, csv, io, mo


@app.cell(hide_code=True)
def _(mo):
    mo.md("""
    # Transform explorer

    A minimal example of the three supported levels of context:

    | Provide | What becomes available |
    |---|---|
    | Transform results | Rule-to-product graph, effects, evidence filters, and export |
    | + query compound | Query structure and optional changed-atom highlights |
    | + MMPDB | Experimental source pairs, identifiers, values, and observed deltas |

    The transform file is required. The query SMILES and MMPDB are optional.
    """)
    return


@app.cell(hide_code=True)
def _(Path, mo):
    project_root = Path(__file__).resolve().parents[1]
    default_transform = project_root / "data" / "processed" / "bilastine_transforms.tsv"
    default_mmpdb = project_root / "data" / "processed" / "h1_ic50.mmpdb"
    bilastine_smiles = "CCOCCn1c(C2CCN(CCc3ccc(C(C)(C)C(=O)O)cc3)CC2)nc2ccccc21"

    transform_upload = mo.ui.file(
        filetypes=[".tsv"],
        kind="area",
        label="Transform results (TSV)",
    )
    original_input = mo.ui.text(
        value=bilastine_smiles,
        label="Query SMILES (optional)",
        full_width=True,
    )
    mmpdb_input = mo.ui.file(
        label="MMPDB file (optional, source pairs loaded into memory)",
        filetypes=[".mmpdb"],
        kind="area",
    )
    mo.vstack(
        [
            mo.md("## Inputs"),
            transform_upload,
            original_input,
            mmpdb_input,
            mo.md(
                f"No upload uses the included `{default_transform.name}` example. Clear either optional field to see the simpler modes."
            ),
        ]
    )
    return (
        default_mmpdb,
        default_transform,
        mmpdb_input,
        original_input,
        transform_upload,
    )


@app.cell
def _(
    Path,
    TransformDataset,
    default_mmpdb,
    default_transform,
    mmpdb_input,
    original_input,
    transform_upload,
):
    import tempfile
    from contextlib import ExitStack

    _source = (
        transform_upload.value[0].contents
        if transform_upload.value
        else default_transform
    )
    _original = original_input.value.strip() or None

    try:
        with ExitStack() as _cleanup:
            _database = default_mmpdb
            if mmpdb_input.value:
                _directory = _cleanup.enter_context(
                    tempfile.TemporaryDirectory(prefix="marimo-mmp-")
                )
                _database = Path(_directory) / "uploaded.mmpdb"
                _database.write_bytes(mmpdb_input.value[0].contents)

            dataset = TransformDataset.from_tsv(
                _source, original_smiles=_original, mmpdb=_database
            )
        load_error = None
    except (OSError, ValueError, TypeError) as _exc:
        dataset = None
        load_error = str(_exc)
    return dataset, load_error


@app.cell
def _(dataset, load_error, mo):
    load_status = (
        mo.callout(
            f"Loaded {len(dataset.records)} products · {len(dataset.properties)} property family/families"
            + (" · MMPDB source pairs loaded" if dataset.mmpdb_path else ""),
            kind="success",
        )
        if dataset is not None
        else mo.callout(
            f"Transform input could not be loaded: {load_error}", kind="danger"
        )
    )
    load_status
    return


@app.cell
def _(TransformGraph, dataset, mo):
    graph = (
        mo.ui.anywidget(TransformGraph(dataset, max_nodes=100, highlight_changes=False))
        if dataset is not None
        else None
    )
    return (graph,)


@app.cell
def _(graph, mo):
    if graph is None:
        graph_output = mo.callout(
            "Load valid transform results to draw the graph.", kind="info"
        )
    else:
        graph_output = graph
    graph_output
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Graph state reference

    `graph.state` is an immutable `TransformGraphState` snapshot and the public domain view of the graph's current interactive state. `graph.value` is marimo's dictionary of synchronized transport traits.

    | Property | Type | Meaning |
    |---|---|---|
    | `property_name` | `str` | Active matched-pair property, such as `pIC50`. |
    | `available_properties` | `tuple[str, ...]` | Property names available for exploration. |
    | `direction` | `str` | Property orientation: whether `higher` or `lower` deltas count as favorable (green) changes. |
    | `filters` | `TransformFilters` | Typed direction, effect, support, radius, evidence, text, standard-deviation, and p-value filters. |
    | `max_nodes` | `int` | Maximum number of compounds rendered after filtering and ranking. |
    | `height` | `int` | Graph stage height in pixels. |
    | `selected_id` | `str \| None` | ID of the selected visible compound, or `None`. |
    | `selected_compound` | `TransformRecord \| None` | Selected compound record, derived from `selected_id`. |
    | `selected_stats` | `PropertyStats \| None` | Active-property statistics for the selected compound. |
    | `shown_compounds` | `tuple[TransformRecord, ...]` | Visible compounds in the same order as the graph. |
    | `shown_count` | `int` | Number of compounds currently visible. |
    | `matching_count` | `int` | Number matching the filters before `max_nodes` truncation. |
    | `truncated` | `bool` | Whether more compounds matched than are shown. |
    | `query_smiles` | `str \| None` | Optional query-compound SMILES used for context and highlighting. |
    | `warnings` | `tuple[str, ...]` | Dataset validation or missing-statistic warnings. |

    ### State helpers

    | Method | Result |
    |---|---|
    | `has_mmpdb()` | Returns whether source-pair provenance was loaded from an MMPDB. |
    | `record(record_id)` | Returns a shown `TransformRecord`, or `None`. |
    | `rows()` | Returns table- and CSV-ready dictionaries for shown compounds. |
    | `source_pairs(record_id=None)` | Returns in-memory source pairs for a shown compound; defaults to the selected compound. |

    ```python
    state = graph.state
    state.selected_compound
    state.filters
    state.shown_compounds
    state.has_mmpdb()
    state.rows()
    ```
    """)
    return


@app.cell(hide_code=True)
def _(graph):
    graph_state = graph.state if graph is not None else None
    return (graph_state,)


@app.cell(hide_code=True)
def _(graph_state, mo):
    if graph_state is None or graph_state.selected_compound is None:
        _provenance_body = mo.callout(
            "Select a visible product to inspect its source pairs.", kind="info"
        )
    elif not graph_state.has_mmpdb():
        _provenance_body = mo.callout(
            "Upload an MMPDB file to inspect experimental source pairs.", kind="info"
        )
    else:
        _pair_rows = [
            {
                "from ID": pair.from_id,
                "to ID": pair.to_id,
                "from value": pair.from_value,
                "to value": pair.to_value,
                "observed delta": pair.delta,
                "from SMILES": pair.from_smiles,
                "to SMILES": pair.to_smiles,
            }
            for pair in graph_state.source_pairs()
        ]
        _provenance_body = mo.ui.table(
            _pair_rows,
            selection=None,
            pagination=False,
            show_download=True,
            hidden_columns=["from SMILES", "to SMILES"],
            label="Experimental source pairs",
        )
    mo.vstack([mo.md("## Source-pair provenance"), _provenance_body])
    return


@app.cell
def _(csv, graph_state, io, mo):
    _rows = graph_state.rows() if graph_state is not None else []
    results_table = mo.ui.table(
        _rows,
        selection="single",
        page_size=15,
        show_download=True,
        freeze_columns_left=["ID"] if _rows else None,
        hidden_columns=["from_smiles", "to_smiles"] if _rows else None,
        label="Filtered transform results",
    )

    def _csv_bytes():
        _buffer = io.StringIO()
        if _rows:
            _writer = csv.DictWriter(_buffer, fieldnames=list(_rows[0]))
            _writer.writeheader()
            _writer.writerows(_rows)
        return _buffer.getvalue()

    csv_download = mo.download(
        _csv_bytes,
        filename="filtered_transforms.csv",
        mimetype="text/csv",
        label="Download filtered CSV",
    )
    mo.vstack(
        [
            mo.md("## Filtered results"),
            mo.md(f"{len(_rows)} products shown."),
            csv_download,
            results_table,
        ]
    )
    return


if __name__ == "__main__":
    app.run()
