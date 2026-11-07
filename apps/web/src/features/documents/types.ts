export interface FileEntry {
  id: string;
  name: string;
  kind: "file" | "folder";
  parent_id: string | null;
  content: Record<string, unknown> | unknown[];
  updated_at: string;
}

export interface SearchResult {
  id: string;
  name: string;
  workspace_id: string;
  workspace_name: string;
  updated_at: string;
}