import assert from "node:assert/strict"
import test from "node:test"

import {
  classifyValidationCommand,
  isValidationCommand,
  validationCommandDirectory,
} from "../dist/hooks/shared/validation-command-matcher.js"

test("validation-command-matcher classifies repo-native and wrapped test commands", () => {
  assert.deepEqual(classifyValidationCommand("python3 scripts/selftest.py"), ["test"])
  assert.deepEqual(classifyValidationCommand("make install-test"), ["test"])
  assert.deepEqual(classifyValidationCommand("uv run pytest tests/test_api.py"), ["test"])
  assert.deepEqual(classifyValidationCommand("npm exec vitest run"), ["test"])
  assert.deepEqual(classifyValidationCommand("./scripts/ci-check tests/api smoke"), ["test"])
})

test("validation-command-matcher covers run and prefix package-manager forms", () => {
  assert.deepEqual(classifyValidationCommand("pnpm run typecheck"), ["typecheck"])
  assert.deepEqual(classifyValidationCommand("yarn run build"), ["build"])
  assert.deepEqual(classifyValidationCommand("npm --prefix plugin/gateway-core run build"), ["build"])
})

test("validation-command-matcher exposes validation truthiness", () => {
  assert.equal(isValidationCommand("make validate"), true)
  assert.deepEqual(classifyValidationCommand("make validate"), ["lint", "test"])
  assert.deepEqual(classifyValidationCommand("uvx ruff check ."), ["lint"])
  assert.deepEqual(classifyValidationCommand("uv run ruff check src"), ["lint"])
  assert.equal(isValidationCommand("git status --short"), false)
})

test("validation-command-matcher ignores bare filenames that mention tool names", () => {
  assert.deepEqual(classifyValidationCommand("cat pytest.ini"), [])
  assert.deepEqual(classifyValidationCommand("ls eslint.config.js"), [])
  assert.equal(isValidationCommand("cat docs/jest-notes.md"), false)
})

test("validation-command-matcher rejects shell composition and swallowed failures", () => {
  for (const command of [
    "npm test || true",
    "npm test && echo done",
    "npm test; true",
    "npm test | tee test.log",
    "npm test > test.log",
    "npm test 2>&1",
    "npm test &",
    "cd project && npm test",
    "$(printf npm) test",
    "`printf npm` test",
  ]) {
    assert.deepEqual(classifyValidationCommand(command), [], command)
  }
})

test("validation-command-matcher accepts quoted metacharacters and environment prefixes", () => {
  assert.deepEqual(classifyValidationCommand("CI=true npm test -- --name='a|b'"), ["test"])
  assert.deepEqual(
    classifyValidationCommand("OPENCODE_SESSION_ID='session-1' CI=true make validate"),
    ["lint", "test"],
  )
})

test("validation-command-matcher binds only standalone absolute make -C validation to its target", () => {
  assert.deepEqual(classifyValidationCommand('make -C "/tmp/target worktree" validate'), ["lint", "test"])
  assert.equal(
    validationCommandDirectory('CI=true make -C "/tmp/target worktree" validate', "/tmp/session-root"),
    "/tmp/target worktree",
  )
  assert.equal(validationCommandDirectory("make -C relative validate", "/tmp/session-root"), "/tmp/session-root")
  assert.equal(validationCommandDirectory("make -C /tmp/target validate && true", "/tmp/session-root"), "/tmp/session-root")
})
