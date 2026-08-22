import next from "eslint-config-next";

import { baseRules } from "@artrestore/config/eslint.base.mjs";

// eslint-config-next exports a flat-config array.
const config = [
  {
    ignores: [".next/**", "node_modules/**", "playwright-report/**", "test-results/**"],
  },
  ...next,
  {
    files: ["**/*.{ts,tsx}"],
    rules: baseRules,
  },
  {
    // Tests and Playwright specs talk to the console and to globals directly.
    files: ["tests/**/*.{ts,tsx}", "e2e/**/*.ts"],
    rules: { "no-console": "off" },
  },
];

export default config;
