export class ApiError extends Error {
  code: string;
  status: number;

  constructor(message: string, code = "HTTP_ERROR", status = 400) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const csrf = sessionStorage.getItem("hub_csrf");
  if (csrf) {
    headers.set("X-CSRF-Token", csrf);
  }
  const response = await fetch(`/api/admin/v1${path}`, {
    ...init,
    headers,
    credentials: "include",
  });
  const body = (await response.json().catch(() => ({}))) as {
    success?: boolean;
    data?: T;
    error?: { code?: string; message?: string };
    detail?: unknown;
  };
  if (!response.ok || body.success === false) {
    if (!body.error && (response.status === 404 || response.status === 405)) {
      // No Hub error envelope: the server does not know this route, usually because it runs older code than this page.
      throw new ApiError("This Hub server does not have this feature yet. Restart it with the latest code and run the database upgrade.",
                         "SERVER_OUTDATED", response.status);
    }
    throw new ApiError(body.error?.message || (typeof body.detail === "string" ? body.detail : "Request failed"),
                       body.error?.code || "HTTP_ERROR", response.status);
  }
  return body.data as T;
}
