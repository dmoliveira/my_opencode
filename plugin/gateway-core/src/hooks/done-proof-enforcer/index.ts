import { markerCategory, missingValidationMarkers } from "../validation-evidence-ledger/evidence.js"
import type { GatewayHook } from "../registry.js"
import type { LlmDecisionRuntime } from "../shared/llm-decision-runtime.js"
import { writeGatewayEventAudit } from "../../audit/event-audit.js"

interface ToolAfterPayload {
  input?: { tool?: string; sessionID?: string; sessionId?: string }
  output?: { output?: unknown }
}

function buildMarkerInstruction(marker: string): string {
  return `Does this completion text include evidence-equivalent wording for '${marker}'? Y=yes, N=no.`
}

function buildMarkerContext(text: string): string {
  return `completion=${text.trim() || "(empty)"}`
}

// Creates done proof enforcer that requires evidence markers near completion token.
export function createDoneProofEnforcerHook(options: {
  enabled: boolean
  requiredMarkers: string[]
  requireLedgerEvidence: boolean
  allowTextFallback: boolean
  directory?: string
  decisionRuntime?: LlmDecisionRuntime
}): GatewayHook {
  const markers = options.requiredMarkers.map((item) => item.trim().toLowerCase()).filter(Boolean)
  return {
    id: "done-proof-enforcer",
    priority: 410,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled || type !== "tool.execute.after") {
        return
      }
      const eventPayload = (payload ?? {}) as ToolAfterPayload
      if (typeof eventPayload.output?.output !== "string") {
        return
      }
      const sessionId = String(eventPayload.input?.sessionID ?? eventPayload.input?.sessionId ?? "").trim()
      const text = eventPayload.output.output
      if (!/<promise>\s*DONE\s*<\/promise>/i.test(text)) {
        return
      }
      const lower = text.toLowerCase()
      const missingFromLedger =
        options.requireLedgerEvidence && sessionId
          ? missingValidationMarkers(sessionId, markers)
          : []
      const missingMarkers: string[] = []
      for (const marker of markers) {
        const category = markerCategory(marker)
        if (category) {
          if (options.requireLedgerEvidence && sessionId && missingFromLedger.includes(marker)) {
            let fallbackSatisfied = options.allowTextFallback && lower.includes(marker)
            if (!fallbackSatisfied && options.allowTextFallback && options.decisionRuntime) {
              const decision = await options.decisionRuntime.decide({
                hookId: "done-proof-enforcer",
                sessionId,
                templateId: `done-proof-marker-${marker}-v1`,
                instruction: buildMarkerInstruction(marker),
                context: buildMarkerContext(text),
                allowedChars: ["Y", "N"],
                decisionMeaning: { Y: `${marker}_present`, N: `${marker}_missing` },
                cacheKey: `done-proof:${marker}:${text.trim().toLowerCase()}`,
              })
              if (decision.accepted) {
                fallbackSatisfied = decision.char === "Y"
                writeGatewayEventAudit(options.directory ?? process.cwd(), {
                  hook: "done-proof-enforcer",
                  stage: "state",
                  reason_code: "llm_done_proof_marker_decision_recorded",
                  session_id: sessionId,
                  llm_decision_char: decision.char,
                  llm_decision_meaning: decision.meaning,
                  llm_decision_mode: options.decisionRuntime.config.mode,
                  evidence: marker,
                })
              }
            }
            if (!fallbackSatisfied) {
              missingMarkers.push(marker)
            }
            continue
          }
          if (!options.requireLedgerEvidence && !lower.includes(marker)) {
            missingMarkers.push(marker)
          }
          if (options.requireLedgerEvidence && !sessionId && !(options.allowTextFallback && lower.includes(marker))) {
            missingMarkers.push(marker)
          }
          continue
        }
        if (!lower.includes(marker)) {
          missingMarkers.push(marker)
        }
      }
      if (missingMarkers.length === 0) {
        return
      }
      eventPayload.output.output = text.replace(/<promise>\s*DONE\s*<\/promise>/gi, "<promise>PENDING_VALIDATION</promise>")
      eventPayload.output.output +=
        `\n\n[done-proof-enforcer] Completion token deferred until validation evidence is included (${missingMarkers.join(", ")}).`
    },
  }
}
