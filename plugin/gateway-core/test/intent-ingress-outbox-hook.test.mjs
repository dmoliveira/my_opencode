import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  chmodSync,
  existsSync,
  linkSync,
  lstatSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  realpathSync,
  readdirSync,
  rmSync,
  statSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import GatewayCorePlugin from "../dist/index.js";
import {
  flushGatewayEventAuditExportsForTest,
  resetGatewayEventAuditStateForTest,
} from "../dist/audit/event-audit.js";
import {
  compareIntentIngressEnvelopes,
  createIntentIngressOutboxHook,
  persistIntentIngressEnvelope,
} from "../dist/hooks/intent-ingress-outbox/index.js";

function sha256(value) {
  return createHash("sha256").update(value, "utf8").digest("hex");
}

function framedDigest(parts) {
  const hash = createHash("sha256");
  for (const part of parts) {
    hash.update(String(Buffer.byteLength(part, "utf8")));
    hash.update(":");
    hash.update(part);
    hash.update("\0");
  }
  return hash.digest("hex");
}

function derivedEnvelopeId(projectDigest, sessionId, messageId) {
  return `intent_ingress_${framedDigest([
    "intent-ingress-envelope-v1",
    projectDigest,
    sessionId,
    messageId,
  ]).slice(0, 32)}`;
}

function hookOptions(directory, overrides = {}) {
  return {
    directory,
    enabled: true,
    captureContent: false,
    stateDir: join(directory, "intent-state"),
    maxInputChars: 4096,
    maxContentChars: 256,
    maxEnvelopeBytes: 4096,
    softMaxPendingEntries: 10,
    redactionToken: "[REDACTED]",
    secretPatterns: ["sk-[A-Za-z0-9_-]+"],
    secretLimits: {
      maxDepth: 8,
      maxNodes: 1000,
    },
    ...overrides,
  };
}

function pendingDirectory(stateDir) {
  return join(stateDir, "ingress", "pending");
}

function envelopePaths(stateDir) {
  const pending = pendingDirectory(stateDir);
  if (!existsSync(pending)) {
    return [];
  }
  return readdirSync(pending)
    .filter((name) => name.endsWith(".json"))
    .map((name) => join(pending, name))
    .sort();
}

function readEnvelopes(stateDir) {
  return envelopePaths(stateDir).map((path) =>
    JSON.parse(readFileSync(path, "utf8")),
  );
}

function directEnvelope({
  envelopeId,
  messageId = "message-1",
  observedAt = "2026-08-15T01:00:00.000Z",
  prompt = "ship the change",
} = {}) {
  const projectDigest = "b".repeat(32);
  const sessionId = "session-1";
  return {
    version: 1,
    envelope_id:
      envelopeId ?? derivedEnvelopeId(projectDigest, sessionId, messageId),
    project_digest: projectDigest,
    observed_at: observedAt,
    source: {
      kind: "user",
      session_id: sessionId,
      message_id: messageId,
    },
    content: {
      mode: "metadata",
      char_count: prompt.length,
      sha256: sha256(prompt),
    },
  };
}

function withDirectory(run) {
  const directory = realpathSync(
    mkdtempSync(join(tmpdir(), "gateway-intent-ingress-")),
  );
  return Promise.resolve(run(directory)).finally(() => {
    rmSync(directory, { recursive: true, force: true });
  });
}

async function sendMessage(hook, directory, overrides = {}) {
  const sessionID = overrides.sessionID ?? "session-hook";
  const outputMessageID = overrides.outputMessageID ?? "message-output";
  await hook.event("chat.message", {
    properties: {
      sessionID,
      ...(overrides.messageID ? { messageID: overrides.messageID } : {}),
      prompt: overrides.prompt ?? "Please track this request",
    },
    output: {
      message: {
        id: outputMessageID,
        sessionID,
        role: overrides.role ?? "user",
      },
    },
    directory,
  });
}

test("metadata-only ingress persists a private bounded envelope", async () => {
  await withDirectory(async (directory) => {
    const stateDir = join(directory, "state");
    const prompt = "Please deploy with sk-private-token";
    const hook = createIntentIngressOutboxHook(
      hookOptions(directory, { stateDir }),
    );

    await sendMessage(hook, directory, { prompt });

    const paths = envelopePaths(stateDir);
    assert.equal(paths.length, 1);
    const raw = readFileSync(paths[0], "utf8");
    const envelope = JSON.parse(raw);
    assert.equal(envelope.version, 1);
    assert.match(envelope.envelope_id, /^intent_ingress_[0-9a-f]{32}$/);
    assert.match(envelope.project_digest, /^[0-9a-f]{32}$/);
    assert.equal(envelope.source.kind, "user");
    assert.equal(envelope.source.session_id, "session-hook");
    assert.equal(envelope.source.message_id, "message-output");
    assert.deepEqual(envelope.content, {
      mode: "metadata",
      char_count: prompt.length,
      sha256: sha256(prompt),
    });
    assert.equal(raw.includes(prompt), false);
    assert.equal(raw.includes("sk-private-token"), false);
    assert.equal(statSync(stateDir).mode & 0o777, 0o700);
    assert.equal(statSync(join(stateDir, "ingress")).mode & 0o777, 0o700);
    assert.equal(statSync(pendingDirectory(stateDir)).mode & 0o777, 0o700);
    assert.equal(statSync(paths[0]).mode & 0o777, 0o600);
  });
});

test("intent ingress audit remains local when OTLP export is configured", async () => {
  await withDirectory(async (directory) => {
    const previousAudit = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT;
    const previousOtel = process.env.MY_OPENCODE_OTEL_EXPORT_ENABLED;
    const previousConfigPath = process.env.OPENCODE_CONFIG_PATH;
    const originalFetch = globalThis.fetch;
    const requests = [];
    process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = "1";
    process.env.MY_OPENCODE_OTEL_EXPORT_ENABLED = "1";
    process.env.OPENCODE_CONFIG_PATH = join(directory, "opencode.json");
    writeFileSync(
      process.env.OPENCODE_CONFIG_PATH,
      JSON.stringify({
        observability: {
          enabled: true,
          provider: "otlp",
          otlp_traces_endpoint: "http://localhost:4318/v1/traces",
        },
      }),
      "utf8",
    );
    globalThis.fetch = async (url, init) => {
      requests.push({ url, init });
      return { ok: true, status: 200, text: async () => "ok" };
    };
    resetGatewayEventAuditStateForTest();

    try {
      const hook = createIntentIngressOutboxHook(hookOptions(directory));
      await sendMessage(hook, directory);
      await flushGatewayEventAuditExportsForTest();

      assert.deepEqual(requests, []);
      const audit = readFileSync(
        join(directory, ".opencode", "gateway-events.jsonl"),
        "utf8",
      );
      assert.match(audit, /"reason_code":"intent_ingress_enqueued"/);
    } finally {
      resetGatewayEventAuditStateForTest();
      if (previousAudit === undefined) {
        delete process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT;
      } else {
        process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = previousAudit;
      }
      if (previousOtel === undefined) {
        delete process.env.MY_OPENCODE_OTEL_EXPORT_ENABLED;
      } else {
        process.env.MY_OPENCODE_OTEL_EXPORT_ENABLED = previousOtel;
      }
      if (previousConfigPath === undefined) {
        delete process.env.OPENCODE_CONFIG_PATH;
      } else {
        process.env.OPENCODE_CONFIG_PATH = previousConfigPath;
      }
      globalThis.fetch = originalFetch;
    }
  });
});

test("content capture redacts, normalizes, and truncates the preview", async () => {
  await withDirectory(async (directory) => {
    const stateDir = join(directory, "state");
    const prompt = "Deploy sk-supersecret now\n\twith care";
    const normalized = "Deploy [REDACTED] now with care";
    const hook = createIntentIngressOutboxHook(
      hookOptions(directory, {
        stateDir,
        captureContent: true,
        maxContentChars: 20,
      }),
    );

    await sendMessage(hook, directory, { prompt });

    const [envelope] = readEnvelopes(stateDir);
    assert.deepEqual(envelope.content, {
      mode: "redacted_preview",
      char_count: prompt.length,
      sha256: sha256(prompt),
      preview: normalized.slice(0, 20),
      truncated: true,
      redacted_fields: 1,
    });
    const raw = JSON.stringify(envelope);
    assert.equal(raw.includes("sk-supersecret"), false);
    assert.equal(raw.includes("[REDACTED]"), true);
  });
});

test("disabled, oversized, empty, and non-user messages do not create the spool", async () => {
  await withDirectory(async (directory) => {
    const stateDir = join(directory, "state");
    const disabled = createIntentIngressOutboxHook(
      hookOptions(directory, { enabled: false, stateDir }),
    );
    await sendMessage(disabled, directory);
    assert.equal(existsSync(stateDir), false);

    const enabled = createIntentIngressOutboxHook(
      hookOptions(directory, { maxInputChars: 5, stateDir }),
    );
    await sendMessage(enabled, directory, { prompt: "123456" });
    await sendMessage(enabled, directory, {
      prompt: "",
      outputMessageID: "empty",
    });
    await sendMessage(enabled, directory, {
      prompt: "1234",
      outputMessageID: "assistant",
      role: "assistant",
    });
    assert.equal(existsSync(stateDir), false);
  });
});

test("persistence deduplicates retries and rejects changed content for one identity", async () => {
  await withDirectory(async (directory) => {
    const stateDir = join(directory, "state");
    const options = {
      stateDir,
      maxEnvelopeBytes: 4096,
      softMaxPendingEntries: 10,
    };
    const first = directEnvelope();
    const retry = directEnvelope({ observedAt: "2026-08-15T02:00:00.000Z" });
    const changed = directEnvelope({
      observedAt: "2026-08-15T03:00:00.000Z",
      prompt: "ship a different change",
    });

    assert.equal(
      (await persistIntentIngressEnvelope(first, options)).outcome,
      "enqueued",
    );
    assert.deepEqual(await persistIntentIngressEnvelope(retry, options), {
      outcome: "deduplicated",
    });
    assert.deepEqual(await persistIntentIngressEnvelope(changed, options), {
      outcome: "conflict",
    });
    assert.deepEqual(readEnvelopes(stateDir), [first]);
  });
});

test("persistence rejects a malformed identity-matching existing envelope", async () => {
  await withDirectory(async (directory) => {
    const stateDir = join(directory, "state");
    const options = {
      stateDir,
      maxEnvelopeBytes: 4096,
      softMaxPendingEntries: 10,
    };
    const envelope = directEnvelope();
    assert.equal(
      (await persistIntentIngressEnvelope(envelope, options)).outcome,
      "enqueued",
    );
    const [finalPath] = envelopePaths(stateDir);
    const malformedRaw = JSON.stringify({
      ...envelope,
      content: {
        ...envelope.content,
        char_count: 0,
      },
    });
    writeFileSync(finalPath, malformedRaw, "utf8");
    chmodSync(finalPath, 0o600);
    const stagePath = join(
      pendingDirectory(stateDir),
      `.intent-ingress-stage-${envelope.envelope_id}-invalid`,
    );
    linkSync(finalPath, stagePath);
    assert.equal(lstatSync(finalPath).nlink, 2);

    assert.deepEqual(await persistIntentIngressEnvelope(envelope, options), {
      outcome: "conflict",
    });
    assert.equal(readFileSync(finalPath, "utf8"), malformedRaw);
    assert.deepEqual(envelopePaths(stateDir), [finalPath]);
    assert.equal(existsSync(stagePath), true);
    assert.equal(lstatSync(finalPath).nlink, 2);
  });
});

test("a recreated hook retains pending state and deduplicates the same message", async () => {
  await withDirectory(async (directory) => {
    const stateDir = join(directory, "state");
    const options = hookOptions(directory, { stateDir });
    await sendMessage(createIntentIngressOutboxHook(options), directory, {
      messageID: "message-restart",
    });
    await sendMessage(createIntentIngressOutboxHook(options), directory, {
      messageID: "message-restart",
    });
    assert.equal(envelopePaths(stateDir).length, 1);

    await sendMessage(createIntentIngressOutboxHook(options), directory, {
      messageID: "message-after-restart",
    });
    assert.equal(envelopePaths(stateDir).length, 2);
  });
});

test("serialized envelope byte overflow fails open without publishing a file", async () => {
  await withDirectory(async (directory) => {
    const stateDir = join(directory, "state");
    const hook = createIntentIngressOutboxHook(
      hookOptions(directory, {
        stateDir,
        captureContent: true,
        maxContentChars: 1000,
        maxEnvelopeBytes: 512,
      }),
    );

    await sendMessage(hook, directory, { prompt: "x".repeat(1000) });

    assert.deepEqual(envelopePaths(stateDir), []);
    assert.deepEqual(readdirSync(pendingDirectory(stateDir)), []);
  });
});

test("retry repairs a published envelope left with its staging hard link", async () => {
  await withDirectory(async (directory) => {
    const stateDir = join(directory, "state");
    const options = {
      stateDir,
      maxEnvelopeBytes: 4096,
      softMaxPendingEntries: 10,
    };
    const envelope = directEnvelope();
    await persistIntentIngressEnvelope(envelope, options);
    const [finalPath] = envelopePaths(stateDir);
    const stagePath = join(
      pendingDirectory(stateDir),
      `.intent-ingress-stage-${envelope.envelope_id}-crash`,
    );
    linkSync(finalPath, stagePath);
    assert.equal(lstatSync(finalPath).nlink, 2);

    assert.deepEqual(
      await Promise.all([
        persistIntentIngressEnvelope(envelope, options),
        persistIntentIngressEnvelope(envelope, options),
        persistIntentIngressEnvelope(envelope, options),
      ]),
      [
        { outcome: "deduplicated" },
        { outcome: "deduplicated" },
        { outcome: "deduplicated" },
      ],
    );
    assert.equal(existsSync(stagePath), false);
    assert.equal(lstatSync(finalPath).nlink, 1);
  });
});

test("malformed external envelope identity is rejected before spool creation", async () => {
  await withDirectory(async (directory) => {
    const stateDir = join(directory, "state");
    const envelope = directEnvelope({ envelopeId: "../../escape" });

    await assert.rejects(
      persistIntentIngressEnvelope(envelope, {
        stateDir,
        maxEnvelopeBytes: 4096,
        softMaxPendingEntries: 10,
      }),
      /invalid intent ingress envelope/,
    );
    assert.equal(existsSync(stateDir), false);
    assert.equal(existsSync(join(directory, "escape.json")), false);
  });
});

test("well-formed envelope id must match its project and source identity", async () => {
  await withDirectory(async (directory) => {
    const stateDir = join(directory, "state");
    const envelope = directEnvelope({
      envelopeId: "intent_ingress_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    });

    await assert.rejects(
      persistIntentIngressEnvelope(envelope, {
        stateDir,
        maxEnvelopeBytes: 4096,
        softMaxPendingEntries: 10,
      }),
      /identity mismatch/,
    );
    assert.equal(existsSync(stateDir), false);
  });
});

test("soft capacity drops new identities without disturbing pending envelopes", async () => {
  await withDirectory(async (directory) => {
    const stateDir = join(directory, "state");
    const options = {
      stateDir,
      maxEnvelopeBytes: 4096,
      softMaxPendingEntries: 1,
    };
    const first = directEnvelope();
    const second = directEnvelope({
      messageId: "message-2",
    });

    assert.equal(
      (await persistIntentIngressEnvelope(first, options)).outcome,
      "enqueued",
    );
    assert.deepEqual(await persistIntentIngressEnvelope(second, options), {
      outcome: "overflow",
    });
    assert.deepEqual(readEnvelopes(stateDir), [first]);
  });
});

test("soft capacity ignores unpublished stages and non-file envelope names", async () => {
  await withDirectory(async (directory) => {
    const stateDir = join(directory, "state");
    const pending = pendingDirectory(stateDir);
    mkdirSync(pending, { recursive: true, mode: 0o700 });
    for (const path of [stateDir, join(stateDir, "ingress"), pending]) {
      chmodSync(path, 0o700);
    }
    const stageEnvelope = directEnvelope({ messageId: "message-stage" });
    const stagePath = join(
      pending,
      `.intent-ingress-stage-${stageEnvelope.envelope_id}-crash`,
    );
    writeFileSync(stagePath, "crash-left stage", { mode: 0o600 });
    chmodSync(stagePath, 0o600);
    const directoryName = join(
      pending,
      `intent_ingress_${"a".repeat(32)}.json`,
    );
    mkdirSync(directoryName, { mode: 0o700 });
    const symlinkTarget = join(directory, "symlink-target");
    writeFileSync(symlinkTarget, "not an envelope", { mode: 0o600 });
    symlinkSync(
      symlinkTarget,
      join(pending, `intent_ingress_${"b".repeat(32)}.json`),
    );
    const envelope = directEnvelope({ messageId: "message-after-stage" });

    assert.equal(
      (await persistIntentIngressEnvelope(envelope, {
        stateDir,
        maxEnvelopeBytes: 4096,
        softMaxPendingEntries: 1,
      })).outcome,
      "enqueued",
    );
    assert.deepEqual(
      JSON.parse(
        readFileSync(join(pending, `${envelope.envelope_id}.json`), "utf8"),
      ),
      envelope,
    );
    assert.equal(existsSync(stagePath), true);
    assert.equal(lstatSync(directoryName).isDirectory(), true);
    assert.equal(
      lstatSync(join(pending, `intent_ingress_${"b".repeat(32)}.json`)).isSymbolicLink(),
      true,
    );
  });
});

test("unsafe pending symlinks fail open without writing through the link", async () => {
  await withDirectory(async (directory) => {
    const stateDir = join(directory, "state");
    const ingress = join(stateDir, "ingress");
    const target = join(directory, "target");
    mkdirSync(ingress, { recursive: true, mode: 0o700 });
    chmodSync(stateDir, 0o700);
    chmodSync(ingress, 0o700);
    mkdirSync(target, { mode: 0o700 });
    symlinkSync(target, pendingDirectory(stateDir), "dir");
    const hook = createIntentIngressOutboxHook(
      hookOptions(directory, { stateDir }),
    );

    await sendMessage(hook, directory);

    assert.deepEqual(readdirSync(target), []);
    assert.equal(lstatSync(pendingDirectory(stateDir)).isSymbolicLink(), true);
  });
});

test("intermediate state-directory symlinks are rejected before creating descendants", async () => {
  await withDirectory(async (directory) => {
    const parent = join(directory, "state-parent");
    const target = join(directory, "target");
    mkdirSync(parent, { mode: 0o700 });
    mkdirSync(target, { mode: 0o700 });
    symlinkSync(target, join(parent, "linked"), "dir");
    const hook = createIntentIngressOutboxHook(
      hookOptions(directory, {
        stateDir: join(parent, "linked", "state"),
      }),
    );

    await sendMessage(hook, directory);

    assert.deepEqual(readdirSync(target), []);
  });
});

test("unsafe writable state ancestors are rejected before creating descendants", async () => {
  await withDirectory(async (directory) => {
    const unsafeParent = join(directory, "unsafe-parent");
    mkdirSync(unsafeParent, { mode: 0o700 });
    chmodSync(unsafeParent, 0o777);
    const hook = createIntentIngressOutboxHook(
      hookOptions(directory, {
        stateDir: join(unsafeParent, "state"),
      }),
    );

    await sendMessage(hook, directory);

    assert.deepEqual(readdirSync(unsafeParent), []);
  });
});

test("replay ordering is deterministic by observation time then envelope id", () => {
  const late = directEnvelope({
    envelopeId: "intent_ingress_dddddddddddddddddddddddddddddddd",
    observedAt: "2026-08-15T03:00:00.000Z",
  });
  const sameTimeSecond = directEnvelope({
    envelopeId: "intent_ingress_cccccccccccccccccccccccccccccccc",
    messageId: "message-2",
    observedAt: "2026-08-15T02:00:00.000Z",
  });
  const sameTimeFirst = directEnvelope({
    envelopeId: "intent_ingress_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    messageId: "message-3",
    observedAt: "2026-08-15T02:00:00.000Z",
  });

  assert.deepEqual(
    [late, sameTimeSecond, sameTimeFirst]
      .sort(compareIntentIngressEnvelopes)
      .map((item) => item.envelope_id),
    [sameTimeFirst.envelope_id, sameTimeSecond.envelope_id, late.envelope_id],
  );
});

test("gateway registration uses input message identity and project-relative state", async () => {
  await withDirectory(async (directory) => {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["intent-ingress-outbox"],
          disabled: [],
        },
        intentIngressOutbox: {
          enabled: true,
          captureContent: false,
          stateDir: ".runtime/intent-test",
          maxInputChars: 4096,
          maxContentChars: 256,
          maxEnvelopeBytes: 4096,
          softMaxPendingEntries: 10,
        },
      },
    });

    await plugin["chat.message"](
      { sessionID: "session-plugin", messageID: "message-input" },
      {
        message: {
          id: "message-output",
          sessionID: "session-plugin",
          role: "user",
        },
        parts: [{ type: "text", text: "Create a durable task" }],
      },
    );

    const [envelope] = readEnvelopes(
      join(directory, ".runtime", "intent-test"),
    );
    assert.equal(envelope.source.message_id, "message-input");
    assert.equal(envelope.source.session_id, "session-plugin");
    assert.equal(envelope.content.mode, "metadata");
    assert.equal(envelope.content.sha256, sha256("Create a durable task"));
  });
});

test("legacy messageId cannot override the official output message identity", async () => {
  await withDirectory(async (directory) => {
    const stateDir = join(directory, "state");
    const hook = createIntentIngressOutboxHook(
      hookOptions(directory, { stateDir }),
    );
    await hook.event("chat.message", {
      properties: {
        sessionID: "session-official-id",
        messageId: "legacy-alias",
        prompt: "Track the official message",
      },
      output: {
        message: {
          id: "official-output-id",
          sessionID: "session-official-id",
          role: "user",
        },
      },
      directory,
    });

    const [envelope] = readEnvelopes(stateDir);
    assert.equal(envelope.source.message_id, "official-output-id");
  });
});
