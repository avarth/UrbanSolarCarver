// Keeps the scroll of the elements inside a panel that is hidden for a while: a browser forgets the scroll of an element that is not
// displayed, so the position of each scrolled element is noted while the panel shows and put back when it shows again.
import { useLayoutEffect, useRef, type RefObject, type UIEvent } from "react";

/** Returns the scroll handler to give the panel as onScrollCapture; *panel* is the panel's element. */
export function useKeptScroll(panel: RefObject<HTMLElement | null>, shown: boolean): (event: UIEvent) => void {
  const noted = useRef(new Map<HTMLElement, number>());
  useLayoutEffect(() => {
    if (!shown) return;
    for (const [element, top] of noted.current) {
      if (panel.current?.contains(element)) element.scrollTop = top;
    }
    noted.current.clear();
  }, [shown]);
  return (event) => {
    if (!shown) return;       // the reset a browser reports when the panel goes away is not the position to keep
    const element = event.target as HTMLElement;
    noted.current.set(element, element.scrollTop);
  };
}
