// Assistant link, embed code, live preview, reset (docs/frontend.md §6.5).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, ExternalLink } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { PageHeader } from "@/app/AppShell";
import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogTrigger } from "@/components/ui/overlay";
import { ErrorState, Skeleton } from "@/components/ui/states";
import { api, unwrap } from "@/lib/api";
import { messageOf } from "@/lib/errors";
import { formatFullDate } from "@/lib/format";
import type { AssistantLink } from "@/lib/types";

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

/** The optional JS embed (public/embed.js): a floating chat button that opens the widget. */
function scriptEmbed(url: string): string {
  return `<script src="${new URL(url).origin}/embed.js" data-assistant="${url}" async></script>`;
}

function CopyButton({ text, label, done }: { text: string; label: string; done: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <Button
      variant="secondary"
      onClick={async () => {
        if (await copyText(text)) {
          setCopied(true);
          toast.success(done);
          window.setTimeout(() => setCopied(false), 2000);
        } else {
          toast.error("Couldn't copy. Select the text and copy it instead.");
        }
      }}
    >
      {copied ? <Check strokeWidth={1.75} aria-hidden="true" /> : <Copy strokeWidth={1.75} aria-hidden="true" />}
      {label}
    </Button>
  );
}

function Section({ title, children, description }: { title: string; description?: string; children: React.ReactNode }) {
  return (
    <section className="border-t border-line py-8 first:border-t-0 first:pt-0">
      <h2 className="text-base font-semibold text-ink">{title}</h2>
      {description ? <p className="mt-1 text-sm text-slate">{description}</p> : null}
      <div className="mt-4">{children}</div>
    </section>
  );
}

export function Assistant() {
  const queryClient = useQueryClient();
  const link = useQuery({ queryKey: ["assistant"], queryFn: () => unwrap(api.GET("/api/admin/assistant")) });
  const docs = useQuery({ queryKey: ["documents"], queryFn: () => unwrap(api.GET("/api/admin/documents")) });
  const [confirmOpen, setConfirmOpen] = useState(false);
  const noneReady = docs.data ? !docs.data.documents.some((d) => d.status === "ready") : false;

  const reset = useMutation({
    mutationFn: () => unwrap(api.POST("/api/admin/assistant/regenerate")),
    onSuccess: (fresh) => {
      const { token: _token, ...rest } = fresh;
      queryClient.setQueryData<AssistantLink>(["assistant"], rest);
      setConfirmOpen(false);
      toast.success("Link reset. Update the embed code on your site.");
    },
    onError: (e) => toast.error(messageOf(e, "Couldn't reset the link. Try again.")),
  });

  return (
    <>
      <PageHeader title="Assistant" />
      {link.isPending ? (
        <div className="space-y-4">
          <Skeleton className="h-6 w-40" />
          <Skeleton className="h-11 w-full max-w-xl" />
          <Skeleton className="h-28 w-full max-w-xl" />
        </div>
      ) : link.isError ? (
        <ErrorState message={messageOf(link.error, "Couldn't load your assistant link.")} onRetry={() => void link.refetch()} />
      ) : (
        <div className="rounded-panel border border-line bg-surface px-6 py-8">
          <Section title="Assistant link" description="Anyone with this link can ask questions about your documents. No login needed.">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
              <code className="min-w-0 flex-1 truncate rounded-control border border-line bg-canvas px-3 py-2.5 text-sm text-ink" title={link.data.url}>
                {link.data.url}
              </code>
              <div className="flex gap-2">
                <CopyButton text={link.data.url} label="Copy link" done="Link copied" />
                <a
                  href={link.data.url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex h-10 items-center gap-2 rounded-control border border-line bg-surface px-4 text-sm font-semibold text-ink hover:bg-canvas"
                >
                  <ExternalLink className="size-4" strokeWidth={1.75} aria-hidden="true" />
                  Open
                </a>
              </div>
            </div>
            <p className="mt-2 text-xs text-slate">Created {formatFullDate(link.data.created_at)}</p>
          </Section>

          <Section title="Embed on your site" description="Paste this where the assistant should appear.">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start">
              <pre className="min-w-0 flex-1 overflow-x-auto rounded-control border border-line bg-canvas px-3 py-2.5 text-xs whitespace-pre-wrap break-all text-ink">
                {link.data.embed_code}
              </pre>
              <CopyButton text={link.data.embed_code} label="Copy code" done="Code copied" />
            </div>
            <details className="mt-5 group">
              <summary className="cursor-pointer text-sm font-semibold text-teal underline-offset-4 hover:underline">
                Or add a chat button instead
              </summary>
              <p className="mt-2 text-sm text-slate">
                One script tag adds a button in the corner of every page that opens the assistant.
              </p>
              <div className="mt-3 flex flex-col gap-3 sm:flex-row sm:items-start">
                <pre className="min-w-0 flex-1 overflow-x-auto rounded-control border border-line bg-canvas px-3 py-2.5 text-xs whitespace-pre-wrap break-all text-ink">
                  {scriptEmbed(link.data.url)}
                </pre>
                <CopyButton text={scriptEmbed(link.data.url)} label="Copy script" done="Script copied" />
              </div>
            </details>
          </Section>

          <Section title="Preview" description="This is the live assistant, exactly as visitors will see it.">
            {noneReady ? (
              <p className="mb-4 rounded-control bg-needinfo-tint px-3 py-2 text-sm text-ink" role="status">
                Upload at least one document so the assistant has something to answer from.{" "}
                <Link to="/app/documents" className="font-semibold text-teal underline-offset-4 hover:underline">
                  Go to documents
                </Link>
              </p>
            ) : null}
            <iframe
              key={link.data.url}
              src={link.data.url}
              title="Assistant preview"
              className="h-[600px] w-full max-w-[400px] rounded-panel border border-line bg-surface"
            />
          </Section>

          <Section title="Reset link" description="Anyone using the old link or embed will lose access.">
            <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
              <DialogTrigger asChild>
                <Button variant="secondary" className="text-notmet">
                  Reset link
                </Button>
              </DialogTrigger>
              <DialogContent
                title="Reset the assistant link?"
                description="The current link and embed code stop working immediately. You'll need to update them on your site."
              >
                <div className="flex justify-end gap-3">
                  <DialogClose asChild>
                    <Button variant="secondary">Cancel</Button>
                  </DialogClose>
                  <Button variant="danger" disabled={reset.isPending} onClick={() => reset.mutate()}>
                    {reset.isPending ? "Resetting…" : "Reset link"}
                  </Button>
                </div>
              </DialogContent>
            </Dialog>
          </Section>
        </div>
      )}
    </>
  );
}
