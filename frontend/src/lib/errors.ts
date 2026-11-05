/** An API error carrying the server's own message (the backend writes its errors for people). */
export class ApiError extends Error {
  readonly status: number;
  readonly fieldErrors: Record<string, string>;

  constructor(status: number, message: string, fieldErrors: Record<string, string> = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.fieldErrors = fieldErrors;
  }
}

type ErrorBody = { detail?: unknown; errors?: { field?: string | null; message?: string }[] };

export function apiErrorFromBody(status: number, body: unknown, fallback: string): ApiError {
  const b = (body ?? {}) as ErrorBody;
  const fields: Record<string, string> = {};
  for (const e of b.errors ?? []) {
    if (e.field && e.message) fields[e.field] = e.message;
  }
  return new ApiError(status, typeof b.detail === "string" ? b.detail : fallback, fields);
}

export async function apiErrorFrom(response: Response, fallback: string): Promise<ApiError> {
  let body: unknown = {};
  try {
    body = await response.json();
  } catch {
    // Not JSON (proxy error page): keep the fallback message.
  }
  return apiErrorFromBody(response.status, body, fallback);
}

export function messageOf(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof TypeError) {
    return "Can't reach the server. Check your connection and try again.";
  }
  return fallback;
}
