import { ApiError } from "@/services/api";

export type StreamHandler = (event: string, data: Record<string, unknown>) => void;

/** POST to an admin endpoint that answers with Server-Sent Events and hand each event to `onEvent`. */
export async function postStream(path: string, body: unknown, onEvent: StreamHandler, signal?: AbortSignal): Promise<void> {
  const headers = new Headers({ "Content-Type": "application/json", Accept: "text/event-stream" });
  const csrf = sessionStorage.getItem("hub_csrf");
  if (csrf) headers.set("X-CSRF-Token", csrf);
  const response = await fetch(`/api/admin/v1${path}`, {
    method: "POST", headers, body: JSON.stringify(body), credentials: "include", signal,
  });
  if (!response.ok || !response.body) {
    const failure = (await response.json().catch(() => ({}))) as { error?: { code?: string; message?: string } };
    if (!failure.error && (response.status === 404 || response.status === 405)) {
      throw new ApiError("This Hub server does not have this feature yet. Restart it with the latest code and run the database upgrade.",
                         "SERVER_OUTDATED", response.status);
    }
    throw new ApiError(failure.error?.message || "Request failed", failure.error?.code || "HTTP_ERROR", response.status);
  }
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value.replace(/\r\n/g, "\n");
    let end = buffer.indexOf("\n\n");
    while (end >= 0) {
      const block = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      let event = "message";
      const data: string[] = [];
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
      }
      if (data.length) onEvent(event, JSON.parse(data.join("\n")) as Record<string, unknown>);
      end = buffer.indexOf("\n\n");
    }
  }
}
