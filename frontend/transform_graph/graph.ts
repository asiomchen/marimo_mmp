import { resolveDepiction } from "./depiction";
import { addNotice, appendMolecule, svgElement } from "./dom";
import { colorFor, dashFor } from "./encoding";
import { updateControls } from "./controls";
import { absolutePosition, radialRings, requiredPosition } from "./layout";
import { attachProductNavigation, restoreRovingFocus, updateSelection } from "./selection";
import {
  accessibleProductLabel,
  attachTooltip,
  fillFromTooltip,
  fillProductTooltip,
  fillQueryTooltip,
  fillRuleTooltip,
  hideTooltip,
} from "./tooltips";
import type {
  AbsolutePosition,
  AnywidgetModel,
  FromGroup,
  GraphData,
  Position,
  PropertyDirection,
  ViewRefs,
} from "./types";
import { updateCanvasSize } from "./viewport";

type DepictionLookup = (depictionId: string | null) => string | null;

interface GraphLayout {
  canvasSize: number;
  center: number;
  fromPositions: Map<string, AbsolutePosition>;
  rulePositions: Map<string, AbsolutePosition>;
  productPositions: Map<string, AbsolutePosition>;
}

// Per-render inputs shared by the ring drawing helpers.
interface GraphScene {
  refs: ViewRefs;
  data: GraphData;
  direction: PropertyDirection;
  depiction: DepictionLookup;
  layout: GraphLayout;
}

export function renderGraph(model: AnywidgetModel, refs: ViewRefs): void {
  const data = model.get("data");
  const depictions = model.get("depictions");
  const selected = model.get("selected_id");
  const depiction: DepictionLookup = (depictionId) => resolveDepiction(depictions, depictionId);
  const missingDepictions = hasMissingDepictions(data, depiction);
  updateControls(model, refs.controls, refs.controlSync.current());
  refs.counter.textContent = `${data.shown || 0} / ${data.matching || 0} PRODUCTS · ${model.get("property_name") || "PROPERTY"}`;
  hideTooltip(refs);
  const previousRoving = refs.canvas.querySelector<SVGElement>('.mmp-product-node[tabindex="0"]')?.dataset.productId ?? null;
  const focusRoot = refs.canvas.getRootNode() as Document | ShadowRoot;
  const hadFocus = Boolean(focusRoot.activeElement && refs.canvas.contains(focusRoot.activeElement));
  refs.canvas.replaceChildren();

  const layout = computeGraphLayout(data);
  updateCanvasSize(refs, layout.canvasSize);
  const scene: GraphScene = {
    refs,
    data,
    direction: model.get("direction") || "higher",
    depiction,
    layout,
  };
  // Edges are inserted before the query node so every node paints above every edge.
  const queryNode = drawQueryNode(scene);
  drawFromGroups(scene, queryNode);
  drawRuleNodes(scene, queryNode);
  const navNodes = drawProductNodes(scene, queryNode, model, selected);

  restoreRovingFocus(navNodes, previousRoving, selected, hadFocus);
  updateSelection(model, refs);
  renderNotices(refs, data, missingDepictions);
}

function hasMissingDepictions(data: GraphData, depiction: DepictionLookup): boolean {
  const requiredDepictionIds = [
    data.queryDepictionId,
    ...data.products.map((product) => product.depictionId),
    ...data.fromGroups.map((group) => group.fromDepictionId),
    ...data.groups.flatMap((group) => [group.fromDepictionId, group.toDepictionId]),
  ].filter(Boolean);
  return (Boolean(data.querySmiles) && !data.queryDepictionId)
    || requiredDepictionIds.some((depictionId) => !depiction(depictionId));
}

// Concentric rings: source fragments, then their rules, then each rule's products,
// each ring ordered by its parent so children sit near their parent.
function computeGraphLayout(data: GraphData): GraphLayout {
  const { products, groups, fromGroups } = data;
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
  const toAbsolute = (positions: Map<string, Position>) =>
    new Map([...positions].map(([id, position]) => [id, absolutePosition(position, center)]));
  return {
    canvasSize,
    center,
    fromPositions: toAbsolute(fromLayout.positions),
    rulePositions: toAbsolute(ruleLayout.positions),
    productPositions: toAbsolute(productLayout.positions),
  };
}

function drawQueryNode({ refs, data, depiction, layout: { center } }: GraphScene): SVGElement {
  const queryNode = svgElement("g", {
    class: "mmp-query-node",
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
  refs.canvas.append(queryNode);
  return queryNode;
}

function drawFromGroups({ refs, data, depiction, layout }: GraphScene, queryNode: SVGElement): void {
  const { center, fromPositions } = layout;
  data.fromGroups.forEach((group) => {
    const position = requiredPosition(fromPositions, group.id);
    const line = svgElement("line", { x1: center, y1: center, x2: position.x, y2: position.y, class: "mmp-from-spoke" });
    refs.canvas.insertBefore(line, queryNode);
    const node = svgElement("g", {
      class: "mmp-from-node",
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
    refs.canvas.append(node);
  });
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

function drawRuleNodes({ refs, data, direction, depiction, layout }: GraphScene, queryNode: SVGElement): void {
  const { fromPositions, rulePositions } = layout;
  data.groups.forEach((group) => {
    const position = requiredPosition(rulePositions, group.id);
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
    refs.canvas.append(node);
  });
}

// Product nodes form one roving-tabindex group, navigated in on-screen
// clockwise order (from 12 o'clock) using the layout angles computed above.
// Returns the nodes in that navigation order.
function drawProductNodes(
  { refs, data, direction, depiction, layout }: GraphScene,
  queryNode: SVGElement,
  model: AnywidgetModel,
  selected: string | null,
): SVGElement[] {
  const { rulePositions, productPositions } = layout;
  const navNodes: SVGElement[] = [];
  const navAngles = new Map<SVGElement, { angle: number; radius: number }>();
  data.products.forEach((product, index) => {
    const { x, y, angle, radius } = requiredPosition(productPositions, product.id);
    const groupPosition = requiredPosition(rulePositions, product.group);
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
      tabindex: "-1", role: "button",
      "aria-pressed": "false",
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
    attachProductNavigation(model, refs, navNodes, node, product.id);
    navNodes.push(node);
    // Clockwise from 12 o'clock: layout angles start at -PI/2 and grow clockwise on screen.
    navAngles.set(node, { angle: (angle + Math.PI / 2 + 2 * Math.PI) % (2 * Math.PI), radius });
    refs.canvas.append(node);
  });
  navNodes.sort((left, right) => {
    const a = navAngles.get(left);
    const b = navAngles.get(right);
    return (a?.angle ?? 0) - (b?.angle ?? 0) || (a?.radius ?? 0) - (b?.radius ?? 0);
  });
  return navNodes;
}

function renderNotices(refs: ViewRefs, data: GraphData, missingDepictions: boolean): void {
  refs.notices.replaceChildren();
  if (missingDepictions) addNotice(refs.notices, "Some molecule depictions are unavailable.", "warn");
  if (data.truncated) addNotice(refs.notices, `Showing the highest-ranked ${data.shown} of ${data.matching} matching products.`, "info");
  for (const warning of data.warnings || []) addNotice(refs.notices, warning, "warn");
}
