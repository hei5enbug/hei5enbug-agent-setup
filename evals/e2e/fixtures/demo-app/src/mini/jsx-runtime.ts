type Props = Record<string, unknown> & { children?: unknown };
type Component = (props: Props) => Node;

export const Fragment = Symbol("Fragment");

function append(parent: Node, child: unknown): void {
  if (child === null || child === undefined || child === false || child === true) return;
  if (Array.isArray(child)) {
    child.forEach((item) => append(parent, item));
  } else if (child instanceof Node) {
    parent.appendChild(child);
  } else {
    parent.appendChild(document.createTextNode(String(child)));
  }
}

function setProp(element: HTMLElement, name: string, value: unknown): void {
  if (name === "children" || name === "key" || value === undefined || value === null) return;
  if (name === "className") {
    element.setAttribute("class", String(value));
  } else if (name === "style" && typeof value === "object") {
    for (const [key, item] of Object.entries(value as Record<string, string | number>)) {
      const css = key.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`);
      const unitless = ["flex", "flexGrow", "flexShrink", "opacity", "order", "zIndex", "lineHeight", "fontWeight"];
      element.style.setProperty(css, typeof item === "number" && !unitless.includes(key) ? `${item}px` : String(item));
    }
  } else if (name.startsWith("on") && typeof value === "function") {
    element.addEventListener(name.slice(2).toLowerCase(), value as EventListener);
  } else if (typeof value === "boolean") {
    if (value) element.setAttribute(name, "");
  } else {
    element.setAttribute(name, String(value));
  }
}

export function jsx(type: string | symbol | Component, props: Props): Node {
  if (typeof type === "function") return type(props);
  if (type === Fragment) {
    const fragment = document.createDocumentFragment();
    append(fragment, props.children);
    return fragment;
  }
  const element = document.createElement(String(type));
  for (const [name, value] of Object.entries(props)) setProp(element, name, value);
  append(element, props.children);
  return element;
}

export const jsxs = jsx;
export const jsxDEV = jsx;

declare global {
  namespace JSX {
    type Element = Node;
    interface IntrinsicElements {
      [name: string]: Record<string, unknown>;
    }
    interface ElementChildrenAttribute {
      children: unknown;
    }
  }
}
