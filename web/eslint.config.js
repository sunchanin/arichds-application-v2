import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import globals from "globals";
import tseslint from "typescript-eslint";

/**
 * Flat ESLint config for the ARICHDS SPA.
 *
 * `pnpm lint` is half of the web side of the per-module gate in CLAUDE.md
 * ("เทสผ่าน" = `pnpm lint` + `pnpm build`), so this config has to stay
 * runnable and clean — a documented gate that cannot be run is worse than no
 * gate at all.
 *
 * The rules-of-hooks check is the one that earns its keep here: the Monitor
 * page drives a refresh timer from `useEffect` + `useCallback`, and a
 * mis-declared dependency there shows up as a stale or runaway poll loop.
 */
export default tseslint.config(
  { ignores: ["dist", "node_modules"] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
      // Unused args are fine when prefixed with _ (event handlers, catch params).
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
    },
  },
);
