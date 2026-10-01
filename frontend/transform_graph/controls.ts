import { labeledControl } from "./dom";
import type {
  AnywidgetModel,
  ControlPatch,
  ControlState,
  Controls,
  ControlSync,
  Direction,
  Evidence,
  PropertyDirection,
  TimerId,
  ViewRefs,
} from "./types";

function acceptedControls(model: AnywidgetModel): ControlState {
  return {
    property_name: model.get("property_name"),
    direction: model.get("direction") || "higher",
    filters: { ...(model.get("filters") || {}) },
    max_nodes: model.get("max_nodes"),
  };
}

export function createControlSync(model: AnywidgetModel, getRefs: () => ViewRefs | undefined): ControlSync {
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

export function buildControls(
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
  direction.addEventListener("change", () => submitControls({ filters: { effect: direction.value as Direction } }), { signal });

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
  const searchPending = () => searchTimer != null;
  return { rail, property, optimum, direction, effect, effectOutput, support, supportOutput, radius, quality, search, searchPending, signal, submitControls };
}

export function updateControls(model: AnywidgetModel, controls: Controls, state = acceptedControls(model)): void {
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
  controls.direction.value = filters.effect || "all";
  controls.effect.max = String(Math.max(options.maxEffect || 1, 0.05));
  controls.effect.value = String(filters.min_abs_effect || 0);
  controls.effectOutput.value = Number(controls.effect.value).toFixed(2);
  controls.support.max = String(Math.max(options.maxSupport || 1, 1));
  controls.support.value = String(filters.min_support || 1);
  controls.supportOutput.value = controls.support.value;
  // Don't overwrite text the user is still typing or has not yet submitted.
  if (!controls.search.matches(":focus") && !controls.searchPending()) {
    controls.search.value = filters.text || "";
  }

  const radii = options.radii || [];
  const selectedRadii = new Set(filters.radii == null ? radii : filters.radii);
  const radiusInputs = [...controls.radius.querySelectorAll<HTMLInputElement>("input")];
  // Update checkboxes in place so the one being toggled keeps keyboard focus.
  if (radiusInputs.length === radii.length && radiusInputs.every((input, index) => input.value === String(radii[index]))) {
    for (const checkbox of radiusInputs) checkbox.checked = selectedRadii.has(Number(checkbox.value));
  } else {
    rebuildRadii(controls, radii, selectedRadii);
  }
  const selectedQuality =new Set(filters.quality == null ? ["Strong", "Moderate", "Exploratory"] : filters.quality);
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

function rebuildRadii(controls: Controls, radii: number[], selected: Set<number>): void {
  controls.radius.replaceChildren();
  for (const value of radii) {
    const label = document.createElement("label");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = String(value);
    checkbox.setAttribute("aria-label", `Radius ${value}`);
    checkbox.checked = selected.has(value);
    checkbox.addEventListener("change", () => {
      const values = [...controls.radius.querySelectorAll<HTMLInputElement>("input:checked")].map((input) => Number(input.value));
      controls.submitControls({ filters: { radii: values } });
    }, { signal: controls.signal });
    const text = document.createElement("span");
    text.textContent = String(value);
    label.append(checkbox, text);
    controls.radius.append(label);
  }
}
