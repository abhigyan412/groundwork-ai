// The embeddable chat widget (/a/:token, docs/frontend.md §6.7). Lazy-loaded with its own layout;
// imports only the public API client, the evidence trail and UI primitives, never dashboard code.
import { useQuery } from "@tanstack/react-query";
import { ArrowUp, RotateCcw } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { useParams } from "react-router-dom";
import { EvidenceTrail } from "@/components/evidence-trail/EvidenceTrail";
import { Skeleton } from "@/components/ui/states";
import { cn } from "@/lib/cn";
import { ApiError, messageOf } from "@/lib/errors";
import { formatReference } from "@/lib/format";
import { askQuestion, getPublicAssistant } from "@/lib/public-api";
import type { AskResult } from "@/lib/types";

type Message =
  | { id: number; role: "user"; text: string }
  | { id: number; role: "assistant"; result: AskResult }
  | { id: number; role: "error"; text: string; question: string };

const SLOW_AFTER_MS = 4000;

function Inactive() {
  return (
    <div className="flex h-dvh flex-col items-center justify-center bg-surface px-6 text-center">
      <p className="text-base font-semibold text-ink">This assistant link is no longer active.</p>
      <p className="mt-2 text-sm text-slate">Ask the site owner for the current link.</p>
    </div>
  );
}

function AssistantBubble({ result }: { result: AskResult }) {
  const showTrail = result.route !== null && (result.verdicts.length > 0 || result.references.length > 0);
  return (
    <div className="max-w-[92%] space-y-2">
      <div className="rounded-bubble rounded-tl-chip border border-line bg-surface px-4 py-3 text-sm leading-relaxed text-ink">
        <p className="whitespace-pre-line">{result.answer}</p>
        {result.references.length > 0 ? (
          <ul className="mt-2 space-y-0.5">
            {result.references.map((r) => (
              <li key={`${r.file}-${r.page}`} className="font-serif text-xs text-slate">
                {formatReference(r.file, r.page)}
              </li>
            ))}
          </ul>
        ) : null}
      </div>
      {showTrail ? <EvidenceTrail trail={result} collapsible className="text-left" /> : null}
    </div>
  );
}

function Typing({ slow }: { slow: boolean }) {
  return (
    <div className="flex flex-col items-start gap-1" role="status" aria-label="Waiting for the answer">
      <div className="flex gap-1 rounded-bubble rounded-tl-chip border border-line bg-surface px-4 py-3.5">
        {[0, 150, 300].map((delay) => (
          <span
            key={delay}
            className="size-1.5 animate-bounce rounded-full bg-slate/60"
            style={{ animationDelay: `${delay}ms` }}
          />
        ))}
      </div>
      {slow ? <p className="pl-1 text-xs text-slate">Checking the documents…</p> : null}
    </div>
  );
}

export function WidgetPage() {
  const { token = "" } = useParams();
  const info = useQuery({
    queryKey: ["public-assistant", token],
    queryFn: () => getPublicAssistant(token),
    retry: (count, e) => !(e instanceof ApiError && e.status === 401) && count < 2,
    staleTime: Infinity,
  });
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState(false);
  const [slow, setSlow] = useState(false);
  const [inactive, setInactive] = useState(false);
  const nextId = useRef(1);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, pending]);

  // Inside the JS embed's panel, keystrokes don't reach the host page, so tell the parent
  // (public/embed.js) to close on Escape. The message carries no data.
  useEffect(() => {
    if (window.parent === window) return;
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") window.parent.postMessage({ type: "assistant:close" }, "*");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  async function ask(question: string) {
    const q = question.trim();
    if (!q || pending) return;
    setMessages((m) => [...m, { id: nextId.current++, role: "user", text: q }]);
    setDraft("");
    setPending(true);
    setSlow(false);
    const timer = window.setTimeout(() => setSlow(true), SLOW_AFTER_MS);
    try {
      const result = await askQuestion(token, q);
      setMessages((m) => [...m, { id: nextId.current++, role: "assistant", result }]);
      if (result.outcome === "needs_info") window.setTimeout(() => inputRef.current?.focus(), 0);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        setInactive(true);
      } else {
        // 400/429/503 carry messages the API writes for visitors ("Today's question limit has been
        // reached", "This is taking too long right now"). Other 5xx (nginx 502/504) don't.
        const generic = "Couldn't get an answer right now. Try again.";
        const shown =
          e instanceof ApiError && [400, 429, 503].includes(e.status)
            ? e.message
            : e instanceof ApiError
              ? generic
              : messageOf(e, generic);
        setMessages((m) => [...m, { id: nextId.current++, role: "error", text: shown, question: q }]);
      }
    } finally {
      window.clearTimeout(timer);
      setPending(false);
      setSlow(false);
    }
  }

  /** Drop the failed exchange (the question and its error), then ask again. */
  function retry(question: string, errorId: number) {
    setMessages((m) => {
      const at = m.findIndex((x) => x.id === errorId);
      const before = m[at - 1];
      const dropUser = before?.role === "user" && before.text === question;
      return m.filter((_, i) => i !== at && !(dropUser && i === at - 1));
    });
    void ask(question);
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void ask(draft);
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void ask(draft);
  }

  if (inactive || (info.error instanceof ApiError && info.error.status === 401)) return <Inactive />;

  return (
    <div className="flex h-dvh flex-col bg-canvas">
      <header className="border-b border-line bg-surface px-4 py-3">
        {info.isPending ? (
          <Skeleton className="h-5 w-40" />
        ) : (
          <p className="truncate text-base font-semibold text-ink">{info.data?.org_name ?? "Assistant"}</p>
        )}
        <p className="text-xs text-slate">Ask about our policies</p>
      </header>

      <div className="flex-1 overflow-y-auto px-3 py-4 sm:px-4">
        {info.isError ? (
          <div role="alert" className="rounded-panel border border-line bg-surface p-4 text-sm text-ink">
            Couldn't load the assistant.{" "}
            <button type="button" className="font-semibold text-teal underline-offset-4 hover:underline" onClick={() => void info.refetch()}>
              Try again
            </button>
          </div>
        ) : null}

        {messages.length === 0 && info.data ? (
          <div className="mb-4">
            <p className="text-sm text-slate">Try asking</p>
            <div className="mt-2 flex flex-col items-start gap-2">
              {info.data.suggested_questions.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => void ask(s)}
                  className="rounded-bubble border border-line bg-surface px-3 py-1.5 text-left text-sm text-ink hover:border-teal hover:text-teal"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : null}

        {/* The chat log is announced to screen readers as it grows. */}
        <div className="space-y-4" aria-live="polite" aria-relevant="additions">
          {messages.map((m) =>
            m.role === "user" ? (
              <div key={m.id} className="flex justify-end">
                <p className="max-w-[85%] rounded-bubble rounded-tr-chip bg-teal-tint px-4 py-2.5 text-sm whitespace-pre-line text-ink">
                  {m.text}
                </p>
              </div>
            ) : m.role === "assistant" ? (
              <div key={m.id}>
                <AssistantBubble result={m.result} />
              </div>
            ) : (
              <div key={m.id} role="alert" className="max-w-[92%] rounded-bubble rounded-tl-chip border border-notmet/30 bg-notmet-tint px-4 py-3 text-sm text-ink">
                <p>{m.text}</p>
                <button
                  type="button"
                  onClick={() => retry(m.question, m.id)}
                  className="mt-2 inline-flex items-center gap-1.5 font-semibold text-ink underline-offset-4 hover:underline"
                >
                  <RotateCcw className="size-3.5" strokeWidth={1.75} aria-hidden="true" />
                  Try again
                </button>
              </div>
            ),
          )}
        </div>
        {pending ? <div className="mt-4"><Typing slow={slow} /></div> : null}
        <div ref={endRef} />
      </div>

      <form onSubmit={onSubmit} className="border-t border-line bg-surface p-3">
        <div className="flex items-end gap-2">
          <label htmlFor="question" className="sr-only">
            Your question
          </label>
          <textarea
            id="question"
            ref={inputRef}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKeyDown}
            rows={1}
            maxLength={1000}
            placeholder="Ask a question…"
            className={cn(
              "max-h-32 min-h-10 flex-1 resize-none rounded-control border border-line bg-surface px-3 py-2 text-sm text-ink",
              "field-sizing-content placeholder:text-slate/70",
            )}
          />
          <button
            type="submit"
            disabled={pending || draft.trim().length === 0}
            className="flex size-10 shrink-0 items-center justify-center rounded-control bg-ink text-surface disabled:opacity-40"
            aria-label="Send"
          >
            <ArrowUp className="size-4" strokeWidth={2} aria-hidden="true" />
          </button>
        </div>
        <p className="mt-1.5 text-xs text-slate">Answers come only from this organization's documents.</p>
      </form>
    </div>
  );
}
