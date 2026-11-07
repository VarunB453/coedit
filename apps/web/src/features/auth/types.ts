export type AuthMode = "login" | "register";

export interface AuthUser {
  id: number;
  username: string;
  display_name: string;
  email: string;
}