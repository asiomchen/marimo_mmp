import "./transform_graph.css";

type Evidence = "Strong" | "Moderate" | "Exploratory";
type Direction = "all" | "gain" | "loss" | "neutral";
type PropertyDirection = "higher" | "lower";
type TimerId = ReturnType<typeof globalThis.setTimeout>;
type FrameId = ReturnType<typeof globalThis.requestAnimationFrame>;

interface TransformFilters {
  direction: Direction;
  min_abs_effect: number;
  min_support: number;
  radii: number[] | null;
  quality: Evidence[] | null;
  text: string;
}

interface ControlState {
  property_name: string;
  direction: PropertyDirection;
  filters: TransformFilters;
  max_nodes: number;
}

interface ControlPatch {
  property_name?: string;
  direction?: PropertyDirection;
  filters?: Partial<TransformFilters>;
  max_nodes?: number;
}

interface ControlRequest extends ControlState {
  revision: number;
}

interface ControlResponse {
  revision: number;
  ok: boolean;
  error: string | null;
}

interface Product {
  id: string;
  smiles: string;
  group: string;
  median: number;
  count: number;
  evidence: Evidence;
  radius: number;
  std: number | null;
  min: number | null;
  q1: number | null;
  q3: number | null;
  max: number | null;
  pValue: number | null;
  missing: string[];
  depictionId: string;
}

interface RuleGroup {
  id: string;
  environmentId: number;
  fromGroup: string;
  from: string;
  to: string;
  fromDepictionId: string;
  toDepictionId: string;
  smarts: string | null;
  pseudosmiles: string | null;
  radius: number;
  median: number;
  min: number | null;
  max: number | null;
  count: number;
  evidence: Evidence;
}

interface FromGroup {
  id: string;
  from: string;
  fromDepictionId: string;
  ruleIds: string[];
  productCount: number;
  ruleCount: number;
  gainCount: number;
  lossCount: number;
  neutralCount: number;
  totalSupport: number;
  aggregateMedian: number;
  effectMin: number;
  effectMax: number;
}

interface GraphData {
  properties: string[];
  controlOptions: {
    radii: number[];
    maxSupport: number;
    maxEffect: number;
    evidenceThresholds: { moderate: number; strong: number };
  };
  querySmiles: string | null;
  queryDepictionId: string | null;
  products: Product[];
  fromGroups: FromGroup[];
  groups: RuleGroup[];
  shown: number;
  matching: number;
  truncated: boolean;
  warnings: string[];
  hasMmpdb: boolean;
}

interface WidgetState {
  data: GraphData;
  depictions: Record<string, string>;
  selected_id: string | null;
  property_name: string;
  direction: PropertyDirection;
  filters: TransformFilters;
  max_nodes: number;
  height: number;
  _control_request: Partial<ControlRequest>;
  _control_response: ControlResponse;
}

type ModelCallback = () => void;

interface AnywidgetModel {
  get<K extends keyof WidgetState>(name: K): WidgetState[K];
  set<K extends keyof WidgetState>(name: K, value: WidgetState[K]): void;
  save_changes(): void;
  on(event: `change:${keyof WidgetState}`, callback: ModelCallback): void;
  off(event: `change:${keyof WidgetState}`, callback: ModelCallback): void;
}

interface Controls {
  rail: HTMLDivElement;
  property: HTMLSelectElement;
  optimum: HTMLSelectElement;
  direction: HTMLSelectElement;
  effect: HTMLInputElement;
  effectOutput: HTMLOutputElement;
  support: HTMLInputElement;
  supportOutput: HTMLOutputElement;
  radius: HTMLDivElement;
  quality: HTMLDivElement;
  search: HTMLInputElement;
  signal: AbortSignal;
  submitControls: (patch: ControlPatch) => void;
}

interface ControlSync {
  submit: (patch: ControlPatch) => void;
  requestChanged: ModelCallback;
  responseChanged: ModelCallback;
  acceptedChanged: ModelCallback;
  current: () => ControlState;
}

interface ShellRefs {
  el: HTMLElement;
  frame: HTMLDivElement;
  toggle: HTMLButtonElement;
  counter: HTMLDivElement;
  toolbar: HTMLDivElement;
  status: HTMLParagraphElement;
  stage: HTMLDivElement;
  canvas: SVGElement;
  tooltip: HTMLElement;
  notices: HTMLDivElement;
  controls: Controls;
  signal: AbortSignal;
}

interface ViewRefs extends ShellRefs {
  controlSync: ControlSync;
  setViewTimeout: (callback: () => void, delay: number) => TimerId;
  requestFrame: (callback: () => void) => FrameId;
  layoutSize?: number;
}

interface Position {
  radius: number;
  angle: number;
  x?: number;
  y?: number;
}

type AbsolutePosition = Required<Position>;
type MetricEntry = [string, string];
type TooltipFill = (tooltip: HTMLElement) => void;

const NS = "http://www.w3.org/2000/svg";
let tooltipSequence = 0;
let toolbarSequence = 0;
const expandedMarimoOutputs = new WeakMap<HTMLElement, {
  views: number;
  maxHeight: string;
  maxHeightPriority: string;
  overflow: string;
  overflowPriority: string;
}>();

function svgElement(name: string, attributes: Record<string, unknown> = {}): SVGElement {
  const node = document.createElementNS(NS, name);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
  return node;
}

function colorFor(value: number, direction: PropertyDirection): string {
  if (value > 0.00001) {
    return direction === "higher" ? "var(--mmp-gain)" : "var(--mmp-loss)";
  }
  if (value < -0.00001) {
    return direction === "higher" ? "var(--mmp-loss)" : "var(--mmp-gain)";
  }
  return "var(--mmp-neutral)";
}

function dashFor(evidence: Evidence): string {
  if (evidence === "Strong") return "";
  if (evidence === "Moderate") return "8 5";
  return "3 7";
}

export function resolveDepiction(depictions: Record<string, string> | null, depictionId: string | null): string | null {
  if (!depictionId || !depictions || typeof depictions !== "object") return null;
  const source = depictions[depictionId];
  return typeof source === "string" && source ? source : null;
}

function appendMolecule(container: Element, source: string | null): boolean {
  container.replaceChildren();
  if (!source) return false;
  const parsed = new DOMParser().parseFromString(source, "image/svg+xml");
  const root = parsed.documentElement;
  if (root.localName === "svg" && !parsed.querySelector("parsererror")) {
    root.removeAttribute("width");
    root.removeAttribute("height");
    root.setAttribute("aria-hidden", "true");
    container.append(root);
    return true;
  }
  return false;
}

function labeledControl(labelText: string, control: HTMLElement, className = ""): HTMLLabelElement {
  const label = document.createElement("label");
  label.className = `mmp-control ${className}`.trim();
  const caption = document.createElement("span");
  caption.textContent = labelText;
  label.append(caption, control);
  return label;
}

function acceptedControls(model: AnywidgetModel): ControlState {
  return {
    property_name: model.get("property_name"),
    direction: model.get("direction") || "higher",
    filters: { ...(model.get("filters") || {}) },
    max_nodes: model.get("max_nodes"),
  };
}

function createControlSync(model: AnywidgetModel, getRefs: () => ViewRefs | undefined): ControlSync {
  let draft = acceptedControls(model);
  let pendingRevision: number | null = null;

  const nextRevision = () => {
    const requestRevision = Number(model.get("_control_request")?.revision) || 0;
    const responseRevision = Number(model.get("_control_response")?.revision) || 0;
    return Math.max(requestRevision, responseRevision, pendingRevision || 0) + 1;
  };
  const showPending = () => {
    const refs = getRefs();
    if (!refs) return;
    refs.toolbar.setAttribute("aria-busy", "true");
    refs.status.textContent = "Updating graph…";
  };
  const submit = (patch: ControlPatch) => {
    draft = {
      property_name: patch.property_name ?? draft.property_name,
      direction: patch.direction ?? draft.direction,
      filters: { ...draft.filters, ...(patch.filters || {}) },
      max_nodes: patch.max_nodes ?? draft.max_nodes,
    };
    pendingRevision = nextRevision();
    model.set("_control_request", { revision: pendingRevision, ...draft });
    model.save_changes();
    const refs = getRefs();
    if (refs) updateControls(model, refs.controls, draft);
    showPending();
  };
  const requestChanged = () => {
    const request = model.get("_control_request") || {};
    const revision = request.revision;
    if (typeof revision !== "number" || !Number.isInteger(revision) || revision < (pendingRevision || 0)) return;
    const accepted = acceptedControls(model);
    pendingRevision = revision;
    draft = {
      property_name: request.property_name ?? accepted.property_name,
      direction: (request.direction as PropertyDirection) ?? accepted.direction,
      filters: { ...accepted.filters, ...(request.filters || {}) },
      max_nodes: request.max_nodes ?? accepted.max_nodes,
    };
    showPending();
    const refs = getRefs();
    if (refs) updateControls(model, refs.controls, draft);
  };
  const responseChanged = () => {
    const response = model.get("_control_response") || {};
    if (pendingRevision == null || response.revision !== pendingRevision) return;
    const refs = getRefs();
    pendingRevision = null;
    draft = acceptedControls(model);
    if (!refs) return;
    refs.toolbar.setAttribute("aria-busy", "false");
    if (response.ok) {
      refs.status.textContent = "Graph updated.";
    } else {
      refs.status.textContent = `Update failed: ${response.error || "invalid controls"}`;
      updateControls(model, refs.controls, draft);
    }
  };
  const acceptedChanged = () => {
    if (pendingRevision != null) return;
    draft = acceptedControls(model);
    const refs = getRefs();
    if (refs) updateControls(model, refs.controls, draft);
  };
  return { submit, requestChanged, responseChanged, acceptedChanged, current: () => draft };
}

function buildControls(
  model: AnywidgetModel,
  signal: AbortSignal,
  submitControls: (patch: ControlPatch) => void,
  timers: Set<TimerId>,
): Controls {
  const rail = document.createElement("div");
  rail.className = "mmp-controls";
  rail.setAttribute("role", "group");
  rail.setAttribute("aria-label", "Graph filters");

  const property = document.createElement("select");
  property.addEventListener("change", () => {
    submitControls({
      property_name: property.value,
      filters: { radii: null, min_abs_effect: 0, min_support: 1 },
    });
  }, { signal });

  const optimum = document.createElement("select");
  for (const [value, label] of [["higher", "Higher"], ["lower", "Lower"]] as const) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    optimum.append(option);
  }
  optimum.addEventListener("change", () => submitControls({ direction: optimum.value as PropertyDirection }), { signal });

  const direction = document.createElement("select");
  for (const [value, label] of [["all", "All"], ["gain", "Gains"], ["loss", "Losses"], ["neutral", "Neutral"]] as const) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    direction.append(option);
  }
  direction.addEventListener("change", () => submitControls({ filters: { direction: direction.value as Direction } }), { signal });

  const effect = document.createElement("input");
  effect.type = "range";
  effect.min = "0";
  effect.step = "0.05";
  const effectOutput = document.createElement("output");
  const effectWrap = document.createElement("div");
  effectWrap.className = "mmp-range-wrap";
  effectWrap.append(effect, effectOutput);
  effect.addEventListener("input", () => {
    effectOutput.value = Number(effect.value).toFixed(2);
  }, { signal });
  effect.addEventListener("change", () => submitControls({ filters: { min_abs_effect: Number(effect.value) } }), { signal });

  const support = document.createElement("input");
  support.type = "range";
  support.min = "1";
  support.step = "1";
  const supportOutput = document.createElement("output");
  const supportWrap = document.createElement("div");
  supportWrap.className = "mmp-range-wrap";
  supportWrap.append(support, supportOutput);
  support.addEventListener("input", () => { supportOutput.value = support.value; }, { signal });
  support.addEventListener("change", () => submitControls({
    filters: { min_support: Number(support.value), quality: null },
  }), { signal });

  const radius = document.createElement("div");
  radius.className = "mmp-chipset";
  radius.setAttribute("role", "group");
  radius.setAttribute("aria-label", "Environment radius");

  const quality = document.createElement("div");
  quality.className = "mmp-chipset";
  quality.setAttribute("role", "group");
  quality.setAttribute("aria-label", "Evidence tier");
  for (const name of ["Strong", "Moderate", "Exploratory"]) {
    const label = document.createElement("label");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = name;
    checkbox.setAttribute("aria-label", name);
    checkbox.addEventListener("change", () => {
      const values = [...quality.querySelectorAll<HTMLInputElement>("input:checked")].map((input) => input.value as Evidence);
      submitControls({ filters: { quality: values, min_support: 1 } });
    }, { signal });
    const text = document.createElement("span");
    text.textContent = name[0] ?? "";
    label.title = name;
    label.append(checkbox, text);
    quality.append(label);
  }

  const search = document.createElement("input");
  search.type = "search";
  search.placeholder = "ID, SMILES, rule, SMARTS";
  let searchTimer: TimerId | null = null;
  search.addEventListener("input", () => {
    if (searchTimer != null) {
      clearTimeout(searchTimer);
      timers.delete(searchTimer);
    }
    const timer = setTimeout(() => {
      timers.delete(timer);
      searchTimer = null;
      submitControls({ filters: { text: search.value } });
    }, 180);
    searchTimer = timer;
    timers.add(timer);
  }, { signal });
  signal.addEventListener("abort", () => {
    if (searchTimer != null) clearTimeout(searchTimer);
  }, { once: true });

  rail.append(
    labeledControl("Property", property),
    labeledControl("Optimum", optimum),
    labeledControl("Direction", direction),
    labeledControl("Minimum |Δ|", effectWrap, "mmp-wide-control"),
    labeledControl("Support", supportWrap, "mmp-wide-control"),
    labeledControl("Radius", radius),
    labeledControl("Evidence", quality),
    labeledControl("Find", search, "mmp-search-control"),
  );
  return { rail, property, optimum, direction, effect, effectOutput, support, supportOutput, radius, quality, search, signal, submitControls };
}

function updateControls(model: AnywidgetModel, controls: Controls, state = acceptedControls(model)): void {
  const data = model.get("data");
  const filters = state.filters;
  const options = data.controlOptions;
  const currentProperty = state.property_name;
  const properties = data.properties || [];
  if (controls.property.options.length !== properties.length || [...controls.property.options].some((option, index) => option.value !== properties[index])) {
    controls.property.replaceChildren();
    for (const name of properties) {
      const option = document.createElement("option");
      option.value = name;
      option.textContent = name;
      controls.property.append(option);
    }
  }
  controls.property.value = currentProperty;
  controls.optimum.value = state.direction || "higher";
  controls.direction.value = filters.direction || "all";
  controls.effect.max = String(Math.max(options.maxEffect || 1, 0.05));
  controls.effect.value = String(filters.min_abs_effect || 0);
  controls.effectOutput.value = Number(controls.effect.value).toFixed(2);
  controls.support.max = String(Math.max(options.maxSupport || 1, 1));
  controls.support.value = String(filters.min_support || 1);
  controls.supportOutput.value = controls.support.value;
  controls.search.value = filters.text || "";

  const selectedRadii = new Set(filters.radii == null ? (options.radii || []) : filters.radii);
  controls.radius.replaceChildren();
  for (const value of options.radii || []) {
    const label = document.createElement("label");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = String(value);
    checkbox.setAttribute("aria-label", `Radius ${value}`);
    checkbox.checked = selectedRadii.has(value);
    checkbox.addEventListener("change", () => {
      const values = [...controls.radius.querySelectorAll<HTMLInputElement>("input:checked")].map((input) => Number(input.value));
      controls.submitControls({ filters: { radii: values } });
    }, { signal: controls.signal });
    const text = document.createElement("span");
    text.textContent = String(value);
    label.append(checkbox, text);
    controls.radius.append(label);
  }
  const selectedQuality = new Set(filters.quality == null ? ["Strong", "Moderate", "Exploratory"] : filters.quality);
  const evidenceThresholds = options.evidenceThresholds;
  const evidenceRanges: Record<Evidence, string> = {
    Strong: `${evidenceThresholds.strong}+ pairs`,
    Moderate: `${evidenceThresholds.moderate}–${evidenceThresholds.strong - 1} pairs`,
    Exploratory: `1–${evidenceThresholds.moderate - 1} pairs`,
  };
  for (const checkbox of controls.quality.querySelectorAll<HTMLInputElement>("input")) {
    const evidence = checkbox.value as Evidence;
    const description = `${evidence}: ${evidenceRanges[evidence]}`;
    checkbox.checked = selectedQuality.has(evidence);
    checkbox.setAttribute("aria-label", description);
    if (checkbox.parentElement) checkbox.parentElement.title = description;
  }
}

function buildShell(
  model: AnywidgetModel,
  el: HTMLElement,
  signal: AbortSignal,
  submitControls: (patch: ControlPatch) => void,
  timers: Set<TimerId>,
): ShellRefs {
  el.classList.add("mmp-instrument");
  const header = document.createElement("header");
  header.className = "mmp-header";
  const counter = document.createElement("div");
  counter.className = "mmp-counter";
  header.append(counter);
  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "mmp-sidebar-toggle";
  toggle.setAttribute("aria-expanded", "false");
  toggle.setAttribute("aria-label", "Expand controls");
  header.prepend(toggle);

  const controls = buildControls(model, signal, submitControls, timers);
  const legend = document.createElement("div");
  legend.className = "mmp-legend";
  legend.innerHTML = `<span><i class="source"></i>source fragment</span><span><i class="gain"></i>gain</span><span><i class="loss"></i>loss</span><span><b class="strong"></b>Strong</span><span><b class="moderate"></b>Moderate</span><span><b class="exploratory"></b>Exploratory</span>`;

  const toolbar = document.createElement("div");
  toolbar.className = "mmp-toolbar";
  toolbar.id = `mmp-toolbar-${toolbarSequence++}`;
  toggle.setAttribute("aria-controls", toolbar.id);
  toolbar.setAttribute("aria-busy", "false");
  const status = document.createElement("p");
  status.className = "mmp-update-status";
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");
  toolbar.append(header, controls.rail, legend, status);

  const stage = document.createElement("div");
  stage.className = "mmp-stage";
  stage.setAttribute("role", "region");
  stage.setAttribute("aria-label", "Reaction constellation graph");
  stage.setAttribute("aria-description", "Drag with a mouse or pen, or use scrollbars, to pan the graph");
  const canvas = svgElement("svg", { viewBox: "0 0 1100 1100", role: "group" });
  canvas.setAttribute("aria-label", "Query at center, source-fragment groups and transformation rules in middle rings, and products in outer rings");
  stage.append(canvas);

  const tooltip = document.createElement("aside");
  tooltip.className = "mmp-tooltip";
  tooltip.id = `mmp-tooltip-${tooltipSequence++}`;
  tooltip.setAttribute("role", "tooltip");
  tooltip.hidden = true;

  const notices = document.createElement("div");
  notices.className = "mmp-notices";
  const frame = document.createElement("div");
  frame.className = "mmp-frame is-collapsed";
  frame.append(toolbar, stage, notices);
  el.replaceChildren(frame, tooltip);
  return { el, frame, toggle, counter, toolbar, status, stage, canvas, tooltip, notices, controls, signal };
}

function metricEntries(product: Product): MetricEntry[] {
  const entries: MetricEntry[] = [
    ["Median Δ", product.median.toFixed(3)],
    ["Minimum Δ", product.min == null ? "Not reported" : product.min.toFixed(3)],
    ["Maximum Δ", product.max == null ? "Not reported" : product.max.toFixed(3)],
    ["Evidence", `${product.evidence} · ${product.count} pair${product.count === 1 ? "" : "s"}`],
    ["Radius", String(product.radius)],
    ["Std. dev.", product.std == null ? "Not reported" : product.std.toFixed(3)],
    ["Quartiles", product.q1 == null || product.q3 == null ? "Not reported" : `${product.q1.toFixed(3)} → ${product.q3.toFixed(3)}`],
    ["p-value", product.pValue == null ? "Not reported" : product.pValue.toPrecision(3)],
  ];
  return entries;
}

function accessibleProductLabel(product: Product): string {
  const metrics = metricEntries(product).map(([label, value]) => `${label}: ${value}`).join("; ");
  return `Product ${product.id}; SMILES: ${product.smiles}; ${metrics}`;
}

function appendMetrics(container: HTMLElement, entries: MetricEntry[]): void {
  const metrics = document.createElement("dl");
  for (const [label, value] of entries) {
    const dt = document.createElement("dt");
    dt.textContent = label;
    const dd = document.createElement("dd");
    dd.textContent = value;
    metrics.append(dt, dd);
  }
  container.append(metrics);
}

function fillProductTooltip(product: Product, depiction: string | null, tooltip: HTMLElement): void {
  tooltip.replaceChildren();
  const molecule = document.createElement("div");
  molecule.className = "mmp-tooltip-molecule";
  if (!appendMolecule(molecule, depiction)) molecule.textContent = "Depiction unavailable";

  const copy = document.createElement("div");
  copy.className = "mmp-tooltip-copy";
  const heading = document.createElement("h3");
  heading.textContent = `Product ${product.id}`;
  const smiles = document.createElement("p");
  smiles.className = "mmp-tooltip-smiles";
  smiles.textContent = product.smiles;
  copy.append(heading, smiles);
  appendMetrics(copy, metricEntries(product));
  tooltip.append(molecule, copy);
}

function fillQueryTooltip(data: GraphData, depiction: string | null, tooltip: HTMLElement): void {
  tooltip.replaceChildren();
  const heading = document.createElement("h3");
  heading.textContent = "Query compound";
  const molecule = document.createElement("div");
  molecule.className = "mmp-tooltip-query-molecule";
  if (depiction) appendMolecule(molecule, depiction);
  else molecule.textContent = data.querySmiles ? "Depiction unavailable" : "Query structure not attached";
  const smiles = document.createElement("p");
  smiles.className = "mmp-tooltip-smiles";
  smiles.textContent = data.querySmiles || "No query SMILES attached";
  tooltip.append(heading, molecule, smiles);
}

function fillFromTooltip(group: FromGroup, depiction: string | null, tooltip: HTMLElement): void {
  tooltip.replaceChildren();
  const heading = document.createElement("h3");
  heading.textContent = "Source fragment aggregate";
  const molecule = document.createElement("div");
  molecule.className = "mmp-tooltip-from-molecule";
  if (!appendMolecule(molecule, depiction)) molecule.textContent = "Depiction unavailable";
  const smiles = document.createElement("p");
  smiles.className = "mmp-tooltip-smiles";
  smiles.textContent = group.from;
  tooltip.append(heading, molecule, smiles);
  const direction = ([
    ["gain", group.gainCount],
    ["loss", group.lossCount],
    ["neutral", group.neutralCount],
  ] as const).map(([label, count]) => `${Math.round(count / group.ruleCount * 100)}% ${label}`).join(" · ");
  appendMetrics(tooltip, [
    ["Median rule Δ", group.aggregateMedian.toFixed(3)],
    ["Rule Δ range", `${group.effectMin.toFixed(3)} → ${group.effectMax.toFixed(3)}`],
    ["Rule direction", direction],
    ["Rule environments", String(group.ruleCount)],
    ["Visible products", String(group.productCount)],
    ["Summed pair support", String(group.totalSupport)],
  ]);
}

function fillRuleTooltip(
  group: RuleGroup,
  hasMmpdb: boolean,
  fromDepiction: string | null,
  toDepiction: string | null,
  tooltip: HTMLElement,
): void {
  tooltip.replaceChildren();
  const heading = document.createElement("h3");
  heading.textContent = `Rule environment ${group.environmentId}`;
  const reaction = document.createElement("div");
  reaction.className = "mmp-tooltip-reaction";
  for (const [side, svg, smiles] of [["From", fromDepiction, group.from], ["To", toDepiction, group.to]] as const) {
    const fragment = document.createElement("div");
    fragment.className = "mmp-tooltip-fragment";
    const caption = document.createElement("span");
    caption.textContent = side;
    const molecule = document.createElement("div");
    if (!appendMolecule(molecule, svg)) molecule.textContent = "Depiction unavailable";
    const code = document.createElement("code");
    code.textContent = smiles;
    fragment.append(caption, molecule, code);
    reaction.append(fragment);
    if (side === "From") {
      const arrow = document.createElement("span");
      arrow.className = "mmp-tooltip-arrow";
      arrow.textContent = "→";
      reaction.append(arrow);
    }
  }
  tooltip.append(heading, reaction);
  if (hasMmpdb) {
    const details = document.createElement("div");
    details.className = "mmp-tooltip-rule-details";
    appendMetrics(details, [
      ["Median Δ", group.median.toFixed(3)],
      ["Minimum Δ", group.min == null ? "Not reported" : group.min.toFixed(3)],
      ["Maximum Δ", group.max == null ? "Not reported" : group.max.toFixed(3)],
      ["Evidence", `${group.evidence} · ${group.count} pair${group.count === 1 ? "" : "s"}`],
      ["Radius", String(group.radius)],
      ["SMARTS", group.smarts || "Not reported"],
      ["Pseudo-SMILES", group.pseudosmiles || "Not reported"],
    ]);
    tooltip.append(details);
  }
}

function positionTooltip(refs: ViewRefs, node: Element, event?: PointerEvent): void {
  const hostRect = refs.el.getBoundingClientRect();
  const nodeRect = node.getBoundingClientRect();
  const viewport = window.visualViewport;
  const viewportLeft = viewport?.offsetLeft ?? 0;
  const viewportTop = viewport?.offsetTop ?? 0;
  const viewportRight = viewportLeft + (viewport?.width ?? window.innerWidth);
  const viewportBottom = viewportTop + (viewport?.height ?? window.innerHeight);
  const gap = 14;
  const margin = 8;
  const availableWidth = viewportRight - viewportLeft - margin * 2;
  if (refs.tooltip.classList.contains("is-compact") !== availableWidth < 520) {
    refs.tooltip.classList.toggle("is-compact", availableWidth < 520);
  }
  const tooltipRect = refs.tooltip.getBoundingClientRect();
  const anchorX = event?.clientX ?? nodeRect.right;
  const anchorY = event?.clientY ?? (nodeRect.top + nodeRect.height / 2);
  const localX = anchorX - hostRect.left;
  const localY = anchorY - hostRect.top;
  const minLeft = viewportLeft - hostRect.left + margin;
  const maxLeft = viewportRight - hostRect.left - margin - tooltipRect.width;
  const minTop = viewportTop - hostRect.top + margin;
  const maxTop = viewportBottom - hostRect.top - margin - tooltipRect.height;

  let left = localX + gap;
  if (left > maxLeft) left = localX - tooltipRect.width - gap;
  let top = localY + gap;
  if (top > maxTop) top = localY - tooltipRect.height - gap;
  refs.tooltip.style.left = `${Math.max(minLeft, Math.min(left, Math.max(minLeft, maxLeft)))}px`;
  refs.tooltip.style.top = `${Math.max(minTop, Math.min(top, Math.max(minTop, maxTop)))}px`;
}

function showTooltip(
  refs: ViewRefs,
  node: Element,
  key: string,
  kind: string,
  fill: TooltipFill,
  event?: PointerEvent,
): void {
  refs.tooltip.className = `mmp-tooltip mmp-tooltip-${kind}`;
  fill(refs.tooltip);
  refs.tooltip.dataset.tooltipKey = key;
  refs.tooltip.hidden = false;
  node.setAttribute("aria-describedby", refs.tooltip.id);
  positionTooltip(refs, node, event);
}

function attachTooltip(
  node: Element,
  refs: ViewRefs,
  { key, kind, fill }: { key: string; kind: string; fill: TooltipFill },
): void {
  const options = { signal: refs.signal };
  node.addEventListener("pointerenter", (event) => showTooltip(refs, node, key, kind, fill, event as PointerEvent), options);
  node.addEventListener("pointermove", (event) => {
    if (refs.tooltip.dataset.tooltipKey === key) positionTooltip(refs, node, event as PointerEvent);
  }, options);
  node.addEventListener("pointerleave", () => hideTooltip(refs, node), options);
  node.addEventListener("focus", () => showTooltip(refs, node, key, kind, fill), options);
  node.addEventListener("blur", () => hideTooltip(refs, node), options);
}

function hideTooltip(refs: ViewRefs, node: Element | null = null): void {
  if (node?.matches(":focus-visible")) return;
  for (const describedNode of refs.canvas.querySelectorAll(`[aria-describedby="${refs.tooltip.id}"]`)) {
    describedNode.removeAttribute("aria-describedby");
  }
  refs.tooltip.hidden = true;
  delete refs.tooltip.dataset.tooltipKey;
}

function updateSelection(model: AnywidgetModel, refs: ViewRefs): void {
  const selected = model.get("selected_id");
  for (const node of refs.canvas.querySelectorAll<SVGElement>(".mmp-product-node")) {
    node.classList.toggle("is-selected", String(node.dataset.productId) === String(selected));
  }
}

function updateHeight(model: AnywidgetModel, refs: ViewRefs): void {
  const requested = Number(model.get("height"));
  const height = Number.isFinite(requested) ? Math.max(480, Math.round(requested)) : 1220;
  refs.stage.style.setProperty("--mmp-graph-height", `${height}px`);
  refs.requestFrame(() => updatePanAvailability(refs));
}

function releaseMarimoOutputHeightLimit(el: HTMLElement): () => void {
  const root = el.getRootNode();
  const rootHost = "host" in root ? (root as ShadowRoot).host : null;
  const host: Element = rootHost && typeof rootHost.closest === "function" ? rootHost : el;
  const outputArea = host.closest<HTMLElement>(".marimo-cell.interactive .output-area");
  if (!outputArea) return () => {};

  let state = expandedMarimoOutputs.get(outputArea);
  if (state) {
    state.views += 1;
  } else {
    state = {
      views: 1,
      maxHeight: outputArea.style.getPropertyValue("max-height"),
      maxHeightPriority: outputArea.style.getPropertyPriority("max-height"),
      overflow: outputArea.style.getPropertyValue("overflow"),
      overflowPriority: outputArea.style.getPropertyPriority("overflow"),
    };
    expandedMarimoOutputs.set(outputArea, state);
    outputArea.style.setProperty("max-height", "none");
    outputArea.style.setProperty("overflow", "visible");
  }

  let active = true;
  return () => {
    if (!active) return;
    active = false;
    state.views -= 1;
    if (state.views > 0) return;
    expandedMarimoOutputs.delete(outputArea);
    if (outputArea.style.getPropertyValue("max-height") === "none") {
      if (state.maxHeight) outputArea.style.setProperty("max-height", state.maxHeight, state.maxHeightPriority);
      else outputArea.style.removeProperty("max-height");
    }
    if (outputArea.style.getPropertyValue("overflow") === "visible") {
      if (state.overflow) outputArea.style.setProperty("overflow", state.overflow, state.overflowPriority);
      else outputArea.style.removeProperty("overflow");
    }
  };
}

function updatePanAvailability(refs: ViewRefs): void {
  const canPan = refs.stage.scrollWidth > refs.stage.clientWidth || refs.stage.scrollHeight > refs.stage.clientHeight;
  refs.stage.classList.toggle("is-pannable", canPan);
}

function attachDragPan(refs: ViewRefs, signal: AbortSignal): void {
  const threshold = 5;
  let drag: {
    pointerId: number;
    clientX: number;
    clientY: number;
    scrollLeft: number;
    scrollTop: number;
    moved: boolean;
  } | null = null;
  let suppressClick = false;

  refs.stage.addEventListener("pointerdown", (event) => {
    if (!event.isPrimary || event.button !== 0 || event.pointerType === "touch") return;
    drag = {
      pointerId: event.pointerId,
      clientX: event.clientX,
      clientY: event.clientY,
      scrollLeft: refs.stage.scrollLeft,
      scrollTop: refs.stage.scrollTop,
      moved: false,
    };
  }, { signal });

  refs.stage.addEventListener("pointermove", (event) => {
    if (!drag || event.pointerId !== drag.pointerId) return;
    const deltaX = event.clientX - drag.clientX;
    const deltaY = event.clientY - drag.clientY;
    if (!drag.moved && Math.hypot(deltaX, deltaY) < threshold) return;
    if (!drag.moved) {
      drag.moved = true;
      refs.stage.setPointerCapture(event.pointerId);
      refs.stage.classList.add("is-panning");
      hideTooltip(refs);
    }
    event.preventDefault();
    refs.stage.scrollLeft = drag.scrollLeft - deltaX;
    refs.stage.scrollTop = drag.scrollTop - deltaY;
  }, { signal });

  const finish = (event: PointerEvent) => {
    if (!drag || event.pointerId !== drag.pointerId) return;
    const moved = drag.moved;
    const pointerId = drag.pointerId;
    drag = null;
    refs.stage.classList.remove("is-panning");
    if (refs.stage.hasPointerCapture(pointerId)) refs.stage.releasePointerCapture(pointerId);
    if (moved) {
      suppressClick = true;
      refs.setViewTimeout(() => { suppressClick = false; }, 0);
    }
  };
  refs.stage.addEventListener("pointerup", finish, { signal });
  refs.stage.addEventListener("pointercancel", finish, { signal });
  refs.stage.addEventListener("lostpointercapture", finish, { signal });
  refs.stage.addEventListener("click", (event) => {
    if (!suppressClick) return;
    event.preventDefault();
    event.stopPropagation();
    suppressClick = false;
  }, { capture: true, signal });
}

function radialRings<T extends { id: string }>(items: T[], startRadius: number, footprint: number, gap = 12): {
  positions: Map<string, Position>;
  outerRadius: number;
} {
  const positions = new Map<string, Position>();
  let cursor = 0;
  let radius = startRadius;
  while (cursor < items.length) {
    const spacing = footprint + gap;
    const angleStep = 2 * Math.asin(Math.min(1, spacing / (2 * radius)));
    const capacity = Math.max(1, Math.floor((Math.PI * 2) / angleStep));
    const count = Math.min(capacity, items.length - cursor);
    for (let index = 0; index < count; index += 1) {
      const angle = -Math.PI / 2 + (Math.PI * 2 * index) / count;
      const item = items[cursor + index];
      if (item) positions.set(item.id, { radius, angle });
    }
    cursor += count;
    if (cursor < items.length) radius += spacing;
  }
  return { positions, outerRadius: items.length ? radius + footprint / 2 : startRadius };
}

function absolutePosition(position: Position, center: number): AbsolutePosition {
  return {
    ...position,
    x: center + Math.cos(position.angle) * position.radius,
    y: center + Math.sin(position.angle) * position.radius,
  };
}

function requiredPosition(positions: Map<string, AbsolutePosition>, id: string): AbsolutePosition {
  const position = positions.get(id);
  if (!position) throw new Error(`Missing layout position for ${id}`);
  return position;
}

function appendDirectionArcs(node: SVGElement, group: FromGroup, position: AbsolutePosition): void {
  const segments = [
    ["gain", group.gainCount],
    ["loss", group.lossCount],
    ["neutral", group.neutralCount],
  ] as const;
  let offset = 0;
  for (const [direction, count] of segments) {
    if (!count) continue;
    const proportion = count / group.ruleCount;
    const arc = svgElement("circle", {
      cx: position.x,
      cy: position.y,
      r: 36,
      class: `mmp-from-arc is-${direction}`,
      pathLength: 1,
      "stroke-dasharray": `${proportion} ${1 - proportion}`,
      "stroke-dashoffset": -offset,
      transform: `rotate(-90 ${position.x} ${position.y})`,
    });
    node.append(arc);
    offset += proportion;
  }
}

function updateCanvasSize(refs: ViewRefs, size: number): void {
  const previousSize = refs.layoutSize || size;
  const centerRatioX = refs.layoutSize ? (refs.stage.scrollLeft + refs.stage.clientWidth / 2) / previousSize : 0.5;
  const centerRatioY = refs.layoutSize ? (refs.stage.scrollTop + refs.stage.clientHeight / 2) / previousSize : 0.5;
  refs.layoutSize = size;
  refs.canvas.setAttribute("viewBox", `0 0 ${size} ${size}`);
  refs.canvas.style.setProperty("--mmp-canvas-size", `${size}px`);
  refs.requestFrame(() => {
    refs.stage.scrollLeft = Math.max(0, centerRatioX * size - refs.stage.clientWidth / 2);
    refs.stage.scrollTop = Math.max(0, centerRatioY * size - refs.stage.clientHeight / 2);
    updatePanAvailability(refs);
  });
}

function renderGraph(model: AnywidgetModel, refs: ViewRefs): void {
  const data = model.get("data");
  const depictions = model.get("depictions");
  const direction: PropertyDirection = model.get("direction") || "higher";
  const products = data.products;
  const groups = data.groups;
  const fromGroups = data.fromGroups;
  const selected = model.get("selected_id");
  const depiction = (depictionId: string | null) => resolveDepiction(depictions, depictionId);
  const requiredDepictionIds = [
    data.queryDepictionId,
    ...products.map((product) => product.depictionId),
    ...fromGroups.map((group) => group.fromDepictionId),
    ...groups.flatMap((group) => [group.fromDepictionId, group.toDepictionId]),
  ].filter(Boolean);
  const hasMissingDepictions =
    (Boolean(data.querySmiles) && !data.queryDepictionId)
    || requiredDepictionIds.some((depictionId) => !depiction(depictionId));
  updateControls(model, refs.controls, refs.controlSync.current());
  refs.counter.textContent = `${data.shown || 0} / ${data.matching || 0} PRODUCTS · ${model.get("property_name") || "PROPERTY"}`;
  hideTooltip(refs);
  refs.canvas.replaceChildren();

  const fromLayout = radialRings(fromGroups, 178, 80, 14);
  const fromOrder = new Map(fromGroups.map((group, index) => [group.id, index]));
  const orderedRules = [...groups].sort((left, right) => {
    const parentDifference = (fromOrder.get(left.fromGroup) || 0) - (fromOrder.get(right.fromGroup) || 0);
    return parentDifference || left.environmentId - right.environmentId || left.to.localeCompare(right.to);
  });
  const ruleStart = fromLayout.outerRadius + 67;
  const ruleLayout = radialRings(orderedRules, ruleStart, 74, 14);
  const ruleOrder = new Map(orderedRules.map((group, index) => [group.id, index]));
  const orderedProducts = [...products].sort((left, right) => {
    const ruleDifference = (ruleOrder.get(left.group) || 0) - (ruleOrder.get(right.group) || 0);
    return ruleDifference || String(left.id).localeCompare(String(right.id), undefined, { numeric: true });
  });
  const productStart = ruleLayout.outerRadius + 75;
  const productLayout = radialRings(orderedProducts, productStart, 80, 14);
  const layoutRadius = products.length ? productLayout.outerRadius : groups.length ? ruleLayout.outerRadius : fromLayout.outerRadius;
  const canvasSize = Math.max(1100, Math.ceil((layoutRadius + 48) * 2));
  const center = canvasSize / 2;
  updateCanvasSize(refs, canvasSize);
  const fromPositions = new Map([...fromLayout.positions].map(([id, position]) => [id, absolutePosition(position, center)]));
  const positions = new Map([...ruleLayout.positions].map(([id, position]) => [id, absolutePosition(position, center)]));
  const productPositions = new Map([...productLayout.positions].map(([id, position]) => [id, absolutePosition(position, center)]));

  const queryNode = svgElement("g", {
    class: "mmp-query-node",
    tabindex: "0",
    role: "img",
    "aria-label": data.querySmiles ? `Query compound; SMILES: ${data.querySmiles}` : "Query structure not attached",
  });
  const queryRing = svgElement("circle", { cx: center, cy: center, r: 112, class: "mmp-query-ring" });
  const queryForeign = svgElement("foreignObject", { x: center - 95, y: center - 70, width: 190, height: 130, class: "mmp-query-structure" });
  const queryBox = document.createElement("div");
  queryBox.setAttribute("xmlns", "http://www.w3.org/1999/xhtml");
  const queryDepiction = depiction(data.queryDepictionId);
  if (queryDepiction) appendMolecule(queryBox, queryDepiction);
  else {
    queryBox.className = "mmp-query-placeholder";
    queryBox.textContent = data.querySmiles ? "DEPICTION\nUNAVAILABLE" : "QUERY\nSTRUCTURE\nNOT ATTACHED";
  }
  queryForeign.append(queryBox);
  const queryLabel = svgElement("text", { x: center, y: center + 93, class: "mmp-query-label", "text-anchor": "middle" });
  queryLabel.textContent = "QUERY";
  queryNode.append(queryRing, queryForeign, queryLabel);
  attachTooltip(queryNode, refs, {
    key: "query",
    kind: "query",
    fill: (tooltip) => fillQueryTooltip(data, depiction(data.queryDepictionId), tooltip),
  });
  queryNode.addEventListener("keydown", (event) => {
    if (event.key === "Escape") hideTooltip(refs);
  }, { signal: refs.signal });
  refs.canvas.append(queryNode);

  fromGroups.forEach((group) => {
    const position = requiredPosition(fromPositions, group.id);
    const line = svgElement("line", { x1: center, y1: center, x2: position.x, y2: position.y, class: "mmp-from-spoke" });
    refs.canvas.insertBefore(line, queryNode);
    const node = svgElement("g", {
      class: "mmp-from-node",
      tabindex: "0",
      role: "img",
      "aria-label": `Source fragment ${group.from}; median rule effect ${group.aggregateMedian.toFixed(3)}; range ${group.effectMin.toFixed(3)} to ${group.effectMax.toFixed(3)}; ${group.gainCount} favorable, ${group.lossCount} unfavorable, and ${group.neutralCount} neutral rule environments; ${group.productCount} visible products; summed support ${group.totalSupport}`,
    });
    const halo = svgElement("circle", { cx: position.x, cy: position.y, r: 40, class: "mmp-from-halo" });
    const core = svgElement("circle", { cx: position.x, cy: position.y, r: 30, class: "mmp-from-core" });
    const label = svgElement("text", { x: position.x, y: position.y - 2, "text-anchor": "middle" });
    const top = svgElement("tspan", { x: position.x, dy: 0 });
    top.textContent = "FROM";
    const bottom = svgElement("tspan", { x: position.x, dy: 14 });
    bottom.textContent = `${group.ruleCount}R · ${group.productCount}P`;
    label.append(top, bottom);
    node.append(halo, core);
    appendDirectionArcs(node, group, position);
    node.append(label);
    attachTooltip(node, refs, {
      key: `from:${group.id}`,
      kind: "from",
      fill: (tooltip) => fillFromTooltip(group, depiction(group.fromDepictionId), tooltip),
    });
    node.addEventListener("keydown", (event) => {
      if (event.key === "Escape") hideTooltip(refs);
    }, { signal: refs.signal });
    refs.canvas.append(node);
  });

  groups.forEach((group) => {
    const position = requiredPosition(positions, group.id);
    const parentPosition = requiredPosition(fromPositions, group.fromGroup);
    const connection = {
      x1: parentPosition.x,
      y1: parentPosition.y,
      x2: position.x,
      y2: position.y,
    };
    const halo = svgElement("line", { ...connection, class: "mmp-rule-link-halo" });
    const line = svgElement("line", {
      ...connection,
      class: "mmp-rule-link",
      stroke: colorFor(group.median, direction),
      "stroke-width": 2.2 + Math.log2(group.count + 1) * 0.45,
    });
    refs.canvas.insertBefore(halo, queryNode);
    refs.canvas.insertBefore(line, queryNode);
    const node = svgElement("g", {
      class: "mmp-rule-node",
      tabindex: "0",
      role: "img",
      "aria-label": `Rule environment ${group.environmentId}; ${group.from} to ${group.to}; radius ${group.radius}; median effect ${group.median.toFixed(3)}; ${group.evidence} evidence with ${group.count} pairs`,
    });
    const circle = svgElement("circle", { cx: position.x, cy: position.y, r: 37 });
    const label = svgElement("text", { x: position.x, y: position.y - 2, "text-anchor": "middle" });
    const top = svgElement("tspan", { x: position.x, dy: 0 });
    top.textContent = `RE ${group.environmentId}`;
    const bottom = svgElement("tspan", { x: position.x, dy: 15 });
    bottom.textContent = `r${group.radius} · n${group.count}`;
    label.append(top, bottom);
    node.append(circle, label);
    attachTooltip(node, refs, {
      key: `rule:${group.id}`,
      kind: "rule",
      fill: (tooltip) => fillRuleTooltip(
        group,
        Boolean(data.hasMmpdb),
        depiction(group.fromDepictionId),
        depiction(group.toDepictionId),
        tooltip,
      ),
    });
    node.addEventListener("keydown", (event) => {
      if (event.key === "Escape") hideTooltip(refs);
    }, { signal: refs.signal });
    refs.canvas.append(node);
  });

  products.forEach((product, index) => {
    const { x, y } = requiredPosition(productPositions, product.id);
    const groupPosition = requiredPosition(positions, product.group);
    const edge = svgElement("line", {
      x1: groupPosition.x, y1: groupPosition.y, x2: x, y2: y,
      class: "mmp-product-edge",
      stroke: colorFor(product.median, direction),
      "stroke-width": 1.4 + Math.log2(product.count + 1),
      "stroke-dasharray": dashFor(product.evidence),
    });
    refs.canvas.insertBefore(edge, queryNode);

    const node = svgElement("g", {
      class: `mmp-product-node${String(selected) === String(product.id) ? " is-selected" : ""}`,
      tabindex: "0", role: "button",
      "aria-label": accessibleProductLabel(product),
      "data-index": index,
      "data-product-id": String(product.id),
      transform: `translate(${x - 31} ${y - 25})`,
    });
    const plate = svgElement("rect", { x: 0, y: 0, width: 62, height: 50, rx: 4 });
    const productDepiction = depiction(product.depictionId);
    const evidence = svgElement("text", { x: 31, y: 47, "text-anchor": "middle" });
    evidence.textContent = `${product.id} · ${product.evidence[0]}${product.count}`;
    node.append(plate);
    if (productDepiction) {
      node.append(svgElement("image", {
        x: 3, y: 3, width: 56, height: 37,
        href: `data:image/svg+xml;charset=utf-8,${encodeURIComponent(productDepiction)}`,
      }));
    } else {
      const placeholder = svgElement("text", { x: 31, y: 25, "text-anchor": "middle", class: "mmp-product-placeholder" });
      placeholder.textContent = "?";
      node.append(placeholder);
    }
    node.append(evidence);
    attachTooltip(node, refs, {
      key: `product:${product.id}`,
      kind: "product",
      fill: (tooltip) => fillProductTooltip(product, depiction(product.depictionId), tooltip),
    });
    node.addEventListener("click", () => selectProduct(model, product.id), { signal: refs.signal });
    node.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        hideTooltip(refs);
      } else if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectProduct(model, product.id);
      } else if (["ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp"].includes(event.key)) {
        event.preventDefault();
        const step = event.key === "ArrowRight" || event.key === "ArrowDown" ? 1 : -1;
        const nodes = [...refs.canvas.querySelectorAll<SVGElement>(".mmp-product-node")];
        nodes[(index + step + nodes.length) % nodes.length]?.focus();
      }
    }, { signal: refs.signal });
    refs.canvas.append(node);
  });
  updateSelection(model, refs);
  refs.notices.replaceChildren();
  if (hasMissingDepictions) addNotice(refs.notices, "Some molecule depictions are unavailable.", "warn");
  if (data.truncated) addNotice(refs.notices, `Showing the highest-ranked ${data.shown} of ${data.matching} matching products.`, "info");
  for (const warning of data.warnings || []) addNotice(refs.notices, warning, "warn");
}

function selectProduct(model: AnywidgetModel, id: string): void {
  model.set("selected_id", String(id));
  model.save_changes();
}

function addNotice(container: HTMLElement, message: string, kind: string): void {
  const notice = document.createElement("p");
  notice.className = `mmp-notice ${kind}`;
  notice.textContent = message;
  container.append(notice);
}

export function render({
  model,
  el,
  signal,
}: {
  model: AnywidgetModel;
  el: HTMLElement;
  signal?: AbortSignal;
}): () => void {
  const viewController = new AbortController();
  const lifecycleSignal = viewController.signal;
  const forwardHostAbort = () => viewController.abort();
  if (signal) {
    if (signal.aborted) viewController.abort();
    else signal.addEventListener("abort", forwardHostAbort, { once: true });
  }
  const restoreMarimoOutput = releaseMarimoOutputHeightLimit(el);
  const timers = new Set<TimerId>();
  const frames = new Set<FrameId>();
  let refs: ViewRefs;
  const controlSync = createControlSync(model, () => refs);
  const shell = buildShell(model, el, lifecycleSignal, controlSync.submit, timers);
  const setViewTimeout = (callback: () => void, delay: number): TimerId => {
    const timer = setTimeout(() => {
      timers.delete(timer);
      if (!lifecycleSignal.aborted) callback();
    }, delay);
    timers.add(timer);
    return timer;
  };
  const requestFrame = (callback: () => void): FrameId => {
    const frame = requestAnimationFrame(() => {
      frames.delete(frame);
      if (!lifecycleSignal.aborted) callback();
    });
    frames.add(frame);
    return frame;
  };
  refs = { ...shell, controlSync, setViewTimeout, requestFrame };
  attachDragPan(refs, lifecycleSignal);
  refs.toggle.addEventListener("click", () => {
    const collapsed = refs.frame.classList.toggle("is-collapsed");
    refs.toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
    refs.toggle.setAttribute(
      "aria-label",
      collapsed ? "Expand controls" : "Collapse controls",
    );
    refs.requestFrame(() => updatePanAvailability(refs));
  }, { signal: lifecycleSignal });
  let cleaned = false;
  let renderQueued = false;
  const scheduleGraphRender = () => {
    if (cleaned || renderQueued) return;
    renderQueued = true;
    queueMicrotask(() => {
      renderQueued = false;
      if (!cleaned) renderGraph(model, refs);
    });
  };
  const onSelectionChanged = () => updateSelection(model, refs);
  const onAcceptedControlsChanged = () => controlSync.acceptedChanged();
  const onDirectionChanged = () => {
    controlSync.acceptedChanged();
    scheduleGraphRender();
  };
  const onHeightChanged = () => updateHeight(model, refs);
  const modelListeners: Array<[`change:${keyof WidgetState}`, ModelCallback]> = [
    ["change:data", scheduleGraphRender],
    ["change:depictions", scheduleGraphRender],
    ["change:selected_id", onSelectionChanged],
    ["change:filters", onAcceptedControlsChanged],
    ["change:property_name", onAcceptedControlsChanged],
    ["change:direction", onDirectionChanged],
    ["change:max_nodes", onAcceptedControlsChanged],
    ["change:_control_request", controlSync.requestChanged],
    ["change:_control_response", controlSync.responseChanged],
    ["change:height", onHeightChanged],
  ];
  for (const [event, callback] of modelListeners) model.on(event, callback);

  const cleanup = () => {
    if (cleaned) return;
    cleaned = true;
    signal?.removeEventListener("abort", forwardHostAbort);
    for (const [event, callback] of modelListeners) model.off(event, callback);
    for (const timer of timers) clearTimeout(timer);
    timers.clear();
    for (const frame of frames) cancelAnimationFrame(frame);
    frames.clear();
    el.replaceChildren();
    el.classList.remove("mmp-instrument");
    restoreMarimoOutput();
  };
  lifecycleSignal.addEventListener("abort", cleanup, { once: true });

  if (lifecycleSignal.aborted) cleanup();
  else {
    updateHeight(model, refs);
    scheduleGraphRender();
  }
  return () => {
    viewController.abort();
    cleanup();
  };
}

export default { render };
