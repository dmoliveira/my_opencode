export declare function parseSlashCommand(raw: string): {
    name: string;
    args: string;
};
export declare function isAutopilotCommand(name: string): boolean;
export declare function isAutopilotStopCommand(name: string): boolean;
