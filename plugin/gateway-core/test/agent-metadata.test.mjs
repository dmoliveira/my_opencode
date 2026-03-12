import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { loadAgentMetadata } from "../dist/hooks/shared/agent-metadata.js";

test("agent metadata discovers all spec json files dynamically", () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-agent-metadata-"));
  try {
    const specsDir = join(directory, "agent", "specs");
    mkdirSync(specsDir, { recursive: true });
    writeFileSync(
      join(specsDir, "custom-scout.json"),
      JSON.stringify({
        name: "custom-scout",
        metadata: {
          default_category: "quick",
          triggers: ["scan custom paths"],
        },
        tools: { read: true },
      }),
      "utf-8",
    );
    const metadata = loadAgentMetadata(directory);
    assert.equal(metadata.get("custom-scout")?.default_category, "quick");
    assert.deepEqual(metadata.get("custom-scout")?.triggers, [
      "scan custom paths",
    ]);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});
