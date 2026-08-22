/** Shared ESLint rules for every TypeScript package in the monorepo. */
export const baseRules = {
  "no-console": ["warn", { allow: ["warn", "error"] }],
  "prefer-const": "error",
  eqeqeq: ["error", "smart"],
  "no-restricted-syntax": [
    "error",
    {
      // Signed URLs and image data must never reach the console or telemetry.
      selector: "CallExpression[callee.object.name='console'][callee.property.name='log']",
      message: "Use the app logger; console.log risks leaking signed URLs.",
    },
  ],
};

export default baseRules;
