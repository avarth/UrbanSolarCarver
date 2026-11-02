// Import rules of the app (dependency-cruiser), checked by `npm test` (the `deps` script) and drawn by
// `python tools/draw_maps.py`. docs/project-map.md explains them.

// The folders of src/ in layers, top first. A file may import from its own folder and from the layers below, not from a
// layer above and not from another folder of its own layer. Above them all are App.tsx and main.tsx; below them all the
// other top-level files (messages.ts, format_numbers.ts, modes.ts, stages.ts), which import no folder. Tests may import
// anything.
const LAYERS = [
  ["workspace"],
  ["steps", "criteria", "simulate", "inspect"],
  ["common"],
  ["settings_form"],
  ["viewer_overlays"],
  ["theme"],
  ["viewer"],
  ["api_client"],
  ["hooks"],
];
const TESTS = ["[.]test[.]tsx?$", "_for_test[.]tsx?$"];

const layerRules = LAYERS.flatMap((layer, index) => layer.map((folder) => {
  const notAllowed = [...LAYERS.slice(0, index).flat(), ...layer.filter((other) => other !== folder)];
  return {
    name: `layer-${folder}`,
    severity: "error",
    comment: `${folder}/ imports only from its own folder and the layers below it (${notAllowed.join(", ") || "none"} are not).`,
    from: { path: `^src/${folder}/`, pathNot: TESTS },
    to: { path: `^src/(${notAllowed.join("|")})/` },
  };
})).filter((rule) => !rule.to.path.includes("()"));

/** @type {import('dependency-cruiser').IConfiguration} */
module.exports = {
  forbidden: [
    ...layerRules,
    {
      name: "top-level-files-below-the-folders",
      severity: "error",
      comment: "The top-level files other than App.tsx and main.tsx (the texts, numbers, modes, stages) import no folder.",
      from: { path: "^src/[^/]+$", pathNot: ["^src/(App|main)[.]tsx$", ...TESTS] },
      to: { path: "^src/[^/]+/" },
    },
    {
      name: "no-circular",
      severity: "error",
      comment: "Two files that import each other, directly or through others, cannot be understood or changed apart.",
      from: {},
      to: { circular: true },
    },
    {
      name: "no-orphans",
      severity: "error",
      comment: "A source file nothing imports is dead code (test helpers named *_for_test are imported by tests only).",
      from: { orphan: true, pathNot: ["[.]test[.]tsx?$", "_for_test[.]ts$", "[.]d[.]ts$", "^src/main[.]tsx$", "[.]css$"] },
      to: {},
    },
    {
      name: "not-to-test",
      severity: "error",
      comment: "Source code does not import test files.",
      from: { pathNot: "[.]test[.]tsx?$" },
      to: { path: "[.]test[.]tsx?$" },
    },
    {
      name: "not-to-dev-dependency",
      severity: "error",
      comment: "The built app may only use packages under dependencies in package.json.",
      from: { path: "^src/", pathNot: ["[.]test[.]tsx?$", "_for_test[.]ts$"] },
      to: { dependencyTypes: ["npm-dev"], dependencyTypesNot: ["type-only"] },
    },
    {
      name: "api-client-stands-alone",
      severity: "error",
      comment: "The service client knows no screen: it imports only itself and the messages.",
      from: { path: "^src/api_client/" },
      to: { path: "^src/", pathNot: ["^src/api_client/", "^src/messages[.]ts$"] },
    },
    {
      name: "viewer-without-components",
      severity: "error",
      comment: "The 3D scene (three.js) imports no React component, so it can be read and tested without the screens.",
      from: { path: "^src/viewer/", pathNot: "[.]test[.]tsx?$" },
      to: { path: "[.]tsx$" },
    },
  ],
  options: {
    doNotFollow: { path: "node_modules" },
    exclude: { path: "node_modules" },
    tsPreCompilationDeps: true,
    tsConfig: { fileName: "tsconfig.json" },
    reporterOptions: {
      archi: { collapsePattern: "^src/[^/]+/" },
    },
  },
};
