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
    filters: { effect: "gain", min_abs_effect: 0, min_support: 1, radii: null, quality: null, text: "" },
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
  assert.equal(view.model.get("_control_request").filters.effect, "all");
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
  assert.equal(view.model.get("_control_request").filters.effect, "loss");
  assert.equal(view.model.get("_control_request").filters.min_support, 4);

  view.model.set("_control_response", { revision: 1, ok: true, error: null });
  assert.equal(view.el.querySelector(".mmp-toolbar").getAttribute("aria-busy"), "true");
  view.model.set("filters", { ...view.model.get("filters"), effect: "loss", min_support: 4 });
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


test("toggling a radius keeps the same focused checkbox and rebuilds only for new radii", async () => {
  const view = mount();
  await settle();
  const [first, second] = view.el.querySelectorAll('input[aria-label^="Radius"]');
  second.focus();
  second.checked = false;
  second.dispatchEvent(new window.Event("change"));
  await settle();

  assert.deepEqual(view.model.get("_control_request").filters.radii, [0]);
  const afterToggle = view.el.querySelectorAll('input[aria-label^="Radius"]');
  assert.equal(afterToggle[1], second);
  assert.equal(second.isConnected, true);
  assert.equal(second.matches(":focus"), true);
  assert.equal(first.checked, true);
  assert.equal(second.checked, false);

  const data = structuredClone(view.model.get("data"));
  data.controlOptions.radii = [0, 1, 2];
  view.model.set("data", data);
  await settle();
  const rebuilt = [...view.el.querySelectorAll('input[aria-label^="Radius"]')];
  assert.deepEqual(rebuilt.map((input) => input.value), ["0", "1", "2"]);
  view.cleanup();
});


test("a graph re-render does not overwrite search text that is being typed", async () => {
  const view = mount();
  await settle();
  const search = view.el.querySelector('input[type="search"]');
  search.focus();
  search.value = "abc";
  search.dispatchEvent(new window.Event("input"));
  await new Promise((resolve) => setTimeout(resolve, 220));
  assert.equal(view.model.get("_control_request").filters.text, "abc");

  search.value = "abcd";
  search.dispatchEvent(new window.Event("input"));
  view.model.set("data", structuredClone(view.model.get("data")));
  await settle();
  assert.equal(search.value, "abcd");

  search.blur();
  view.cleanup();
});


test("search text follows accepted filters while the input is idle", async () => {
  const view = mount();
  await settle();
  const search = view.el.querySelector('input[type="search"]');
  view.model.set("filters", { ...view.model.get("filters"), text: "from python" });
  view.model.set("data", structuredClone(view.model.get("data")));
  await settle();
  assert.equal(search.value, "from python");
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


function multiProductState(ids = ["30", "10", "40", "20"]) {
  const state = directionalState();
  const template = state.data.products[0];
  state.data = {
    ...state.data,
    products: ids.map((id) => ({ ...template, id })),
    shown: ids.length,
    matching: ids.length,
  };
  return state;
}

const productNodes = (view) => [...view.el.querySelectorAll(".mmp-product-node")];
const tabStops = (view) => [...view.el.querySelectorAll('.mmp-stage [tabindex="0"]')];
const productId = (node) => node.getAttribute("data-product-id");
const press = (node, key) => node.dispatchEvent(new window.KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }));

test("the graph exposes exactly one tab stop, on the first radial product by default", async () => {
  const view = mount(new AnywidgetModelStub(multiProductState()));
  await settle();
  const stops = tabStops(view);
  assert.equal(stops.length, 1);
  assert.equal(productId(stops[0]), "10");
  assert.equal(productNodes(view).filter((node) => node.getAttribute("tabindex") === "-1").length, 3);
  view.cleanup();
});

test("the selected product holds the tab stop", async () => {
  const state = multiProductState();
  state.selected_id = "40";
  const view = mount(new AnywidgetModelStub(state));
  await settle();
  assert.deepEqual(tabStops(view).map(productId), ["40"]);
  assert.equal(view.el.querySelector('[data-product-id="40"]').getAttribute("aria-pressed"), "true");
  assert.equal(view.el.querySelector('[data-product-id="10"]').getAttribute("aria-pressed"), "false");
  view.cleanup();
});

test("arrow keys follow clockwise radial order, wrap, and move the tab stop", async () => {
  const view = mount(new AnywidgetModelStub(multiProductState()));
  await settle();
  const byId = (id) => view.el.querySelector(`[data-product-id="${id}"]`);
  // Data order is 30, 10, 40, 20; on-screen clockwise order is 10, 20, 30, 40.
  press(byId("10"), "ArrowRight");
  assert.equal(productId(document.activeElement), "20");
  assert.deepEqual(tabStops(view).map(productId), ["20"]);
  press(byId("20"), "ArrowDown");
  assert.equal(productId(document.activeElement), "30");
  press(byId("30"), "ArrowLeft");
  assert.equal(productId(document.activeElement), "20");
  press(byId("20"), "ArrowUp");
  press(byId("10"), "ArrowUp");
  assert.equal(productId(document.activeElement), "40", "counter-clockwise from the first node wraps to the last");
  press(byId("40"), "ArrowRight");
  assert.equal(productId(document.activeElement), "10", "clockwise from the last node wraps to the first");
  assert.equal(tabStops(view).length, 1);
  view.cleanup();
});

test("Home and End jump to the first and last radial product", async () => {
  const view = mount(new AnywidgetModelStub(multiProductState()));
  await settle();
  press(view.el.querySelector('[data-product-id="10"]'), "End");
  assert.equal(productId(document.activeElement), "40");
  assert.deepEqual(tabStops(view).map(productId), ["40"]);
  press(document.activeElement, "Home");
  assert.equal(productId(document.activeElement), "10");
  assert.deepEqual(tabStops(view).map(productId), ["10"]);
  view.cleanup();
});

test("the roving position and focus survive a re-render", async () => {
  const view = mount(new AnywidgetModelStub(multiProductState()));
  await settle();
  press(view.el.querySelector('[data-product-id="10"]'), "ArrowRight");
  press(view.el.querySelector('[data-product-id="20"]'), "ArrowRight");
  assert.deepEqual(tabStops(view).map(productId), ["30"]);

  view.model.set("data", { ...view.model.get("data") });
  await settle();
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.deepEqual(tabStops(view).map(productId), ["30"]);
  assert.equal(productId(document.activeElement), "30");

  // A vanished roving node falls back to the first radial product.
  const data = view.model.get("data");
  view.model.set("data", { ...data, products: data.products.filter((product) => product.id !== "30") });
  await settle();
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.deepEqual(tabStops(view).map(productId), ["10"]);
  view.cleanup();
});

test("rule and from nodes are non-focusable informational images with labels", async () => {
  const view = mount(new AnywidgetModelStub(multiProductState()));
  await settle();
  for (const selector of [".mmp-from-node", ".mmp-rule-node", ".mmp-query-node"]) {
    const node = view.el.querySelector(selector);
    assert.equal(node.getAttribute("role"), "img", selector);
    assert.ok(node.getAttribute("aria-label"), selector);
    assert.equal(node.hasAttribute("tabindex"), false, selector);
  }
  const canvas = view.el.querySelector(".mmp-stage > svg");
  assert.equal(canvas.getAttribute("role"), "group");
  assert.ok(canvas.getAttribute("aria-label"));
  assert.equal(view.el.querySelector(".mmp-product-node").getAttribute("role"), "button");
  view.cleanup();
});

test("Enter, Space, and click still select a product and update aria-pressed", async () => {
  const model = new AnywidgetModelStub(multiProductState());
  const view = mount(model);
  await settle();
  press(view.el.querySelector('[data-product-id="20"]'), "Enter");
  assert.equal(model.get("selected_id"), "20");
  assert.equal(view.el.querySelector('[data-product-id="20"]').getAttribute("aria-pressed"), "true");
  press(view.el.querySelector('[data-product-id="30"]'), " ");
  assert.equal(model.get("selected_id"), "30");
  assert.equal(view.el.querySelector('[data-product-id="20"]').getAttribute("aria-pressed"), "false");
  view.el.querySelector('[data-product-id="40"]').dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  assert.equal(model.get("selected_id"), "40");
  assert.deepEqual(tabStops(view).map(productId), ["40"]);
  view.cleanup();
});
