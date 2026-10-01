import { hideTooltip } from "./tooltips";
import type { AnywidgetModel, ViewRefs } from "./types";

const NAVIGATION_KEYS = ["ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp", "Home", "End"];

export function setRovingNode(nodes: SVGElement[], target: SVGElement): void {
  for (const node of nodes) node.setAttribute("tabindex", node === target ? "0" : "-1");
}

export function updateSelection(model: AnywidgetModel, refs: ViewRefs): void {
  const selected = model.get("selected_id");
  for (const node of refs.canvas.querySelectorAll<SVGElement>(".mmp-product-node")) {
    const isSelected = String(node.dataset.productId) === String(selected);
    node.classList.toggle("is-selected", isSelected);
    node.setAttribute("aria-pressed", isSelected ? "true" : "false");
  }
}

export function selectProduct(model: AnywidgetModel, id: string): void {
  model.set("selected_id", String(id));
  model.save_changes();
}

// `navNodes` is shared by every product node and sorted once all nodes exist,
// so handlers read the final on-screen order at event time.
export function attachProductNavigation(
  model: AnywidgetModel,
  refs: ViewRefs,
  navNodes: SVGElement[],
  node: SVGElement,
  productId: string,
): void {
  node.addEventListener("focus", () => setRovingNode(navNodes, node), { signal: refs.signal });
  node.addEventListener("click", () => {
    setRovingNode(navNodes, node);
    selectProduct(model, productId);
  }, { signal: refs.signal });
  node.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      hideTooltip(refs);
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      selectProduct(model, productId);
    } else if (NAVIGATION_KEYS.includes(event.key)) {
      event.preventDefault();
      const current = navNodes.indexOf(node);
      let target = 0;
      if (event.key === "End") target = navNodes.length - 1;
      else if (event.key !== "Home") {
        const step = event.key === "ArrowRight" || event.key === "ArrowDown" ? 1 : -1;
        target = (current + step + navNodes.length) % navNodes.length;
      }
      const next = navNodes[target];
      if (next) {
        setRovingNode(navNodes, next);
        next.focus();
      }
    }
  }, { signal: refs.signal });
}

// Keep the Tab stop on the previously active product, else the selection, else the first node.
export function restoreRovingFocus(
  navNodes: SVGElement[],
  previousRoving: string | null,
  selected: string | null | undefined,
  hadFocus: boolean,
): void {
  const byId = (id: string | null) => (id === null ? undefined : navNodes.find((node) => node.dataset.productId === id));
  const rovingStart = byId(previousRoving) ?? byId(selected === null || selected === undefined ? null : String(selected)) ?? navNodes[0];
  if (rovingStart) {
    setRovingNode(navNodes, rovingStart);
    if (hadFocus) rovingStart.focus();
  }
}
