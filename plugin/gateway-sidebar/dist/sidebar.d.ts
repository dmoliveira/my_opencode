/** @jsxImportSource @opentui/solid */
import type { TuiPluginApi } from "@opencode-ai/plugin/tui";
export declare function shouldBindStateDirectory(filename: string | Buffer | null | undefined): boolean;
export declare function shouldApplyRefresh(closed: boolean, generation: number, latestGeneration: number): boolean;
export declare function createExecutionStatusSidebar(api: TuiPluginApi): (props: {
    sessionId: string;
}) => import("solid-js").JSX.Element;
