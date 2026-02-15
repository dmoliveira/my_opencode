import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
// Finds nearest ancestor file from start directory.
export function findNearestFile(startDirectory, fileName) {
    let current = resolve(startDirectory);
    while (true) {
        const candidate = join(current, fileName);
        if (existsSync(candidate)) {
            return candidate;
        }
        const parent = dirname(current);
        if (parent === current) {
            break;
        }
        current = parent;
    }
    return null;
}
