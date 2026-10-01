const NS = "http://www.w3.org/2000/svg";

export function svgElement(name: string, attributes: Record<string, unknown> = {}): SVGElement {
  const node = document.createElementNS(NS, name);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
  return node;
}

export function appendMolecule(container: Element, source: string | null): boolean {
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

export function labeledControl(labelText: string, control: HTMLElement, className = ""): HTMLLabelElement {
  const label = document.createElement("label");
  label.className = `mmp-control ${className}`.trim();
  const caption = document.createElement("span");
  caption.textContent = labelText;
  label.append(caption, control);
  return label;
}

export function addNotice(container: HTMLElement, message: string, kind: string): void {
  const notice = document.createElement("p");
  notice.className = `mmp-notice ${kind}`;
  notice.textContent = message;
  container.append(notice);
}
