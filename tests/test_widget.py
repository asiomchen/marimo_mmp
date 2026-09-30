import hashlib
import inspect
import json
import re
from collections.abc import MutableMapping
from copy import deepcopy
from dataclasses import FrozenInstanceError, asdict, replace
from pathlib import Path
from statistics import median
from typing import Any, cast

import marimo as mo
import pandas as pd
import pytest
import traitlets

from marimo_mmp import (
    EvidenceThresholds,
    PropertyStats,
    TransformDataset,
    TransformFilters,
    TransformGraph,
    TransformGraphState,
)
from marimo_mmp.depiction import molecule_svg

ROOT = Path(__file__).resolve().parents[1]
TRANSFORMS = ROOT / "data" / "processed" / "bilastine_transforms.tsv"
ORIGINAL = "CCOCCn1c(C2CCN(CCc3ccc(C(C)(C)C(=O)O)cc3)CC2)nc2ccccc21"
MMPDB = ROOT / "data" / "processed" / "h1_ic50.mmpdb"


def _z_index(css: str, selector: str) -> int:
    rule = re.search(rf"{re.escape(selector)}\s*\{{[^}}]*\bz-index:\s*(\d+)", css)
    assert rule is not None
    return int(rule.group(1))


def _referenced_depictions(data):
    result = {product["depictionId"] for product in data["products"]}
    result.update(group["fromDepictionId"] for group in data["fromGroups"])
    for group in data["groups"]:
        result.add(group["fromDepictionId"])
        result.add(group["toDepictionId"])
    if data["queryDepictionId"] is not None:
        result.add(data["queryDepictionId"])
    return result


def test_graph_topology_payload_and_local_assets():
    dataset = TransformDataset.from_tsv(TRANSFORMS, original_smiles=ORIGINAL)
    graph = TransformGraph(dataset, max_nodes=25)
    assert len(graph.data["products"]) == 25
    assert {product["group"] for product in graph.data["products"]} <= {
        group["id"] for group in graph.data["groups"]
    }
    assert {group["fromGroup"] for group in graph.data["groups"]} <= {
        group["id"] for group in graph.data["fromGroups"]
    }
    assert graph.data["queryDepictionId"] in graph.depictions
    assert _referenced_depictions(graph.data) <= set(graph.depictions)
    assert all(svg.startswith("<") for svg in graph.depictions.values())
    assert "querySvg" not in graph.data
    assert all("svg" not in product for product in graph.data["products"])
    assert all("fromSvg" not in group for group in graph.data["fromGroups"])
    assert all(
        "fromSvg" not in group and "toSvg" not in group
        for group in graph.data["groups"]
    )
    assert all(
        depiction_id == f"sha256:{hashlib.sha256(svg.encode('utf-8')).hexdigest()}"
        for depiction_id, svg in graph.depictions.items()
    )
    assert all(
        "smarts" in group and "pseudosmiles" in group for group in graph.data["groups"]
    )
    assert all("min" in group and "max" in group for group in graph.data["groups"])
    assert all(
        "min" in product and "max" in product for product in graph.data["products"]
    )
    assert graph.data["properties"] == ["pIC50"]
    assert graph.data["controlOptions"]["radii"]
    assert graph.data["controlOptions"]["evidenceThresholds"] == {
        "moderate": 2,
        "strong": 5,
    }
    assert graph.state.evidence_thresholds == EvidenceThresholds()
    assert len(json.dumps(graph.data, separators=(",", ":")).encode()) < 30_000
    assert graph.height == 1220
    frontend_source = (ROOT / "frontend" / "transform_graph.ts").read_text()
    css_source = (ROOT / "frontend" / "transform_graph.css").read_text()
    esm_source = graph._esm
    assert isinstance(esm_source, str)
    assert "https://esm.sh" not in esm_source
    assert "https://cdn" not in esm_source
    assert "sourceMappingURL" not in esm_source
    assert 'import "./transform_graph.css"' in frontend_source
    assert "export function render" in frontend_source
    assert "export function resolveDepiction" in frontend_source
    assert 'event.pointerType === "touch"' in frontend_source
    assert 'event.key === "Escape"' in frontend_source
    assert "window.visualViewport" in frontend_source
    assert 'role: "button"' in frontend_source
    assert ":focus" in css_source
    assert "prefers-reduced-motion" in css_source
    assert "@media (max-width: 680px)" in css_source
    assert ".mmp-stage.is-pannable" in css_source
    assert "touch-action: pan-x pan-y" in css_source
    assert "container-type: inline-size" in css_source
    assert "@container (min-width: 900px)" in css_source
    assert ".mmp-frame" in css_source
    assert "grid-template-columns: minmax(240px, 290px) minmax(0, 1fr)" in css_source
    assert ".mmp-frame.is-collapsed" in css_source
    assert "mmp-sidebar-toggle" in frontend_source
    assert "mmp-sidebar-toggle" in css_source
    assert "aria-expanded" in frontend_source
    assert "calc(100dvh - 140px)" in css_source
    assert "min-height: 480px" in css_source
    assert "calc(100vw - 32px)" in css_source
    assert ".mmp-tooltip.is-compact .mmp-tooltip-product" in css_source
    assert _z_index(css_source, ".mmp-tooltip") > _z_index(css_source, ".mmp-toolbar")
    assert "var(--background" in css_source
    assert "var(--popover" in css_source
    assert "max-height: 680px" not in css_source
    assert "mmp-detail" not in frontend_source
    assert ".mmp-detail" not in css_source


@pytest.mark.parametrize("highlight_changes", [False, True])
def test_highlighting_is_opt_in_and_preserved_across_refreshes_and_copies(
    monkeypatch, highlight_changes
):
    import marimo_mmp.depiction as depiction_module
    import marimo_mmp.widget as widget_module

    frame = pd.DataFrame(
        {
            "ID": ["1"],
            "SMILES": ["CCN"],
            "activity_from_smiles": ["[*:1]O"],
            "activity_to_smiles": ["[*:1]N"],
            "activity_radius": [0],
            "activity_rule_environment_id": [1],
            "activity_count": [1],
            "activity_median": [1.0],
        }
    )
    dataset = TransformDataset.from_df(frame, original_smiles="CCO")
    searches = []
    original_changed_atoms = depiction_module._changed_atoms

    def track_changed_atoms(molecule, reference):
        searches.append(molecule)
        return original_changed_atoms(molecule, reference)

    monkeypatch.setattr(depiction_module, "_changed_atoms", track_changed_atoms)
    # Cached SVGs must not hide an accidental expensive search in this test.
    monkeypatch.setattr(widget_module, "molecule_svg", molecule_svg.__wrapped__)

    graph = (
        TransformGraph(dataset, highlight_changes=True)
        if highlight_changes
        else TransformGraph(dataset)
    )
    graph.max_nodes = 1
    graph.filters = {"effect": "gain"}
    graph.update(TransformDataset.from_df(frame, original_smiles="CCO"))
    clone = deepcopy(graph)
    wrapped_clone = deepcopy(mo.ui.anywidget(graph))

    for widget in (graph, clone, wrapped_clone.widget):
        assert isinstance(widget, TransformGraph)
        assert widget.highlight_changes is highlight_changes
        assert widget.data["querySmiles"] == "CCO"
        assert widget.data["queryDepictionId"] in widget.depictions
        svg = widget.depictions[widget.data["products"][0]["depictionId"]]
        unhighlighted = molecule_svg.__wrapped__("CCN", None, 180, 116)
        assert (svg != unhighlighted) is highlight_changes
    assert bool(searches) is highlight_changes


def test_highlight_changes_requires_a_boolean():
    dataset = TransformDataset.from_tsv(TRANSFORMS)
    with pytest.raises(TypeError, match="highlight_changes must be a boolean"):
        TransformGraph(dataset, highlight_changes=cast(bool, "false"))


def test_from_smiles_groups_aggregate_visible_directed_rules():
    dataset = TransformDataset.from_tsv(TRANSFORMS)
    graph = TransformGraph(dataset, max_nodes=100)

    source = next(
        group for group in graph.data["fromGroups"] if group["from"] == "[*:1]C"
    )
    rules = [
        group for group in graph.data["groups"] if group["fromGroup"] == source["id"]
    ]
    products = [
        product
        for product in graph.data["products"]
        if product["group"] in source["ruleIds"]
    ]
    effects = [rule["median"] for rule in rules]

    assert source["ruleCount"] == len(rules) == len(source["ruleIds"])
    assert source["gainCount"] == sum(rule["median"] > 0 for rule in rules)
    assert source["lossCount"] == sum(rule["median"] < 0 for rule in rules)
    assert source["neutralCount"] == sum(rule["median"] == 0 for rule in rules)
    assert (
        source["gainCount"] + source["lossCount"] + source["neutralCount"]
        == source["ruleCount"]
    )
    assert source["productCount"] == len(products)
    assert source["totalSupport"] == sum(rule["count"] for rule in rules)
    assert source["aggregateMedian"] == median(effects)
    assert source["effectMin"] == min(effects)
    assert source["effectMax"] == max(effects)

    reversed_environment = [
        group for group in graph.data["groups"] if group["environmentId"] == 210
    ]
    assert len(reversed_environment) == 2
    assert len({group["fromGroup"] for group in reversed_environment}) == 2


def test_from_smiles_aggregate_tracks_visible_children_after_truncation():
    dataset = TransformDataset.from_tsv(TRANSFORMS)
    graph = TransformGraph(dataset, max_nodes=5)

    assert sum(group["productCount"] for group in graph.data["fromGroups"]) == 5
    assert {
        rule_id for group in graph.data["fromGroups"] for rule_id in group["ruleIds"]
    } == {group["id"] for group in graph.data["groups"]}


def test_depictions_are_deduplicated_and_dynamic_payload_stays_small():
    dataset = TransformDataset.from_tsv(TRANSFORMS)
    graph = TransformGraph(dataset, max_nodes=100)

    assert len(json.dumps(graph.data, separators=(",", ":")).encode()) < 200_000
    assert _referenced_depictions(graph.data) <= set(graph.depictions)
    for source_group in graph.data["fromGroups"]:
        child_rules = [
            group
            for group in graph.data["groups"]
            if group["fromGroup"] == source_group["id"]
        ]
        assert child_rules
        assert all(
            group["fromDepictionId"] == source_group["fromDepictionId"]
            for group in child_rules
        )


def test_depiction_cache_only_updates_for_new_assets_and_resets_for_a_new_dataset():
    dataset = TransformDataset.from_tsv(TRANSFORMS)
    graph = TransformGraph(dataset, max_nodes=5)
    depiction_events = []
    graph.observe(depiction_events.append, names="depictions")
    initial_depictions = dict(graph.depictions)

    graph.max_nodes = 25
    expanded_depictions = dict(graph.depictions)
    assert len(expanded_depictions) > len(initial_depictions)
    assert set(initial_depictions) < set(expanded_depictions)
    assert len(depiction_events) == 1

    graph.max_nodes = 5
    assert graph.depictions == expanded_depictions
    assert len(depiction_events) == 1

    graph.filters = {"min_support": 2, "effect": "all"}
    assert graph.depictions == expanded_depictions
    assert len(depiction_events) == 1

    replacement = TransformDataset.from_tsv(TRANSFORMS, original_smiles=ORIGINAL)
    graph.update(replacement, max_nodes=5)
    assert set(graph.depictions) == _referenced_depictions(graph.data)
    assert len(depiction_events) == 2


def test_graph_height_is_configurable_and_synced():
    dataset = TransformDataset.from_tsv(TRANSFORMS)
    graph = TransformGraph(dataset, max_nodes=5, height=1250)
    assert graph.height == 1250
    graph.height = 720
    assert graph.height == 720


def test_graph_exposes_custom_evidence_thresholds():
    thresholds = EvidenceThresholds(moderate=3, strong=8)
    dataset = TransformDataset.from_tsv(TRANSFORMS, evidence_thresholds=thresholds)
    graph = TransformGraph(dataset, max_nodes=5)

    assert graph.data["controlOptions"]["evidenceThresholds"] == {
        "moderate": 3,
        "strong": 8,
    }
    assert graph.state.evidence_thresholds == thresholds
    assert all(
        product["evidence"]
        == (
            "Strong"
            if product["count"] >= 8
            else "Moderate"
            if product["count"] >= 3
            else "Exploratory"
        )
        for product in graph.data["products"]
    )


def test_direction_reorients_payload_counts_and_gain_filter():
    dataset = TransformDataset.from_tsv(TRANSFORMS)
    graph = TransformGraph(dataset, max_nodes=100)
    flipped = TransformGraph(dataset, max_nodes=100, direction="lower")

    assert graph.direction == "higher"
    assert flipped.direction == "lower"
    assert graph.state.direction == "higher"
    assert flipped.state.direction == "lower"
    assert [
        (group["gainCount"], group["lossCount"]) for group in flipped.data["fromGroups"]
    ] == [
        (group["lossCount"], group["gainCount"]) for group in graph.data["fromGroups"]
    ]

    graph._control_request = {
        "revision": 1,
        "property_name": "pIC50",
        "direction": "lower",
        "filters": {"effect": "gain"},
        "max_nodes": 100,
    }
    assert graph.direction == "lower"
    assert graph.state.filters.effect == "gain"
    assert graph.state.shown_count
    assert all(record.properties["pIC50"].median < 0 for record in graph.state.records)


def test_direction_rejects_unknown_orientation():
    dataset = TransformDataset.from_tsv(TRANSFORMS)
    with pytest.raises(ValueError, match="direction must be higher or lower"):
        TransformGraph(dataset, direction="up")
    graph = TransformGraph(dataset, max_nodes=5)
    with pytest.raises(traitlets.TraitError):
        graph.direction = "up"


def test_embedded_controls_refresh_the_graph_state():
    dataset = TransformDataset.from_tsv(TRANSFORMS)
    graph = TransformGraph(dataset, max_nodes=100)
    graph.filters = {"min_support": 2, "effect": "all"}
    assert graph.state.shown_count == 27
    assert graph.state.filters == TransformFilters(min_support=2, effect="all")
    assert "filters" not in graph.data
    assert "property" not in graph.data

    graph.filters = {"quality": [], "radii": [], "effect": "all"}
    assert graph.state.records == ()
    assert graph.selected_id is None


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("filters", {"bogus": 1}),
        ("filters", {"effect": "sideways"}),
        ("property_name", "missing"),
        ("max_nodes", True),
    ],
)
def test_invalid_direct_control_assignment_preserves_accepted_state(name, value):
    graph = TransformGraph(TransformDataset.from_tsv(TRANSFORMS), max_nodes=5)
    state = graph.state
    data = dict(graph.data)
    with pytest.raises((KeyError, TypeError, ValueError, traitlets.TraitError)):
        setattr(graph, name, value)
    assert graph.state == state
    assert graph.data == data


def test_direct_filter_assignment_is_normalized():
    graph = TransformGraph(TransformDataset.from_tsv(TRANSFORMS))
    graph.filters = {"min_support": 2, "radii": [1, 2]}
    assert graph.filters == asdict(TransformFilters(min_support=2, radii=(1, 2)))


def test_atomic_control_request_refreshes_once_and_publishes_accepted_state(
    monkeypatch,
):
    dataset = TransformDataset.from_tsv(TRANSFORMS)
    graph = TransformGraph(dataset, max_nodes=100)
    original_refresh = graph._refresh
    refreshes = []
    published = []

    def counted_refresh(**kwargs):
        refreshes.append(kwargs)
        return original_refresh(**kwargs)

    monkeypatch.setattr(graph, "_refresh", counted_refresh)
    graph.observe(
        lambda change: published.append(
            (graph.property_name, dict(graph.filters), graph.max_nodes)
        ),
        names="data",
    )
    graph._control_request = {
        "revision": 1,
        "property_name": "pIC50",
        "direction": "higher",
        "filters": {"effect": "gain", "min_support": 2},
        "max_nodes": 12,
    }

    assert len(refreshes) == 1
    assert graph._control_response == {"revision": 1, "ok": True, "error": None}
    assert graph.property_name == "pIC50"
    assert graph.state.filters == TransformFilters(effect="gain", min_support=2)
    assert graph.max_nodes == 12
    assert published == [("pIC50", graph.filters, 12)]


def test_invalid_and_stale_control_requests_preserve_accepted_state():
    graph = TransformGraph(TransformDataset.from_tsv(TRANSFORMS), max_nodes=10)
    accepted = graph.state
    requests = [
        {
            "revision": 1,
            "property_name": "missing",
            "direction": "higher",
            "filters": {},
            "max_nodes": 10,
        },
        {
            "revision": 2,
            "property_name": "pIC50",
            "direction": "higher",
            "filters": {"unknown": True},
            "max_nodes": 10,
        },
        {
            "revision": 3,
            "property_name": "pIC50",
            "direction": "sideways",
            "filters": {},
            "max_nodes": 10,
        },
        {
            "revision": 4,
            "property_name": "pIC50",
            "direction": "higher",
            "filters": {},
            "max_nodes": 0,
        },
        {
            "revision": "5",
            "property_name": "pIC50",
            "direction": "higher",
            "filters": {},
            "max_nodes": 10,
        },
        {
            "revision": 2,
            "property_name": "pIC50",
            "direction": "higher",
            "filters": {},
            "max_nodes": 10,
        },
    ]

    for request in requests:
        graph._control_request = request
        assert graph._control_response["ok"] is False
        assert graph._control_response["error"]
        assert graph.state == accepted


def test_malformed_control_request_is_rejected_without_refresh(monkeypatch):
    graph = TransformGraph(TransformDataset.from_tsv(TRANSFORMS), max_nodes=10)
    refreshes = []
    monkeypatch.setattr(graph, "_refresh", lambda **kwargs: refreshes.append(kwargs))
    graph._control_request = {"revision": 1, "property_name": "pIC50"}

    assert refreshes == []
    assert graph._control_response["revision"] == 1
    assert graph._control_response["ok"] is False


def test_selection_persists_only_while_visible():
    dataset = TransformDataset.from_tsv(TRANSFORMS)
    graph = TransformGraph(dataset, max_nodes=20)
    chosen = graph.data["products"][5]["id"]
    graph.selected_id = chosen
    graph.update(dataset, max_nodes=10)
    expected = (
        chosen
        if chosen in {item["id"] for item in graph.data["products"]}
        else graph.data["products"][0]["id"]
    )
    assert graph.state.selected_id == expected
    graph.update(dataset, filters={"text": "does-not-exist"})
    assert graph.state.selected_id is None
    assert graph.state.selected_compound is None
    assert graph.state.selected_stats is None
    assert graph.state.rows() == []
    assert graph.state.source_pairs() == ()


def test_transform_graph_uses_standard_reactive_marimo_wrapper():
    dataset = TransformDataset.from_tsv(TRANSFORMS)
    view = dataset.view(max_nodes=5)
    raw_graph = TransformGraph(dataset, max_nodes=5, height=760)
    graph = mo.ui.anywidget(raw_graph)

    assert isinstance(graph, mo.ui.anywidget)
    assert graph.widget is raw_graph
    assert graph.height == graph.widget.height == 760
    assert graph.property_name == graph.widget.property_name == "pIC50"
    assert not hasattr(graph.widget, "property")
    assert graph.data == graph.widget.data
    assert not hasattr(graph.widget, "view")

    assert graph.value == {
        name: getattr(raw_graph, name)
        for name in (
            "_control_request",
            "_control_response",
            "data",
            "depictions",
            "direction",
            "filters",
            "height",
            "max_nodes",
            "property_name",
            "selected_id",
        )
    }

    state = graph.state
    assert isinstance(state, TransformGraphState)
    assert state.property_name == "pIC50"
    assert state.available_properties == ("pIC50",)
    assert state.filters == TransformFilters()
    assert state.max_nodes == 5
    assert state.height == 760
    assert state.records == view.records
    assert state.shown_count == 5
    assert state.matching_count == view.matching_count
    assert state.truncated == view.truncated
    assert state.selected_compound == view.records[0]
    assert state.selected_stats == view.records[0].properties[view.property_name]
    assert state.rows() == view.rows()
    assert state.source_pairs() == ()
    with pytest.raises(FrozenInstanceError):
        state.selected_id = "replacement"

    selected_id = graph.data["products"][1]["id"]
    graph.selected_id = selected_id
    assert graph.widget.selected_id == selected_id
    assert graph.value["selected_id"] == selected_id
    assert graph.state.selected_id == selected_id
    assert graph.state.selected_compound.id == selected_id

    graph.filters = {"min_support": 2, "effect": "all"}
    refreshed = graph.state
    assert refreshed.filters.min_support == 2
    assert refreshed.shown_count == 5
    assert refreshed.matching_count == 27
    assert state.shown_count == 5
    assert state.filters == TransformFilters()

    with pytest.raises(KeyError, match="not among the shown compounds"):
        refreshed.source_pairs("does-not-exist")

    graph.selected_id = "does-not-exist"
    assert graph.state.selected_id is None
    assert graph.state.selected_compound is None

    raw_clone = deepcopy(raw_graph)
    assert isinstance(raw_clone, TransformGraph)
    assert raw_clone.state == graph.state
    assert raw_clone._dataset is not raw_graph._dataset
    assert raw_clone._dataset._source_pairs is not raw_graph._dataset._source_pairs

    clone = deepcopy(graph)
    assert isinstance(clone, mo.ui.anywidget)
    assert isinstance(clone.widget, TransformGraph)
    assert clone.state == graph.state
    assert clone.value["filters"] == asdict(graph.state.filters)
    assert clone.value["selected_id"] is None
    assert clone.widget._dataset is not graph.widget._dataset
    assert (
        clone.widget._dataset._source_pairs is not graph.widget._dataset._source_pairs
    )
    assert clone.widget._control_request == {}
    assert clone.widget._control_response == {"revision": 0, "ok": True, "error": None}


def test_graph_state_properties_cannot_mutate_the_snapshot_or_dataset():
    dataset = TransformDataset.from_tsv(TRANSFORMS)
    graph = TransformGraph(dataset, max_nodes=1)
    snapshot = graph.state
    stats = snapshot.selected_stats
    assert stats is not None
    record = snapshot.records[0]
    properties = cast(MutableMapping[str, PropertyStats], record.properties)
    rows = snapshot.rows()
    with pytest.raises(TypeError):
        properties[snapshot.property_name] = replace(stats, median=999)
    with pytest.raises(TypeError):
        del properties[snapshot.property_name]
    assert snapshot.selected_stats == stats
    dataset_record = next(item for item in dataset.records if item.id == record.id)
    assert dataset_record.properties[snapshot.property_name] == stats
    assert snapshot.rows() == rows
    assert graph.data["products"][0]["median"] == stats.median
    assert deepcopy(graph).state == snapshot


def test_graph_state_constructor_hides_private_dataset():
    from marimo_mmp.widget import TransformGraphState

    parameters = inspect.signature(TransformGraphState).parameters
    assert not any(name.startswith("_") for name in parameters)
    state = TransformGraph(TransformDataset.from_tsv(TRANSFORMS), max_nodes=1).state
    assert "_dataset" not in repr(state)
    assert not state.has_mmpdb


def test_graph_state_is_hashable_and_matches_equal_snapshots():
    graph = TransformGraph(TransformDataset.from_tsv(TRANSFORMS), max_nodes=5)
    state = graph.state
    assert hash(state) == hash(graph.state)
    assert hash(deepcopy(graph).state) == hash(state)
    converted = asdict(state)
    assert converted["property_name"] == state.property_name
    assert len(converted["records"]) == state.shown_count


def test_transform_graph_requires_transform_dataset():
    with pytest.raises(TypeError, match="expects a TransformDataset"):
        TransformGraph(cast(TransformDataset, object()))


@pytest.fixture
def multi_property_dataset():
    frame = pd.DataFrame({"ID": ["1", "2", "3"], "SMILES": ["CCN", "CCC", "CCF"]})
    for property, medians in (("activity", [3, 2, 1]), ("logD", [-2, -1, 0.5])):
        for suffix, values in {
            "from_smiles": ["[*:1]O"] * 3,
            "to_smiles": ["[*:1]N", "[*:1]C", "[*:1]F"],
            "radius": [0] * 3,
            "rule_environment_id": [1, 2, 3],
            "count": [4, 3, 5],
            "median": medians,
        }.items():
            frame[f"{property}_{suffix}"] = values
    return TransformDataset.from_df(frame, original_smiles="CCO")


@pytest.mark.parametrize("typed_filters", [False, True])
def test_constructor_selects_property_filters_limit_and_orientation(
    multi_property_dataset, typed_filters
):
    filters = (
        TransformFilters(effect="gain", min_support=2)
        if typed_filters
        else {"effect": "gain", "min_support": 2}
    )
    graph = TransformGraph(
        multi_property_dataset,
        property_name="logD",
        filters=filters,
        max_nodes=1,
        direction="lower",
    )
    state = graph.state
    assert state.available_properties == ("activity", "logD")
    assert state.property_name == "logD"
    assert state.direction == "lower"
    assert state.filters == TransformFilters(effect="gain", min_support=2)
    assert state.max_nodes == 1
    assert state.matching_count == 2
    assert [record.id for record in state.records] == ["1"]
    stats = state.selected_stats
    assert stats is not None
    assert stats.median == -2
    assert graph.data["fromGroups"][0]["gainCount"] == 1
    assert deepcopy(graph).state == state


def test_update_accepts_dataset_and_options_and_retains_direction(
    multi_property_dataset,
):
    graph = TransformGraph(multi_property_dataset, max_nodes=1, height=760)
    graph.selected_id = "3"
    graph.update(
        multi_property_dataset,
        property_name="logD",
        filters={"effect": "gain"},
        max_nodes=2,
        direction="lower",
    )
    assert graph.state.property_name == "logD"
    assert graph.state.direction == "lower"
    assert [record.id for record in graph.state.records] == ["1", "2"]
    assert graph.state.selected_id == "1"
    graph.update(multi_property_dataset)
    assert graph.state.property_name == "activity"
    assert graph.state.filters == TransformFilters()
    assert graph.state.max_nodes == 100
    assert graph.state.direction == "lower"
    assert graph.state.height == 760
    assert graph.state.selected_id == "1"


@pytest.mark.parametrize(
    "options",
    [
        {"property_name": "missing"},
        {"max_nodes": 0},
        {"direction": "up"},
        {"filters": {"effect": "up"}},
    ],
)
def test_invalid_update_options_preserve_dataset_and_state(
    multi_property_dataset, options
):
    original = TransformDataset.from_tsv(TRANSFORMS)
    graph = TransformGraph(original, max_nodes=5)
    state = graph.state
    depictions = dict(graph.depictions)
    with pytest.raises((KeyError, ValueError)):
        graph.update(multi_property_dataset, **options)
    assert graph._dataset is original
    assert graph.state == state
    assert graph.depictions == depictions


def test_graph_state_queries_source_pairs_after_database_cleanup(tmp_path):
    database = tmp_path / "uploaded.mmpdb"
    database.write_bytes(MMPDB.read_bytes())
    dataset = TransformDataset.from_tsv(TRANSFORMS, mmpdb_path=database)
    database.unlink()
    state = TransformGraph(dataset, max_nodes=5).state

    assert state.has_mmpdb
    assert state.selected_id is not None
    assert state.source_pairs() == dataset.source_pairs(
        state.selected_id, state.property_name
    )
    assert state.source_pairs(include_missing=True) == dataset.source_pairs(
        state.selected_id, state.property_name, include_missing=True
    )


def test_explorer_uses_explicit_ui_element_dependencies():
    source = (ROOT / "notebooks" / "transform_explorer.py").read_text()

    assert "mo.state(" not in source
    assert ".observe(" not in source
    assert "mo.ui.anywidget(TransformGraph(" in source
    assert "graph_state = graph.state if graph is not None else None" in source
    assert "graph_state.selected_compound" in source
    assert "graph_state.source_pairs()" in source
    assert "graph_state.rows()" in source
    assert "graph.view" not in source
    assert 'freeze_columns_left=["ID"] if _rows else None' in source
    assert 'hidden_columns=["from_smiles", "to_smiles"] if _rows else None' in source


def test_rdkit_svg_is_sanitized_and_change_highlighted():
    svg = molecule_svg("CCN", "CCO")
    assert "<script" not in svg.lower()
    assert "javascript:" not in svg.lower()
    assert (
        "#e08f1f" not in svg
    )  # RDKit serializes the explicit highlight color, not raw CSS.
    assert "atom-2" in svg


def test_state_has_mmpdb_property_records_and_compact_repr():
    dataset = TransformDataset.from_tsv(TRANSFORMS, original_smiles=ORIGINAL)
    graph = TransformGraph(dataset, property_name="pIC50")
    state = graph.state
    assert state.has_mmpdb is False
    assert state.records == tuple(state.records)
    assert len(repr(state)) < 300
    assert "selected_id=" in repr(state)
    with pytest.raises((AttributeError, TypeError)):
        state.has_mmpdb = True
    with pytest.raises(TypeError):
        TransformGraph(dataset, **cast(Any, {"property": "pIC50"}))
    with pytest.raises(TypeError):
        graph.update(dataset, **cast(Any, {"property": "pIC50"}))
    with pytest.raises(ValueError, match="effect"):
        TransformGraph(dataset, filters={"effect": "up"})


def test_loading_and_depicting_emits_no_rdkit_stderr(capfd):
    molecule_svg.cache_clear()
    dataset = TransformDataset.from_tsv(TRANSFORMS, original_smiles=ORIGINAL)
    TransformGraph(dataset, highlight_changes=True)
    assert "not removing hydrogen" not in capfd.readouterr().err
