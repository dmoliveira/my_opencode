export declare function parseSlashCommand(raw: string): {
    name: string;
    args: string;
};
export declare function parseAutopilotTemplateCommand(raw: string): {
    name: string;
    args: string;
} | null;
export declare function canonicalAutopilotCommandName(name: string): string;
export declare function resolveAutopilotAction(name: string, args: string): "start" | "stop" | "none";
export declare function isAutopilotCommand(name: string): boolean;
export declare function isAutopilotStopCommand(name: string): boolean;
export declare function parseCompletionMode(args: string): "promise" | "objective";
export declare function parseCompletionPromise(args: string, fallback: string): string;
export declare function parseMaxIterations(args: string, fallback: number): number;
export declare function parseGoal(args: string): string;
export declare function parseDoneCriteria(args: string): string[];
