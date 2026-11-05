// Widget API: assistant token only. No session, no redirects, nothing from the dashboard.
import { apiErrorFrom } from "./errors";
import type { AskResult, PublicAssistant } from "./types";

export async function getPublicAssistant(token: string): Promise<PublicAssistant> {
  const r = await fetch(`/api/public/assistant/${encodeURIComponent(token)}`);
  if (!r.ok) throw await apiErrorFrom(r, "Couldn't load the assistant.");
  return (await r.json()) as PublicAssistant;
}

export async function askQuestion(
  token: string,
  question: string,
  signal?: AbortSignal,
): Promise<AskResult> {
  const r = await fetch("/api/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token, question }),
    signal,
  });
  if (!r.ok) throw await apiErrorFrom(r, "Couldn't get an answer right now. Try again.");
  return (await r.json()) as AskResult;
}
