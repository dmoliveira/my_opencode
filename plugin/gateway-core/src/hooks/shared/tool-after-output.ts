export type ToolAfterOutputChannel = "string" | "stdout" | "output" | "message" | "stderr" | "unknown"

export interface ToolAfterOutputEntry {
  channel: ToolAfterOutputChannel
  text: string
}

export function listToolAfterOutputTexts(output: unknown): ToolAfterOutputEntry[] {
  if (typeof output === "string") {
    return output.trim() ? [{ channel: "string", text: output }] : []
  }
  if (!output || typeof output !== "object") {
    return []
  }
  const record = output as Record<string, unknown>
  const entries: ToolAfterOutputEntry[] = []
  for (const channel of ["stdout", "output", "message", "stderr"] as const) {
    const value = record[channel]
    if (typeof value === "string" && value.trim()) {
      entries.push({ channel, text: value })
    }
  }
  return entries
}

export function inspectToolAfterOutputText(output: unknown): {
  text: string
  channel: ToolAfterOutputChannel
} {
  const first = listToolAfterOutputTexts(output)[0]
  return first ?? { text: "", channel: "unknown" }
}

export function readToolAfterOutputText(output: unknown): string {
  return inspectToolAfterOutputText(output).text
}

export function readCombinedToolAfterOutputText(output: unknown): string {
  return listToolAfterOutputTexts(output)
    .map((entry) => entry.text)
    .join("\n")
}

export function writeToolAfterOutputChannelText(
  output: unknown,
  channel: ToolAfterOutputChannel,
  text: string,
): boolean {
  if (typeof output === "string" || !output || typeof output !== "object") {
    return false
  }
  const record = output as Record<string, unknown>
  if (channel === "stdout" && typeof record.stdout === "string") {
    record.stdout = text
    return true
  }
  if (channel === "output" && typeof record.output === "string") {
    record.output = text
    return true
  }
  if (channel === "message" && typeof record.message === "string") {
    record.message = text
    return true
  }
  if (channel === "stderr" && typeof record.stderr === "string") {
    record.stderr = text
    return true
  }
  return false
}

export function writeToolAfterOutputText(
  output: unknown,
  text: string,
  preferredChannel: ToolAfterOutputChannel = "unknown",
): boolean {
  if (typeof output === "string" || !output || typeof output !== "object") {
    return false
  }
  const record = output as Record<string, unknown>
  if (preferredChannel === "stdout" && typeof record.stdout === "string") {
    record.stdout = text
    return true
  }
  if (preferredChannel === "output" && typeof record.output === "string") {
    record.output = text
    return true
  }
  if (preferredChannel === "message" && typeof record.message === "string") {
    record.message = text
    return true
  }
  if (preferredChannel === "stderr" && typeof record.stderr === "string") {
    record.stderr = text
    return true
  }
  if (typeof record.stdout === "string") {
    record.stdout = text
    return true
  }
  if (typeof record.output === "string") {
    record.output = text
    return true
  }
  if (typeof record.message === "string") {
    record.message = text
    return true
  }
  record.output = text
  return true
}
