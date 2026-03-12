import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import {
  posix as pathPosix,
  relative as pathRelative,
  resolve as pathResolve,
} from "node:path";
import type { GatewayHook } from "../registry.js";
import { changedPathsFromToolPayload } from "../path-tracking/changed-paths.js";
import { getDelegationChildSessionLink } from "../shared/delegation-child-session.js";

interface ToolBeforePayload {
  input?: {
    tool?: string;
    sessionID?: string;
    sessionId?: string;
  };
  output?: {
    args?: {
      filePath?: string;
      path?: string;
      file?: string;
    };
    message?: string;
  };
}

interface SessionDeletedPayload {
  properties?: {
    info?: {
      id?: string;
    };
  };
}

const WRITE_LIKE_TOOLS = new Set(["write", "edit", "multiedit", "apply_patch"]);
const REMINDER_HEADER = "[direct-work-warning]";
const BLOCK_HEADER = "[direct-work-discipline]";

function sessionId(payload: ToolBeforePayload): string {
  return String(
    payload.input?.sessionID ?? payload.input?.sessionId ?? "",
  ).trim();
}

function reminderText(path: string): string {
  const suffix = path ? ` Target: ${path}.` : "";
  return `${REMINDER_HEADER} Direct file edits from the primary orchestrator should be exceptional.${suffix} Prefer delegating implementation first, then verify and integrate the result.`;
}

function blockText(path: string): string {
  const suffix = path ? ` Target: ${path}.` : "";
  return `${BLOCK_HEADER} Repeated direct file edits from the primary orchestrator are blocked for this session.${suffix} Delegate implementation first, then verify and integrate the result.`;
}

export function createDirectWorkWarningHook(options: {
  directory: string;
  enabled: boolean;
  blockRepeatedEdits: boolean;
  allowPaths: string[];
}): GatewayHook {
  const warnedSessions = new Set<string>();
  const allowPatterns = options.allowPaths.map((pattern) => {
    try {
      return globToRegex(pattern);
    } catch {
      return null;
    }
  });
  return {
    id: "direct-work-warning",
    priority: 366,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled) {
        return;
      }
      if (type === "session.deleted") {
        const sid = String(
          ((payload ?? {}) as SessionDeletedPayload).properties?.info?.id ?? "",
        ).trim();
        if (sid) {
          warnedSessions.delete(sid);
        }
        return;
      }
      if (type !== "tool.execute.before") {
        return;
      }
      const eventPayload = (payload ?? {}) as ToolBeforePayload;
      const tool = String(eventPayload.input?.tool ?? "")
        .toLowerCase()
        .trim();
      if (!WRITE_LIKE_TOOLS.has(tool)) {
        return;
      }
      const sid = sessionId(eventPayload);
      if (!sid || getDelegationChildSessionLink(sid)) {
        return;
      }
      const paths = targetPaths(options.directory, eventPayload);
      const primaryPath = paths[0] ?? "";
      if (
        paths.length > 0 &&
        paths.every((path) => isAllowedPath(path, allowPatterns))
      ) {
        return;
      }
      if (options.blockRepeatedEdits && warnedSessions.has(sid)) {
        writeGatewayEventAudit(options.directory, {
          hook: "direct-work-warning",
          stage: "before",
          reason_code: "direct_work_repeat_blocked",
          session_id: sid,
          tool,
          file_path: primaryPath || undefined,
        });
        throw new Error(blockText(primaryPath));
      }
      const reminder = reminderText(primaryPath);
      const existing = String(eventPayload.output?.message ?? "");
      if (existing.includes(REMINDER_HEADER)) {
        return;
      }
      eventPayload.output = eventPayload.output ?? {};
      eventPayload.output.message = existing
        ? `${existing}\n${reminder}`
        : reminder;
      writeGatewayEventAudit(options.directory, {
        hook: "direct-work-warning",
        stage: "before",
        reason_code: "direct_work_warning_injected",
        session_id: sid,
        tool,
        file_path: primaryPath || undefined,
      });
      warnedSessions.add(sid);
    },
  };
}

function isAllowedPath(path: string, patterns: Array<RegExp | null>): boolean {
  if (!path) {
    return false;
  }
  const normalized = normalizePath(path);
  return patterns.some((pattern) => pattern?.test(normalized));
}

function normalizePath(path: string): string {
  const normalized = path.replace(/\\/g, "/").trim();
  return pathPosix.normalize(normalized).replace(/^\.\//, "");
}

function targetPaths(directory: string, payload: unknown): string[] {
  return changedPathsFromToolPayload(payload).map((path) =>
    relativizeToDirectory(directory, path),
  );
}

function relativizeToDirectory(directory: string, path: string): string {
  const normalized = normalizePath(path);
  if (!normalized.startsWith("/")) {
    return normalized;
  }
  const absoluteDirectory = pathResolve(directory);
  const relativePath = pathRelative(absoluteDirectory, normalized).replace(
    /\\/g,
    "/",
  );
  if (!relativePath || relativePath.startsWith("../")) {
    return normalized;
  }
  return normalizePath(relativePath);
}

function globToRegex(pattern: string): RegExp {
  let regex = "^";
  for (let index = 0; index < pattern.length; index += 1) {
    const char = pattern[index];
    const next = pattern[index + 1];
    const nextNext = pattern[index + 2];
    if (char === "*") {
      if (next === "*") {
        if (nextNext === "/") {
          regex += "(?:.*/)?";
          index += 2;
        } else {
          regex += ".*";
          index += 1;
        }
      } else {
        regex += "[^/]*";
      }
      continue;
    }
    if (char === "?") {
      regex += ".";
      continue;
    }
    if (".()+|^${}[]\\".includes(char)) {
      regex += `\\${char}`;
      continue;
    }
    regex += char;
  }
  regex += "$";
  return new RegExp(regex);
}
