import { basename } from "node:path"

import { findNearestFile } from "../directory-context/finder.js"
import type { GatewayHook } from "../registry.js"
import { readFilePrefix } from "../shared/read-file-prefix.js"
import { insertStableSystemContext, stableContextLabel } from "../shared/stable-system-context.js"
import { truncateInjectedText } from "../shared/injected-text-truncator.js"

interface SystemTransformPayload {
  output?: { system?: string[] }
  directory?: string
}

const MARKER = "Local README context loaded from:"

function buildContextLine(path: string, maxChars: number): { text: string } {
  const sourceText = readFilePrefix(path, maxChars)
  const normalized = sourceText.trim()
  let contextLine = `Local README context loaded from: ${stableContextLabel(basename(path))}`
  if (normalized) {
    const truncated = truncateInjectedText(normalized, maxChars)
    contextLine = `${contextLine}\n\nREADME.md excerpt:\n${truncated.text}`
  }
  return { text: contextLine }
}

// Injects stable local repository guidance into the system prompt once per request.
export function createDirectoryReadmeInjectorHook(options: {
  directory: string
  enabled: boolean
  maxChars: number
}): GatewayHook {
  return {
    id: "directory-readme-injector",
    priority: 300,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled || type !== "experimental.chat.system.transform") return
      const eventPayload = (payload ?? {}) as SystemTransformPayload
      const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
        ? eventPayload.directory : options.directory
      const system = eventPayload.output?.system
      if (!Array.isArray(system) || system.some((entry) => entry.includes(MARKER))) return
      const path = findNearestFile(directory, "README.md")
      if (!path) return
      insertStableSystemContext(system, buildContextLine(path, options.maxChars).text)
    },
  }
}
