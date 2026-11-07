import type { FormEvent } from "react";
import type { CommentInfo, VersionInfo } from "../types";

interface DocumentActivityPanelProps {
  comments: CommentInfo[];
  versions: VersionInfo[];
  commentInput: string;
  error: string;
  versionPreview: string | null;
  onCommentChange: (value: string) => void;
  onSubmitComment: (event: FormEvent<HTMLFormElement>) => void;
  onPreviewVersion: (versionId: number) => void;
}

const DocumentActivityPanel = ({
  comments,
  versions,
  commentInput,
  error,
  versionPreview,
  onCommentChange,
  onSubmitComment,
  onPreviewVersion,
}: DocumentActivityPanelProps) => (
  <section className="document-activity card-surface">
    <div className="section-heading-row">
      <div>
        <p className="eyebrow">Collaboration</p>
        <h2>Comments &amp; history</h2>
      </div>
    </div>
    <form onSubmit={onSubmitComment} className="comment-form">
      <label htmlFor="new-comment" className="sr-only">Add a comment</label>
      <textarea
        id="new-comment"
        value={commentInput}
        onChange={(event) => onCommentChange(event.target.value)}
        placeholder="Share feedback with your team…"
        maxLength={4000}
        className="text-input comment-input"
      />
      <button type="submit" className="primary-btn" disabled={!commentInput.trim()}>Comment</button>
    </form>
    {error && <p role="alert" className="auth-error">{error}</p>}
    <div className="comment-list">
      {comments.map((comment) => (
        <article key={comment.id} className="comment-item">
          <div className="section-heading-row">
            <strong>{comment.author}</strong>
            <small>{new Date(comment.created_at).toLocaleString()}</small>
          </div>
          <p>{comment.body}</p>
        </article>
      ))}
      {!comments.length && <p className="empty-state-inline">No comments yet.</p>}
    </div>
    <div className="history-list">
      <h3>Document history</h3>
      {versions.length ? versions.map((version) => (
        <button type="button" key={version.id} className="history-row" onClick={() => onPreviewVersion(version.id)}>
          <span>{version.author}</span>
          <small>{new Date(version.created_at).toLocaleString()}</small>
        </button>
      )) : <p className="empty-state-inline">History snapshots are saved as you edit.</p>}
      {versionPreview !== null && <pre className="version-preview">{versionPreview}</pre>}
    </div>
  </section>
);

export default DocumentActivityPanel;