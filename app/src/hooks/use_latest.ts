// A value of the latest render for code that runs later: a reply, a timer, a listener, a callback handed out once.
import { useLayoutEffect, useRef } from "react";

/**
 * A ref holding *value* as of the last committed render. It is written in a layout effect, not during render, so a render React
 * throws away does not leave its value there; read it in callbacks, not during render. Effects read the latest props through
 * useEffectEvent instead.
 */
export function useLatest<T>(value: T): { readonly current: T } {
  const latest = useRef(value);
  useLayoutEffect(() => {
    latest.current = value;
  });
  return latest;
}
