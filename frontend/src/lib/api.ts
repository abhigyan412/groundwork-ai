// Dashboard API client: attaches the admin JWT; on 401 clears the session and goes to /login.
// The widget must not import this file; it uses public-api.ts.
import createClient, { type Middleware } from "openapi-fetch";
import type { paths } from "./api-schema";
import { clearToken, getToken } from "./auth";
import { apiErrorFrom, apiErrorFromBody } from "./errors";
import type { UploadAccepted } from "./types";

function sessionExpired(): void {
  clearToken();
  const next = encodeURIComponent(window.location.pathname);
  window.location.assign(`/login?next=${next}&expired=1`);
}

const auth: Middleware = {
  onRequest({ request }) {
    const token = getToken();
    if (token) request.headers.set("Authorization", `Bearer ${token}`);
    return request;
  },
  onResponse({ response, request }) {
    const isAuthCall = new URL(request.url).pathname.startsWith("/auth/");
    if (response.status === 401 && !isAuthCall) sessionExpired();
    return response;
  },
};

export const api = createClient<paths>({ baseUrl: window.location.origin });
api.use(auth);

/** An openapi-fetch result's data, or an ApiError with the server's message. */
export async function unwrap<T>(
  call: Promise<{ data?: T; error?: unknown; response: Response }>,
  fallback = "That didn't work. Try again.",
): Promise<T> {
  const { data, error, response } = await call;
  if (!response.ok) throw apiErrorFromBody(response.status, error, fallback);
  return data as T;
}

/** Upload (POST) or replace (PUT) a PDF. Plain fetch: multipart doesn't fit the JSON typing. */
export async function sendPdf(file: File, replaceId?: string): Promise<UploadAccepted> {
  const form = new FormData();
  form.append("file", file);
  const token = getToken();
  const response = await fetch(
    replaceId ? `/api/admin/documents/${replaceId}` : "/api/admin/documents",
    {
      method: replaceId ? "PUT" : "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: form,
    },
  );
  if (response.status === 401) sessionExpired();
  if (!response.ok) throw await apiErrorFrom(response, "Upload failed. Try again.");
  return (await response.json()) as UploadAccepted;
}
