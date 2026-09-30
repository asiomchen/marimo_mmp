import { buildControls } from "./controls";
import { svgElement } from "./dom";
import type { AnywidgetModel, ControlPatch, ShellRefs, TimerId } from "./types";

let tooltipSequence = 0;
let toolbarSequence = 0;

export function buildShell(
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
  canvas.setAttribute("aria-description", "Products are one Tab stop. Use arrow keys to move clockwise or counter-clockwise, Home and End to jump, Enter or Space to select");
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
