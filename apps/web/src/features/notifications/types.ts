export interface NotificationInfo {
  id: number;
  kind: string;
  message: string;
  workspace_id: string;
  document_id: string | null;
  created_at: string;
  read: boolean;
}