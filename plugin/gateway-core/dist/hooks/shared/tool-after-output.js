export function inspectToolAfterOutputText(output) {
    if (typeof output === "string") {
        return { text: output, channel: "string" };
    }
    if (!output || typeof output !== "object") {
        return { text: "", channel: "unknown" };
    }
    const record = output;
    if (typeof record.stdout === "string" && record.stdout.trim()) {
        return { text: record.stdout.trim(), channel: "stdout" };
    }
    if (typeof record.output === "string" && record.output.trim()) {
        return { text: record.output.trim(), channel: "output" };
    }
    if (typeof record.message === "string" && record.message.trim()) {
        return { text: record.message.trim(), channel: "message" };
    }
    if (typeof record.stderr === "string" && record.stderr.trim()) {
        return { text: record.stderr.trim(), channel: "stderr" };
    }
    return { text: "", channel: "unknown" };
}
export function readToolAfterOutputText(output) {
    return inspectToolAfterOutputText(output).text;
}
export function writeToolAfterOutputText(output, text, preferredChannel = "unknown") {
    if (typeof output === "string" || !output || typeof output !== "object") {
        return false;
    }
    const record = output;
    if (preferredChannel === "stdout" && typeof record.stdout === "string") {
        record.stdout = text;
        return true;
    }
    if (preferredChannel === "output" && typeof record.output === "string") {
        record.output = text;
        return true;
    }
    if (preferredChannel === "message" && typeof record.message === "string") {
        record.message = text;
        return true;
    }
    if (preferredChannel === "stderr" && typeof record.stderr === "string") {
        record.stderr = text;
        return true;
    }
    if (typeof record.stdout === "string") {
        record.stdout = text;
        return true;
    }
    if (typeof record.output === "string") {
        record.output = text;
        return true;
    }
    if (typeof record.message === "string") {
        record.message = text;
        return true;
    }
    record.output = text;
    return true;
}
