// The Sites table and the drawn blocks' rows show at most five rows, and more scroll inside the list (sites.css). Rows differ in
// height (a site row with no height column is lower than one with a field, a row with a problem line is taller), so after each
// render the list is held to where its sixth row starts; the stylesheet's max-height stays as the fallback where nothing is laid out.
import { useLayoutEffect, useRef, type RefObject } from "react";

export const ROWS_SHOWN = 5;

/** The ref to give the list. */
export function useFiveRows(): RefObject<HTMLUListElement | null> {
  const list = useRef<HTMLUListElement>(null);
  useLayoutEffect(() => {
    const element = list.current;
    if (!element) return;
    const sixth = element.children[ROWS_SHOWN] as HTMLElement | undefined;
    const top = sixth ? sixth.getBoundingClientRect().top - element.getBoundingClientRect().top + element.scrollTop : 0;
    element.style.maxHeight = top > 0 ? `${Math.ceil(top)}px` : "";
  });
  return list;
}
