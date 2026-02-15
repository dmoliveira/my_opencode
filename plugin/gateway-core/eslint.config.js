import tseslint from "@typescript-eslint/eslint-plugin"
import parser from "@typescript-eslint/parser"

export default [
  {
    files: ["src/**/*.ts"],
    languageOptions: {
      parser,
      parserOptions: {
        sourceType: "module",
        ecmaVersion: "latest",
        project: "./tsconfig.json",
        tsconfigRootDir: import.meta.dirname,
      },
    },
    plugins: {
      "@typescript-eslint": tseslint,
    },
    rules: {
      "@typescript-eslint/explicit-function-return-type": "error",
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/no-floating-promises": "error",
      "@typescript-eslint/consistent-type-imports": "error",
    },
  },
]
