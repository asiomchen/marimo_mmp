"""Anywidget reaction-constellation renderer."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from importlib.resources import files
from statistics import median
from typing import Any

import anywidget
import traitlets

from .dataset import (
    EvidenceThresholds,
    PropertyStats,
    SourcePair,
    TransformDataset,
    TransformFilters,
    TransformRecord,
    TransformView,
)
from .depiction import molecule_svg

DEFAULT_GRAPH_HEIGHT = 1220


@dataclass(frozen=True, slots=True)
class TransformGraphState:
    """Immutable Python snapshot of the graph's current interactive state."""

    property_name: str
    available_properties: tuple[str, ...]
    evidence_thresholds: EvidenceThresholds
    direction: str
    filters: TransformFilters
    max_nodes: int
    height: int
    selected_id: str | None
    shown_compounds: tuple[TransformRecord, ...]
    matching_count: int
    query_smiles: str | None
    warnings: tuple[str, ...]
    _has_mmpdb: bool = field(repr=False)
    _dataset: TransformDataset = field(repr=False, compare=False)

    @property
    def shown_count(self) -> int:
        return len(self.shown_compounds)

    @property
    def truncated(self) -> bool:
        return self.matching_count > self.shown_count

    @property
    def selected_compound(self) -> TransformRecord | None:
        if self.selected_id is None:
            return None
        return self.record(self.selected_id)

    @property
    def selected_stats(self) -> PropertyStats | None:
        selected = self.selected_compound
        return None if selected is None else selected.properties.get(self.property_name)

    def record(self, record_id: str) -> TransformRecord | None:
        target = str(record_id)
        return next(
            (record for record in self.shown_compounds if record.id == target), None
        )

    def has_mmpdb(self) -> bool:
        """Return whether source-pair provenance was loaded from an MMPDB."""
        return self._has_mmpdb

    def rows(self) -> list[dict[str, Any]]:
        """Return table-ready rows for the shown compounds."""
        return TransformView(
            dataset=self._dataset,
            property=self.property_name,
            records=self.shown_compounds,
            total_matching=self.matching_count,
            max_nodes=self.max_nodes,
            filters=self.filters,
        ).rows()

    def source_pairs(
        self, record_id: str | None = None, *, include_missing: bool = False
    ) -> tuple[SourcePair, ...]:
        """Return selected-property source pairs for a shown compound.

        The selected compound is used when ``record_id`` is omitted. Set
        ``include_missing=True`` to inspect structural pairs with a missing
        selected-property value.
        """
        target = self.selected_id if record_id is None else str(record_id)
        if target is None:
            return ()
        if self.record(target) is None:
            raise KeyError(f"transform ID {target!r} is not among the shown compounds")
        if not self.has_mmpdb():
            return ()
        return self._dataset.source_pairs(
            target, self.property_name, include_missing=include_missing
        )


def _store_depiction(depictions: dict[str, str], svg: str) -> str:
    depiction_id = f"sha256:{hashlib.sha256(svg.encode('utf-8')).hexdigest()}"
    existing = depictions.setdefault(depiction_id, svg)
    if existing != svg:
        raise RuntimeError(f"depiction digest collision for {depiction_id}")
    return depiction_id


def _payload(
    view: TransformView,
    direction: str = "higher",
    *,
    highlight_changes: bool = False,
) -> tuple[dict[str, Any], dict[str, str]]:
    original = view.dataset.original_smiles
    depictions: dict[str, str] = {}
    products: list[dict[str, Any]] = []
    from_groups: dict[str, dict[str, Any]] = {}
    groups: dict[str, dict[str, Any]] = {}
    for record in view.records:
        stats = record.properties[view.property]
        from_group_id = f"from:{stats.from_smiles}"
        group_id = (
            f"rule:{stats.rule_environment_id}:{stats.from_smiles}>{stats.to_smiles}"
        )
        from_groups.setdefault(
            from_group_id,
            {
                "id": from_group_id,
                "from": stats.from_smiles,
                "fromDepictionId": _store_depiction(
                    depictions,
                    molecule_svg(stats.from_smiles, None, 220, 140),
                ),
                "ruleIds": [],
                "productCount": 0,
            },
        )
        groups.setdefault(
            group_id,
            {
                "id": group_id,
                "environmentId": stats.rule_environment_id,
                "fromGroup": from_group_id,
                "from": stats.from_smiles,
                "to": stats.to_smiles,
                "fromDepictionId": _store_depiction(
                    depictions,
                    molecule_svg(stats.from_smiles, None, 220, 140),
                ),
                "toDepictionId": _store_depiction(
                    depictions,
                    molecule_svg(stats.to_smiles, None, 220, 140),
                ),
                "smarts": stats.smarts,
                "pseudosmiles": stats.pseudosmiles,
                "radius": stats.radius,
                "median": stats.median,
                "min": stats.min,
                "max": stats.max,
                "count": stats.count,
                "evidence": stats.evidence.value,
            },
        )
        source_group = from_groups[from_group_id]
        if group_id not in source_group["ruleIds"]:
            source_group["ruleIds"].append(group_id)
        source_group["productCount"] += 1
        products.append(
            {
                "id": record.id,
                "smiles": record.smiles,
                "group": group_id,
                "median": stats.median,
                "count": stats.count,
                "evidence": stats.evidence.value,
                "radius": stats.radius,
                "std": stats.std,
                "min": stats.min,
                "q1": stats.q1,
                "q3": stats.q3,
                "max": stats.max,
                "pValue": stats.p_value,
                "missing": list(stats.missing_statistics),
                "depictionId": _store_depiction(
                    depictions,
                    molecule_svg(
                        record.smiles, original if highlight_changes else None, 180, 116
                    ),
                ),
            }
        )

    for source_group in from_groups.values():
        child_rules = [groups[group_id] for group_id in source_group["ruleIds"]]
        effects = [rule["median"] for rule in child_rules]
        source_group.update(
            {
                "ruleCount": len(child_rules),
                "gainCount": sum(
                    (effect > 0) if direction == "higher" else (effect < 0)
                    for effect in effects
                ),
                "lossCount": sum(
                    (effect < 0) if direction == "higher" else (effect > 0)
                    for effect in effects
                ),
                "neutralCount": sum(effect == 0 for effect in effects),
                "totalSupport": sum(rule["count"] for rule in child_rules),
                "aggregateMedian": median(effects),
                "effectMin": min(effects),
                "effectMax": max(effects),
            }
        )
    query_depiction_id = (
        _store_depiction(depictions, molecule_svg(original, None, 210, 140))
        if original
        else None
    )
    return {
        "properties": list(view.dataset.properties),
        "controlOptions": {
            "radii": sorted(
                {
                    record.properties[view.property].radius
                    for record in view.dataset.records
                    if view.property in record.properties
                }
            ),
            "maxSupport": max(
                (
                    record.properties[view.property].count
                    for record in view.dataset.records
                    if view.property in record.properties
                ),
                default=1,
            ),
            "maxEffect": max(
                (
                    abs(record.properties[view.property].median)
                    for record in view.dataset.records
                    if view.property in record.properties
                ),
                default=1.0,
            ),
            "evidenceThresholds": {
                "moderate": view.dataset.evidence_thresholds.moderate,
                "strong": view.dataset.evidence_thresholds.strong,
            },
        },
        "querySmiles": original,
        "queryDepictionId": query_depiction_id,
        "products": products,
        "fromGroups": list(from_groups.values()),
        "groups": list(groups.values()),
        "shown": len(products),
        "matching": view.total_matching,
        "truncated": view.truncated,
        "warnings": list(view.dataset.warnings),
        "hasMmpdb": view.dataset.mmpdb_path is not None,
    }, depictions


class TransformGraph(anywidget.AnyWidget):
    """Render a matched-molecular-pair dataset as an interactive graph.

    Python owns filtering, aggregation, molecule depiction, and conversion to
    browser-safe state. The packaged Anywidget frontend owns layout and user
    interaction, synchronizing selection and graph controls back to Python.

    Parameters
    ----------
    dataset : TransformDataset
        Loaded transform records and optional source-pair provenance.
    property : str or None, default=None
        Property to display. Defaults to the dataset's first property.
    filters : TransformFilters or mapping or None, default=None
        Initial product filters. Defaults to all products.
    max_nodes : int, default=100
        Maximum number of visible products after filtering and ranking.
    height : int, default=DEFAULT_GRAPH_HEIGHT
        Maximum graph-stage height in pixels. The rendered stage also caps
        itself to the browser viewport. Values below 480 are rejected by the
        synchronized trait.
    direction : {"higher", "lower"}, default="higher"
        Property orientation that decides whether an increase or a decrease
        counts as a favorable change. Favorable changes are colored as gains
        and unfavorable ones as losses, and the Gains/Losses/Neutral filter
        follows the same orientation.
    highlight_changes : bool, default=False
        Highlight product atoms that differ from the query compound. Requires
        query SMILES on the dataset. Enabling this performs potentially slow
        maximum-common-substructure searches for uncached product depictions.
        This constructor setting is retained across updates and copies.
    **kwargs : Any
        Additional keyword arguments forwarded to ``anywidget.AnyWidget``.

    Notes
    -----
    ``state`` returns an immutable, domain-aware snapshot of the synchronized
    traits. In marimo, wrap this widget with ``mo.ui.anywidget`` when downstream
    cells should react to selection or control changes; other Anywidget hosts
    can display the raw instance directly.
    """

    data = traitlets.Dict().tag(sync=True)
    depictions = traitlets.Dict().tag(sync=True)
    selected_id = traitlets.Unicode(allow_none=True, default_value=None).tag(sync=True)
    property_name = traitlets.Unicode().tag(sync=True)
    direction = traitlets.Enum(("higher", "lower"), default_value="higher").tag(
        sync=True
    )
    filters = traitlets.Dict().tag(sync=True)
    max_nodes = traitlets.Int(100, min=1).tag(sync=True)
    height = traitlets.Int(DEFAULT_GRAPH_HEIGHT, min=480).tag(sync=True)
    _control_request = traitlets.Dict(default_value={}).tag(sync=True)
    _control_response = traitlets.Dict(default_value={}).tag(sync=True)
    _esm = files("marimo_mmp").joinpath("static/transform_graph.js")
    _css = files("marimo_mmp").joinpath("static/transform_graph.css")

    def __init__(
        self,
        dataset: TransformDataset,
        *,
        property: str | None = None,
        filters: TransformFilters | Mapping[str, Any] | None = None,
        max_nodes: int = 100,
        height: int = DEFAULT_GRAPH_HEIGHT,
        direction: str = "higher",
        highlight_changes: bool = False,
        **kwargs: Any,
    ) -> None:
        if not isinstance(dataset, TransformDataset):
            raise TypeError("TransformGraph expects a TransformDataset")
        if not isinstance(highlight_changes, bool):
            raise TypeError("highlight_changes must be a boolean")
        if direction not in ("higher", "lower"):
            raise ValueError("direction must be higher or lower")
        view = dataset.view(
            property=property, filters=filters, max_nodes=max_nodes, direction=direction
        )
        self._highlight_changes = highlight_changes
        self._dataset = dataset
        self._suspend_refresh = True
        self._control_revision = 0
        initial = view.records[0].id if view.records else None
        data, depictions = _payload(
            view, direction, highlight_changes=self.highlight_changes
        )
        super().__init__(
            data=data,
            depictions=depictions,
            selected_id=initial,
            property_name=view.property,
            direction=direction,
            filters=asdict(view.filters),
            max_nodes=view.max_nodes,
            height=height,
            _control_request={},
            _control_response={"revision": 0, "ok": True, "error": None},
            **kwargs,
        )
        self._suspend_refresh = False

    @property
    def highlight_changes(self) -> bool:
        """Whether product depictions highlight differences from the query."""
        return self._highlight_changes

    @traitlets.observe("property_name", "filters", "max_nodes", "direction")
    def _controls_changed(self, change: dict[str, Any]) -> None:
        if getattr(self, "_suspend_refresh", False):
            return
        self._refresh()

    @traitlets.observe("_control_request")
    def _control_requested(self, change: dict[str, Any]) -> None:
        """Validate and atomically accept a complete browser control state."""
        if getattr(self, "_suspend_refresh", False):
            return
        request = change["new"]
        revision: Any = request.get("revision") if isinstance(request, dict) else None
        try:
            if not isinstance(request, dict):
                raise TypeError("control request must be an object")
            expected = {
                "revision",
                "property_name",
                "direction",
                "filters",
                "max_nodes",
            }
            if set(request) != expected:
                raise ValueError(
                    "control request must contain revision, direction, property_name, filters, and max_nodes"
                )
            if (
                isinstance(revision, bool)
                or not isinstance(revision, int)
                or revision < 1
            ):
                raise ValueError("control revision must be a positive integer")
            if revision <= self._control_revision:
                raise ValueError(f"stale control revision {revision}")
            self._control_revision = revision
            property_name = request["property_name"]
            direction = request["direction"]
            filters = request["filters"]
            max_nodes = request["max_nodes"]
            if not isinstance(property_name, str):
                raise TypeError("property_name must be a string")
            if not isinstance(direction, str) or direction not in {
                "higher",
                "lower",
            }:
                raise ValueError("direction must be higher or lower")
            if not isinstance(filters, dict):
                raise TypeError("filters must be an object")
            if isinstance(max_nodes, bool) or not isinstance(max_nodes, int):
                raise TypeError("max_nodes must be an integer")
            view = self._dataset.view(
                property=property_name,
                filters=filters,
                max_nodes=max_nodes,
                direction=direction,
            )
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            self._control_response = {
                "revision": revision,
                "ok": False,
                "error": str(exc),
            }
            return

        self._suspend_refresh = True
        try:
            with self.hold_sync():
                self.property_name = view.property
                self.direction = direction
                self.filters = asdict(view.filters)
                self.max_nodes = view.max_nodes
                self._refresh(
                    view=view,
                    response={"revision": revision, "ok": True, "error": None},
                )
        finally:
            self._suspend_refresh = False

    def _refresh(
        self,
        *,
        reset_depictions: bool = False,
        view: TransformView | None = None,
        response: dict[str, Any] | None = None,
    ) -> None:
        if view is None:
            view = self._dataset.view(
                property=self.property_name,
                filters=self.filters,
                max_nodes=self.max_nodes,
                direction=self.direction,
            )
        visible = {record.id for record in view.records}
        selected = (
            self.selected_id
            if self.selected_id in visible
            else (view.records[0].id if view.records else None)
        )
        data, required_depictions = _payload(
            view, self.direction, highlight_changes=self.highlight_changes
        )
        depictions = (
            required_depictions
            if reset_depictions
            else {**self.depictions, **required_depictions}
        )
        with self.hold_sync():
            if depictions != self.depictions:
                self.depictions = depictions
            self.data = data
            self.selected_id = selected
            if response is not None:
                self._control_response = response

    @property
    def state(self) -> TransformGraphState:
        """Return a typed snapshot derived from the synchronized widget state."""
        records_by_id = {record.id: record for record in self._dataset.records}
        product_ids = [str(product["id"]) for product in self.data.get("products", ())]
        try:
            shown_compounds = tuple(
                records_by_id[record_id] for record_id in product_ids
            )
        except KeyError as exc:
            raise RuntimeError(
                f"graph payload references unknown transform ID {exc.args[0]!r}"
            ) from exc
        selected_id = self.selected_id if self.selected_id in product_ids else None
        return TransformGraphState(
            property_name=self.property_name,
            available_properties=tuple(
                self.data.get("properties", self._dataset.properties)
            ),
            evidence_thresholds=self._dataset.evidence_thresholds,
            direction=self.direction,
            filters=TransformFilters.coerce(self.filters),
            max_nodes=self.max_nodes,
            height=self.height,
            selected_id=selected_id,
            shown_compounds=shown_compounds,
            matching_count=int(self.data.get("matching", len(shown_compounds))),
            query_smiles=self.data.get("querySmiles"),
            warnings=tuple(self.data.get("warnings", ())),
            _has_mmpdb=bool(self.data.get("hasMmpdb", False)),
            _dataset=self._dataset,
        )

    def update(
        self,
        dataset: TransformDataset,
        *,
        property: str | None = None,
        filters: TransformFilters | Mapping[str, Any] | None = None,
        max_nodes: int = 100,
        direction: str | None = None,
    ) -> None:
        """Replace graph data and filters, retaining a still-visible selection.

        Property, filters, and product limit use the constructor defaults when
        omitted. Direction retains its current value unless supplied. Height
        and changed-atom highlighting are retained. Invalid view options leave
        the current dataset and state intact.
        """
        if not isinstance(dataset, TransformDataset):
            raise TypeError("TransformGraph.update expects a TransformDataset")
        selected_direction = self.direction if direction is None else direction
        if selected_direction not in ("higher", "lower"):
            raise ValueError("direction must be higher or lower")
        view = dataset.view(
            property=property,
            filters=filters,
            max_nodes=max_nodes,
            direction=selected_direction,
        )
        dataset_changed = dataset is not self._dataset
        self._suspend_refresh = True
        try:
            self._dataset = dataset
            self.property_name = view.property
            self.direction = selected_direction
            self.filters = asdict(view.filters)
            self.max_nodes = view.max_nodes
            self._refresh(view=view, reset_depictions=dataset_changed)
        finally:
            self._suspend_refresh = False

    def __deepcopy__(self, memo: dict[int, Any]) -> TransformGraph:
        """Copy the domain-aware widget without copying anywidget comm state."""
        state = self.state
        dataset = deepcopy(self._dataset, memo)
        clone = TransformGraph(
            dataset,
            property=state.property_name,
            filters=state.filters,
            max_nodes=state.max_nodes,
            height=state.height,
            direction=state.direction,
            highlight_changes=self.highlight_changes,
        )
        clone.selected_id = state.selected_id
        memo[id(self)] = clone
        return clone
