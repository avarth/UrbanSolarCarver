// React's "adjusting some state when a prop changes": state set during render when a value differs from the one of the render
// before, so the adjusted state shows in the same paint, without an effect and the extra render it takes.
import { useState } from "react";

/**
 * Calls *changed* with the value before, during render, when *value* differs (Object.is) from the one of the last render. With
 * *options.before*, the first render compares with it, so a value other than it counts as a change at once; without, nothing
 * changes at the first render. *changed* may set the state of the component that calls this, as the render goes on.
 */
export function useChangedDuringRender<T>(value: T, changed: (before: T) => void, options?: { before: T }): void {
  const [seen, setSeen] = useState<T>(options === undefined ? value : options.before);
  if (Object.is(seen, value)) return;
  setSeen(value);
  changed(seen);
}
