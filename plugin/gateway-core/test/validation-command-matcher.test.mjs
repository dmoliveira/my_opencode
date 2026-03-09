import assert from "node:assert/strict"
import test from "node:test"

import { classifyValidationCommand, isValidationCommand } from "../dist/hooks/shared/validation-command-matcher.js"

test("validation-command-matcher classifies repo-native and wrapped test commands", () => {
  assert.deepEqual(classifyValidationCommand("python3 scripts/selftest.py"), ["test"])
  assert.deepEqual(classifyValidationCommand("make install-test"), ["test"])
  assert.deepEqual(classifyValidationCommand("uv run pytest tests/test_api.py"), ["test"])
  assert.deepEqual(classifyValidationCommand("npm exec vitest run"), ["test"])
})

test("validation-command-matcher covers run and prefix package-manager forms", () => {
  assert.deepEqual(classifyValidationCommand("pnpm run typecheck"), ["typecheck"])
  assert.deepEqual(classifyValidationCommand("yarn run build"), ["build"])
  assert.deepEqual(classifyValidationCommand("npm --prefix plugin/gateway-core run build"), ["build"])
})

test("validation-command-matcher exposes validation truthiness", () => {
  assert.equal(isValidationCommand("make validate"), true)
  assert.equal(isValidationCommand("git status --short"), false)
})

test("validation-command-matcher ignores bare filenames that mention tool names", () => {
  assert.deepEqual(classifyValidationCommand("cat pytest.ini"), [])
  assert.deepEqual(classifyValidationCommand("ls eslint.config.js"), [])
  assert.equal(isValidationCommand("cat docs/jest-notes.md"), false)
})
