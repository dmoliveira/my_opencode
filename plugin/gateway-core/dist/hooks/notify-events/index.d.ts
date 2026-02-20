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
    visual: {
        enabled: boolean;
    };
    icons: {
        enabled: boolean;
        version: string;
        mode: NotifyIconMode;
    };
    events: Record<NotifyEvent, boolean>;
    channels: Record<NotifyEvent, {
        sound: boolean;
        visual: boolean;
    }>;
}
interface NotifyContent {
    title: string;
    message: string;
}
interface TerminalNotifierAttempt {
    args: string[];
    soundSent: boolean;
}
export declare function terminalNotifierAttempts(options: {
    title: string;
    message: string;
    imagePath: string;
    soundName: string;
    sender: string;
}): TerminalNotifierAttempt[];
export declare function sendBasicVisualNotification(title: string, message: string): boolean;
export declare function createNotifyEventsHook(options: {
    directory: string;
    enabled: boolean;
    cooldownMs: number;
    style: NotifyStyle;
    now?: () => number;
    loadState?: (directory: string) => NotifyState;
    notify?: (eventName: NotifyEvent, visual: boolean, sound: boolean, content: NotifyContent, state: NotifyState, directory: string) => {
        visualSent: boolean;
        soundSent: boolean;
    };
}): GatewayHook;
export {};
