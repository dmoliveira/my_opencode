import { existsSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { basename, join, resolve } from "node:path";
import { spawnSync } from "node:child_process";

import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import type { GatewayHook } from "../registry.js";

type NotifyEvent = "complete" | "error" | "permission" | "question";
type NotifyStyle = "brief" | "detailed";
type NotifyIconMode = "nerd+emoji" | "emoji";

interface NotifyState {
  enabled: boolean;
  sound: {
    enabled: boolean;
    theme: string;
    eventThemes: Record<NotifyEvent, string>;
    customFiles: Record<NotifyEvent, string>;
  };
  visual: { enabled: boolean };
  icons: {
    enabled: boolean;
    version: string;
    mode: NotifyIconMode;
  };
  events: Record<NotifyEvent, boolean>;
  channels: Record<NotifyEvent, { sound: boolean; visual: boolean }>;
}

interface EventPayload {
  input?: {
    tool?: string;
    sessionID?: string;
    sessionId?: string;
    windowID?: string;
    windowId?: string;
  };
  properties?: Record<string, unknown>;
  directory?: string;
}

interface NotifyContent {
  title: string;
  message: string;
}

const NERD_ICON_BY_EVENT: Record<NotifyEvent, string> = {
  complete: "\udb80\udd2c",
  error: "\udb80\udd5a",
  permission: "\udb80\udf3e",
  question: "\udb80\udde2",
};

const EMOJI_BY_EVENT: Record<NotifyEvent, string> = {
  complete: "✅",
  error: "❌",
  permission: "🔐",
  question: "❓",
};

const SOUND_THEME_LIBRARY: Record<string, Record<NotifyEvent, string>> = {
  classic: {
    complete: "Glass",
    error: "Basso",
    permission: "Purr",
    question: "Ping",
  },
  minimal: {
    complete: "Tink",
    error: "Basso",
    permission: "Pop",
    question: "Ping",
  },
  retro: {
    complete: "Frog",
    error: "Sosumi",
    permission: "Morse",
    question: "Submarine",
  },
  urgent: {
    complete: "Hero",
    error: "Basso",
    permission: "Funk",
    question: "Sosumi",
  },
  chime: {
    complete: "Tink",
    error: "Bottle",
    permission: "Glass",
    question: "Pop",
  },
};

function defaultState(): NotifyState {
  return {
    enabled: true,
    sound: {
      enabled: true,
      theme: "classic",
      eventThemes: {
        complete: "default",
        error: "default",
        permission: "default",
        question: "default",
      },
      customFiles: {
        complete: "",
        error: "",
        permission: "",
        question: "",
      },
    },
    visual: { enabled: true },
    icons: {
      enabled: true,
      version: "v1",
      mode: "emoji",
    },
    events: {
      complete: true,
      error: true,
      permission: true,
      question: true,
    },
    channels: {
      complete: { sound: true, visual: true },
      error: { sound: true, visual: true },
      permission: { sound: true, visual: true },
      question: { sound: true, visual: true },
    },
  };
}

function toBool(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function normalizeLabel(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function parseState(raw: unknown): NotifyState {
  const source =
    raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  const state = defaultState();
  state.enabled = toBool(source.enabled, state.enabled);

  if (source.sound && typeof source.sound === "object") {
    const sound = source.sound as Record<string, unknown>;
    state.sound.enabled = toBool(sound.enabled, state.sound.enabled);
    const theme = normalizeLabel(sound.theme).toLowerCase();
    if (theme) {
      state.sound.theme = theme;
    }
    if (sound.eventThemes && typeof sound.eventThemes === "object") {
      for (const event of Object.keys(
        state.sound.eventThemes,
      ) as NotifyEvent[]) {
        const themeOverride = normalizeLabel(
          (sound.eventThemes as Record<string, unknown>)[event],
        ).toLowerCase();
        if (themeOverride) {
          state.sound.eventThemes[event] = themeOverride;
        }
      }
    }
    if (sound.customFiles && typeof sound.customFiles === "object") {
      for (const event of Object.keys(
        state.sound.customFiles,
      ) as NotifyEvent[]) {
        const custom = normalizeLabel(
          (sound.customFiles as Record<string, unknown>)[event],
        );
        if (
          custom ||
          (sound.customFiles as Record<string, unknown>)[event] === ""
        ) {
          state.sound.customFiles[event] = custom;
        }
      }
    }
  }

  if (source.visual && typeof source.visual === "object") {
    state.visual.enabled = toBool(
      (source.visual as Record<string, unknown>).enabled,
      state.visual.enabled,
    );
  }

  if (source.icons && typeof source.icons === "object") {
    const icons = source.icons as Record<string, unknown>;
    state.icons.enabled = toBool(icons.enabled, state.icons.enabled);
    const version = normalizeLabel(icons.version);
    if (version) {
      state.icons.version = version;
    }
    const mode = normalizeLabel(icons.mode).toLowerCase();
    if (mode === "emoji" || mode === "nerd+emoji") {
      state.icons.mode = mode;
    }
  }

  if (source.events && typeof source.events === "object") {
    for (const key of Object.keys(state.events) as NotifyEvent[]) {
      state.events[key] = toBool(
        (source.events as Record<string, unknown>)[key],
        state.events[key],
      );
    }
  }

  if (source.channels && typeof source.channels === "object") {
    for (const key of Object.keys(state.channels) as NotifyEvent[]) {
      const channels = (source.channels as Record<string, unknown>)[key];
      if (!channels || typeof channels !== "object") {
        continue;
      }
      state.channels[key].sound = toBool(
        (channels as Record<string, unknown>).sound,
        state.channels[key].sound,
      );
      state.channels[key].visual = toBool(
        (channels as Record<string, unknown>).visual,
        state.channels[key].visual,
      );
    }
  }
  return state;
}

function readJson(path: string): unknown | null {
  try {
    return JSON.parse(readFileSync(path, "utf-8"));
  } catch {
    return null;
  }
}

function loadNotifyState(directory: string): NotifyState {
  const legacyPath = process.env.OPENCODE_NOTIFICATIONS_PATH;
  if (legacyPath) {
    const legacy = readJson(legacyPath);
    if (legacy) {
      return parseState(legacy);
    }
  }

  const globalConfigPath = join(
    homedir(),
    ".config",
    "opencode",
    "opencode.json",
  );
  const globalConfig = readJson(globalConfigPath);
  if (
    globalConfig &&
    typeof globalConfig === "object" &&
    "notify" in (globalConfig as Record<string, unknown>)
  ) {
    return parseState((globalConfig as Record<string, unknown>).notify);
  }

  const projectConfigPath = join(directory, "opencode.json");
  const projectConfig = readJson(projectConfigPath);
  if (
    projectConfig &&
    typeof projectConfig === "object" &&
    "notify" in (projectConfig as Record<string, unknown>)
  ) {
    return parseState((projectConfig as Record<string, unknown>).notify);
  }

  return defaultState();
}

function eventFromType(
  type: string,
  payload: EventPayload,
): NotifyEvent | null {
  if (type === "session.idle") {
    return "complete";
  }
  if (type === "session.error") {
    return "error";
  }
  if (type.toLowerCase().includes("permission")) {
    return "permission";
  }
  if (type === "tool.execute.before") {
    const tool = String(payload.input?.tool || "").toLowerCase();
    if (tool === "question" || tool === "askuserquestion") {
      return "question";
    }
  }
  return null;
}

let terminalNotifierBin: string | null | undefined;

function terminalNotifierPath(): string | null {
  if (terminalNotifierBin !== undefined) {
    return terminalNotifierBin;
  }
  const result = spawnSync("which", ["terminal-notifier"], {
    stdio: ["ignore", "pipe", "ignore"],
    encoding: "utf-8",
    timeout: 1000,
  });
  if (
    result.status === 0 &&
    typeof result.stdout === "string" &&
    result.stdout.trim()
  ) {
    terminalNotifierBin = result.stdout.trim();
  } else {
    terminalNotifierBin = null;
  }
  return terminalNotifierBin;
}

function iconPrefix(eventName: NotifyEvent, mode: NotifyIconMode): string {
  const emoji = EMOJI_BY_EVENT[eventName];
  if (mode === "emoji") {
    return emoji;
  }
  return `${NERD_ICON_BY_EVENT[eventName]} ${emoji}`;
}

function titleWithIcon(
  eventName: NotifyEvent,
  state: NotifyState,
  title: string,
): string {
  if (!state.icons.enabled) {
    return title;
  }
  return `${iconPrefix(eventName, state.icons.mode)} ${title}`.trim();
}

function iconImagePath(
  eventName: NotifyEvent,
  state: NotifyState,
  directory: string,
): string {
  if (!state.icons.enabled) {
    return "";
  }
  const candidate = resolve(
    directory,
    "assets",
    "notify-icons",
    state.icons.version,
    `${eventName}.png`,
  );
  return existsSync(candidate) ? candidate : "";
}

function normalizeTheme(theme: string): string {
  const key = theme.trim().toLowerCase();
  return key in SOUND_THEME_LIBRARY ? key : "classic";
}

function resolvedEventTheme(
  state: NotifyState,
  eventName: NotifyEvent,
): string {
  const override = state.sound.eventThemes[eventName].trim().toLowerCase();
  if (override && override !== "default") {
    return normalizeTheme(override);
  }
  return normalizeTheme(state.sound.theme);
}

function soundNameForEvent(state: NotifyState, eventName: NotifyEvent): string {
  const theme = resolvedEventTheme(state, eventName);
  return (
    SOUND_THEME_LIBRARY[theme][eventName] ??
    SOUND_THEME_LIBRARY.classic[eventName]
  );
}

function customSoundPath(
  state: NotifyState,
  eventName: NotifyEvent,
  directory: string,
): string {
  const configured = state.sound.customFiles[eventName];
  if (!configured) {
    return "";
  }
  const absolute = configured.startsWith("~")
    ? join(homedir(), configured.slice(1))
    : resolve(directory, configured);
  return existsSync(absolute) ? absolute : "";
}

interface TerminalNotifierAttempt {
  args: string[];
  soundSent: boolean;
}

const GHOSTTY_BUNDLE_ID = "com.mitchellh.ghostty";

export function terminalNotifierAttempts(options: {
  title: string;
  message: string;
  imagePath: string;
  soundName: string;
  sender: string;
}): TerminalNotifierAttempt[] {
  const base = ["-title", options.title, "-message", options.message];
  const sender = options.sender.trim();
  const identityVariants: Array<{ sender?: string; activate?: string }> = [];
  if (sender) {
    if (sender.toLowerCase() === GHOSTTY_BUNDLE_ID) {
      identityVariants.push({ activate: sender });
    } else {
      identityVariants.push({ sender });
      identityVariants.push({ activate: sender });
    }
  }
  identityVariants.push({});

  const includeImageVariants = options.imagePath ? [true, false] : [false];
  const attempts: TerminalNotifierAttempt[] = [];
  const seen = new Set<string>();
  for (const identity of identityVariants) {
    for (const includeImage of includeImageVariants) {
      const args = [...base];
      if (includeImage) {
        args.push("-appIcon", options.imagePath, "-contentImage", options.imagePath);
      }
      if (options.soundName) {
        args.push("-sound", options.soundName);
      }
      if (identity.sender) {
        args.push("-sender", identity.sender);
      }
      if (identity.activate) {
        args.push("-activate", identity.activate);
      }
      const key = args.join("\u0000");
      if (seen.has(key)) {
        continue;
      }
      seen.add(key);
      attempts.push({ args, soundSent: Boolean(options.soundName) });
    }
  }
  return attempts;
}

function notifyVisualMac(options: {
  title: string;
  message: string;
  imagePath: string;
  soundName: string;
}): { visualSent: boolean; soundSent: boolean } {
  const notifier = terminalNotifierPath();
  if (notifier) {
    const attempts = terminalNotifierAttempts({
      title: options.title,
      message: options.message,
      imagePath: options.imagePath,
      soundName: options.soundName,
      sender: cleanText(process.env.OPENCODE_NOTIFY_SENDER),
    });
    for (const attempt of attempts) {
      const result = spawnSync(notifier, attempt.args, {
        stdio: ["ignore", "ignore", "ignore"],
        timeout: 1200,
      });
      if (result.status === 0) {
        return { visualSent: true, soundSent: attempt.soundSent };
      }
    }
  }

  const script = `display notification ${JSON.stringify(options.message)} with title ${JSON.stringify(options.title)}`;
  const fallback = spawnSync("osascript", ["-e", script], {
    stdio: ["ignore", "ignore", "ignore"],
    timeout: 1000,
  });
  return { visualSent: fallback.status === 0, soundSent: false };
}

function notifyVisualLinux(
  title: string,
  message: string,
  imagePath: string,
): boolean {
  const args = imagePath ? ["-i", imagePath, title, message] : [title, message];
  const result = spawnSync("notify-send", args, {
    stdio: ["ignore", "ignore", "ignore"],
    timeout: 1000,
  });
  return result.status === 0;
}

function notifyVisual(options: {
  eventName: NotifyEvent;
  state: NotifyState;
  directory: string;
  content: NotifyContent;
}): { visualSent: boolean; soundSent: boolean } {
  const title = titleWithIcon(
    options.eventName,
    options.state,
    options.content.title,
  );
  const imagePath = iconImagePath(
    options.eventName,
    options.state,
    options.directory,
  );

  if (process.platform === "darwin") {
    return notifyVisualMac({
      title,
      message: options.content.message,
      imagePath,
      soundName: soundNameForEvent(options.state, options.eventName),
    });
  }
  if (process.platform === "linux") {
    return {
      visualSent: notifyVisualLinux(title, options.content.message, imagePath),
      soundSent: false,
    };
  }
  return { visualSent: false, soundSent: false };
}

function notifySound(
  eventName: NotifyEvent,
  state: NotifyState,
  directory: string,
): boolean {
  const custom = customSoundPath(state, eventName, directory);
  if (custom && process.platform === "darwin") {
    const result = spawnSync("afplay", [custom], {
      stdio: ["ignore", "ignore", "ignore"],
      timeout: 2000,
    });
    return result.status === 0;
  }

  if (process.platform === "darwin") {
    const systemSound = `/System/Library/Sounds/${soundNameForEvent(state, eventName)}.aiff`;
    if (existsSync(systemSound)) {
      const result = spawnSync("afplay", [systemSound], {
        stdio: ["ignore", "ignore", "ignore"],
        timeout: 1500,
      });
      if (result.status === 0) {
        return true;
      }
    }
  }

  try {
    process.stderr.write("\u0007");
    return true;
  } catch {
    return false;
  }
}

function cleanText(value: unknown): string {
  if (typeof value !== "string") {
    return "";
  }
  return value
    .replace(/\b(?:undefined|null|nan|none|\(null\))\b/gi, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function truncateText(value: string, maxChars: number): string {
  if (value.length <= maxChars) {
    return value;
  }
  if (maxChars <= 3) {
    return value.slice(0, maxChars);
  }
  return `${value.slice(0, maxChars - 3).trimEnd()}...`;
}

function firstPropertyText(
  properties: Record<string, unknown>,
  keys: string[],
): string {
  for (const key of keys) {
    const value = cleanText(properties[key]);
    if (value) {
      return value;
    }
  }
  return "";
}

function contextParts(payload: EventPayload): string[] {
  const properties =
    payload.properties && typeof payload.properties === "object"
      ? payload.properties
      : {};
  const input =
    payload.input && typeof payload.input === "object"
      ? (payload.input as Record<string, unknown>)
      : {};
  const sessionId =
    firstPropertyText(properties, ["session_id", "sessionID", "sessionId"]) ||
    firstPropertyText(input, ["sessionID", "sessionId"]);
  const windowId =
    firstPropertyText(properties, ["window_id", "windowID", "windowId", "window"]) ||
    firstPropertyText(input, ["windowID", "windowId"]);
  const workingDir =
    cleanText(payload.directory) ||
    firstPropertyText(properties, ["cwd", "working_directory", "workingDirectory", "directory"]);
  const tmuxLabel =
    firstPropertyText(properties, ["tmux", "tmux_session", "tmuxSession", "tmux_window", "tmuxWindow"]) ||
    firstPropertyText(input, ["tmux", "tmuxSession", "tmuxWindow"]) ||
    cleanText(process.env.OPENCODE_TMUX_LABEL);
  const tmuxAuto = (() => {
    if (tmuxLabel) {
      return "";
    }
    const direct = cleanText(process.env.TMUX_SESSION || process.env.TMUX_WINDOW || process.env.TMUX_PANE);
    if (direct) {
      return direct;
    }
    if (!process.env.TMUX) {
      return "";
    }
    const probe = spawnSync("tmux", ["display-message", "-p", "#S.#I"], {
      stdio: ["ignore", "pipe", "ignore"],
      timeout: 120,
    });
    if (probe.status !== 0) {
      return "";
    }
    return cleanText(probe.stdout.toString("utf8"));
  })();

  const parts: string[] = [];
  if (workingDir) {
    const homeProjects = `${homedir()}/Codes/Projects/`;
    const shortDir = workingDir.startsWith(homeProjects)
      ? workingDir.slice(homeProjects.length)
      : basename(workingDir);
    parts.push(shortDir);
  }
  const tmuxContext = tmuxLabel || tmuxAuto;
  if (tmuxContext) {
    parts.push(`tmux ${tmuxContext}`);
  }
  if (sessionId) {
    parts.push(`s:${sessionId}`);
  }
  if (windowId) {
    parts.push(`w:${windowId}`);
  }
  return parts;
}

function headlineFromPayload(payload: EventPayload): string {
  const properties =
    payload.properties && typeof payload.properties === "object"
      ? payload.properties
      : {};
  const input =
    payload.input && typeof payload.input === "object"
      ? (payload.input as Record<string, unknown>)
      : {};
  const raw =
    firstPropertyText(properties, [
      "session_title",
      "sessionTitle",
      "task_title",
      "taskTitle",
      "title",
      "summary",
      "headline",
    ]) || firstPropertyText(input, ["sessionTitle", "title", "summary"]);
  if (!raw) {
    return "";
  }
  return raw.split(/\s+/).filter(Boolean).slice(0, 4).join(" ");
}

function messageWithContext(
  baseMessage: string,
  payload: EventPayload,
  style: NotifyStyle,
): string {
  const parts = contextParts(payload);
  if (!parts.length) {
    return baseMessage;
  }
  const maxChars = style === "detailed" ? 230 : 170;
  return truncateText(`${baseMessage} [${parts.join(" | ")}]`, maxChars);
}

function messageForEvent(
  eventName: NotifyEvent,
  payload: EventPayload,
  style: NotifyStyle,
): NotifyContent {
  const properties =
    payload.properties && typeof payload.properties === "object"
      ? payload.properties
      : {};
  if (eventName === "complete") {
    const head = headlineFromPayload(payload);
    return {
      title: head ? `OpenCode • ${head}` : "OpenCode Complete",
      message: messageWithContext(
        "Done.",
        payload,
        style,
      ),
    };
  }
  if (eventName === "error") {
    const head = headlineFromPayload(payload);
    const detail = truncateText(
      firstPropertyText(properties, ["message", "error", "reason", "detail"]),
      style === "detailed" ? 180 : 120,
    );
    return {
      title: head ? `OpenCode • ${head}` : "OpenCode Needs Attention",
      message: messageWithContext(
        detail ? `Needs attention: ${detail}` : "Could not finish task.",
        payload,
        style,
      ),
    };
  }
  if (eventName === "permission") {
    const head = headlineFromPayload(payload);
    const detail = truncateText(
      firstPropertyText(properties, [
        "permission",
        "action",
        "command",
        "tool",
      ]),
      style === "detailed" ? 140 : 100,
    );
    return {
      title: head ? `OpenCode • ${head}` : "OpenCode Permission",
      message: messageWithContext(
        detail ? `Action needed: ${detail}` : "Permission prompt requires input.",
        payload,
        style,
      ),
    };
  }
  const question = truncateText(
    firstPropertyText(properties, ["question", "prompt", "title", "label"]),
    style === "detailed" ? 140 : 100,
  );
  const head = headlineFromPayload(payload);
  return {
    title: head ? `OpenCode • ${head}` : "OpenCode Input Needed",
    message: messageWithContext(
      question ? `Input needed: ${question}` : "Question requires input.",
      payload,
      style,
    ),
  };
}

export function createNotifyEventsHook(options: {
  directory: string;
  enabled: boolean;
  cooldownMs: number;
  style: NotifyStyle;
  now?: () => number;
  loadState?: (directory: string) => NotifyState;
  notify?: (
    eventName: NotifyEvent,
    visual: boolean,
    sound: boolean,
    content: NotifyContent,
    state: NotifyState,
    directory: string,
  ) => {
    visualSent: boolean;
    soundSent: boolean;
  };
}): GatewayHook {
  const lastSent = new Map<NotifyEvent, number>();
  const now = options.now ?? ((): number => Date.now());
  const loadStateFn = options.loadState ?? loadNotifyState;
  const notifyFn =
    options.notify ??
    ((
      eventName: NotifyEvent,
      visual: boolean,
      sound: boolean,
      content: NotifyContent,
      state: NotifyState,
      directory: string,
    ): {
      visualSent: boolean;
      soundSent: boolean;
    } => {
      const visualResult = visual
        ? notifyVisual({
            eventName,
            state,
            directory,
            content,
          })
        : { visualSent: false, soundSent: false };
      const soundSent =
        sound && !visualResult.soundSent
          ? notifySound(eventName, state, directory)
          : visualResult.soundSent;
      return {
        visualSent: visualResult.visualSent,
        soundSent,
      };
    });

  return {
    id: "notify-events",
    priority: 175,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled) {
        return;
      }
      const eventPayload = (payload ?? {}) as EventPayload;
      const directory =
        typeof eventPayload.directory === "string" &&
        eventPayload.directory.trim()
          ? eventPayload.directory
          : options.directory;
      const eventName = eventFromType(type, eventPayload);
      if (!eventName) {
        return;
      }
      const state = loadStateFn(directory);
      if (!state.enabled || !state.events[eventName]) {
        return;
      }

      const visual = state.visual.enabled && state.channels[eventName].visual;
      const sound = state.sound.enabled && state.channels[eventName].sound;
      if (!visual && !sound) {
        return;
      }

      const ts = now();
      const previous = lastSent.get(eventName) ?? 0;
      if (
        options.cooldownMs > 0 &&
        previous > 0 &&
        ts - previous < options.cooldownMs
      ) {
        writeGatewayEventAudit(directory, {
          hook: "notify-events",
          stage: "skip",
          reason_code: "cooldown_active",
          event_type: type,
          notify_event: eventName,
          cooldown_ms: options.cooldownMs,
        });
        return;
      }

      const content = messageForEvent(eventName, eventPayload, options.style);
      const resolvedImagePath = iconImagePath(eventName, state, directory);
      const result = notifyFn(
        eventName,
        visual,
        sound,
        content,
        state,
        directory,
      );
      lastSent.set(eventName, ts);
      writeGatewayEventAudit(directory, {
        hook: "notify-events",
        stage: "state",
        reason_code:
          result.visualSent || result.soundSent
            ? "notification_sent"
            : "notification_not_sent",
        event_type: type,
        notify_event: eventName,
        visual_enabled: visual,
        sound_enabled: sound,
        visual_sent: result.visualSent,
        sound_sent: result.soundSent,
        icon_mode: state.icons.mode,
        icon_version: state.icons.version,
        icon_image_path: resolvedImagePath,
        icon_image_present: Boolean(resolvedImagePath),
        sound_theme: state.sound.theme,
      });
    },
  };
}
