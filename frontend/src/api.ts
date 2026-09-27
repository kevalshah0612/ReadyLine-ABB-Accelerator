/** Same-origin, cookie-authenticated API. Provider secrets never enter the browser. */
export async function api<T>(
  path: string,
  body?: unknown,
  method?: string,
): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method: method ?? (body === undefined ? "GET" : "POST"),
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-ReadyLine": "1" },
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  });
  const data = await response.json();
  if (!response.ok) {
    const detail = data.detail;
    const message =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail
              .map(
                (e: { msg?: string; loc?: string[] }) =>
                  `${e.loc?.slice(1).join(".")}: ${e.msg}`,
              )
              .join("; ")
          : JSON.stringify(detail ?? data);
    throw new Error(message);
  }
  return data as T;
}
