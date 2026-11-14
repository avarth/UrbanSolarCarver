// The Sites table and the drawn blocks' rows show at most five rows and scroll inside their box past that; the column heading stays
// above the rows that scroll, and a row that starts being edited scrolls into view.
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { addStyleSheetForTest, renderForTest, type RenderedOverlay } from "../viewer_overlays/render_for_test";
import { ContextBlocksList, type ContextBlocksListProps } from "./ContextBlocksList";
import { SiteBox } from "./SiteInput";
import type { Site } from "./site_geometry";
import type { SiteTool } from "./SiteEditor";

let rendered: RenderedOverlay | null = null;
let removeStyles: () => void = () => {};
const scrolled: Element[] = [];
beforeEach(() => {
  removeStyles = addStyleSheetForTest("src/sites/sites.css");
  scrolled.length = 0;
  Element.prototype.scrollIntoView = vi.fn(function (this: Element) { scrolled.push(this); });
});
afterEach(() => {
  rendered?.unmount();
  rendered = null;
  removeStyles();
  delete (Element.prototype as { scrollIntoView?: unknown }).scrollIntoView;
});

const square = (name: string, at: number): Site => ({ name, points: [[at, 0, 0], [at + 10, 0, 0], [at + 10, 10, 0], [at, 10, 0]], height: 12 });
const eight = (word: string) => Array.from({ length: 8 }, (_, index) => square(`${word} ${index + 1}`, index * 20));
const HEIGHTS = { max: { for_all_sites: false, value: null }, base: { for_all_sites: true, value: null } };

function siteBox(tool: SiteTool | null) {
  return (
    <SiteBox sites={eight("Site")} heights={HEIGHTS as never} tool={tool} onDraw={() => {}} onEdit={() => {}} onChangeSite={async () => null}
             onDeleteSite={() => {}} onSwitch={() => {}} onImport={() => {}} onPlaceOnTerrain={() => {}} onRestoreOriginal={() => {}}
             hasTerrain={false} refusal={null} disabledReason={null} />
  );
}
function blocksList(editing: number | null) {
  const props: ContextBlocksListProps = {
    blocks: eight("Block"), disabledReason: null, hasTerrain: false, focusHeightOf: null, refusal: null, editing, onEdit: () => {},
    onDrawHole: () => {}, onChange: async () => null, onRemove: () => {}, onPlaceOnTerrain: () => {}, canUndo: false, onUndo: () => {},
  };
  return <ContextBlocksList {...props} />;
}

/** Whether the element scrolls its overflow and is held to a height. */
function scrollsInside(element: Element) {
  const style = getComputedStyle(element);
  return style.overflowY === "auto" && style.maxHeight !== "" && style.maxHeight !== "none";
}

test("the Sites table's rows scroll under a fixed column heading; the box does not grow", () => {
  rendered = renderForTest(siteBox(null));
  const list = rendered.container.querySelector(".site-table .site-list")!;
  expect(scrollsInside(list)).toBe(true);
  expect(list.contains(rendered.container.querySelector(".site-table-head"))).toBe(false);
  expect(getComputedStyle(rendered.container.querySelector(".site-table")!).overflowY).not.toBe("auto");
});

test("the drawn blocks' rows scroll inside the Context box", () => {
  rendered = renderForTest(blocksList(null));
  const list = rendered.container.querySelector(".context-blocks .site-list")!;
  expect(list.querySelectorAll(".context-block-row")).toHaveLength(8);
  expect(scrollsInside(list)).toBe(true);
});

test("a site row that starts being edited scrolls into view", () => {
  rendered = renderForTest(siteBox(null));
  expect(scrolled).toEqual([]);
  rendered.rerender(siteBox({ kind: "edit", index: 6 }));
  const rows = [...rendered.container.querySelectorAll(".site-row")];
  expect(rows[6].classList).toContain("site-row-editing");
  expect(scrolled).toEqual([rows[6]]);
});

test("a block row that starts being edited scrolls into view", () => {
  rendered = renderForTest(blocksList(null));
  rendered.rerender(blocksList(7));
  const rows = [...rendered.container.querySelectorAll(".context-block-row")];
  expect(rows[7].classList).toContain("site-row-editing");
  expect(scrolled).toEqual([rows[7]]);
});

test("laid out, each list is held to where its sixth row starts, whatever the rows' heights", () => {
  const rect = vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
    const index = this.parentElement ? [...this.parentElement.children].indexOf(this) : 0;
    const top = this.matches(".site-row") ? 100 + index * 33 : 100;
    return { top, bottom: top + 33, left: 0, right: 100, width: 100, height: 33, x: 0, y: top, toJSON: () => ({}) } as DOMRect;
  });
  try {
    rendered = renderForTest(siteBox(null));
    expect(rendered.container.querySelector<HTMLElement>(".site-table .site-list")!.style.maxHeight).toBe("165px");
    rendered.unmount();
    rendered = null;
    rendered = renderForTest(blocksList(null));
    expect(rendered.container.querySelector<HTMLElement>(".context-blocks .site-list")!.style.maxHeight).toBe("165px");
  } finally {
    rect.mockRestore();
  }
});
