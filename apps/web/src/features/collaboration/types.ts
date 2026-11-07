export interface CommentInfo {
  id: number;
  body: string;
  author: string;
  created_at: string;
  resolved: boolean;
}

export interface VersionInfo {
  id: number;
  author: string;
  created_at: string;
}