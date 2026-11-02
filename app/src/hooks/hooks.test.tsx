import { useState } from "react";
import { afterEach, expect, test } from "vitest";
import { renderForTest, type RenderedOverlay } from "../viewer_overlays/render_for_test";
import { useChangedDuringRender } from "./use_changed_during_render";
import { useKeyedValue } from "./use_keyed_value";
import { useLatest } from "./use_latest";

let rendered: RenderedOverlay | null = null;

afterEach(() => {
  rendered?.unmount();
  rendered = null;
});

test("a keyed value stays the same object while its key does, and is the new one at once when the key changes", () => {
  const seen: number[][] = [];
  function Probe({ point }: { point: number[] }) {
    seen.push(useKeyedValue(point, point.join(",")));
    return null;
  }
  rendered = renderForTest(<Probe point={[1, 2]} />);
  const first = seen[0];
  rendered.rerender(<Probe point={[1, 2]} />);
  expect(seen.at(-1)).toBe(first);
  rendered.rerender(<Probe point={[3, 4]} />);
  expect(seen.at(-1)).toEqual([3, 4]);
});

test("a change is seen in the same render, with the value before; an equal value or the first render is not a change", () => {
  const changes: [string, string][] = [];
  let shown = "";
  function Probe({ value }: { value: string }) {
    const [adjusted, setAdjusted] = useState("start");
    useChangedDuringRender(value, (before) => {
      changes.push([before, value]);
      setAdjusted(`after ${before}`);
    });
    shown = adjusted;
    return null;
  }
  rendered = renderForTest(<Probe value="a" />);
  rendered.rerender(<Probe value="a" />);
  expect(changes).toEqual([]);
  rendered.rerender(<Probe value="b" />);
  expect(changes).toEqual([["a", "b"]]);
  expect(shown).toBe("after a");
});

test("with a value before given, the first render compares with it", () => {
  const changes: boolean[] = [];
  function Probe({ open }: { open: boolean }) {
    useChangedDuringRender(open, (before) => { changes.push(before); }, { before: false });
    return null;
  }
  rendered = renderForTest(<Probe open />);
  expect(changes).toEqual([false]);
});

test("the latest value is there for a callback made in an earlier render", () => {
  let readLater: (() => string) | null = null;
  function Probe({ name }: { name: string }) {
    const latest = useLatest(name);
    const [read] = useState(() => () => latest.current);
    readLater = read;
    return null;
  }
  rendered = renderForTest(<Probe name="first" />);
  rendered.rerender(<Probe name="second" />);
  expect(readLater!()).toBe("second");
});
