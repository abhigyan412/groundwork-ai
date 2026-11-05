// Knowledge base (docs/frontend.md §6.4).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, FileUp, Loader2, MoreHorizontal, RefreshCw, Trash2, XCircle } from "lucide-react";
import { useRef, useState, type DragEvent } from "react";
import { toast } from "sonner";
import { PageHeader } from "@/app/AppShell";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  Tooltip,
} from "@/components/ui/overlay";
import { EmptyState, ErrorState, SkeletonRows } from "@/components/ui/states";
import { api, sendPdf, unwrap } from "@/lib/api";
import { cn } from "@/lib/cn";
import { messageOf } from "@/lib/errors";
import { formatBytes, formatFullDate, formatWhen } from "@/lib/format";
import type { DocumentOut, Limits } from "@/lib/types";

type UploadItem = { key: string; name: string; state: "waiting" | "uploading" | "done" | "error"; message?: string };

function useDocuments() {
  return useQuery({
    queryKey: ["documents"],
    queryFn: () => unwrap(api.GET("/api/admin/documents")),
    // Poll every 2 s while anything is processing (status moves without a refresh).
    refetchInterval: (q) => (q.state.data?.documents.some((d) => d.status === "processing") ? 2000 : false),
  });
}

/** Browser-side checks before uploading; the server re-checks everything. */
function clientCheck(file: File, limits: Limits): string | null {
  const isPdf = file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
  if (!isPdf) return "This file isn't a PDF.";
  if (file.size > limits.max_mb * 1024 * 1024) {
    return `This PDF is ${formatBytes(file.size)}. The limit is ${limits.max_mb} MB.`;
  }
  return null;
}

function LimitsMeter({ limits }: { limits: Limits }) {
  const pct = Math.min(100, (limits.documents_used / limits.documents_max) * 100);
  return (
    <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-slate">
      <span className="tabular">
        <span className="font-semibold text-ink">{limits.documents_used}</span> of {limits.documents_max} documents used
      </span>
      <span
        className="h-1.5 w-32 rounded-full bg-line"
        role="meter"
        aria-label="Documents used"
        aria-valuemin={0}
        aria-valuemax={limits.documents_max}
        aria-valuenow={limits.documents_used}
      >
        <span className="block h-1.5 rounded-full bg-teal" style={{ width: `${pct}%` }} />
      </span>
      <span>
        PDFs up to {limits.max_pages} pages, {limits.max_mb} MB
      </span>
    </div>
  );
}

function StatusCell({ doc }: { doc: DocumentOut }) {
  if (doc.status === "ready") {
    return (
      <span>
        <span className="text-ink">Ready</span>
        {doc.pages_without_text.length > 0 ? (
          <span className="block text-xs text-needinfo">
            No readable text on page{doc.pages_without_text.length > 1 ? "s" : ""} {doc.pages_without_text.join(", ")}
          </span>
        ) : null}
      </span>
    );
  }
  if (doc.status === "processing") {
    return <span className="animate-pulse text-slate">Processing…</span>;
  }
  return <span className="text-notmet">Failed: {doc.error ?? "processing failed"}</span>;
}

function UploadList({ items, onDismiss }: { items: UploadItem[]; onDismiss: () => void }) {
  if (items.length === 0) return null;
  const busy = items.some((i) => i.state === "waiting" || i.state === "uploading");
  return (
    <div className="mt-4 rounded-panel border border-line bg-surface p-4" aria-live="polite">
      <ul className="space-y-2">
        {items.map((i) => (
          <li key={i.key} className="flex items-start gap-2 text-sm">
            {i.state === "done" ? (
              <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-met" strokeWidth={1.75} aria-hidden="true" />
            ) : i.state === "error" ? (
              <XCircle className="mt-0.5 size-4 shrink-0 text-notmet" strokeWidth={1.75} aria-hidden="true" />
            ) : (
              <Loader2 className="mt-0.5 size-4 shrink-0 animate-spin text-slate" strokeWidth={1.75} aria-hidden="true" />
            )}
            <span className="min-w-0">
              <span className="font-semibold text-ink">{i.name}</span>{" "}
              <span className={i.state === "error" ? "text-notmet" : "text-slate"}>
                {i.state === "done"
                  ? "uploaded"
                  : i.state === "error"
                    ? i.message
                    : i.state === "uploading"
                      ? "uploading…"
                      : "waiting"}
              </span>
            </span>
          </li>
        ))}
      </ul>
      {!busy ? (
        <Button variant="ghost" size="sm" className="mt-3" onClick={onDismiss}>
          Clear list
        </Button>
      ) : null}
    </div>
  );
}

export function Documents() {
  const queryClient = useQueryClient();
  const docs = useDocuments();
  const fileInput = useRef<HTMLInputElement>(null);
  const replaceInput = useRef<HTMLInputElement>(null);
  const [replaceTarget, setReplaceTarget] = useState<DocumentOut | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<DocumentOut | null>(null);
  const [uploads, setUploads] = useState<UploadItem[]>([]);
  const [dragging, setDragging] = useState(false);

  const limits = docs.data?.limits;
  const full = limits ? limits.documents_used >= limits.documents_max : false;

  const patch = (key: string, change: Partial<UploadItem>) =>
    setUploads((items) => items.map((i) => (i.key === key ? { ...i, ...change } : i)));

  async function uploadFiles(files: File[]) {
    if (!limits || files.length === 0) return;
    let slots = limits.documents_max - limits.documents_used;
    const items: (UploadItem & { file: File })[] = files.map((file, n) => {
      const key = `${Date.now()}-${n}-${file.name}`;
      const problem = clientCheck(file, limits) ?? (slots-- <= 0 ? `Document limit reached (${limits.documents_max}). Delete one to upload more.` : null);
      return { key, name: file.name, file, state: problem ? "error" : "waiting", message: problem ?? undefined };
    });
    setUploads((prev) => [...items.map(({ file: _file, ...rest }) => rest), ...prev]);
    for (const item of items.filter((i) => i.state === "waiting")) {
      patch(item.key, { state: "uploading" });
      try {
        await sendPdf(item.file);
        patch(item.key, { state: "done" });
      } catch (e) {
        patch(item.key, { state: "error", message: messageOf(e, "Upload failed. Try again.") });
      }
      await queryClient.invalidateQueries({ queryKey: ["documents"] });
    }
  }

  const replace = useMutation({
    mutationFn: ({ doc, file }: { doc: DocumentOut; file: File }) => sendPdf(file, doc.id),
    onSuccess: (_, { doc, file }) => {
      toast.success(`Replacing ${doc.filename} with ${file.name}`);
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
    },
    onError: (e) => toast.error(messageOf(e, "Couldn't replace the document. Try again.")),
  });

  const remove = useMutation({
    mutationFn: (doc: DocumentOut) =>
      unwrap(api.DELETE("/api/admin/documents/{document_id}", { params: { path: { document_id: doc.id } } })),
    onSuccess: () => {
      toast.success("Document deleted");
      setDeleteTarget(null);
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
    },
    onError: (e) => toast.error(messageOf(e, "Couldn't delete the document. Try again.")),
  });

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
    if (full) return;
    void uploadFiles(Array.from(e.dataTransfer.files));
  }

  const uploadButton = (
    <Button onClick={() => fileInput.current?.click()} disabled={!limits || full} aria-disabled={full}>
      <FileUp strokeWidth={1.75} aria-hidden="true" />
      Upload PDF
    </Button>
  );

  return (
    <>
      <PageHeader
        title="Documents"
        action={
          full ? (
            <Tooltip content="Delete a document to upload another.">
              <span tabIndex={0}>{uploadButton}</span>
            </Tooltip>
          ) : (
            uploadButton
          )
        }
      >
        {limits ? <LimitsMeter limits={limits} /> : null}
      </PageHeader>

      <input
        ref={fileInput}
        type="file"
        accept="application/pdf,.pdf"
        multiple
        className="sr-only"
        tabIndex={-1}
        aria-hidden="true"
        onChange={(e) => {
          void uploadFiles(Array.from(e.target.files ?? []));
          e.target.value = "";
        }}
      />
      <input
        ref={replaceInput}
        type="file"
        accept="application/pdf,.pdf"
        className="sr-only"
        tabIndex={-1}
        aria-hidden="true"
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = "";
          if (!file || !replaceTarget || !limits) return;
          const problem = clientCheck(file, limits);
          if (problem) toast.error(problem);
          else replace.mutate({ doc: replaceTarget, file });
          setReplaceTarget(null);
        }}
      />

      {!full ? (
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={cn(
            "rounded-panel border border-dashed px-6 py-8 text-center transition-colors",
            dragging ? "border-teal bg-teal-tint" : "border-line bg-surface",
          )}
        >
          <p className="text-base text-slate">
            Drop PDFs here or{" "}
            <button type="button" className="font-semibold text-teal underline-offset-4 hover:underline" onClick={() => fileInput.current?.click()} disabled={!limits}>
              browse
            </button>
          </p>
        </div>
      ) : null}

      <UploadList items={uploads} onDismiss={() => setUploads([])} />

      <section className="mt-8" aria-labelledby="doc-list">
        <h2 id="doc-list" className="sr-only">
          Your documents
        </h2>
        {docs.isPending ? (
          <SkeletonRows rows={4} />
        ) : docs.isError ? (
          <ErrorState message={messageOf(docs.error, "Couldn't load your documents.")} onRetry={() => void docs.refetch()} />
        ) : docs.data.documents.length === 0 ? (
          <EmptyState action={uploadButton}>No documents yet. Upload the PDFs your assistant should answer from.</EmptyState>
        ) : (
          <div className="overflow-x-auto rounded-panel border border-line bg-surface">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-line text-xs text-slate">
                <tr>
                  <th scope="col" className="px-4 py-3 font-semibold">Name</th>
                  <th scope="col" className="hidden px-4 py-3 font-semibold sm:table-cell">Pages</th>
                  <th scope="col" className="hidden px-4 py-3 font-semibold sm:table-cell">Size</th>
                  <th scope="col" className="px-4 py-3 font-semibold">Status</th>
                  <th scope="col" className="hidden px-4 py-3 font-semibold md:table-cell">Added</th>
                  <th scope="col" className="w-12 px-2 py-3"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {docs.data.documents.map((doc) => (
                  <tr key={doc.id} className="align-top">
                    <td className="max-w-64 px-4 py-3 font-semibold break-words text-ink">{doc.filename}</td>
                    <td className="tabular hidden px-4 py-3 text-slate sm:table-cell">{doc.page_count ?? "—"}</td>
                    <td className="tabular hidden px-4 py-3 text-slate sm:table-cell">{formatBytes(doc.size_bytes)}</td>
                    <td className="px-4 py-3"><StatusCell doc={doc} /></td>
                    <td className="hidden px-4 py-3 text-slate md:table-cell" title={formatFullDate(doc.created_at)}>
                      {formatWhen(doc.created_at)}
                    </td>
                    <td className="px-2 py-2 text-right">
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button variant="ghost" size="icon" aria-label={`Actions for ${doc.filename}`}>
                            <MoreHorizontal strokeWidth={1.75} />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent>
                          <DropdownMenuItem
                            onSelect={() => {
                              setReplaceTarget(doc);
                              replaceInput.current?.click();
                            }}
                          >
                            <RefreshCw strokeWidth={1.75} aria-hidden="true" /> Replace
                          </DropdownMenuItem>
                          <DropdownMenuItem danger onSelect={() => setDeleteTarget(doc)}>
                            <Trash2 strokeWidth={1.75} aria-hidden="true" /> Delete
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <Dialog open={deleteTarget !== null} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        {deleteTarget ? (
          <DialogContent
            title={`Delete ${deleteTarget.filename}?`}
            description="The assistant will stop using it immediately."
          >
            <div className="flex justify-end gap-3">
              <DialogClose asChild>
                <Button variant="secondary">Cancel</Button>
              </DialogClose>
              <Button variant="danger" disabled={remove.isPending} onClick={() => remove.mutate(deleteTarget)}>
                {remove.isPending ? "Deleting…" : "Delete document"}
              </Button>
            </div>
          </DialogContent>
        ) : null}
      </Dialog>
    </>
  );
}
