export type FrontendLogEntry = {
  timestamp: string;
  level: "info" | "warn" | "error";
  scope: string;
  message: string;
};

const entries: FrontendLogEntry[] = [];
const listeners = new Set<() => void>();
const MAX_ENTRIES = 300;

export function recordFrontendLog(level: FrontendLogEntry["level"], scope: string, message: string) {
  entries.unshift({
    timestamp: new Date().toISOString(),
    level,
    scope,
    message,
  });
  if (entries.length > MAX_ENTRIES) {
    entries.length = MAX_ENTRIES;
  }
  listeners.forEach((listener) => listener());
}

export function getFrontendLogs(limit = 200) {
  return entries.slice(0, limit);
}

export function subscribeFrontendLogs(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
