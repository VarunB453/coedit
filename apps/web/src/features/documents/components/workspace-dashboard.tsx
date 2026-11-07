import type { FileEntry } from "../types";
import type { WorkspaceRole } from "../../workspaces/types";

interface WorkspaceDashboardProps {
  recentDocuments: FileEntry[];
  fileCount: number;
  workspaceName?: string;
  workspaceRole?: WorkspaceRole;
  onCreateFile: () => void;
  onCreateFolder: () => void;
  onSelectDocument: (id: string) => void;
}

const WorkspaceDashboard = ({
  recentDocuments,
  fileCount,
  workspaceName,
  workspaceRole,
  onCreateFile,
  onCreateFolder,
  onSelectDocument,
}: WorkspaceDashboardProps) => (
  <div className="workspace-dashboard">
    <div className="dashboard-hero card-surface">
      <div>
        <p className="eyebrow">Overview</p>
        <h1>Keep the whole team moving.</h1>
        <p>
          Collaborate on product strategy, meeting notes, and launch artifacts in one visually calm workspace.
        </p>
      </div>
      <div className="dashboard-hero-actions">
        <button type="button" className="primary-btn" onClick={onCreateFile}>Create file</button>
        <button type="button" className="soft-button subtle-button" onClick={onCreateFolder}>New folder</button>
      </div>
    </div>

    <div className="dashboard-metrics">
      <div className="metric-card card-surface">
        <p className="metric-card-label">Documents</p>
        <strong>{fileCount}</strong>
        <span>Active files</span>
      </div>
      <div className="metric-card card-surface">
        <p className="metric-card-label">Workspace</p>
        <strong>{workspaceName ?? "Ready"}</strong>
        <span>Shared room</span>
      </div>
      <div className="metric-card card-surface">
        <p className="metric-card-label">Collaboration</p>
        <strong>{workspaceRole ?? "Guest"}</strong>
        <span>Access role</span>
      </div>
    </div>

    <div className="recent-documents card-surface">
      <div className="section-heading-row">
        <h2>Recent documents</h2>
        <button type="button" className="inline-link" onClick={onCreateFile}>Create new</button>
      </div>
      {recentDocuments.length ? recentDocuments.map((entry) => (
        <button key={entry.id} type="button" className="recent-document-row" onClick={() => onSelectDocument(entry.id)}>
          <span className="recent-document-icon">D</span>
          <span className="recent-document-copy">
            <strong>{entry.name}</strong>
            <small>{entry.updated_at ? new Date(entry.updated_at).toLocaleDateString() : "Updated recently"}</small>
          </span>
          <span className="recent-arrow">→</span>
        </button>
      )) : (
        <div className="empty-state-inline">
          <p>No documents yet. Create your first note to get started.</p>
        </div>
      )}
    </div>
  </div>
);

export default WorkspaceDashboard;