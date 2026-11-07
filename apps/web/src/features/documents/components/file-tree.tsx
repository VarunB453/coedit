import { useMemo } from "react";
import type { FileEntry } from "../types";

interface FileTreeProps {
  entries: FileEntry[];
  expandedFolders: Set<string>;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onToggleFolder: (id: string) => void;
}

const FileTree = ({ entries, expandedFolders, selectedId, onSelect, onToggleFolder }: FileTreeProps) => {
  const childrenByParent = useMemo(() => {
    const grouped = new Map<string | null, FileEntry[]>();
    for (const entry of entries) {
      const siblings = grouped.get(entry.parent_id) ?? [];
      siblings.push(entry);
      grouped.set(entry.parent_id, siblings);
    }
    return grouped;
  }, [entries]);

  const renderTree = (parentId: string | null, depth = 0): React.ReactNode =>
    (childrenByParent.get(parentId) ?? []).map((entry) => {
      const isFolder = entry.kind === "folder";
      const expanded = expandedFolders.has(entry.id);
      const selected = selectedId === entry.id;
      return (
        <div key={entry.id}>
          <button
            type="button"
            onClick={() => {
              if (isFolder) onToggleFolder(entry.id);
              onSelect(entry.id);
            }}
            className={`file-tree-item ${selected ? "file-tree-item-selected" : ""}`}
            style={{ paddingLeft: `${12 + depth * 16}px` }}
          >
            <span className="file-tree-caret" aria-hidden="true">
              {isFolder ? (expanded ? "▾" : "▸") : "•"}
            </span>
            <span className="truncate">{entry.name}</span>
          </button>
          {isFolder && expanded && renderTree(entry.id, depth + 1)}
        </div>
      );
    });

  return <>{renderTree(null)}</>;
};

export default FileTree;