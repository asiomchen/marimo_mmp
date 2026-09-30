import assert from "node:assert/strict";
import test from "node:test";
import { Window } from "happy-dom";

import { render, resolveDepiction } from "../../src/marimo_mmp/static/transform_graph.js";
import { AnywidgetModelStub, modelState } from "./model_stub.js";

const window = new Window();
globalThis.window = window;
globalThis.document = window.document;
globalThis.DOMParser = window.DOMParser;
globalThis.requestAnimationFrame = window.requestAnimationFrame.bind(window);
globalThis.cancelAnimationFrame = window.cancelAnimationFrame.bind(window);

const settle = async () => {
  await Promise.resolve();
  await Promise.resolve();
};

function mount(model = new AnywidgetModelStub(modelState()), signal = undefined, parent = document.body) {
  const el = document.createElement("div");
  parent.append(el);
  const cleanup = render({ model, el, signal });
  return { model, el, cleanup };
}


test("resolveDepiction returns the referenced SVG without mutating the table", () => {
  const depictions = Object.freeze({ "sha256:known": "<svg></svg>" });

  assert.equal(resolveDepiction(depictions, "sha256:known"), "<svg></svg>");
  assert.deepEqual(depictions, { "sha256:known": "<svg></svg>" });
});


test("resolveDepiction returns null for missing or invalid references", () => {
  assert.equal(resolveDepiction({}, "sha256:missing"), null);
  assert.equal(resolveDepiction({}, null), null);
  assert.equal(resolveDepiction(null, "sha256:missing"), null);
  assert.equal(resolveDepiction({ "sha256:empty": "" }, "sha256:empty"), null);
});


test("resolveDepiction reads replacement model state instead of retaining stale assets", () => {
  const previous = { "sha256:shared": "<svg id=\"old\"></svg>" };
  const replacement = { "sha256:shared": "<svg id=\"new\"></svg>" };

  assert.equal(resolveDepiction(previous, "sha256:shared"), "<svg id=\"old\"></svg>");
  assert.equal(resolveDepiction(replacement, "sha256:shared"), "<svg id=\"new\"></svg>");
});


test("a browser gesture sends one complete atomic request and saves once", async () => {
  const view = mount();
  await settle();
  const direction = view.el.querySelectorAll("select")[2];
  direction.value = "gain";
  direction.dispatchEvent(new window.Event("change"));

  assert.equal(view.model.saved.length, 1);
  assert.deepEqual(view.model.get("_control_request"), {
    revision: 1,
    property_name: "pIC50",
    direction: "higher",
    filters: { direction: "gain", min_abs_effect: 0, min_support: 1, radii: null, quality: null, text: "" },
    max_nodes: 100,
  });
  assert.equal(view.el.querySelector(".mmp-toolbar").getAttribute("aria-busy"), "true");
  view.cleanup();
});


test("the optimum control submits the property direction", async () => {
  const view = mount();
  await settle();
  const optimum = view.el.querySelectorAll("select")[1];
  optimum.value = "lower";
  optimum.dispatchEvent(new window.Event("change"));

  assert.equal(view.model.get("_control_request").revision, 1);
  assert.equal(view.model.get("_control_request").direction, "lower");
  assert.equal(view.model.get("_control_request").filters.direction, "all");
  view.cleanup();
});


test("the tooltip is hosted by the instrument so the scrolling stage cannot clip it", async () => {
  const view = mount();
  await settle();
  const tooltip = view.el.querySelector(".mmp-tooltip");

  assert.ok(tooltip);
  assert.equal(tooltip.closest(".mmp-instrument"), view.el);
  assert.equal(tooltip.closest(".mmp-stage"), null);
  view.cleanup();
});


test("the panes sit in a layout frame that the instrument container query can target", async () => {
  const view = mount();
  await settle();
  const [frame, tooltip] = view.el.children;

  assert.ok(frame.classList.contains("mmp-frame"));
  assert.ok(tooltip.classList.contains("mmp-tooltip"));
  assert.ok(frame.querySelector(".mmp-toolbar"));
  assert.ok(frame.querySelector(".mmp-stage"));
  assert.ok(frame.querySelector(".mmp-notices"));
  view.cleanup();
});


test("the controls sidebar starts collapsed and can expand again", async () => {
  const view = mount();
  await settle();
  const toggle = view.el.querySelector(".mmp-sidebar-toggle");
  const frame = view.el.querySelector(".mmp-frame");
  const toolbar = frame.querySelector(".mmp-toolbar");

  assert.ok(frame.classList.contains("is-collapsed"));
  assert.equal(toggle.getAttribute("aria-expanded"), "false");
  assert.equal(toggle.getAttribute("aria-controls"), toolbar.id);
  assert.equal(toggle.getAttribute("aria-label"), "Expand controls");

  toggle.click();
  assert.ok(!frame.classList.contains("is-collapsed"));
  assert.equal(toggle.getAttribute("aria-expanded"), "true");
  assert.equal(toggle.getAttribute("aria-label"), "Collapse controls");

  toggle.click();
  assert.ok(frame.classList.contains("is-collapsed"));
  assert.equal(toggle.getAttribute("aria-expanded"), "false");
  view.cleanup();
});


test("tooltips collapse to compact and clamp within a narrow viewport", async () => {
  const view = mount(new AnywidgetModelStub(directionalState()));
  await settle();
  const product = view.el.querySelector(".mmp-product-node");
  const tooltip = view.el.querySelector(".mmp-tooltip");
  const hostRect = { left: 0, top: 0, right: 1200, bottom: 800, width: 1200, height: 800, x: 0, y: 0, toJSON: () => ({}) };
  view.el.getBoundingClientRect = () => hostRect;
  const originalViewport = Object.getOwnPropertyDescriptor(window, "visualViewport");
  Object.defineProperty(window, "visualViewport", {
    configurable: true,
    value: { offsetLeft: 0, offsetTop: 0, width: 480, height: 700 },
  });

  tooltip.getBoundingClientRect = () => ({ left: 0, top: 0, right: 560, bottom: 400, width: 560, height: 400, x: 0, y: 0, toJSON: () => ({}) });
  product.dispatchEvent(new window.Event("focus"));

  assert.ok(tooltip.classList.contains("is-compact"));
  assert.ok(!tooltip.hidden);
  assert.equal(tooltip.style.left, "8px");
  assert.equal(tooltip.style.top, "14px");
  assert.ok(product.hasAttribute("aria-describedby"));

  Object.defineProperty(window, "visualViewport", { configurable: true, value: originalViewport?.value });
  view.cleanup();
});


function directionalState() {
  const state = modelState();
  state.data = {
    ...state.data,
    fromGroups: [{
      id: "from:a", from: "[*:1]C", fromDepictionId: null, ruleIds: ["rule:1"],
      productCount: 1, ruleCount: 1, gainCount: 1, lossCount: 0, neutralCount: 0,
      totalSupport: 3, aggregateMedian: 1.2, effectMin: 1.2, effectMax: 1.2,
    }],
    groups: [{
      id: "rule:1", environmentId: 7, fromGroup: "from:a", from: "[*:1]C", to: "[*:1]CC",
      fromDepictionId: null, toDepictionId: null, smarts: null, pseudosmiles: null,
      radius: 1, median: 1.2, min: null, max: null, count: 3, evidence: "Strong",
    }],
    products: [{
      id: "42", smiles: "CCO", group: "rule:1", median: 1.2, count: 3,
      evidence: "Strong", radius: 1, std: null, min: null, q1: null, q3: null,
      max: null, pValue: null, missing: [], depictionId: null,
    }],
    shown: 1,
    matching: 1,
  };
  return state;
}


test("rule links and product edges recolor when the direction trait flips", async () => {
  const state = directionalState();
  const view = mount(new AnywidgetModelStub(state));
  await settle();

  assert.equal(view.el.querySelector(".mmp-rule-link").getAttribute("stroke"), "var(--mmp-gain)");
  assert.equal(view.el.querySelector(".mmp-product-edge").getAttribute("stroke"), "var(--mmp-gain)");

  view.model.set("direction", "lower");
  await settle();
  assert.equal(view.el.querySelector(".mmp-rule-link").getAttribute("stroke"), "var(--mmp-loss)");
  assert.equal(view.el.querySelector(".mmp-product-edge").getAttribute("stroke"), "var(--mmp-loss)");
  assert.equal(view.el.querySelectorAll("select")[1].value, "lower");
  view.cleanup();
});


test("rapid gestures compose drafts and only the latest response clears busy state", async () => {
  const view = mount();
  await settle();
  const direction = view.el.querySelectorAll("select")[2];
  const support = view.el.querySelectorAll('.mmp-range-wrap input')[1];
  direction.value = "loss";
  direction.dispatchEvent(new window.Event("change"));
  support.value = "4";
  support.dispatchEvent(new window.Event("change"));

  assert.equal(view.model.saved.length, 2);
  assert.equal(view.model.get("_control_request").revision, 2);
  assert.equal(view.model.get("_control_request").filters.direction, "loss");
  assert.equal(view.model.get("_control_request").filters.min_support, 4);

  view.model.set("_control_response", { revision: 1, ok: true, error: null });
  assert.equal(view.el.querySelector(".mmp-toolbar").getAttribute("aria-busy"), "true");
  view.model.set("filters", { ...view.model.get("filters"), direction: "loss", min_support: 4 });
  view.model.set("_control_response", { revision: 2, ok: true, error: null });
  assert.equal(view.el.querySelector(".mmp-toolbar").getAttribute("aria-busy"), "false");
  assert.match(view.el.querySelector(".mmp-update-status").textContent, /updated/i);
  view.cleanup();
});


test("evidence and minimum-support controls reset one another", async () => {
  const state = modelState();
  state.filters = { ...state.filters, min_support: 4 };
  const view = mount(new AnywidgetModelStub(state));
  await settle();
  const support = view.el.querySelectorAll('.mmp-range-wrap input')[1];
  const evidence = [...view.el.querySelectorAll('.mmp-chipset[aria-label="Evidence tier"] input')];
  const strong = evidence.find((input) => input.value === "Strong");

  assert.equal(support.value, "4");
  strong.checked = false;
  strong.dispatchEvent(new window.Event("change"));
  assert.equal(view.model.get("_control_request").filters.min_support, 1);
  assert.deepEqual(view.model.get("_control_request").filters.quality, ["Moderate", "Exploratory"]);
  assert.equal(support.value, "1");

  support.value = "3";
  support.dispatchEvent(new window.Event("change"));
  assert.equal(view.model.get("_control_request").filters.min_support, 3);
  assert.equal(view.model.get("_control_request").filters.quality, null);
  assert.ok(evidence.every((input) => input.checked));
  view.cleanup();
});


test("evidence controls describe configured pair-count thresholds", async () => {
  const state = modelState();
  state.data.controlOptions.evidenceThresholds = { moderate: 3, strong: 8 };
  const view = mount(new AnywidgetModelStub(state));
  await settle();

  const controls = [...view.el.querySelectorAll('.mmp-chipset[aria-label="Evidence tier"] input')];
  assert.deepEqual(controls.map((input) => input.getAttribute("aria-label")), [
    "Strong: 8+ pairs",
    "Moderate: 3–7 pairs",
    "Exploratory: 1–2 pairs",
  ]);
  view.cleanup();
});


test("an error response restores accepted controls and announces the failure", async () => {
  const view = mount();
  await settle();
  const direction = view.el.querySelectorAll("select")[2];
  direction.value = "gain";
  direction.dispatchEvent(new window.Event("change"));
  view.model.set("_control_response", { revision: 1, ok: false, error: "bad direction" });

  assert.equal(direction.value, "all");
  assert.equal(view.el.querySelector(".mmp-toolbar").getAttribute("aria-busy"), "false");
  assert.match(view.el.querySelector(".mmp-update-status").textContent, /bad direction/);
  view.cleanup();
});


test("data and depiction changes coalesce into one graph render", async () => {
  const view = mount();
  await settle();
  const canvas = view.el.querySelector(".mmp-stage > svg");
  let renders = 0;
  const replaceChildren = canvas.replaceChildren.bind(canvas);
  canvas.replaceChildren = (...children) => {
    renders += 1;
    return replaceChildren(...children);
  };
  view.model.set("data", structuredClone(view.model.get("data")));
  view.model.set("depictions", {});
  await settle();
  assert.equal(renders, 1);
  view.cleanup();
});


test("host abort and returned cleanup remove DOM, listeners, and pending search", async () => {
  const hostController = new AbortController();
  const view = mount(new AnywidgetModelStub(modelState()), hostController.signal);
  await settle();
  const search = view.el.querySelector('input[type="search"]');
  search.value = "pending";
  search.dispatchEvent(new window.Event("input"));
  hostController.abort();
  view.cleanup();
  await new Promise((resolve) => setTimeout(resolve, 220));

  assert.equal(view.model.saved.length, 0);
  assert.equal(view.model.listenerCount(), 0);
  assert.equal(view.el.childElementCount, 0);
  assert.equal(view.el.classList.contains("mmp-instrument"), false);
});


test("two views of one model remain independent when one is cleaned", async () => {
  const model = new AnywidgetModelStub(modelState());
  const cell = document.createElement("div");
  cell.className = "marimo-cell interactive";
  const output = document.createElement("div");
  output.className = "output-area";
  output.style.maxHeight = "610px";
  output.style.overflow = "auto";
  cell.append(output);
  document.body.append(cell);
  const first = mount(model, undefined, output);
  const second = mount(model, undefined, output);
  await settle();
  assert.equal(model.listenerCount("change:data"), 2);
  assert.equal(output.style.maxHeight, "none");
  first.cleanup();
  assert.equal(model.listenerCount("change:data"), 1);
  assert.equal(output.style.maxHeight, "none");
  model.set("selected_id", "still-operational");
  assert.ok(second.el.querySelector(".mmp-stage"));
  second.cleanup();
  assert.equal(model.listenerCount(), 0);
  assert.equal(output.style.maxHeight, "610px");
  assert.equal(output.style.overflow, "auto");
});
