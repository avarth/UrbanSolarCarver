// The window of an outline import (design/site-import.md): the count and wording, Place on terrain only with terrain, and what Import sends.
import { act } from "react";
import { afterEach, expect, test, vi } from "vitest";
import type { OutlinesReply } from "../api_client/client";
import { groupedDigits } from "../format_numbers";
import { renderForTest, type RenderedOverlay } from "../viewer_overlays/render_for_test";
import { ImportSitesDialog } from "./ImportSitesDialog";

let rendered: RenderedOverlay | null = null;
afterEach(() => { rendered?.unmount(); rendered = null; });

const ONE: OutlinesReply = {
  file: "plot.obj", unit: "feet", outlines: [{ name: "Corner", points: [[0, 0, 0], [10, 0, 0], [10, 10, 0]], area: 1234.4, rise: 0 }], left_out: [],
  distance_from_inputs: null,
};
const buttonCalled = (text: string) => [...document.body.querySelectorAll<HTMLButtonElement>("button")].find((button) => button.textContent === text)!;

test("one outline: the singular, no left out list and no warning; Import sends the terrain choice", () => {
  const onImport = vi.fn();
  rendered = renderForTest(<ImportSitesDialog found={ONE} names={["Corner"]} hasTerrain busy={false} onImport={onImport} onCancel={() => {}} />);
  const text = document.body.textContent!;
  expect(text).toContain("1 closed polyline, read in feet.");
  expect(text).toContain(`Corner${groupedDigits(1234)} m², rise 0 m`);      // the area rounded
  expect(document.body.querySelector(".import-sites-left-out")).toBeNull();
  expect(document.body.querySelector(".input-box-problem")).toBeNull();
  const terrain = document.body.querySelector<HTMLInputElement>(".import-sites-terrain input")!;
  expect(terrain.checked).toBe(true);
  act(() => { terrain.click(); });
  act(() => { buttonCalled("Import 1 site").click(); });
  expect(onImport).toHaveBeenCalledWith(false);
});

test("without terrain there is no Place on terrain and Import sends false; no outlines: Import waits", () => {
  const onImport = vi.fn();
  rendered = renderForTest(<ImportSitesDialog found={ONE} names={["Corner"]} hasTerrain={false} busy={false} onImport={onImport} onCancel={() => {}} />);
  expect(document.body.querySelector(".import-sites-terrain")).toBeNull();
  act(() => { buttonCalled("Import 1 site").click(); });
  expect(onImport).toHaveBeenCalledWith(false);
  rendered.rerender(<ImportSitesDialog found={{ ...ONE, outlines: [] }} names={[]} hasTerrain={false} busy={false} onImport={onImport} onCancel={() => {}} />);
  expect(buttonCalled("Import 0 sites").disabled).toBe(true);
});

test("while busy both buttons wait, and Cancel calls onCancel", () => {
  const onCancel = vi.fn();
  rendered = renderForTest(<ImportSitesDialog found={ONE} names={["Corner"]} hasTerrain busy={false} onImport={() => {}} onCancel={onCancel} />);
  act(() => { buttonCalled("Cancel").click(); });
  expect(onCancel).toHaveBeenCalledTimes(1);
  rendered.rerender(<ImportSitesDialog found={ONE} names={["Corner"]} hasTerrain busy onImport={() => {}} onCancel={onCancel} />);
  expect(buttonCalled("Cancel").disabled).toBe(true);
  expect(buttonCalled("Import 1 site").disabled).toBe(true);
});
