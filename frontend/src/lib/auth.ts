// MVP session: the admin JWT lives in localStorage (docs/security.md; production: an httpOnly,
// SameSite cookie). Every access is wrapped: storage can be blocked.
const KEY = "groundwork.session";

export function getToken(): string | null {
  try {
    return localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string): void {
  try {
    localStorage.setItem(KEY, token);
  } catch {
    // Storage blocked: the session lasts until the page reloads.
  }
}

export function clearToken(): void {
  try {
    localStorage.removeItem(KEY);
  } catch {
    // ignore
  }
}
