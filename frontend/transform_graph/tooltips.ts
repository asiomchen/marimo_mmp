import { appendMolecule } from "./dom";
import type { FromGroup, GraphData, MetricEntry, Product, RuleGroup, TooltipFill, ViewRefs } from "./types";

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

export function accessibleProductLabel(product: Product): string {
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

export function fillProductTooltip(product: Product, depiction: string | null, tooltip: HTMLElement): void {
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

export function fillQueryTooltip(data: GraphData, depiction: string | null, tooltip: HTMLElement): void {
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

export function fillFromTooltip(group: FromGroup, depiction: string | null, tooltip: HTMLElement): void {
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

export function fillRuleTooltip(
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

export function attachTooltip(
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

export function hideTooltip(refs: ViewRefs, node: Element | null = null): void {
  if (node?.matches(":focus-visible")) return;
  for (const describedNode of refs.canvas.querySelectorAll(`[aria-describedby="${refs.tooltip.id}"]`)) {
    describedNode.removeAttribute("aria-describedby");
  }
  refs.tooltip.hidden = true;
  delete refs.tooltip.dataset.tooltipKey;
}
