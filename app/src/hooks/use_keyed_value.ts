// A value made anew on each render with the same contents (a point, a list of layer names or colours) kept as one object while a key
// of its contents stays the same, so the effects and memos that depend on it do not run again for an equal value.
import { useState } from "react";

/** *value* as it was when *key* last changed; a new key holds the new value at once (state adjusted during render, not in an effect). */
export function useKeyedValue<T>(value: T, key: string): T {
  const [held, setHeld] = useState({ key, value });
  if (held.key === key) return held.value;
  setHeld({ key, value });
  return value;
}
