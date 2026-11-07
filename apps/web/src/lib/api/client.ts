export const API_BASE =
  import.meta.env.VITE_API_URL ??
  (window.location.hostname === "localhost"
    ? "http://localhost:8000"
    : window.location.origin);

export const apiFetch = async (url: string, options: RequestInit = {}): Promise<Response> => {
  const method = options.method ?? "GET";
  const headers = new Headers(options.headers);
  if (method !== "GET" && method !== "HEAD") {
    const csrfResponse = await fetch(`${API_BASE}/api/csrf/`, { credentials: "include" });
    if (!csrfResponse.ok) throw new Error("Could not establish a secure session.");
    const { csrfToken } = (await csrfResponse.json()) as { csrfToken: string };
    headers.set("X-CSRFToken", csrfToken);
  }
  return fetch(url, { ...options, headers, credentials: "include" });
};