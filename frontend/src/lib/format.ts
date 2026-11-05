export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
const shortDay = new Intl.DateTimeFormat("en", { day: "numeric", month: "short" });
const full = new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "short" });

/** "just now", "5 minutes ago", "2h ago", "3 Nov". */
export function formatWhen(iso: string, now = Date.now()): string {
  const seconds = Math.round((now - new Date(iso).getTime()) / 1000);
  if (seconds < 45) return "just now";
  if (seconds < 3600) return rtf.format(-Math.max(1, Math.round(seconds / 60)), "minute");
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`;
  return shortDay.format(new Date(iso));
}

export function formatFullDate(iso: string): string {
  return full.format(new Date(iso));
}

/** "Scholarship_Rules.pdf, page 4" (docs/frontend.md §6.7). */
export function formatReference(file: string, page: number): string {
  return `${file}, page ${page}`;
}
