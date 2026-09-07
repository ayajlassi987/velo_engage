// Thin fetch wrapper for the FastAPI JSON API (/api/v1/*). credentials:
// 'include' sends the same session cookie the existing Jinja pages already
// use — see the "keep auth as-is" decision: this frontend never handles
// tokens itself, it rides the same Keycloak-issued session cookie.
//
// A 401 here means require_login's middleware (services/ve_console/src/
// ve_console/main.py) decided there's no valid session — redirect to the
// real login page rather than rendering a broken app shell.
export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(path, {
    credentials: "include",
    headers: { Accept: "application/json" },
    cache: "no-store",
  });
  if (response.status === 401) {
    window.location.href = `/login?next=${encodeURIComponent(window.location.pathname)}`;
    throw new ApiError(401, "Not signed in");
  }
  if (!response.ok) {
    throw new ApiError(response.status, `Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function apiPost<T>(path: string, body?: Record<string, string>): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    credentials: "include",
    headers: body ? { "Content-Type": "application/x-www-form-urlencoded" } : {},
    body: body ? new URLSearchParams(body) : undefined,
  });
  if (response.status === 401) {
    window.location.href = `/login?next=${encodeURIComponent(window.location.pathname)}`;
    throw new ApiError(401, "Not signed in");
  }
  if (!response.ok) {
    throw new ApiError(response.status, `Request failed: ${response.status}`);
  }
  const contentType = response.headers.get("content-type") || "";
  return (contentType.includes("application/json") ? response.json() : (undefined as T));
}
