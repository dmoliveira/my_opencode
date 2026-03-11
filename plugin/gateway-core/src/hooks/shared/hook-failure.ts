export const CRITICAL_GATEWAY_HOOK_IDS = new Set([
  "agent-denied-tool-enforcer",
  "agent-reservation-guard",
  "branch-freshness-guard",
  "dangerous-command-guard",
  "dependency-risk-guard",
  "docs-drift-guard",
  "gh-checks-merge-guard",
  "hook-test-parity-guard",
  "merge-readiness-guard",
  "pr-body-evidence-guard",
  "pr-readiness-guard",
  "primary-worktree-guard",
  "noninteractive-shell-guard",
  "safety",
  "scope-drift-guard",
  "secret-commit-guard",
  "secret-leak-guard",
  "workflow-conformance-guard",
  "write-existing-file-guard",
]);

export function isCriticalGatewayHookId(hookId: string): boolean {
  return CRITICAL_GATEWAY_HOOK_IDS.has(hookId.trim().toLowerCase());
}

export function describeHookFailure(error: unknown): string {
  if (error instanceof Error) {
    return `${error.name}: ${error.message}`;
  }
  if (typeof error === "string" && error.trim()) {
    return error.trim();
  }
  return "unknown error";
}

export function isIntentionalHookBlock(error: unknown): boolean {
  const message =
    error instanceof Error
      ? error.message
      : typeof error === "string"
        ? error
        : "";
  const trimmed = message.trim();
  return (
    /^\[[^\]]+\]/.test(trimmed) ||
    /^blocked\b/i.test(trimmed) ||
    /\bdisabled\b/i.test(trimmed) ||
    /require(?:s|d)? explicit/i.test(trimmed) ||
    /\bmust include\b/i.test(trimmed) ||
    /\bmust use\b/i.test(trimmed) ||
    /\bmissing active\b/i.test(trimmed)
  );
}

export function surfaceGatewayHookFailure(message: string): void {
  const line = `[gateway-core] ${message}\n`;
  try {
    process.stderr.write(line);
  } catch {
    // stderr best-effort only
  }
}

export function normalizeHookError(error: unknown, fallback: string): Error {
  if (error instanceof Error) {
    return error;
  }
  return new Error(fallback);
}
