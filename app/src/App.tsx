import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import Editor from "./components/editor";

type FileEntry = {
  id: string;
  name: string;
  kind: "file" | "folder";
  parent_id: string | null;
  content: Record<string, unknown> | unknown[];
  updated_at: string;
};

type WorkspaceInfo = { id: string; name: string; role: "owner" | "editor" | "viewer" };
type AuthUser = { id: number; username: string; display_name: string; email: string };
type CommentInfo = { id: number; body: string; author: string; created_at: string; resolved: boolean };
type VersionInfo = { id: number; author: string; created_at: string };
type SearchResult = { id: string; name: string; workspace_id: string; workspace_name: string; updated_at: string };
type NotificationInfo = { id: number; kind: string; message: string; workspace_id: string; document_id: string | null; created_at: string; read: boolean };
type MemberInfo = { id: number; username: string; display_name?: string; role: "owner" | "editor" | "viewer" };

type DialogMode = "create-file" | "create-folder" | "rename";

const API_BASE =
  import.meta.env.VITE_API_URL ??
  (window.location.hostname === "localhost"
    ? "http://localhost:8000"
    : window.location.origin);
const workspaceStorageKey = "collaborative-editor-workspace";

const apiFetch = async (url: string, options: RequestInit = {}) => {
  const method = options.method ?? "GET";
  const headers = new Headers(options.headers);
  if (method !== "GET" && method !== "HEAD") {
    const csrfResponse = await fetch(`${API_BASE}/api/csrf/`, { credentials: "include" });
    if (!csrfResponse.ok) throw new Error("Could not establish a secure session.");
    const { csrfToken } = await csrfResponse.json();
    headers.set("X-CSRFToken", csrfToken);
  }
  return fetch(url, { ...options, headers, credentials: "include" });
};

const validateName = (input: string) => {
  const name = input.trim();
  const deviceName = /^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)/i.test(name);
  const invalidCharacters = /[<>:"|?*\/\\\u0000-\u001f]/.test(name);
  if (
    !name ||
    Array.from(name).length > 100 ||
    name === "." ||
    name === ".." ||
    name.endsWith(".") ||
    deviceName ||
    invalidCharacters
  ) {
    return "Use 1-100 characters. Avoid path separators, reserved punctuation, and device names.";
  }
  return "";
};

const App = () => {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [nameInput, setNameInput] = useState("");
  const [password, setPassword] = useState("");
  const [authMode, setAuthMode] = useState<"login" | "register">("login");
  const [authError, setAuthError] = useState("");
  const [workspaces, setWorkspaces] = useState<WorkspaceInfo[]>([]);
  const [workspaceId, setWorkspaceId] = useState<string | null>(() => {
    const query = new URLSearchParams(window.location.search);
    const sharedId = query.get("workspace");
    const storedId = window.localStorage.getItem(workspaceStorageKey);
    return sharedId && /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(sharedId)
      ? sharedId
      : storedId;
  });
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set());
  const [dialog, setDialog] = useState<DialogMode | null>(null);
  const [dialogName, setDialogName] = useState("");
  const [dialogError, setDialogError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [busy, setBusy] = useState(false);
  const [syncStatus, setSyncStatus] = useState<"connecting" | "synced" | "offline" | "error">("connecting");
  const [linkCopied, setLinkCopied] = useState(false);
  const [inviteName, setInviteName] = useState("");
  const [inviteRole, setInviteRole] = useState<"editor" | "viewer">("editor");
  const [inviteError, setInviteError] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [comments, setComments] = useState<CommentInfo[]>([]);
  const [commentInput, setCommentInput] = useState("");
  const [commentError, setCommentError] = useState("");
  const [versions, setVersions] = useState<VersionInfo[]>([]);
  const [versionPreview, setVersionPreview] = useState<string | null>(null);
  const [notifications, setNotifications] = useState<NotificationInfo[]>([]);
  const [showNotifications, setShowNotifications] = useState(false);
  const [members, setMembers] = useState<MemberInfo[]>([]);
  const [profileOpen, setProfileOpen] = useState(false);
  const [profileName, setProfileName] = useState("");
  const [profileEmail, setProfileEmail] = useState("");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [profileMessage, setProfileMessage] = useState("");
  const [workspaceNameInput, setWorkspaceNameInput] = useState("");
  const [shareLink, setShareLink] = useState("");
  const [shareError, setShareError] = useState("");
  const [shareRole, setShareRole] = useState<"editor" | "viewer">("editor");
  const lastSnapshotByDocument = useRef<Record<string, number>>({});
  const pendingDocumentId = useRef<string | null>(null);
  const selectedEntry = entries.find((entry) => entry.id === selectedId);
  const activeEntry = selectedEntry?.kind === "file" ? selectedEntry : undefined;
  const currentWorkspace = workspaces.find((workspace) => workspace.id === workspaceId);
  const workspaceRole = currentWorkspace?.role;
  const canEdit = workspaceRole === "owner" || workspaceRole === "editor";
  const filesUrl = workspaceId ? `${API_BASE}/api/workspaces/${workspaceId}/files/` : "";
  const documentUrl = workspaceId && activeEntry
    ? `${API_BASE}/api/workspaces/${workspaceId}/files/${activeEntry.id}`
    : "";
  const unreadNotifications = notifications.filter((notification) => !notification.read).length;

  const fileCount = entries.filter((entry) => entry.kind === "file").length;
  const folderCount = entries.filter((entry) => entry.kind === "folder").length;
  const recentDocuments = entries.filter((entry) => entry.kind === "file").slice(0, 4);

  const acceptPendingShare = async () => {
    const query = new URLSearchParams(window.location.search);
    const token = query.get("share");
    if (!token) return null;
    const response = await apiFetch(`${API_BASE}/api/share/${encodeURIComponent(token)}/accept/`, {
      method: "POST",
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error ?? "This sharing link is invalid or expired.");
    query.delete("share");
    query.set("workspace", result.workspace_id);
    window.history.replaceState(null, "", `${window.location.pathname}?${query}${window.location.hash}`);
    return result.workspace_id as string;
  };

  useEffect(() => {
    let active = true;
    apiFetch(`${API_BASE}/api/auth/session/`)
      .then(async (response) => {
        if (response.status === 401) return null;
        if (!response.ok) throw new Error("Could not verify session.");
        return (await response.json()) as AuthUser;
      })
      .then(async (sessionUser) => {
        if (!active) return;
        if (sessionUser) {
          let sharedWorkspace: string | null = null;
          try {
            sharedWorkspace = await acceptPendingShare();
          } catch (error) {
            setLoadError(error instanceof Error ? error.message : "Could not accept the sharing link.");
          }
          const refreshedUser = await apiFetch(`${API_BASE}/api/auth/profile/`);
          if (!refreshedUser.ok) throw new Error("Could not load your profile.");
          const profile = (await refreshedUser.json()) as AuthUser;
          setUser(profile);
          const response = await apiFetch(`${API_BASE}/api/workspaces/`);
          if (!response.ok) throw new Error("Could not load your workspaces.");
          const loaded = (await response.json()) as WorkspaceInfo[];
          if (!active) return;
          setWorkspaces(loaded);
          const requested = loaded.find((workspace) => workspace.id === (sharedWorkspace ?? workspaceId));
          const chosen = requested ?? loaded[0];
          setWorkspaceId(chosen?.id ?? null);
          const noticeResponse = await apiFetch(`${API_BASE}/api/auth/notifications/`);
          if (noticeResponse.ok) setNotifications((await noticeResponse.json()) as NotificationInfo[]);
        }
      })
      .catch(() => {
        if (active) setAuthError("Unable to reach the account server. Check your connection and retry.");
      })
      .finally(() => {
        if (active) setAuthLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!user || searchInput.trim().length < 2) {
      setSearchResults([]);
      return;
    }
    let active = true;
    const timer = window.setTimeout(async () => {
      try {
        const params = new URLSearchParams({ q: searchInput.trim() });
        const response = await apiFetch(`${API_BASE}/api/search/?${params}`);
        const result = await response.json();
        if (!response.ok) throw new Error(result.error ?? "Search failed.");
        if (active) setSearchResults(result.results as SearchResult[]);
      } catch {
        if (active) setSearchResults([]);
      }
    }, 250);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [searchInput, user]);

  useEffect(() => {
    if (!documentUrl) {
      setComments([]);
      setVersions([]);
      setVersionPreview(null);
      return;
    }
    let active = true;
    Promise.all([
      apiFetch(`${documentUrl}/comments/`),
      apiFetch(`${documentUrl}/history/`),
    ]).then(async ([commentResponse, historyResponse]) => {
      if (!commentResponse.ok || !historyResponse.ok) throw new Error("Could not load document activity.");
      const [loadedComments, loadedVersions] = await Promise.all([
        commentResponse.json() as Promise<CommentInfo[]>,
        historyResponse.json() as Promise<VersionInfo[]>,
      ]);
      if (active) {
        setComments(loadedComments);
        setVersions(loadedVersions);
      }
    }).catch(() => {
      if (active) setCommentError("Could not load document activity.");
    });
    return () => { active = false; };
  }, [documentUrl]);

  useEffect(() => {
    if (!workspaceId || workspaceRole !== "owner") {
      setMembers([]);
      return;
    }
    let active = true;
    apiFetch(`${API_BASE}/api/workspaces/${workspaceId}/members/`)
      .then(async (response) => {
        if (!response.ok) throw new Error("Could not load workspace members.");
        return (await response.json()) as MemberInfo[];
      })
      .then((loaded) => { if (active) setMembers(loaded); })
      .catch(() => { if (active) setInviteError("Could not load workspace members."); });
    return () => { active = false; };
  }, [workspaceId, workspaceRole]);

  useEffect(() => {
    if (!user || !workspaceId) {
      setEntries([]);
      setSelectedId(null);
      return;
    }
    let active = true;
    apiFetch(filesUrl)
      .then(async (response) => {
        if (!response.ok) throw new Error("Could not load workspace files.");
        return (await response.json()) as { role: WorkspaceInfo["role"]; entries: FileEntry[] };
      })
      .then((result) => {
        if (!active) return;
        setEntries(result.entries);
        setWorkspaces((current) => current.map((workspace) =>
          workspace.id === workspaceId ? { ...workspace, role: result.role } : workspace
        ));
        setLoadError("");
        const firstFile = result.entries.find((entry) => entry.kind === "file");
        const requestedEntry = result.entries.find((entry) => entry.id === pendingDocumentId.current);
        setSelectedId(requestedEntry?.id ?? firstFile?.id ?? null);
        pendingDocumentId.current = null;
      })
      .catch(() => {
        if (active) setLoadError("Unable to load this workspace. Check your access and retry.");
      });
    return () => { active = false; };
  }, [filesUrl, user, workspaceId]);

  const handleSyncStatusChange = useCallback(
    (status: "connecting" | "synced" | "offline" | "error") => setSyncStatus(status),
    []
  );

  const saveHistorySnapshot = useCallback((content: unknown) => {
    if (!documentUrl || !canEdit) return;
    const now = Date.now();
    if (now - (lastSnapshotByDocument.current[documentUrl] ?? 0) < 30000) return;
    lastSnapshotByDocument.current[documentUrl] = now;
    void apiFetch(`${documentUrl}/history/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    }).then(async (response) => {
      if (!response.ok) {
        const result = await response.json();
        throw new Error(result.error ?? "Could not save document history.");
      }
      const history = await apiFetch(`${documentUrl}/history/`);
      if (history.ok) setVersions((await history.json()) as VersionInfo[]);
    }).catch((error: unknown) => {
      setCommentError(error instanceof Error ? error.message : "Could not save document history.");
    });
  }, [canEdit, documentUrl]);

  const childrenByParent = useMemo(() => {
    const grouped = new Map<string | null, FileEntry[]>();
    for (const entry of entries) {
      const siblings = grouped.get(entry.parent_id) ?? [];
      siblings.push(entry);
      grouped.set(entry.parent_id, siblings);
    }
    return grouped;
  }, [entries]);

  const updateFolder = (folderId: string) => {
    setExpandedFolders((current) => {
      const next = new Set(current);
      if (next.has(folderId)) next.delete(folderId);
      else next.add(folderId);
      return next;
    });
  };

  const openDialog = (mode: DialogMode) => {
    const selected = selectedEntry;
    setDialog(mode);
    setDialogName(mode === "rename" && selected ? selected.name : mode === "create-folder" ? "New folder" : "Untitled.txt");
    setDialogError("");
  };

  const submitDialog = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canEdit) return;
    const name = dialogName.trim();
    const validationError = validateName(name);
    if (validationError) {
      setDialogError(validationError);
      return;
    }
    const selected = entries.find((entry) => entry.id === selectedId);
    const kind = dialog === "create-folder" ? "folder" : "file";
    const parentId = dialog === "rename"
      ? selected?.parent_id ?? null
      : selected?.kind === "folder"
        ? selected.id
        : selected?.parent_id ?? null;
    if (
      entries.some(
        (entry) =>
          entry.parent_id === parentId &&
          entry.id !== (dialog === "rename" ? selectedId : null) &&
          entry.name.toLowerCase() === name.toLowerCase()
      )
    ) {
      setDialogError("An item with that name already exists in this folder.");
      return;
    }

    setBusy(true);
    try {
      const isRename = dialog === "rename" && selected;
      const response = await apiFetch(isRename ? `${filesUrl}${selected.id}/` : filesUrl, {
        method: isRename ? "PATCH" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(
          isRename
            ? { name }
            : {
                name,
                kind,
                parent_id: parentId,
                content: kind === "file" ? { type: "doc", content: [{ type: "paragraph" }] } : {},
              }
        ),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error ?? "File operation failed.");
      if (isRename) {
        setEntries((current) => current.map((entry) => (entry.id === selected.id ? result : entry)));
      } else {
        setEntries((current) => [...current, result]);
        if (result.kind === "file") setSelectedId(result.id);
        else updateFolder(result.id);
      }
      setDialog(null);
    } catch (error) {
      setDialogError(error instanceof Error ? error.message : "File operation failed.");
    } finally {
      setBusy(false);
    }
  };

  const deleteSelected = async () => {
    const selected = entries.find((entry) => entry.id === selectedId);
    if (!canEdit || !selected || !window.confirm(`Delete “${selected.name}”${selected.kind === "folder" ? " and its contents" : ""}?`)) return;
    setBusy(true);
    try {
      const response = await apiFetch(`${filesUrl}${selected.id}/`, { method: "DELETE" });
      if (!response.ok) throw new Error("Delete failed.");
      const removedIds = new Set([selected.id]);
      if (selected.kind === "folder") {
        let changed = true;
        while (changed) {
          changed = false;
          for (const entry of entries) {
            if (entry.parent_id && removedIds.has(entry.parent_id) && !removedIds.has(entry.id)) {
              removedIds.add(entry.id);
              changed = true;
            }
          }
        }
      }
      setEntries((current) => current.filter((entry) => !removedIds.has(entry.id)));
      setSelectedId((current) => (current && removedIds.has(current) ? null : current));
    } catch {
      setLoadError("Could not delete this item. Please try again.");
    } finally {
      setBusy(false);
    }
  };

  const submitAuth = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setAuthError("");
    try {
      const response = await apiFetch(
        `${API_BASE}/api/auth/${authMode === "register" ? "register" : "session"}/`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username: nameInput, password }),
        }
      );
      const result = await response.json();
      if (!response.ok) throw new Error(result.error ?? "Sign-in failed.");
      setUser(result as AuthUser);
      setPassword("");
      let sharedWorkspace: string | null = null;
      try {
        sharedWorkspace = await acceptPendingShare();
      } catch (error) {
        setLoadError(error instanceof Error ? error.message : "Could not accept the sharing link.");
      }
      const workspaceResponse = await apiFetch(`${API_BASE}/api/workspaces/`);
      if (!workspaceResponse.ok) throw new Error("Could not load your workspaces.");
      const loaded = (await workspaceResponse.json()) as WorkspaceInfo[];
      setWorkspaces(loaded);
      const queryWorkspace = new URLSearchParams(window.location.search).get("workspace");
      const selected = loaded.find((workspace) => workspace.id === (sharedWorkspace ?? queryWorkspace)) ?? loaded[0];
      setWorkspaceId(selected?.id ?? null);
      const noticeResponse = await apiFetch(`${API_BASE}/api/auth/notifications/`);
      if (noticeResponse.ok) setNotifications((await noticeResponse.json()) as NotificationInfo[]);
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : "Sign-in failed.");
    }
  };

  const createWorkspace = async () => {
    const name = window.prompt("Workspace name", "My workspace")?.trim();
    if (!name) return;
    try {
      const response = await apiFetch(`${API_BASE}/api/workspaces/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error ?? "Could not create workspace.");
      setWorkspaces((current) => [...current, result]);
      setWorkspaceId(result.id);
      setSelectedId(null);
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "Could not create workspace.");
    }
  };

  const inviteMember = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!workspaceId || workspaceRole !== "owner") return;
    setInviteError("");
    try {
      const response = await apiFetch(`${API_BASE}/api/workspaces/${workspaceId}/members/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: inviteName, role: inviteRole }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error ?? "Could not add member.");
      setInviteName("");
      setInviteError(`Added ${result.username} as ${result.role}.`);
      const membersResponse = await apiFetch(`${API_BASE}/api/workspaces/${workspaceId}/members/`);
      if (membersResponse.ok) setMembers((await membersResponse.json()) as MemberInfo[]);
    } catch (error) {
      setInviteError(error instanceof Error ? error.message : "Could not add member.");
    }
  };

  const updateMemberRole = async (member: MemberInfo, role: "editor" | "viewer") => {
    if (!workspaceId || workspaceRole !== "owner") return;
    try {
      const response = await apiFetch(`${API_BASE}/api/workspaces/${workspaceId}/members/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: member.username, role }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error ?? "Could not update member role.");
      setMembers((current) => current.map((item) => item.id === member.id ? { ...item, role } : item));
    } catch (error) {
      setInviteError(error instanceof Error ? error.message : "Could not update member role.");
    }
  };

  const submitComment = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!documentUrl || !commentInput.trim()) return;
    setCommentError("");
    try {
      const response = await apiFetch(`${documentUrl}/comments/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ body: commentInput }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error ?? "Could not post comment.");
      setComments((current) => [...current, result as CommentInfo]);
      setCommentInput("");
    } catch (error) {
      setCommentError(error instanceof Error ? error.message : "Could not post comment.");
    }
  };

  const createShareLink = async () => {
    if (!workspaceId || workspaceRole !== "owner") return;
    setShareError("");
    try {
      const response = await apiFetch(`${API_BASE}/api/workspaces/${workspaceId}/share-links/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role: shareRole, expires_in_days: 7 }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error ?? "Could not create sharing link.");
      const url = new URL(window.location.href);
      url.searchParams.delete("workspace");
      url.searchParams.set("share", result.token);
      setShareLink(url.toString());
      await navigator.clipboard.writeText(url.toString());
      setLinkCopied(true);
    } catch (error) {
      setShareError(error instanceof Error ? error.message : "Could not create sharing link.");
    }
  };

  const saveProfile = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setProfileMessage("");
    try {
      const payload: Record<string, string> = { display_name: profileName, email: profileEmail };
      if (newPassword) {
        payload.current_password = currentPassword;
        payload.new_password = newPassword;
      }
      const response = await apiFetch(`${API_BASE}/api/auth/profile/`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error ?? "Could not save account settings.");
      setUser(result as AuthUser);
      setCurrentPassword("");
      setNewPassword("");
      setProfileMessage("Account settings saved.");
    } catch (error) {
      setProfileMessage(error instanceof Error ? error.message : "Could not save account settings.");
    }
  };

  const renameWorkspace = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!workspaceId || workspaceRole !== "owner") return;
    try {
      const response = await apiFetch(`${API_BASE}/api/workspaces/${workspaceId}/`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: workspaceNameInput }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error ?? "Could not rename workspace.");
      setWorkspaces((current) => current.map((item) => item.id === workspaceId ? { ...item, name: result.name } : item));
      setProfileMessage("Workspace settings saved.");
    } catch (error) {
      setProfileMessage(error instanceof Error ? error.message : "Could not rename workspace.");
    }
  };

  const markNotificationsRead = async () => {
    const response = await apiFetch(`${API_BASE}/api/auth/notifications/`, { method: "POST" });
    if (!response.ok) {
      setLoadError("Could not update notifications.");
      return;
    }
    setNotifications((current) => current.map((notification) => ({ ...notification, read: true })));
  };

  const previewVersion = async (versionId: number) => {
    if (!documentUrl) return;
    try {
      const response = await apiFetch(`${documentUrl}/history/${versionId}/`);
      const result = await response.json();
      if (!response.ok) throw new Error(result.error ?? "Could not load this version.");
      const extractText = (node: unknown): string => {
        if (!node || typeof node !== "object") return "";
        const value = node as { text?: unknown; content?: unknown };
        return (typeof value.text === "string" ? value.text : "") +
          (Array.isArray(value.content) ? value.content.map(extractText).join(" ") : "");
      };
      setVersionPreview(extractText(result.content).trim() || "This version has no text content.");
    } catch (error) {
      setCommentError(error instanceof Error ? error.message : "Could not load this version.");
    }
  };

  const signOut = async () => {
    await apiFetch(`${API_BASE}/api/auth/logout/`, { method: "POST" });
    setUser(null);
    setWorkspaces([]);
    setWorkspaceId(null);
    setEntries([]);
    setNotifications([]);
  };

  const selectWorkspace = (id: string) => {
    setWorkspaceId(id);
    window.localStorage.setItem(workspaceStorageKey, id);
    const query = new URLSearchParams(window.location.search);
    query.set("workspace", id);
    window.history.replaceState(null, "", `${window.location.pathname}?${query}${window.location.hash}`);
  };

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
              if (isFolder) {
                updateFolder(entry.id);
                setSelectedId(entry.id);
              } else {
                setSelectedId(entry.id);
              }
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

  if (authLoading) {
    return <main className="state-screen">Checking session…</main>;
  }

  if (!user) {
    return (
      <main className="auth-screen">
        <div className="auth-panel">
          <div className="auth-hero">
            <div className="auth-brand">
              <span className="brand-mark">W</span>
              <span>CoEdit</span>
            </div>
            <p className="eyebrow">Collaborative workspace</p>
            <h1>Write together in real time.</h1>
            <p className="auth-copy">
              Create polished product notes, launch plans, and strategy docs with a calm, focused workspace built for teams.
            </p>
            <ul className="feature-list">
              <li>Live collaborative editing</li>
              <li>Structured folder workspaces</li>
              <li>Clean notes and design thinking</li>
            </ul>
          </div>

          <form onSubmit={submitAuth} className="auth-form">
            <p className="eyebrow auth-eyebrow">{authMode === "login" ? "Welcome back" : "Get started"}</p>
            <h2>{authMode === "login" ? "Sign in to your workspace" : "Create your account"}</h2>

            <label htmlFor="username" className="field-label">Username</label>
            <input
              id="username"
              autoComplete="username"
              required
              maxLength={150}
              value={nameInput}
              onChange={(event) => setNameInput(event.target.value)}
              className="text-input"
            />

            <label htmlFor="password" className="field-label">Password</label>
            <input
              id="password"
              type="password"
              autoComplete={authMode === "login" ? "current-password" : "new-password"}
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="text-input"
            />

            {authError && <p role="alert" className="auth-error">{authError}</p>}

            <button className="primary-btn auth-submit">
              {authMode === "login" ? "Sign in" : "Create account"}
            </button>

            <button
              type="button"
              onClick={() => {
                setAuthMode(authMode === "login" ? "register" : "login");
                setAuthError("");
              }}
              className="secondary-link"
            >
              {authMode === "login" ? "Create an account" : "Already have an account? Sign in"}
            </button>
          </form>
        </div>
      </main>
    );
  }

  return (
    <main className="workspace-app-shell">
      <header className="topbar">
        <div className="topbar-brand-block">
          <div className="brand-mark">W</div>
          <select
            aria-label="Workspace"
            value={workspaceId ?? ""}
            onChange={(event) => selectWorkspace(event.target.value)}
            className="workspace-selector"
          >
            {workspaces.map((workspace) => (
              <option key={workspace.id} value={workspace.id}>
                {workspace.name}
              </option>
            ))}
          </select>
          <span className="topbar-divider">/</span>
          <span className="topbar-current">{activeEntry?.name ?? "Dashboard"}</span>
        </div>

        <div className="topbar-actions">
          <span className="save-status-badge" role="status" aria-live="polite">
            <span className={syncStatus === "error" ? "status-text-danger" : "status-text-muted"}>
              {syncStatus === "synced"
                ? "Live and saved"
                : syncStatus === "offline"
                  ? "Offline · saved on this device"
                  : syncStatus === "error"
                    ? "Local storage unavailable"
                    : "Connecting…"}
            </span>
          </span>
          <span className="topbar-user">{user.display_name || user.username}</span>
          <button
            type="button"
            className="soft-button subtle-button"
            onClick={() => setShowNotifications((current) => !current)}
            aria-label={`Notifications${unreadNotifications ? `, ${unreadNotifications} unread` : ""}`}
          >
            Notifications{unreadNotifications ? ` (${unreadNotifications})` : ""}
          </button>
          <button
            type="button"
            className="soft-button subtle-button"
            onClick={() => {
              setProfileName(user.display_name || user.username);
              setProfileEmail(user.email || "");
              setWorkspaceNameInput(currentWorkspace?.name ?? "");
              setProfileMessage("");
              setProfileOpen(true);
            }}
          >
            Account settings
          </button>
          <button type="button" onClick={createWorkspace} className="soft-button subtle-button">
            New workspace
          </button>
          <button type="button" onClick={signOut} className="soft-button subtle-button">
            Sign out
          </button>
          {workspaceRole === "owner" && (
            <>
              <select aria-label="Invite role" value={shareRole} onChange={(event) => setShareRole(event.target.value as "editor" | "viewer")} className="text-input compact-input compact-select">
                <option value="editor">Invite editor</option>
                <option value="viewer">Invite viewer</option>
              </select>
              <button type="button" disabled={!workspaceId} onClick={createShareLink} className="soft-button primary-soft-button">
                {linkCopied ? "Invite link copied" : "Create invite link"}
              </button>
            </>
          )}
        </div>
      </header>
      {(shareError || shareLink) && (
        <div className="share-feedback" role={shareError ? "alert" : "status"}>
          {shareError && <span>{shareError}</span>}
          {shareLink && <span>Invite link (expires in 7 days): <a href={shareLink}>{shareLink}</a></span>}
          <button type="button" className="inline-link" onClick={() => { setShareLink(""); setShareError(""); setLinkCopied(false); }}>Dismiss</button>
        </div>
      )}

      <div className="app-layout">
        <aside className="sidebar-panel">
          {showNotifications && (
            <section className="activity-card">
              <div className="section-heading-row">
                <h2>Notifications</h2>
                <button type="button" className="inline-link" onClick={markNotificationsRead}>Mark all read</button>
              </div>
              {notifications.length ? notifications.slice(0, 8).map((notification) => (
                <button
                  type="button"
                  key={notification.id}
                  className={`activity-row ${notification.read ? "" : "activity-unread"}`}
                  onClick={() => {
                    selectWorkspace(notification.workspace_id);
                    if (notification.document_id) {
                      pendingDocumentId.current = notification.document_id;
                      setSelectedId(notification.document_id);
                    }
                    setShowNotifications(false);
                  }}
                >
                  <span>{notification.message}</span>
                  <small>{new Date(notification.created_at).toLocaleDateString()}</small>
                </button>
              )) : <p className="empty-state-inline">You’re all caught up.</p>}
            </section>
          )}
          <div className="sidebar-header">
            <div>
              <p className="eyebrow">Workspace</p>
              <h2>{currentWorkspace?.name ?? "CoEdit"}</h2>
            </div>
            <div className="toolbar-actions">
              <button type="button" title="New file" disabled={!canEdit || !workspaceId} onClick={() => openDialog("create-file")} className="toolbar-button">
                + File
              </button>
              <button type="button" title="New folder" disabled={!canEdit || !workspaceId} onClick={() => openDialog("create-folder")} className="toolbar-button">
                + Folder
              </button>
            </div>
          </div>

          <div className="search-box">
            <label htmlFor="document-search" className="sr-only">Search documents</label>
            <input
              id="document-search"
              type="search"
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
              placeholder="Search documents…"
              className="text-input compact-input"
            />
            {searchInput.trim().length >= 2 && (
              <div className="search-results">
                {searchResults.length ? searchResults.map((result) => (
                  <button
                    type="button"
                    key={result.id}
                    className="search-result"
                    onClick={() => {
                      if (result.workspace_id !== workspaceId) {
                        pendingDocumentId.current = result.id;
                        selectWorkspace(result.workspace_id);
                      } else {
                        setSelectedId(result.id);
                      }
                      setSearchInput("");
                    }}
                  >
                    <strong>{result.name}</strong>
                    <small>{result.workspace_name}</small>
                  </button>
                )) : <p className="empty-state-inline">No matching documents.</p>}
              </div>
            )}
          </div>

          <div className="sidebar-metrics">
            <div className="metric-pill">
              <span className="metric-value">{fileCount}</span>
              <span className="metric-label">Files</span>
            </div>
            <div className="metric-pill">
              <span className="metric-value">{folderCount}</span>
              <span className="metric-label">Folders</span>
            </div>
            <div className="metric-pill">
              <span className="metric-value">{workspaceRole ?? "Guest"}</span>
              <span className="metric-label">Role</span>
            </div>
          </div>

          <nav aria-label="Workspace files" className="file-tree">
            {renderTree(null)}
            {entries.length === 0 && !loadError && <p className="empty-tree-message">No files yet</p>}
          </nav>

          {workspaceRole === "owner" && workspaceId && (
            <form onSubmit={inviteMember} className="invite-card">
              <label htmlFor="invite-user" className="field-label compact-label">
                Add workspace member
              </label>
              <input
                id="invite-user"
                value={inviteName}
                onChange={(event) => setInviteName(event.target.value)}
                placeholder="Username"
                required
                className="text-input compact-input"
              />
              <div className="invite-controls">
                <select
                  aria-label="Member role"
                  value={inviteRole}
                  onChange={(event) => setInviteRole(event.target.value as "editor" | "viewer")}
                  className="text-input compact-input compact-select"
                >
                  <option value="editor">Editor</option>
                  <option value="viewer">Viewer</option>
                </select>
                <button type="submit" className="primary-btn invite-button">
                  Add
                </button>
              </div>
              {inviteError && <p role="status" className="invite-status">{inviteError}</p>}
              <div className="member-list">
                {members.filter((member) => member.role !== "owner").map((member) => (
                  <div key={member.id} className="member-row">
                    <span>{member.display_name || member.username}</span>
                    <select
                      aria-label={`${member.username} role`}
                      value={member.role}
                      onChange={(event) => updateMemberRole(member, event.target.value as "editor" | "viewer")}
                      className="text-input compact-input compact-select"
                    >
                      <option value="editor">Editor</option>
                      <option value="viewer">Viewer</option>
                    </select>
                    <button
                      type="button"
                      className="inline-link danger-text"
                      onClick={async () => {
                        const response = await apiFetch(`${API_BASE}/api/workspaces/${workspaceId}/members/${member.id}/`, { method: "DELETE" });
                        if (!response.ok) {
                          setInviteError("Could not remove this workspace member.");
                          return;
                        }
                        setMembers((current) => current.filter((item) => item.id !== member.id));
                      }}
                    >
                      Remove
                    </button>
                  </div>
                ))}
              </div>
            </form>
          )}
        </aside>

        <section className="main-panel">
          {loadError && (
            <div role="alert" className="alert-bar">
              {loadError}
              <button type="button" onClick={() => window.location.reload()} className="inline-link">
                Retry
              </button>
            </div>
          )}

          {activeEntry ? (
            <>
              <div className="editor-header-bar">
                <div className="document-meta">
                  <span className="doc-status-dot" />
                  <div>
                    <p className="eyebrow">Active document</p>
                    <h1>{activeEntry.name}</h1>
                  </div>
                </div>
                <div className="header-actions">
                  {canEdit && (
                    <button type="button" disabled={busy} onClick={() => openDialog("rename")} className="soft-button subtle-button">
                      Rename
                    </button>
                  )}
                  {canEdit && (
                    <button type="button" disabled={busy} onClick={deleteSelected} className="soft-button danger-button">
                      Delete
                    </button>
                  )}
                </div>
              </div>

              <div className="editor-scroll-region">
                <Editor
                  key={activeEntry.id}
                  username={user.display_name || user.username}
                  userId={user.id}
                  fileId={activeEntry.id}
                  documentName={activeEntry.name}
                  workspaceId={workspaceId!}
                  initialContent={activeEntry.content}
                  editable={canEdit}
                  onSyncStatusChange={handleSyncStatusChange}
                  onDocumentChange={saveHistorySnapshot}
                />
                <section className="document-activity card-surface">
                  <div className="section-heading-row">
                    <div>
                      <p className="eyebrow">Collaboration</p>
                      <h2>Comments &amp; history</h2>
                    </div>
                  </div>
                  <form onSubmit={submitComment} className="comment-form">
                    <label htmlFor="new-comment" className="sr-only">Add a comment</label>
                    <textarea
                      id="new-comment"
                      value={commentInput}
                      onChange={(event) => setCommentInput(event.target.value)}
                      placeholder="Share feedback with your team…"
                      maxLength={4000}
                      className="text-input comment-input"
                    />
                    <button type="submit" className="primary-btn" disabled={!commentInput.trim()}>Comment</button>
                  </form>
                  {commentError && <p role="alert" className="auth-error">{commentError}</p>}
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
                      <button type="button" key={version.id} className="history-row" onClick={() => previewVersion(version.id)}>
                        <span>{version.author}</span>
                        <small>{new Date(version.created_at).toLocaleString()}</small>
                      </button>
                    )) : <p className="empty-state-inline">History snapshots are saved as you edit.</p>}
                    {versionPreview !== null && (
                      <pre className="version-preview">{versionPreview}</pre>
                    )}
                  </div>
                </section>
              </div>
            </>
          ) : selectedEntry?.kind === "folder" ? (
            <>
              <div className="editor-header-bar">
                <div className="document-meta">
                  <span className="doc-status-dot folder-status" />
                  <div>
                    <p className="eyebrow">Folder</p>
                    <h1>{selectedEntry.name}</h1>
                  </div>
                </div>
                <div className="header-actions">
                  {canEdit && (
                    <button type="button" disabled={busy} onClick={() => openDialog("rename")} className="soft-button subtle-button">
                      Rename
                    </button>
                  )}
                  {canEdit && (
                    <button type="button" disabled={busy} onClick={deleteSelected} className="soft-button danger-button">
                      Delete
                    </button>
                  )}
                </div>
              </div>

              <div className="empty-workspace-card">
                <div className="empty-workspace-inner">
                  <h2>{selectedEntry.name}</h2>
                  <p>Use this folder to group notes, proposals, and collaborative drafts.</p>
                  <button type="button" className="primary-btn" onClick={() => openDialog("create-file")}>
                    Create file inside
                  </button>
                </div>
              </div>
            </>
          ) : (
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
                  <button type="button" className="primary-btn" onClick={() => openDialog("create-file")}>
                    Create file
                  </button>
                  <button type="button" className="soft-button subtle-button" onClick={() => openDialog("create-folder")}>
                    New folder
                  </button>
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
                  <strong>{currentWorkspace?.name ?? "Ready"}</strong>
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
                  <button type="button" className="inline-link" onClick={() => openDialog("create-file")}>
                    Create new
                  </button>
                </div>

                {recentDocuments.length ? (
                  recentDocuments.map((entry) => (
                    <button key={entry.id} type="button" className="recent-document-row" onClick={() => setSelectedId(entry.id)}>
                      <span className="recent-document-icon">D</span>
                      <span className="recent-document-copy">
                        <strong>{entry.name}</strong>
                        <small>{entry.updated_at ? new Date(entry.updated_at).toLocaleDateString() : "Updated recently"}</small>
                      </span>
                      <span className="recent-arrow">→</span>
                    </button>
                  ))
                ) : (
                  <div className="empty-state-inline">
                    <p>No documents yet. Create your first note to get started.</p>
                  </div>
                )}
              </div>
            </div>
          )}
        </section>
      </div>

      {dialog && (
        <div className="modal-backdrop" role="presentation">
          <form onSubmit={submitDialog} role="dialog" aria-modal="true" aria-labelledby="dialog-title" className="modal-card">
            <h2 id="dialog-title">{dialog === "rename" ? "Rename item" : dialog === "create-folder" ? "Create folder" : "Create file"}</h2>
            <label htmlFor="file-name" className="field-label">Name</label>
            <input
              id="file-name"
              autoFocus
              value={dialogName}
              onChange={(event) => setDialogName(event.target.value)}
              maxLength={100}
              className="text-input"
            />
            {dialogError && <p role="alert" className="auth-error">{dialogError}</p>}
            <div className="modal-actions">
              <button type="button" onClick={() => setDialog(null)} className="soft-button subtle-button">
                Cancel
              </button>
              <button type="submit" disabled={busy} className="primary-btn modal-submit">
                {busy ? "Working…" : "Save"}
              </button>
            </div>
          </form>
        </div>
      )}
      {profileOpen && (
        <div className="modal-backdrop" role="presentation">
          <section role="dialog" aria-modal="true" aria-labelledby="account-title" className="modal-card settings-modal">
            <div className="section-heading-row">
              <div>
                <p className="eyebrow">Account</p>
                <h2 id="account-title">Settings</h2>
              </div>
              <button type="button" className="inline-link" onClick={() => setProfileOpen(false)}>Close</button>
            </div>
            <form onSubmit={saveProfile} className="settings-form">
              <label htmlFor="profile-name" className="field-label">Display name</label>
              <input id="profile-name" value={profileName} onChange={(event) => setProfileName(event.target.value)} maxLength={100} className="text-input" />
              <label htmlFor="profile-email" className="field-label">Email</label>
              <input id="profile-email" type="email" value={profileEmail} onChange={(event) => setProfileEmail(event.target.value)} maxLength={254} className="text-input" />
              <label htmlFor="current-password" className="field-label">Current password (to change password)</label>
              <input id="current-password" type="password" autoComplete="current-password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} className="text-input" />
              <label htmlFor="new-password" className="field-label">New password</label>
              <input id="new-password" type="password" autoComplete="new-password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} className="text-input" />
              <button type="submit" className="primary-btn">Save account settings</button>
            </form>
            {workspaceRole === "owner" && (
              <form onSubmit={renameWorkspace} className="settings-form workspace-settings-form">
                <h3>Workspace</h3>
                <label htmlFor="workspace-name" className="field-label">Workspace name</label>
                <input id="workspace-name" value={workspaceNameInput} onChange={(event) => setWorkspaceNameInput(event.target.value)} maxLength={100} className="text-input" />
                <button type="submit" className="soft-button subtle-button">Save workspace</button>
              </form>
            )}
            {profileMessage && <p role="status" className="invite-status">{profileMessage}</p>}
          </section>
        </div>
      )}
    </main>
  );
};

export default App;
