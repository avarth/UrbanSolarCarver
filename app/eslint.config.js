// Lint rules for the app, run by `npm run lint` and by `npm test`.
// The React hooks rules check effect dependencies and what components may do during render; a rule turned off or
// an `eslint-disable` line says why next to it.
import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["src/api_client/generated_types.ts"] },
  js.configs.recommended,
  tseslint.configs.recommended,
  reactHooks.configs.flat["recommended-latest"],
  {
    files: ["src/**/*.{ts,tsx}"],
    languageOptions: { globals: { ...globals.browser } },
  },
  {
    files: ["*.{js,cjs,mjs,ts}", "scripts/**"],
    languageOptions: { globals: { ...globals.node } },
  },
  {
    files: ["*.cjs"],
    languageOptions: { sourceType: "commonjs" },
  },
  {
    linterOptions: { reportUnusedDisableDirectives: "error" },
    rules: {
      "react-hooks/exhaustive-deps": "error",
      // A name starting with _ is unused on purpose (a parameter a signature requires, a field left out of a copy).
      "@typescript-eslint/no-unused-vars": ["error", {
        argsIgnorePattern: "^_", varsIgnorePattern: "^_", destructuredArrayIgnorePattern: "^_", caughtErrorsIgnorePattern: "^_",
      }],
      // The texts put a no-break space between a number and its unit; strings are skipped already, templates too here.
      "no-irregular-whitespace": ["error", { skipTemplates: true, skipRegExps: true, skipComments: true }],
    },
  },
  {
    // Tests read what a hook returned through a variable outside the probe component; that is how they look at it.
    files: ["src/**/*.test.{ts,tsx}", "src/**/*_for_test.{ts,tsx}"],
    rules: { "react-hooks/globals": "off" },
  },
);
