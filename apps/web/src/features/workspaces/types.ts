export type WorkspaceRole = "owner" | "editor" | "viewer";

export interface WorkspaceInfo {
  id: string;
  name: string;
  role: WorkspaceRole;
}

export interface MemberInfo {
  id: number;
  username: string;
  display_name?: string;
  role: WorkspaceRole;
}

export interface ShareLinkInfo {
  id: number;
  role: "editor" | "viewer";
  created_at: string;
  expires_at: string | null;
}