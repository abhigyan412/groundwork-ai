// Usage counts + recent questions, with a side panel showing the evidence trail (§6.6).
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { PageHeader } from "@/app/AppShell";
import { EvidenceTrail, type Trail } from "@/components/evidence-trail/EvidenceTrail";
import { Dialog, DialogContent } from "@/components/ui/overlay";
import { EmptyState, ErrorState, Skeleton, SkeletonRows } from "@/components/ui/states";
import { api, unwrap } from "@/lib/api";
import { cn } from "@/lib/cn";
import { messageOf } from "@/lib/errors";
import { formatFullDate, formatReference, formatWhen } from "@/lib/format";
import type { Outcome, QuestionOut, Route } from "@/lib/types";

const ROUTE: Record<Route, string> = {
  direct: "Direct answer",
  procedural: "Steps",
  policy: "Policy check",
  decision: "Decision check",
  comparison: "Comparison",
};

const OUTCOME: Record<Outcome, string> = {
  answered: "Answered",
  unanswered: "Not in documents",
  needs_info: "Needed info",
  review: "For review",
};

/** Decision questions show their result ("Not eligible"); others their outcome. */
function outcomeText(q: QuestionOut): string {
  if (q.outcome === "answered" && q.route === "decision") {
    if (q.overall === "TRUE") return "Eligible";
    if (q.overall === "FALSE") return "Not eligible";
  }
  return OUTCOME[q.outcome];
}

type CountKey = "asked" | "answered" | "needs_info" | "unanswered" | "review";
const COUNTS: { key: CountKey; label: string }[] = [
  { key: "asked", label: "Asked" },
  { key: "answered", label: "Answered" },
  { key: "needs_info", label: "Needed info" },
  { key: "unanswered", label: "Not in documents" },
  { key: "review", label: "For review" },
];

function useUsage() {
  return useQuery({ queryKey: ["usage"], queryFn: () => unwrap(api.GET("/api/admin/usage")), refetchInterval: 30_000 });
}

export function Usage() {
  const usage = useUsage();
  const questions = useQuery({
    queryKey: ["questions"],
    queryFn: () => unwrap(api.GET("/api/admin/questions", { params: { query: { limit: 50 } } })),
    refetchInterval: 30_000,
  });
  const [selected, setSelected] = useState<QuestionOut | null>(null);

  return (
    <>
      <PageHeader title="Usage" />

      {/* Counts: one row of plain numbers with labels, not five identical cards. */}
      {usage.isPending ? (
        <Skeleton className="h-14 w-full max-w-2xl" />
      ) : usage.isError ? (
        <ErrorState message={messageOf(usage.error, "Couldn't load usage.")} onRetry={() => void usage.refetch()} />
      ) : (
        <dl className="flex flex-wrap gap-x-10 gap-y-4">
          {COUNTS.map(({ key, label }) => (
            <div key={key}>
              <dt className="text-sm text-slate">{label}</dt>
              <dd className="tabular text-xl font-semibold text-ink">{usage.data[key]}</dd>
            </div>
          ))}
        </dl>
      )}

      <section className="mt-10" aria-labelledby="recent">
        <h2 id="recent" className="text-base font-semibold text-ink">
          Recent questions
        </h2>
        <div className="mt-4">
          {questions.isPending ? (
            <SkeletonRows rows={5} />
          ) : questions.isError ? (
            <ErrorState message={messageOf(questions.error, "Couldn't load recent questions.")} onRetry={() => void questions.refetch()} />
          ) : questions.data.questions.length === 0 ? (
            <EmptyState>No questions yet. Share your assistant link, or try it from the Assistant page.</EmptyState>
          ) : (
            <ul className="divide-y divide-line rounded-panel border border-line bg-surface">
              {questions.data.questions.map((q) => (
                <li key={q.id}>
                  <button
                    type="button"
                    onClick={() => setSelected(q)}
                    className="grid w-full grid-cols-1 gap-1 px-4 py-3 text-left hover:bg-canvas/60 sm:grid-cols-[1fr_9rem_9rem_6rem] sm:items-center sm:gap-4"
                  >
                    <span className="truncate text-sm text-ink">{q.question}</span>
                    <span className="text-xs text-slate sm:text-sm">{q.route ? ROUTE[q.route] : "—"}</span>
                    <span className={cn("text-xs sm:text-sm", q.outcome === "unanswered" || q.outcome === "review" ? "text-slate" : "text-ink")}>
                      {outcomeText(q)}
                    </span>
                    <span className="text-xs text-slate sm:text-right sm:text-sm" title={formatFullDate(q.created_at)}>
                      {formatWhen(q.created_at)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>

      <Dialog open={selected !== null} onOpenChange={(open) => !open && setSelected(null)}>
        {selected ? (
          <DialogContent side title={selected.question} description={formatFullDate(selected.created_at)}>
            <h3 className="text-sm font-semibold text-slate">Answer</h3>
            <p className="mt-1 text-base whitespace-pre-line text-ink">{selected.answer}</p>
            {selected.references.length > 0 ? (
              <ul className="mt-3 space-y-0.5">
                {selected.references.map((r) => (
                  <li key={`${r.file}-${r.page}`} className="font-serif text-sm text-slate">
                    {formatReference(r.file, r.page)}
                  </li>
                ))}
              </ul>
            ) : null}
            <EvidenceTrail
              className="mt-6"
              trail={{
                route: selected.route,
                verdicts: selected.verdicts,
                timings_ms: selected.timings_ms as Trail["timings_ms"],
                overall: selected.overall,
                outcome: selected.outcome,
                references: selected.references,
              }}
            />
          </DialogContent>
        ) : null}
      </Dialog>
    </>
  );
}
