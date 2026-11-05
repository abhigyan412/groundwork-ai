// The signature component (docs/frontend.md §5): how an answer was reached, with its evidence.
// Used collapsed under widget answers, expanded on the landing page and in the usage panel.
// Never shows raw JSON, prompts, model names or confidence decimals.
import { ChevronDown } from "lucide-react";
import { useId, useState } from "react";
import { Tooltip } from "@/components/ui/tooltip";
import { cn } from "@/lib/cn";
import { formatReference } from "@/lib/format";
import type { AskResult, Reference, Route, Verdict } from "@/lib/types";

export type Trail = Pick<AskResult, "route" | "verdicts" | "timings_ms" | "overall" | "outcome"> & {
  references?: Reference[];
};

const ROUTE_LABEL: Record<Route, string> = {
  direct: "Direct answer",
  procedural: "Steps from the documents",
  policy: "Policy check",
  decision: "Decision check",
  comparison: "Comparison",
};

type Tone = "met" | "notmet" | "needinfo";

function chip(v: Verdict): { text: string; tone: Tone } {
  if (v.kind === "choice" || v.kind === "score") {
    return v.value === "TRUE"
      ? { text: "Best", tone: "met" }
      : v.value === "FALSE"
        ? { text: "Other", tone: "notmet" }
        : { text: "Unclear", tone: "needinfo" };
  }
  if (v.kind === "policy") {
    return v.value === "TRUE"
      ? { text: "Yes", tone: "met" }
      : v.value === "FALSE"
        ? { text: "No", tone: "notmet" }
        : { text: "Unclear", tone: "needinfo" };
  }
  if (v.value === "TRUE") return { text: "Met", tone: "met" };
  if (v.value === "FALSE") return { text: "Not met", tone: "notmet" };
  return { text: v.missing_fact ? "Need info" : "Unclear", tone: "needinfo" };
}

const TONE_CLASS: Record<Tone, string> = {
  met: "bg-met-tint text-met",
  notmet: "bg-notmet-tint text-notmet",
  needinfo: "bg-needinfo-tint text-needinfo",
};

function confidenceText(v: Verdict): string {
  if (v.value === "UNKNOWN") {
    return v.missing_fact ? "We need this detail from you." : (v.reason ?? "The documents don't settle this.");
  }
  if (v.confidence >= 0.9) return "High confidence";
  if (v.confidence >= 0.7) return "Medium confidence";
  return "Low confidence";
}

function userValue(value: Verdict["user_value"]): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value === "boolean") return value ? "yes" : "no";
  return String(value);
}

function resultLine(t: Trail): string | null {
  if (t.route === "decision" && t.verdicts.length) {
    if (t.overall === "TRUE") return "Result: all conditions are met";
    if (t.overall === "FALSE") return "Result: not met (a required condition fails)";
    return t.outcome === "needs_info"
      ? "Result: needs more information from you"
      : "Result: the documents don't settle this";
  }
  if (t.route === "policy" && t.verdicts.length) {
    if (t.overall === "TRUE") return "Result: the documents say yes";
    if (t.overall === "FALSE") return "Result: the documents say no";
    return "Result: the documents don't clearly say";
  }
  if (t.route === "comparison" && t.verdicts.length) {
    const winner = t.verdicts.find((v) => v.value === "TRUE");
    return winner
      ? `Result: ${winner.label.split(":")[0]}`
      : "Result: the documents don't clearly favour one option";
  }
  return null;
}

function TimingStrip({ verdicts, timings }: { verdicts: Verdict[]; timings: Trail["timings_ms"] }) {
  const decisions = timings["decisions"];
  if (!decisions || typeof decisions !== "object") return null;
  const entries = Object.entries(decisions as Record<string, number>);
  if (entries.length === 0) return null;
  const max = Math.max(...entries.map(([, ms]) => ms), 1);
  const label = (id: string) =>
    id === "compare" ? "Compare" : (verdicts.find((v) => v.id === id)?.label ?? id);
  return (
    <div className="mt-4 border-t border-line pt-3">
      <p className="text-xs font-semibold text-slate">
        {entries.length > 1 ? "Checks ran in parallel" : "Check"}
      </p>
      <ul className="mt-2 space-y-1.5">
        {entries.map(([id, ms]) => (
          <li key={id} className="grid grid-cols-[minmax(0,9rem)_1fr_3.5rem] items-center gap-3 text-xs">
            <span className="truncate text-slate" title={label(id)}>
              {label(id)}
            </span>
            {/* Every bar starts at the same x: parallel work is visible at a glance. */}
            <span className="h-1.5 rounded-full bg-canvas">
              <span
                className="block h-1.5 rounded-full bg-teal"
                style={{ width: `max(2px, ${(ms / max) * 100}%)` }}
              />
            </span>
            <span className="tabular text-right text-slate">{ms} ms</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function VerdictRow({ v }: { v: Verdict }) {
  const c = chip(v);
  const you = userValue(v.user_value);
  return (
    <li className="grid grid-cols-[5.5rem_1fr] gap-x-3 gap-y-1 py-2.5">
      <Tooltip content={confidenceText(v)}>
        <span
          tabIndex={0}
          className={cn(
            "h-fit w-fit rounded-chip px-2 py-0.5 text-xs font-semibold whitespace-nowrap",
            TONE_CLASS[c.tone],
          )}
        >
          {c.text}
        </span>
      </Tooltip>
      <div className="min-w-0">
        <div className="flex flex-wrap items-baseline justify-between gap-x-3">
          <span className="text-sm text-ink">{v.label}</span>
          {you !== null ? <span className="tabular text-xs text-slate">you: {you}</span> : null}
          {v.detail ? <span className="tabular text-xs text-slate">{v.detail}</span> : null}
        </div>
        {v.source ? (
          <figure className="mt-1">
            <blockquote className="font-serif text-sm text-ink/90">“{v.source.excerpt}”</blockquote>
            <figcaption className="mt-0.5 font-serif text-xs text-slate">
              {formatReference(v.source.file, v.source.page)}
            </figcaption>
          </figure>
        ) : v.missing_fact ? (
          <p className="mt-1 text-xs text-needinfo">Not given in your question</p>
        ) : null}
      </div>
    </li>
  );
}

export function EvidenceTrail({
  trail,
  collapsible = false,
  defaultOpen = !collapsible,
  className,
}: {
  trail: Trail;
  collapsible?: boolean;
  defaultOpen?: boolean;
  className?: string;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const bodyId = useId();
  const route = trail.route ? ROUTE_LABEL[trail.route] : null;
  const result = resultLine(trail);
  const sources = trail.verdicts.length === 0 ? (trail.references ?? []) : [];

  const header = (
    <span className="flex w-full items-center justify-between gap-3">
      <span className="flex items-center gap-1.5 text-sm font-semibold text-ink">
        How this was answered
        {collapsible ? (
          <ChevronDown
            className={cn("size-4 text-slate transition-transform", open && "rotate-180")}
            strokeWidth={1.75}
            aria-hidden="true"
          />
        ) : null}
      </span>
      {route ? <span className="text-xs text-slate">{route}</span> : null}
    </span>
  );

  return (
    <section className={cn("rounded-panel border border-line bg-surface", className)} aria-label="How this was answered">
      {collapsible ? (
        <button
          type="button"
          className="w-full rounded-panel px-4 py-3 text-left hover:bg-canvas/60"
          aria-expanded={open}
          aria-controls={bodyId}
          onClick={() => setOpen((o) => !o)}
        >
          {header}
        </button>
      ) : (
        <div className="px-4 pt-3">{header}</div>
      )}
      {open ? (
        <div id={bodyId} className={cn("px-4 pb-4", !collapsible && "pt-1")}>
          {trail.verdicts.length > 0 ? (
            <ul className="divide-y divide-line">
              {trail.verdicts.map((v) => (
                <VerdictRow key={v.id} v={v} />
              ))}
            </ul>
          ) : sources.length > 0 ? (
            <div className="pt-2">
              <p className="text-xs text-slate">Answered from</p>
              <ul className="mt-1 space-y-0.5">
                {sources.map((r) => (
                  <li key={`${r.file}-${r.page}`} className="font-serif text-sm text-ink">
                    {formatReference(r.file, r.page)}
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="pt-2 text-sm text-slate">No document passage was relevant enough to answer from.</p>
          )}
          <TimingStrip verdicts={trail.verdicts} timings={trail.timings_ms} />
          {result ? <p className="mt-3 text-sm font-semibold text-ink">{result}</p> : null}
        </div>
      ) : null}
    </section>
  );
}
