// Hardcoding rules (§2.1): the frontend is a generic renderer. No magic numbers, no raw strings in JSX.
import js from "@eslint/js";
import react from "eslint-plugin-react";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "node_modules", "src/api/schema.d.ts"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["src/**/*.{ts,tsx}"],
    languageOptions: { globals: globals.browser },
    plugins: { react, "react-hooks": reactHooks },
    settings: { react: { version: "18" } },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "no-magic-numbers": "off",
      "@typescript-eslint/no-magic-numbers": [
        "error",
        { ignore: [0, 1, -1], ignoreArrayIndexes: true, ignoreEnums: true, ignoreTypeIndexes: true, ignoreReadonlyClassProperties: true },
      ],
      "react/jsx-no-literals": ["error", { noStrings: true, ignoreProps: true, noAttributeStrings: false }],
      "no-restricted-syntax": [
        "error",
        { selector: "Literal[value=/#[0-9a-fA-F]{3,8}\\b/]", message: "Colours come from config/theme.yaml via CSS variables." },
        { selector: "Literal[value=/^https?:/]", message: "URLs come from VITE_API_BASE_URL or the bootstrap." },
      ],
    },
  },
  {
    // Unit tests may use literal fixtures.
    files: ["src/**/*.test.{ts,tsx}"],
    rules: { "@typescript-eslint/no-magic-numbers": "off", "react/jsx-no-literals": "off" },
  },
);
