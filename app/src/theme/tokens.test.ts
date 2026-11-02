import { readdirSync, readFileSync } from "node:fs";
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

/** The app's own source files under src/ (not the tests and their fakes), with their text. */
function sourceFiles(extensions: RegExp): { file: string; text: string }[] {
  return readdirSync("src", { recursive: true, encoding: "utf8" })
    .map((file) => file.replaceAll("\\", "/"))
    .filter((file) => extensions.test(file) && !/\.test\.|_for_test\./.test(file))
    .map((file) => ({ file, text: readFileSync(`src/${file}`, "utf8") }));
}

test("every colour token the stylesheets, the components and the 3D scene use is defined on the root", () => {
  // A var() of a token tokens.css does not define draws in the inherited colour or none, and colourToken() of one gives "".
  const rootBlock = tokensCss.match(/:root\s*{([^}]*)}/)![1];
  const defined = new Set([...rootBlock.matchAll(/--colour-([a-z0-9-]+):/g)].map((match) => match[1]));
  const used = new Map<string, string>();   // token name -> a file that uses it
  for (const { file, text } of sourceFiles(/\.(css|tsx?)$/))
    for (const match of text.matchAll(/var\(--colour-([a-z0-9-]+)\s*[,)]/g)) used.set(match[1], file);
  // colourToken's argument: each quoted name in it (after the ? of a choice such as theme === "dark" ? a : b); in a template,
  // ${theme} stands for each viewport theme.
  let colourTokenCalls = 0;
  for (const { file, text } of sourceFiles(/\.tsx?$/)) {
    for (const call of text.matchAll(/(?<!function )colourToken\(([^()]*)\)/g)) {
      colourTokenCalls += 1;
      const names = [...call[1].slice(call[1].indexOf("?") + 1).matchAll(/"([^"]+)"|`([^`]+)`/g)].flatMap((literal) => literal[1] !== undefined ? [literal[1]]
        : ["light", "dark"].map((theme) => literal[2].replace(/\$\{[^}]*\}/g, theme)));
      expect(names, `${file}: ${call[0]} names no token this test can read`).not.toEqual([]);
      for (const name of names) used.set(name, file);
    }
  }
  expect(colourTokenCalls).toBeGreaterThan(20);   // the scan finds the calls: 39 when written; a floor, not a count to keep up to date
  const missing = [...used].filter(([name]) => !defined.has(name)).map(([name, file]) => `--colour-${name} (${file})`);
  expect(missing).toEqual([]);
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

test("the dark theme is set on the body and gives dark values to the interface's colours only", () => {
  const darkBlock = tokensCss.match(/body\[data-theme="dark"\]\s*{([^}]*)}/)![1];
  expect(darkBlock).toMatch(/color-scheme:\s*dark/);
  const darkNames = [...darkBlock.matchAll(/--colour-([a-z-]+):\s*#[0-9a-f]{6};/gi)].map((match) => match[1]);
  expect(darkNames).toEqual(expect.arrayContaining(["chrome", "panel", "ink", "muted", "line", "accent", "accent-soft", "shadow"]));
  // The 3D scene reads its colours from the root (colourToken), so its rows have one value in both themes.
  for (const name of darkNames) expect(name).not.toMatch(/viewport|grid|on-dark|light-|storey|context|terrain|axis|carved|sun/);
  expect(tokensCss).not.toMatch(/:root\[data-theme/);
});

test("shadows mix the shadow colour, which stays dark in the dark theme, not the ink, which turns light", () => {
  const cssFiles = ["src/App.css", "src/theme/panels.css", "src/simulate/simulate.css", "src/inspect/inspect.css",
                    "src/settings_form/settings_form.css", "src/viewer_overlays/overlays.css"];
  for (const file of cssFiles) expect(readFileSync(file, "utf8")).not.toMatch(/box-shadow:[^;]*var\(--colour-ink\) (1[268]|35|60)%/);
});
