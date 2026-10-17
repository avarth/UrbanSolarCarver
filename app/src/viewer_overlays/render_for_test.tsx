// Rendering an overlay into the jsdom document for a test, with React's act so effects and updates have run.
import { readFileSync } from "node:fs";
import { act, type ReactElement } from "react";
import { createRoot, type Root } from "react-dom/client";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

export interface RenderedOverlay {
  container: HTMLElement;
  rerender: (element: ReactElement) => void;
  unmount: () => void;
}

export function renderForTest(element: ReactElement): RenderedOverlay {
  const container = document.createElement("div");
  document.body.appendChild(container);
  let root: Root;
  act(() => {
    root = createRoot(container);
    root.render(element);
  });
  return {
    container,
    rerender: (next) => act(() => root.render(next)),
    unmount: () => {
      act(() => root.unmount());
      container.remove();
    },
  };
}

export function click(element: Element): void {
  act(() => {
    element.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
}

/**
 * Adds a style sheet of the app (a path from app/, such as "src/steps/steps.css") to the jsdom document, so getComputedStyle
 * reports what its rules declare (jsdom applies the cascade but resolves no var() and computes no layout); returns its removal.
 */
export function addStyleSheetForTest(path: string): () => void {
  const style = document.createElement("style");
  style.textContent = readFileSync(path, "utf8");
  document.head.appendChild(style);
  return () => style.remove();
}
