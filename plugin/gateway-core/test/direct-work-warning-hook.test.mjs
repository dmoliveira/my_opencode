import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import GatewayCorePlugin from "../dist/index.js";
import { createDirectWorkWarningHook } from "../dist/hooks/direct-work-warning/index.js";
import { registerDelegationChildSession } from "../dist/hooks/shared/delegation-child-session.js";

test("direct-work-warning appends reminder for primary-session write-like tools", async () => {
  const hook = createDirectWorkWarningHook({
    directory: "/tmp/project",
    enabled: true,
    blockRepeatedEdits: false,
    allowPaths: [],
  });
  const payload = {
    input: { tool: "edit", sessionID: "ses_parent1" },
    output: { args: { filePath: "src/app.ts" } },
  };

  await hook.event("tool.execute.before", payload);

  assert.match(String(payload.output.message), /direct-work-warning/);
  assert.match(String(payload.output.message), /src\/app.ts/);
});

test("direct-work-warning skips delegated child sessions", async () => {
  registerDelegationChildSession({
    properties: {
      info: {
        id: "ses_child1",
        parentID: "ses_parent1",
        title: "[DELEGATION TRACE abc123]",
      },
    },
  });
  const hook = createDirectWorkWarningHook({
    directory: "/tmp/project",
    enabled: true,
    blockRepeatedEdits: false,
    allowPaths: [],
  });
  const payload = {
    input: { tool: "write", sessionID: "ses_child1" },
    output: { args: { filePath: "src/child.ts" } },
  };

  await hook.event("tool.execute.before", payload);

  assert.equal(payload.output.message, undefined);
});

test("direct-work-warning ignores non write-like tools", async () => {
  const hook = createDirectWorkWarningHook({
    directory: "/tmp/project",
    enabled: true,
    blockRepeatedEdits: false,
    allowPaths: [],
  });
  const payload = {
    input: { tool: "read", sessionID: "ses_parent2" },
    output: { args: { filePath: "src/app.ts" } },
  };

  await hook.event("tool.execute.before", payload);

  assert.equal(payload.output.message, undefined);
});

test("direct-work-warning blocks repeated primary-session direct edits", async () => {
  const hook = createDirectWorkWarningHook({
    directory: "/tmp/project",
    enabled: true,
    blockRepeatedEdits: true,
    allowPaths: [],
  });
  const firstPayload = {
    input: { tool: "edit", sessionID: "ses_repeat1" },
    output: { args: { filePath: "src/one.ts" } },
  };
  await hook.event("tool.execute.before", firstPayload);

  await assert.rejects(
    hook.event("tool.execute.before", {
      input: { tool: "write", sessionID: "ses_repeat1" },
      output: { args: { filePath: "src/two.ts" } },
    }),
    /direct-work-discipline/i,
  );
});

test("direct-work-warning resets repeated-edit block after session deletion", async () => {
  const hook = createDirectWorkWarningHook({
    directory: "/tmp/project",
    enabled: true,
    blockRepeatedEdits: true,
    allowPaths: [],
  });
  await hook.event("tool.execute.before", {
    input: { tool: "edit", sessionID: "ses_reset1" },
    output: { args: { filePath: "src/one.ts" } },
  });
  await hook.event("session.deleted", {
    properties: { info: { id: "ses_reset1" } },
  });

  const payload = {
    input: { tool: "write", sessionID: "ses_reset1" },
    output: { args: { filePath: "src/two.ts" } },
  };
  await hook.event("tool.execute.before", payload);

  assert.match(String(payload.output.message), /direct-work-warning/);
});

test("direct-work-warning skips configured documentation paths", async () => {
  const hook = createDirectWorkWarningHook({
    directory: "/tmp/project",
    enabled: true,
    blockRepeatedEdits: true,
    allowPaths: ["docs/**/*.md", "**/README*.md", "**/AGENTS.md"],
  });

  const nestedPlanDoc = {
    input: { tool: "edit", sessionID: "ses_docs1" },
    output: { args: { filePath: "docs/plan/notes.md" } },
  };
  await hook.event("tool.execute.before", nestedPlanDoc);
  assert.equal(nestedPlanDoc.output.message, undefined);

  const rootDoc = {
    input: { tool: "edit", sessionID: "ses_docs2" },
    output: { args: { filePath: "docs/notes.md" } },
  };
  await hook.event("tool.execute.before", rootDoc);
  assert.equal(rootDoc.output.message, undefined);

  const rootReadme = {
    input: { tool: "edit", sessionID: "ses_docs3" },
    output: { args: { filePath: "README.md" } },
  };
  await hook.event("tool.execute.before", rootReadme);
  assert.equal(rootReadme.output.message, undefined);

  const rootAgents = {
    input: { tool: "edit", sessionID: "ses_docs4" },
    output: { args: { filePath: "AGENTS.md" } },
  };
  await hook.event("tool.execute.before", rootAgents);
  assert.equal(rootAgents.output.message, undefined);

  const absoluteDoc = {
    input: { tool: "edit", sessionID: "ses_docs5" },
    output: { args: { filePath: "/tmp/project/docs/reference.md" } },
  };
  await hook.event("tool.execute.before", absoluteDoc);
  assert.equal(absoluteDoc.output.message, undefined);

  const patchPayload = {
    input: { tool: "apply_patch", sessionID: "ses_docs6" },
    output: {
      args: {
        patchText:
          "*** Begin Patch\n*** Update File: docs/guide.md\n@@\n-old\n+new\n*** End Patch",
      },
    },
  };
  await hook.event("tool.execute.before", patchPayload);
  assert.equal(patchPayload.output.message, undefined);

  const multieditPayload = {
    input: { tool: "multiedit", sessionID: "ses_docs7" },
    output: { args: { filePath: "docs/guide.md" } },
  };
  await hook.event("tool.execute.before", multieditPayload);
  assert.equal(multieditPayload.output.message, undefined);
});

test("direct-work-warning is active in default gateway hook order", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-direct-work-warning-"));
  try {
    const plugin = GatewayCorePlugin({ directory, config: {} });
    const output = { args: { filePath: "src/default.ts" } };

    await plugin["tool.execute.before"](
      { tool: "edit", sessionID: "ses_parent_default" },
      output,
    );

    assert.match(String(output.message), /direct-work-warning/);
    const second = { args: { filePath: "src/default-2.ts" } };
    await plugin["tool.execute.before"](
      { tool: "write", sessionID: "ses_parent_default" },
      second,
    );
    assert.match(String(second.message), /direct-work-warning/);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});
