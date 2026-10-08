const API_BASE = import.meta.env.VITE_API_URL ?? "";

function sessionGet(key: string): string {
  if (typeof window === "undefined") return "";
  return window.sessionStorage.getItem(key) ?? "";
}

export function getApiKey(): string {
  return sessionGet("aethel.apiKey");
}

export function getAdminKey(): string {
  return sessionGet("aethel.adminKey");
}

export function setApiKey(value: string): void {
  window.sessionStorage.setItem("aethel.apiKey", value.trim());
}

export function setAdminKey(value: string): void {
  window.sessionStorage.setItem("aethel.adminKey", value.trim());
}

export function clearSessionKeys(): void {
  window.sessionStorage.removeItem("aethel.apiKey");
  window.sessionStorage.removeItem("aethel.adminKey");
}

export function hasApiConnection(): boolean {
  return Boolean(getApiKey());
}

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
  auth: "api" | "admin" | "none" = "none",
): Promise<T> {
  const headers = new Headers(options.headers ?? {});
  headers.set("Accept", "application/json");

  const key = auth === "admin" ? getAdminKey() : auth === "api" ? getApiKey() : "";
  if (key) headers.set("Authorization", `Bearer ${key}`);

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`${response.status} ${response.statusText}: ${body}`);
  }

  return (await response.json()) as T;
}
