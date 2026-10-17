import { readFileSync } from "node:fs";
import { expect, test } from "vitest";

const tokensCss = readFileSync("src/theme/tokens.css", "utf8");

test("tokens hold the UX spec colours", () => {
  for (const [name, hex] of [["--colour-accent", "#2f5d7c"], ["--colour-sun", "#f2b632"], ["--colour-carved", "#c8553d"],
                             ["--colour-viewport-light", "#e3e8e7"], ["--colour-viewport-dark", "#22303a"],
                             ["--colour-overlay-on-dark", "#2b3a45"], ["--colour-test-surface-on-dark", "#6fa0c4"],
                             ["--colour-storey-low", "#dfe6ea"], ["--colour-storey-high", "#2f5d7c"]])
    expect(tokensCss).toMatch(new RegExp(`${name}:\\s*${hex}`, "i"));
});

test("every token of UX 10 is defined", () => {
  const names = ["chrome", "panel", "ink", "muted", "line", "accent", "accent-soft", "sun", "carved", "ready", "error",
                 "viewport-light", "viewport-dark", "grid-minor-light", "grid-major-light", "grid-minor-dark", "grid-major-dark",
                 "overlay-on-dark", "ink-on-dark", "muted-on-dark", "line-on-dark", "test-surface-on-dark",
                 "axis-x", "axis-y", "axis-z"];
  for (const name of names) expect(tokensCss).toMatch(new RegExp(`--colour-${name}:\\s*#[0-9a-f]{6};`, "i"));
});

test("type, spacing and shape follow UX 10.2 and 10.3", () => {
  for (const [name, value] of [["--text-body", "14px"], ["--text-secondary", "12px"], ["--text-step-title", "16px"],
                               ["--text-key-number", "20px"], ["--line-height", "1.4"], ["--space-unit", "4px"],
                               ["--radius-large", "6px"], ["--radius-small", "4px"]])
    expect(tokensCss).toMatch(new RegExp(`${name}:\\s*${value}`));
});

test("the bundled font is declared for weights 400, 600 and 700 from files that exist", () => {
  for (const weight of [400, 600, 700]) {
    const fontFile = `atkinson-hyperlegible-next-latin-${weight}-normal.woff2`;
    expect(tokensCss).toContain(`url("./fonts/${fontFile}")`);
    expect(() => readFileSync(`src/theme/fonts/${fontFile}`)).not.toThrow();
  }
});

test("focus is a 2 px accent outline", () => {
  expect(tokensCss).toMatch(/:focus-visible\s*{\s*outline:\s*2px solid var\(--colour-accent\)/);
});
