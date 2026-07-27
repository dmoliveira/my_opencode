import {
  closeSync,
  constants,
  fchmodSync,
  fstatSync,
  fsyncSync,
  lstatSync,
  mkdirSync,
  openSync,
  realpathSync,
  writeSync,
} from "node:fs"
import type { Stats } from "node:fs"
import { join } from "node:path"

import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import type { GatewayHook } from "../registry.js"
import type { LlmDecisionRuntime } from "../shared/llm-decision-runtime.js"
import {
  buildCompactDecisionCacheKey,
  writeDecisionComparisonAudit,
} from "../shared/llm-decision-runtime.js"
import { readCombinedToolAfterOutputText } from "../shared/tool-after-output.js"

interface ToolAfterPayload {
  input?: { tool?: string; sessionID?: string; sessionId?: string }
  output?: { output?: unknown }
  directory?: string
}

interface OpenLedgerFile {
  descriptor: number
  created: boolean
}

const DONE_PROOF_MARKER = "[done-proof-enforcer] Completion token deferred"
const PENDING_VALIDATION_MARKER = "<promise>PENDING_VALIDATION</promise>"
const MISTAKE_LEDGER_RELATIVE_PATH = ".opencode/mistake-ledger.jsonl"

function resolveSessionId(payload: ToolAfterPayload): string {
  const value = payload.input?.sessionID ?? payload.input?.sessionId ?? ""
  return typeof value === "string" ? value.trim() : ""
}

function currentUid(): number {
  if (typeof process.getuid !== "function") {
    throw new Error("mistake ledger unsupported: current-user ownership checks unavailable")
  }
  return process.getuid()
}

function noFollowFlag(): number {
  const flag = constants.O_NOFOLLOW as number | undefined
  if (typeof flag !== "number" || flag === 0) {
    throw new Error("mistake ledger unsupported: no-follow file opens unavailable")
  }
  return flag
}

function assertCurrentUserOwner(state: Stats, label: string): void {
  if (state.uid !== currentUid()) {
    throw new Error(`unsafe mistake ledger ${label}: ownership mismatch`)
  }
}

function assertSafeDirectoryState(state: Stats, label: string): void {
  if (!state.isDirectory() || state.isSymbolicLink()) {
    throw new Error(`unsafe mistake ledger ${label}: expected a real directory`)
  }
  assertCurrentUserOwner(state, label)
  if (state.mode & 0o022) {
    throw new Error(`unsafe mistake ledger ${label}: directory is group/world writable`)
  }
}

function ensureSafeLedgerDirectory(rootDirectory: string): string {
  assertSafeDirectoryState(lstatSync(rootDirectory), "workspace")
  const directory = join(rootDirectory, ".opencode")
  let state: Stats
  try {
    state = lstatSync(directory)
  } catch (error) {
    if ((error as { code?: string }).code !== "ENOENT") {
      throw error
    }
    mkdirSync(directory, { mode: 0o700 })
    state = lstatSync(directory)
  }
  assertSafeDirectoryState(state, "directory")
  return directory
}

function safeExistingLedgerState(path: string): Stats | null {
  let state: Stats
  try {
    state = lstatSync(path)
  } catch (error) {
    if ((error as { code?: string }).code === "ENOENT") {
      return null
    }
    throw error
  }
  if (!state.isFile() || state.isSymbolicLink() || state.nlink !== 1) {
    throw new Error("unsafe mistake ledger file: expected a regular single-link file")
  }
  assertCurrentUserOwner(state, "file")
  return state
}

function openSafeLedger(path: string): OpenLedgerFile {
  const expected = safeExistingLedgerState(path)
  const baseFlags = constants.O_WRONLY | constants.O_APPEND | noFollowFlag()
  let descriptor: number
  let created = false
  try {
    descriptor = openSync(path, baseFlags)
  } catch (error) {
    if ((error as { code?: string }).code !== "ENOENT") {
      throw error
    }
    descriptor = openSync(path, baseFlags | constants.O_CREAT | constants.O_EXCL, 0o600)
    created = true
  }
  try {
    const opened = fstatSync(descriptor)
    if (!opened.isFile() || opened.nlink !== 1) {
      throw new Error("unsafe opened mistake ledger file")
    }
    assertCurrentUserOwner(opened, "file")
    if (expected && (opened.dev !== expected.dev || opened.ino !== expected.ino)) {
      throw new Error("unsafe mistake ledger file: target changed during validation")
    }
    fchmodSync(descriptor, 0o600)
    return { descriptor, created }
  } catch (error) {
    closeSync(descriptor)
    throw error
  }
}

function appendLedgerEntry(path: string, entry: Record<string, string>): void {
  const opened = openSafeLedger(path)
  try {
    writeSync(opened.descriptor, `${JSON.stringify(entry)}
`, null, "utf-8")
    fsyncSync(opened.descriptor)
  } finally {
    closeSync(opened.descriptor)
  }
}

function resolveLedgerStorage(options: { directory: string; path: string }): {
  directory: string
  path: string
} {
  if (options.path !== MISTAKE_LEDGER_RELATIVE_PATH) {
    throw new Error(`mistake ledger path must be ${MISTAKE_LEDGER_RELATIVE_PATH}`)
  }
  currentUid()
  noFollowFlag()
  const directory = realpathSync(options.directory)
  const ledgerDirectory = ensureSafeLedgerDirectory(directory)
  return { directory, path: join(ledgerDirectory, "mistake-ledger.jsonl") }
}

export function createMistakeLedgerHook(options: {
  directory: string
  enabled: boolean
  path: string
  decisionRuntime?: LlmDecisionRuntime
}): GatewayHook {
  const storage = options.enabled ? resolveLedgerStorage(options) : null
  return {
    id: "mistake-ledger",
    priority: 331,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled || !storage || type !== "tool.execute.after") {
        return
      }
      const eventPayload = (payload ?? {}) as ToolAfterPayload
      const text = readCombinedToolAfterOutputText(eventPayload.output?.output)
      if (!text) {
        return
      }
      const directory = storage.directory
      const sessionId = resolveSessionId(eventPayload)
      let shouldRecord = text.includes(DONE_PROOF_MARKER)
      if (!shouldRecord && text.includes(PENDING_VALIDATION_MARKER) && sessionId && options.decisionRuntime) {
        const decision = await options.decisionRuntime.decide({
          hookId: "mistake-ledger",
          sessionId,
          templateId: "mistake-ledger-deferral-v1",
          instruction:
            "Does this output indicate completion was deferred because validation or done-proof evidence is still missing and should be recorded as completion_without_validation? Y=yes, N=no.",
          context: `output=${text.trim() || "(empty)"}`,
          allowedChars: ["Y", "N"],
          decisionMeaning: {
            Y: "record_completion_without_validation",
            N: "ignore",
          },
          cacheKey: buildCompactDecisionCacheKey({
            prefix: "mistake-ledger",
            text,
          }),
        })
        if (decision.accepted) {
          writeDecisionComparisonAudit({
            directory,
            hookId: "mistake-ledger",
            sessionId,
            mode: options.decisionRuntime.config.mode,
            deterministicMeaning: "ignore",
            aiMeaning: decision.meaning || "ignore",
            deterministicValue: "false",
            aiValue: decision.char,
          })
          writeGatewayEventAudit(directory, {
            hook: "mistake-ledger",
            stage: "state",
            reason_code: "llm_mistake_ledger_decision_recorded",
            session_id: sessionId,
            llm_decision_char: decision.char,
            llm_decision_meaning: decision.meaning,
            llm_decision_mode: options.decisionRuntime.config.mode,
          })
          if (options.decisionRuntime.config.mode === "shadow" && decision.char === "Y") {
            writeGatewayEventAudit(directory, {
              hook: "mistake-ledger",
              stage: "state",
              reason_code: "llm_mistake_ledger_shadow_deferred",
              session_id: sessionId,
              llm_decision_char: decision.char,
              llm_decision_meaning: decision.meaning,
              llm_decision_mode: options.decisionRuntime.config.mode,
            })
          } else {
            shouldRecord = decision.char === "Y"
          }
        }
      }
      if (!shouldRecord) {
        return
      }
      appendLedgerEntry(storage.path, {
        ts: new Date().toISOString(),
        category: "completion_without_validation",
        sourceHook: "done-proof-enforcer",
      })
      writeGatewayEventAudit(directory, {
        hook: "mistake-ledger",
        stage: "state",
        reason_code: "mistake_ledger_entry_recorded",
        session_id: sessionId,
        evidence: "completion_without_validation",
      })
    },
  }
}
