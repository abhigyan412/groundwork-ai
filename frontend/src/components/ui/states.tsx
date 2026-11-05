// Loading, empty and error states (docs/frontend.md §7): every data view has all three.
import { AlertCircle } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { Button } from "./button";

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-control bg-line/60", className)} aria-hidden="true" />;
}

/** Skeleton rows matching a table's final layout. */
export function SkeletonRows({ rows = 3, className }: { rows?: number; className?: string }) {
  return (
    <div className={cn("space-y-3", className)} role="status" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-10 w-full" />
      ))}
    </div>
  );
}

export function EmptyState({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="rounded-panel border border-dashed border-line bg-surface px-6 py-10 text-center">
      <p className="mx-auto max-w-md text-base text-slate">{children}</p>
      {action ? <div className="mt-4 flex justify-center">{action}</div> : null}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div
      role="alert"
      className="flex flex-wrap items-center gap-3 rounded-panel border border-notmet/30 bg-notmet-tint px-4 py-3 text-sm text-ink"
    >
      <AlertCircle className="size-4 shrink-0 text-notmet" strokeWidth={1.75} aria-hidden="true" />
      <span className="flex-1">{message}</span>
      {onRetry ? (
        <Button variant="secondary" size="sm" onClick={onRetry}>
          Try again
        </Button>
      ) : null}
    </div>
  );
}
