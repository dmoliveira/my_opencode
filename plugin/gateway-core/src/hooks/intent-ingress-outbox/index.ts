import { createHash, randomBytes } from "node:crypto";
import { constants, type Stats } from "node:fs";
import {
  link,
  lstat,
  mkdir,
  open,
  opendir,
  realpath,
  unlink,
} from "node:fs/promises";
import { homedir } from "node:os";
import {
  dirname,
  isAbsolute,
  join,
  parse,
  relative,
  resolve,
  sep,
} from "node:path";

import { writeGatewayLocalEventAudit } from "../../audit/event-audit.js";
import type { GatewayHook } from "../registry.js";
import {
  createSecretRedactor,
  SecretRedactionError,
  type SecretRedactor,
} from "../shared/secret-redaction.js";

const ENVELOPE_VERSION = 1;
const PRIVATE_DIRECTORY_MODE = 0o700;
const PRIVATE_FILE_MODE = 0o600;
const TEMP_PREFIX = ".intent-ingress-stage-";
const MAX_PENDING_ENTRIES = 10_000;
const MAX_ENVELOPE_BYTES = 262_144;
const MAX_DIRECTORY_SCAN_ENTRIES = MAX_PENDING_ENTRIES + 64;
const PUBLISHED_ENVELOPE_FILENAME = /^intent_ingress_[0-9a-f]{32}\.json$/;

interface ChatPayload {
  properties?: {
    sessionID?: string;
    sessionId?: string;
    messageID?: string;
    prompt?: string;
  };
  output?: {
    message?: {
      id?: string;
      sessionID?: string;
      role?: string;
    };
  };
  directory?: string;
}

interface EnvelopeContent {
  mode: "metadata" | "redacted_preview";
  char_count: number;
  sha256: string;
  preview?: string;
  truncated?: boolean;
  redacted_fields?: number;
  omitted_reason?: "redaction_failed";
}

export interface IntentIngressEnvelope {
  version: 1;
  envelope_id: string;
  project_digest: string;
  observed_at: string;
  source: {
    kind: "user";
    session_id: string;
    message_id: string;
  };
  content: EnvelopeContent;
}

type PersistResult =
  | { outcome: "enqueued"; durability: "synced" | "file_synced" }
  | { outcome: "deduplicated" }
  | { outcome: "overflow" }
  | { outcome: "conflict" };

interface PersistOptions {
  stateDir: string;
  maxEnvelopeBytes: number;
  softMaxPendingEntries: number;
  failureInjector?: (phase: string) => void;
}

interface HookOptions {
  directory: string;
  enabled: boolean;
  captureContent: boolean;
  stateDir: string;
  maxInputChars: number;
  maxContentChars: number;
  maxEnvelopeBytes: number;
  softMaxPendingEntries: number;
  redactionToken: string;
  secretPatterns: string[];
  secretLimits: {
    maxDepth: number;
    maxNodes: number;
  };
}

interface BuildResult {
  envelope?: IntentIngressEnvelope;
  reasonCode?: string;
  redactionFailed?: boolean;
}

function normalizedIdentifier(value: unknown): string {
  const normalized = String(value ?? "").trim();
  if (
    !normalized ||
    normalized.length > 256 ||
    /[\u0000-\u001f\u007f]/.test(normalized)
  ) {
    return "";
  }
  return normalized;
}

function digest(parts: string[]): string {
  const hash = createHash("sha256");
  for (const part of parts) {
    hash.update(String(Buffer.byteLength(part, "utf8")));
    hash.update(":");
    hash.update(part);
    hash.update("\u0000");
  }
  return hash.digest("hex");
}

function contentDigest(value: string): string {
  return createHash("sha256").update(value, "utf8").digest("hex");
}

function configuredStateDir(value: string, directory: string): string {
  const configured = value.trim();
  let stateDir: string;
  if (configured === "~") {
    stateDir = homedir();
  } else if (configured.startsWith("~/")) {
    stateDir = join(homedir(), configured.slice(2));
  } else {
    stateDir = isAbsolute(configured)
      ? resolve(configured)
      : resolve(directory, configured);
  }
  if (
    stateDir === parse(stateDir).root ||
    stateDir === resolve(homedir()) ||
    stateDir === resolve(directory)
  ) {
    throw new Error("intent ingress requires a dedicated state directory");
  }
  return stateDir;
}

function projectDigest(directory: string): string {
  return digest(["intent-ingress-project-v1", resolve(directory)]).slice(0, 32);
}

function sourceDigest(envelope: IntentIngressEnvelope): string {
  return digest([envelope.source.session_id, envelope.source.message_id]).slice(
    0,
    20,
  );
}

function envelopeIdentity(
  project: string,
  sessionId: string,
  messageId: string,
): string {
  return `intent_ingress_${digest([
    "intent-ingress-envelope-v1",
    project,
    sessionId,
    messageId,
  ]).slice(0, 32)}`;
}

function isMissing(error: unknown): boolean {
  return (error as NodeJS.ErrnoException)?.code === "ENOENT";
}

function currentUid(): number {
  if (typeof process.getuid !== "function") {
    throw new Error("intent ingress requires current-user ownership checks");
  }
  return process.getuid();
}

function noFollowFlag(): number {
  const flag = (constants as unknown as Record<string, number>).O_NOFOLLOW;
  if (!Number.isInteger(flag) || flag === 0) {
    throw new Error("intent ingress requires no-follow file opens");
  }
  return flag;
}

async function assertSafeAncestorNamespace(path: string): Promise<void> {
  const uid = currentUid();
  let child = resolve(path);
  while (true) {
    const parent = dirname(child);
    if (parent === child) {
      return;
    }
    const [parentState, childState] = await Promise.all([
      lstat(parent),
      lstat(child),
    ]);
    if (
      !parentState.isDirectory() ||
      parentState.isSymbolicLink() ||
      !childState.isDirectory() ||
      childState.isSymbolicLink() ||
      (parentState.uid !== uid && parentState.uid !== 0)
    ) {
      throw new Error("unsafe intent ingress ancestor namespace");
    }
    if (parentState.mode & 0o022) {
      const sticky = Boolean(parentState.mode & 0o1000);
      const protectedChild = childState.uid === uid || childState.uid === 0;
      if (!sticky || !protectedChild) {
        throw new Error("writable intent ingress ancestor namespace");
      }
    }
    child = parent;
  }
}

async function assertSafeCreationParent(path: string): Promise<void> {
  const state = await lstat(path);
  const uid = currentUid();
  if (
    !state.isDirectory() ||
    state.isSymbolicLink() ||
    (state.uid !== uid && state.uid !== 0) ||
    ((state.mode & 0o022) !== 0 && (state.mode & 0o1000) === 0)
  ) {
    throw new Error("unsafe intent ingress creation parent");
  }
  await assertSafeAncestorNamespace(path);
}

async function ensurePrivateDirectory(path: string): Promise<void> {
  let created = false;
  try {
    await mkdir(path, { mode: PRIVATE_DIRECTORY_MODE });
    created = true;
  } catch (error) {
    if ((error as NodeJS.ErrnoException)?.code !== "EEXIST") {
      throw error;
    }
  }
  let handle: Awaited<ReturnType<typeof open>> | null = null;
  try {
    handle = await open(path, constants.O_RDONLY | noFollowFlag());
    const state = await handle.stat();
    const uid = currentUid();
    if (!state.isDirectory() || state.uid !== uid) {
      throw new Error("unsafe intent ingress directory");
    }
    if ((state.mode & 0o777) !== PRIVATE_DIRECTORY_MODE) {
      if (!created) {
        throw new Error("unsafe intent ingress directory mode");
      }
      await handle.chmod(PRIVATE_DIRECTORY_MODE);
    }
  } finally {
    await handle?.close().catch(() => undefined);
  }
}

async function ensurePrivateDirectoryTree(path: string): Promise<string> {
  const absolute = resolve(path);
  const root = parse(absolute).root;
  const components = relative(root, absolute).split(sep).filter(Boolean);
  if (components.length === 0) {
    throw new Error(
      "intent ingress state directory cannot be a filesystem root",
    );
  }
  let current = root;
  for (let index = 0; index < components.length; index += 1) {
    current = join(current, components[index]);
    if (index === components.length - 1) {
      try {
        await lstat(current);
      } catch (error) {
        if (!isMissing(error)) {
          throw error;
        }
        await assertSafeCreationParent(dirname(current));
      }
      await ensurePrivateDirectory(current);
      continue;
    }
    try {
      const state = await lstat(current);
      if (!state.isDirectory() || state.isSymbolicLink()) {
        throw new Error("unsafe intent ingress parent directory");
      }
    } catch (error) {
      if (!isMissing(error)) {
        throw error;
      }
      await assertSafeCreationParent(dirname(current));
      await ensurePrivateDirectory(current);
    }
  }
  await assertSafeAncestorNamespace(absolute);
  const canonical = await realpath(absolute);
  if (canonical !== absolute) {
    throw new Error("unsafe intent ingress directory path");
  }
  return canonical;
}

async function ensureSpool(stateDir: string): Promise<string> {
  const canonicalStateDir = await ensurePrivateDirectoryTree(stateDir);
  const ingress = join(canonicalStateDir, "ingress");
  await ensurePrivateDirectory(ingress);
  const pending = join(ingress, "pending");
  await ensurePrivateDirectory(pending);
  return pending;
}

function sameEnvelopeIdentity(
  value: unknown,
  envelope: IntentIngressEnvelope,
): boolean {
  if (!value || typeof value !== "object") {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  const source = candidate.source;
  if (!source || typeof source !== "object") {
    return false;
  }
  const sourceRecord = source as Record<string, unknown>;
  const content = candidate.content;
  if (!content || typeof content !== "object") {
    return false;
  }
  const contentRecord = content as Record<string, unknown>;
  return (
    candidate.version === ENVELOPE_VERSION &&
    candidate.envelope_id === envelope.envelope_id &&
    candidate.project_digest === envelope.project_digest &&
    sourceRecord.kind === "user" &&
    sourceRecord.session_id === envelope.source.session_id &&
    sourceRecord.message_id === envelope.source.message_id &&
    contentRecord.sha256 === envelope.content.sha256
  );
}

function hasOnlyKeys(
  value: Record<string, unknown>,
  allowed: ReadonlySet<string>,
): boolean {
  return Object.keys(value).every((key) => allowed.has(key));
}

function assertPersistableEnvelope(envelope: IntentIngressEnvelope): void {
  const candidate = envelope as unknown as Record<string, unknown>;
  const source = candidate.source as Record<string, unknown> | undefined;
  const content = candidate.content as Record<string, unknown> | undefined;
  const observedAt = candidate.observed_at;
  if (
    !hasOnlyKeys(
      candidate,
      new Set([
        "version",
        "envelope_id",
        "project_digest",
        "observed_at",
        "source",
        "content",
      ]),
    ) ||
    candidate.version !== ENVELOPE_VERSION ||
    typeof candidate.envelope_id !== "string" ||
    !/^intent_ingress_[0-9a-f]{32}$/.test(candidate.envelope_id) ||
    typeof candidate.project_digest !== "string" ||
    !/^[0-9a-f]{32}$/.test(candidate.project_digest) ||
    typeof observedAt !== "string" ||
    observedAt.length > 32 ||
    Number.isNaN(Date.parse(observedAt)) ||
    new Date(observedAt).toISOString() !== observedAt ||
    !source ||
    !hasOnlyKeys(source, new Set(["kind", "session_id", "message_id"])) ||
    source.kind !== "user" ||
    typeof source.session_id !== "string" ||
    normalizedIdentifier(source.session_id) !== source.session_id ||
    typeof source.message_id !== "string" ||
    normalizedIdentifier(source.message_id) !== source.message_id ||
    !content ||
    !hasOnlyKeys(
      content,
      new Set([
        "mode",
        "char_count",
        "sha256",
        "preview",
        "truncated",
        "redacted_fields",
        "omitted_reason",
      ]),
    ) ||
    (content.mode !== "metadata" && content.mode !== "redacted_preview") ||
    !Number.isInteger(content.char_count) ||
    (content.char_count as number) < 1 ||
    (content.char_count as number) > 1_048_576 ||
    typeof content.sha256 !== "string" ||
    !/^[0-9a-f]{64}$/.test(content.sha256)
  ) {
    throw new Error("invalid intent ingress envelope");
  }
  if (
    envelope.envelope_id !==
    envelopeIdentity(
      envelope.project_digest,
      envelope.source.session_id,
      envelope.source.message_id,
    )
  ) {
    throw new Error("intent ingress envelope identity mismatch");
  }
  if (
    content.mode === "metadata" &&
    (content.preview !== undefined ||
      content.truncated !== undefined ||
      content.redacted_fields !== undefined ||
      (content.omitted_reason !== undefined &&
        content.omitted_reason !== "redaction_failed"))
  ) {
    throw new Error("invalid intent ingress metadata envelope");
  }
  if (
    content.mode === "redacted_preview" &&
    (typeof content.preview !== "string" ||
      content.preview.length > 65_536 ||
      typeof content.truncated !== "boolean" ||
      !Number.isInteger(content.redacted_fields) ||
      (content.redacted_fields as number) < 0 ||
      content.omitted_reason !== undefined)
  ) {
    throw new Error("invalid intent ingress preview envelope");
  }
}

function boundedPositiveInteger(
  value: number,
  max: number,
  fallback: number,
): number {
  return Number.isInteger(value) && value > 0 ? Math.min(value, max) : fallback;
}

async function readBoundedUtf8(
  handle: Awaited<ReturnType<typeof open>>,
  maxBytes: number,
): Promise<string | null> {
  const buffer = Buffer.alloc(maxBytes + 1);
  let total = 0;
  while (total < buffer.length) {
    const { bytesRead } = await handle.read(
      buffer,
      total,
      buffer.length - total,
      total,
    );
    if (bytesRead === 0) {
      break;
    }
    total += bytesRead;
  }
  return total > maxBytes ? null : buffer.subarray(0, total).toString("utf8");
}

async function pendingCapacityReached(
  pending: string,
  maxEntries: number,
): Promise<boolean> {
  const directory = await opendir(pending);
  try {
    let publishedEntries = 0;
    for (let scanned = 0; scanned < MAX_DIRECTORY_SCAN_ENTRIES; scanned += 1) {
      const entry = await directory.read();
      if (!entry) {
        return false;
      }
      if (!entry.isFile() || !PUBLISHED_ENVELOPE_FILENAME.test(entry.name)) {
        continue;
      }
      publishedEntries += 1;
      if (publishedEntries >= maxEntries) {
        return true;
      }
    }
    return (await directory.read()) !== null;
  } finally {
    await directory.close().catch(() => undefined);
  }
}

async function recoverPublishedStageLinks(
  finalPath: string,
  envelope: IntentIngressEnvelope,
  state: Stats,
  handle: Awaited<ReturnType<typeof open>>,
): Promise<boolean> {
  if (state.nlink === 1) {
    return true;
  }
  if (state.nlink < 1) {
    return false;
  }
  const pending = dirname(finalPath);
  const stagePrefix = `${TEMP_PREFIX}${envelope.envelope_id}-`;
  const stageLinks: string[] = [];
  const directory = await opendir(pending);
  try {
    for (let scanned = 0; scanned < MAX_DIRECTORY_SCAN_ENTRIES; scanned += 1) {
      const entry = await directory.read();
      if (!entry) {
        break;
      }
      if (!entry.isFile() || !entry.name.startsWith(stagePrefix)) {
        continue;
      }
      const candidatePath = join(pending, entry.name);
      try {
        const candidate = await lstat(candidatePath);
        if (
          candidate.isFile() &&
          !candidate.isSymbolicLink() &&
          candidate.dev === state.dev &&
          candidate.ino === state.ino
        ) {
          stageLinks.push(candidatePath);
        }
      } catch (error) {
        if (!isMissing(error)) {
          throw error;
        }
      }
    }
    if (await directory.read()) {
      return false;
    }
  } finally {
    await directory.close().catch(() => undefined);
  }
  if (stageLinks.length !== state.nlink - 1) {
    return (await handle.stat()).nlink === 1;
  }
  for (const stageLink of stageLinks) {
    await unlink(stageLink).catch((error: unknown) => {
      if (!isMissing(error)) {
        throw error;
      }
    });
  }
  await syncDirectory(pending);
  return (await handle.stat()).nlink === 1;
}

async function existingEnvelopeOutcome(
  path: string,
  envelope: IntentIngressEnvelope,
  maxEnvelopeBytes: number,
): Promise<"missing" | "deduplicated" | "conflict"> {
  let handle: Awaited<ReturnType<typeof open>> | null = null;
  try {
    handle = await open(path, constants.O_RDONLY | noFollowFlag());
  } catch (error) {
    if (isMissing(error)) {
      return "missing";
    }
    return "conflict";
  }
  try {
    const state = await handle.stat();
    const uid = currentUid();
    if (
      !state.isFile() ||
      state.size <= 0 ||
      state.size > maxEnvelopeBytes ||
      state.uid !== uid ||
      (state.mode & 0o777) !== PRIVATE_FILE_MODE
    ) {
      return "conflict";
    }
    const raw = await readBoundedUtf8(handle, maxEnvelopeBytes);
    if (raw === null) {
      return "conflict";
    }
    const parsed = JSON.parse(raw) as unknown;
    assertPersistableEnvelope(parsed as IntentIngressEnvelope);
    if (!sameEnvelopeIdentity(parsed, envelope)) {
      return "conflict";
    }
    if (!(await recoverPublishedStageLinks(path, envelope, state, handle))) {
      return "conflict";
    }
    return (await handle.stat()).nlink === 1 ? "deduplicated" : "conflict";
  } catch {
    return "conflict";
  } finally {
    await handle.close().catch(() => undefined);
  }
}

async function syncDirectory(path: string): Promise<boolean> {
  let handle: Awaited<ReturnType<typeof open>> | null = null;
  try {
    handle = await open(path, constants.O_RDONLY | noFollowFlag());
    const state = await handle.stat();
    const uid = currentUid();
    if (
      !state.isDirectory() ||
      state.uid !== uid ||
      (state.mode & 0o777) !== PRIVATE_DIRECTORY_MODE
    ) {
      return false;
    }
    await handle.sync();
    return true;
  } catch {
    return false;
  } finally {
    await handle?.close().catch(() => undefined);
  }
}

export async function persistIntentIngressEnvelope(
  envelope: IntentIngressEnvelope,
  options: PersistOptions,
): Promise<PersistResult> {
  assertPersistableEnvelope(envelope);
  const noFollow = noFollowFlag();
  const maxEnvelopeBytes = boundedPositiveInteger(
    options.maxEnvelopeBytes,
    MAX_ENVELOPE_BYTES,
    16_384,
  );
  const softMaxPendingEntries = boundedPositiveInteger(
    options.softMaxPendingEntries,
    MAX_PENDING_ENTRIES,
    1_000,
  );
  const pending = await ensureSpool(options.stateDir);
  const finalPath = join(pending, `${envelope.envelope_id}.json`);
  const existing = await existingEnvelopeOutcome(
    finalPath,
    envelope,
    maxEnvelopeBytes,
  );
  if (existing !== "missing") {
    return { outcome: existing };
  }
  if (await pendingCapacityReached(pending, softMaxPendingEntries)) {
    return { outcome: "overflow" };
  }

  const serialized = `${JSON.stringify(envelope)}\n`;
  if (Buffer.byteLength(serialized, "utf8") > maxEnvelopeBytes) {
    throw new Error("intent ingress envelope exceeds byte limit");
  }
  const temporaryPath = join(
    pending,
    `${TEMP_PREFIX}${envelope.envelope_id}-${process.pid}-${randomBytes(8).toString("hex")}`,
  );
  let handle: Awaited<ReturnType<typeof open>> | null = null;
  let published = false;
  try {
    handle = await open(
      temporaryPath,
      constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | noFollow,
      PRIVATE_FILE_MODE,
    );
    await handle.chmod(PRIVATE_FILE_MODE);
    await handle.writeFile(serialized, "utf8");
    await handle.sync();
    options.failureInjector?.("after_temp_sync");
    await handle.close();
    handle = null;
    try {
      await link(temporaryPath, finalPath);
      published = true;
    } catch (error) {
      if ((error as NodeJS.ErrnoException)?.code !== "EEXIST") {
        throw error;
      }
      const replay = await existingEnvelopeOutcome(
        finalPath,
        envelope,
        maxEnvelopeBytes,
      );
      return { outcome: replay === "deduplicated" ? replay : "conflict" };
    }
    options.failureInjector?.("after_publish");
    const directorySynced = await syncDirectory(pending);
    options.failureInjector?.("after_directory_sync");
    return {
      outcome: "enqueued",
      durability: directorySynced ? "synced" : "file_synced",
    };
  } finally {
    await handle?.close().catch(() => undefined);
    await unlink(temporaryPath).catch(() => undefined);
    if (published) {
      await syncDirectory(pending);
    }
  }
}

export function compareIntentIngressEnvelopes(
  left: IntentIngressEnvelope,
  right: IntentIngressEnvelope,
): number {
  return (
    left.observed_at.localeCompare(right.observed_at) ||
    left.envelope_id.localeCompare(right.envelope_id)
  );
}

function buildEnvelope(
  payload: ChatPayload,
  options: HookOptions,
  redactor: SecretRedactor,
): BuildResult {
  const sessionId = normalizedIdentifier(
    payload.properties?.sessionID ??
      payload.properties?.sessionId ??
      payload.output?.message?.sessionID,
  );
  const messageId = normalizedIdentifier(
    payload.properties?.messageID ?? payload.output?.message?.id,
  );
  const prompt =
    typeof payload.properties?.prompt === "string"
      ? payload.properties.prompt
      : "";
  if (!sessionId || !messageId) {
    return { reasonCode: "intent_ingress_identity_missing" };
  }
  if (payload.output?.message?.role && payload.output.message.role !== "user") {
    return { reasonCode: "intent_ingress_non_user_message" };
  }
  if (!prompt.trim()) {
    return { reasonCode: "intent_ingress_prompt_empty" };
  }
  if (prompt.length > Math.max(1, options.maxInputChars)) {
    return { reasonCode: "intent_ingress_input_too_large" };
  }
  const directory =
    typeof payload.directory === "string" && payload.directory.trim()
      ? payload.directory
      : options.directory;
  const project = projectDigest(directory);
  const content: EnvelopeContent = {
    mode: "metadata",
    char_count: prompt.length,
    sha256: contentDigest(prompt),
  };
  let redactionFailed = false;
  if (options.captureContent) {
    try {
      const redacted = redactor.redactText(prompt);
      const normalized = redacted.text.replace(/\s+/g, " ").trim();
      const maxContentChars = Math.max(
        1,
        Math.min(options.maxContentChars, options.maxInputChars),
      );
      content.mode = "redacted_preview";
      content.preview = normalized.slice(0, maxContentChars);
      content.truncated = normalized.length > maxContentChars;
      content.redacted_fields = redacted.stats.redactedFields;
    } catch (error) {
      if (!(error instanceof SecretRedactionError)) {
        throw error;
      }
      content.omitted_reason = "redaction_failed";
      redactionFailed = true;
    }
  }
  const envelopeId = envelopeIdentity(project, sessionId, messageId);
  return {
    envelope: {
      version: ENVELOPE_VERSION,
      envelope_id: envelopeId,
      project_digest: project,
      observed_at: new Date().toISOString(),
      source: {
        kind: "user",
        session_id: sessionId,
        message_id: messageId,
      },
      content,
    },
    redactionFailed,
  };
}

// Creates an opt-in, fail-open hook that durably spools bounded intent metadata.
export function createIntentIngressOutboxHook(
  options: HookOptions,
): GatewayHook {
  const redactor = createSecretRedactor({
    patterns: options.secretPatterns,
    redactionToken: options.redactionToken,
    limits: {
      maxDepth: options.secretLimits.maxDepth,
      maxNodes: options.secretLimits.maxNodes,
      maxChars: Math.max(1, options.maxInputChars),
    },
  });
  const stateDir = configuredStateDir(options.stateDir, options.directory);

  function audit(
    directory: string,
    reasonCode: string,
    envelope: IntentIngressEnvelope | undefined,
    startedAt: number,
    extra: Record<string, unknown> = {},
  ): void {
    writeGatewayLocalEventAudit(directory, {
      hook: "intent-ingress-outbox",
      stage: reasonCode === "intent_ingress_enqueued" ? "state" : "skip",
      reason_code: reasonCode,
      envelope_id: envelope?.envelope_id,
      project_digest: envelope?.project_digest,
      source_digest: envelope ? sourceDigest(envelope) : undefined,
      content_mode: envelope?.content.mode,
      content_char_count: envelope?.content.char_count,
      latency_ms: Math.max(0, Date.now() - startedAt),
      ...extra,
    });
  }

  return {
    id: "intent-ingress-outbox",
    priority: 449,
    events: ["chat.message"],
    async event(type: string, rawPayload: unknown): Promise<void> {
      if (!options.enabled || type !== "chat.message") {
        return;
      }
      const startedAt = Date.now();
      const payload = (rawPayload ?? {}) as ChatPayload;
      const directory =
        typeof payload.directory === "string" && payload.directory.trim()
          ? payload.directory
          : options.directory;
      let built: BuildResult;
      try {
        built = buildEnvelope(payload, options, redactor);
      } catch {
        audit(
          directory,
          "intent_ingress_envelope_failed",
          undefined,
          startedAt,
        );
        return;
      }
      if (!built.envelope) {
        audit(
          directory,
          built.reasonCode ?? "intent_ingress_envelope_skipped",
          undefined,
          startedAt,
        );
        return;
      }
      if (built.redactionFailed) {
        audit(
          directory,
          "intent_ingress_redaction_failed_metadata_only",
          built.envelope,
          startedAt,
        );
      }
      try {
        const result = await persistIntentIngressEnvelope(built.envelope, {
          stateDir,
          maxEnvelopeBytes: Math.max(1, options.maxEnvelopeBytes),
          softMaxPendingEntries: Math.max(1, options.softMaxPendingEntries),
        });
        const reasonCode = {
          enqueued: "intent_ingress_enqueued",
          deduplicated: "intent_ingress_deduplicated",
          overflow: "intent_ingress_soft_capacity_reached",
          conflict: "intent_ingress_identity_conflict",
        }[result.outcome];
        audit(directory, reasonCode, built.envelope, startedAt, {
          durability: "durability" in result ? result.durability : undefined,
        });
      } catch {
        audit(
          directory,
          "intent_ingress_persist_failed",
          built.envelope,
          startedAt,
        );
      }
    },
  };
}
