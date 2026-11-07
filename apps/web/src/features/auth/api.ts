import { API_BASE, apiFetch } from "../../lib/api/client";
import type { AuthUser } from "./types";
import type { AuthMode } from "./components/auth-screen";

export interface ProfileUpdate {
  display_name: string;
  email: string;
  current_password?: string;
  new_password?: string;
}

const parseResponse = async <T>(response: Response, fallback: string): Promise<T> => {
  const payload = (await response.json()) as T & { error?: unknown };
  if (!response.ok) {
    throw new Error(typeof payload.error === "string" ? payload.error : fallback);
  }
  return payload;
};

export const getSession = async (): Promise<AuthUser | null> => {
  const response = await apiFetch(`${API_BASE}/api/auth/session/`);
  if (response.status === 401) return null;
  if (!response.ok) throw new Error("Could not verify session.");
  return (await response.json()) as AuthUser;
};

export const getProfile = async (): Promise<AuthUser> => {
  const response = await apiFetch(`${API_BASE}/api/auth/profile/`);
  return parseResponse<AuthUser>(response, "Could not load your profile.");
};

export const authenticate = async (
  mode: AuthMode,
  username: string,
  password: string,
): Promise<AuthUser> => {
  const response = await apiFetch(
    `${API_BASE}/api/auth/${mode === "register" ? "register" : "session"}/`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    },
  );
  return parseResponse<AuthUser>(response, "Sign-in failed.");
};

export const updateProfile = async (profile: ProfileUpdate): Promise<AuthUser> => {
  const response = await apiFetch(`${API_BASE}/api/auth/profile/`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(profile),
  });
  return parseResponse<AuthUser>(response, "Could not save account settings.");
};

export const endSession = async (): Promise<void> => {
  const response = await apiFetch(`${API_BASE}/api/auth/logout/`, { method: "POST" });
  if (!response.ok) throw new Error("Could not end the session.");
};