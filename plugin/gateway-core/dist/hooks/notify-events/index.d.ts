import type { GatewayHook } from "../registry.js";
type NotifyEvent = "complete" | "error" | "permission" | "question";
interface NotifyState {
    enabled: boolean;
    sound: {
        enabled: boolean;
    };
    visual: {
        enabled: boolean;
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
type NotifyStyle = "brief" | "detailed";
export declare function createNotifyEventsHook(options: {
    directory: string;
    enabled: boolean;
    cooldownMs: number;
    style: NotifyStyle;
    now?: () => number;
    loadState?: (directory: string) => NotifyState;
    notify?: (eventName: NotifyEvent, visual: boolean, sound: boolean, content: NotifyContent) => {
        visualSent: boolean;
        soundSent: boolean;
    };
}): GatewayHook;
export {};
