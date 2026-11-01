import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
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
type AuthUser = { id: number; username: string };

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
  const [saveState, setSaveState] = useState<"saved" | "saving" | "error">("saved");
  const [draft, setDraft] = useState<Record<string, unknown> | unknown[]>([]);
  const [dirty, setDirty] = useState(false);
  const [saveAttempt, setSaveAttempt] = useState(0);
  const [linkCopied, setLinkCopied] = useState(false);
  const [inviteName, setInviteName] = useState("");
  const [inviteRole, setInviteRole] = useState<"editor" | "viewer">("editor");
  const [inviteError, setInviteError] = useState("");
  const selectedRef = useRef<string | null>(null);
  const selectedEntry = entries.find((entry) => entry.id === selectedId);
  const activeEntry = selectedEntry?.kind === "file" ? selectedEntry : undefined;
  const currentWorkspace = workspaces.find((workspace) => workspace.id === workspaceId);
  const workspaceRole = currentWorkspace?.role;
  const canEdit = workspaceRole === "owner" || workspaceRole === "editor";
  const filesUrl = workspaceId ? `${API_BASE}/api/workspaces/${workspaceId}/files/` : "";

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
          setUser(sessionUser);
          const response = await apiFetch(`${API_BASE}/api/workspaces/`);
          if (!response.ok) throw new Error("Could not load your workspaces.");
          const loaded = (await response.json()) as WorkspaceInfo[];
          if (!active) return;
          setWorkspaces(loaded);
          const requested = loaded.find((workspace) => workspace.id === workspaceId);
          const chosen = requested ?? loaded[0];
          setWorkspaceId(chosen?.id ?? null);
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
        setSelectedId(firstFile?.id ?? null);
      })
      .catch(() => {
        if (active) setLoadError("Unable to load this workspace. Check your access and retry.");
      });
    return () => { active = false; };
  }, [filesUrl, user, workspaceId]);

  useEffect(() => {
    selectedRef.current = selectedId;
    const selected = entries.find((entry) => entry.id === selectedId && entry.kind === "file");
    setDraft(selected?.content ?? []);
    setDirty(false);
    setSaveState("saved");
  }, [selectedId, entries]);

  useEffect(() => {
    if (!activeEntry || !dirty || !canEdit) return;
    const entryId = activeEntry.id;
    const content = draft;
    const timer = window.setTimeout(async () => {
      setSaveState("saving");
      try {
        const response = await apiFetch(`${filesUrl}${entryId}/`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ content }),
        });
        if (!response.ok) throw new Error("Save failed");
        if (selectedRef.current === entryId) {
          setEntries((current) =>
            current.map((entry) => (entry.id === entryId ? { ...entry, content } : entry))
          );
          setDirty(false);
          setSaveState("saved");
        }
      } catch {
        if (selectedRef.current === entryId) setSaveState("error");
      }
    }, 500);
    return () => window.clearTimeout(timer);
  }, [activeEntry, canEdit, dirty, draft, filesUrl, saveAttempt]);

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
          method: authMode === "register" ? "POST" : "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username: nameInput, password }),
        }
      );
      const result = await response.json();
      if (!response.ok) throw new Error(result.error ?? "Sign-in failed.");
      setUser(result as AuthUser);
      setPassword("");
      const workspaceResponse = await apiFetch(`${API_BASE}/api/workspaces/`);
      if (!workspaceResponse.ok) throw new Error("Could not load your workspaces.");
      const loaded = (await workspaceResponse.json()) as WorkspaceInfo[];
      setWorkspaces(loaded);
      const queryWorkspace = new URLSearchParams(window.location.search).get("workspace");
      const selected = loaded.find((workspace) => workspace.id === queryWorkspace) ?? loaded[0];
      setWorkspaceId(selected?.id ?? null);
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
    } catch (error) {
      setInviteError(error instanceof Error ? error.message : "Could not add member.");
    }
  };

  const signOut = async () => {
    await apiFetch(`${API_BASE}/api/auth/logout/`, { method: "POST" });
    setUser(null);
    setWorkspaces([]);
    setWorkspaceId(null);
    setEntries([]);
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
              }
              else setSelectedId(entry.id);
            }}
            className={`flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm ${selected ? "bg-emerald-50 text-emerald-900" : "text-slate-700 hover:bg-slate-100"}`}
            style={{ paddingLeft: `${12 + depth * 16}px` }}
          >
            <span className="w-4 text-center text-xs text-slate-500" aria-hidden="true">
              {isFolder ? (expanded ? "▾" : "▸") : "·"}
            </span>
            <span className="truncate">{entry.name}</span>
          </button>
          {isFolder && expanded && renderTree(entry.id, depth + 1)}
        </div>
      );
    });

  if (authLoading) {
    return <main className="grid min-h-screen place-items-center bg-[#f3f6f4] text-sm text-slate-600">Checking session…</main>;
  }

  if (!user) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-[#f3f6f4] px-5">
        <form
          onSubmit={submitAuth}
          className="w-full max-w-sm border border-slate-200 bg-white p-7 shadow-sm"
        >
          <p className="text-xs font-semibold uppercase tracking-widest text-emerald-700">Collaborative editor</p>
          <h1 className="mt-3 text-2xl font-semibold text-slate-900">{authMode === "login" ? "Sign in" : "Create account"}</h1>
          <label htmlFor="username" className="mt-6 block text-sm font-medium text-slate-700">Username</label>
          <input
            id="username"
            autoComplete="username"
            required
            maxLength={150}
            value={nameInput}
            onChange={(event) => setNameInput(event.target.value)}
            className="mt-2 w-full border border-slate-300 px-3 py-2 outline-none focus:border-emerald-700 focus:ring-1 focus:ring-emerald-700"
          />
          <label htmlFor="password" className="mt-4 block text-sm font-medium text-slate-700">Password</label>
          <input
            id="password"
            type="password"
            autoComplete={authMode === "login" ? "current-password" : "new-password"}
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className="mt-2 w-full border border-slate-300 px-3 py-2 outline-none focus:border-emerald-700 focus:ring-1 focus:ring-emerald-700"
          />
          {authError && <p role="alert" className="mt-3 text-sm text-red-700">{authError}</p>}
          <button className="mt-5 w-full bg-emerald-800 px-4 py-2.5 text-sm font-medium text-white hover:bg-emerald-900">
            {authMode === "login" ? "Sign in" : "Create account"}
          </button>
          <button type="button" onClick={() => { setAuthMode(authMode === "login" ? "register" : "login"); setAuthError(""); }} className="mt-4 w-full text-sm text-emerald-800 hover:underline">
            {authMode === "login" ? "Create an account" : "Already have an account? Sign in"}
          </button>
        </form>
      </main>
    );
  }

  return (
    <main className="flex h-screen min-h-[480px] flex-col bg-white text-slate-900">
      <header className="flex h-14 shrink-0 items-center justify-between border-b border-slate-200 px-5">
        <div className="flex min-w-0 items-center gap-3">
          <span className="grid h-8 w-8 place-items-center bg-emerald-800 text-sm font-bold text-white">W</span>
          <select aria-label="Workspace" value={workspaceId ?? ""} onChange={(event) => selectWorkspace(event.target.value)} className="max-w-40 truncate border-0 bg-transparent text-sm font-semibold focus:ring-0">
            {workspaces.map((workspace) => <option key={workspace.id} value={workspace.id}>{workspace.name}</option>)}
          </select>
          <span className="hidden text-slate-300 sm:inline">/</span>
          <span className="hidden truncate text-sm text-slate-600 sm:inline">{activeEntry?.name ?? "Files"}</span>
        </div>
        <div className="flex items-center gap-4 text-sm">
          <span className="flex items-center gap-2">
            <span className={saveState === "error" ? "text-red-700" : "text-slate-500"}>
              {saveState === "saving" ? "Saving" : saveState === "error" ? "Save failed" : "Saved"}
            </span>
            {saveState === "error" && <button type="button" onClick={() => setSaveAttempt((attempt) => attempt + 1)} className="text-red-700 underline">Retry</button>}
          </span>
          <span className="hidden text-slate-600 sm:inline">{user.username}</span>
          <button type="button" onClick={createWorkspace} className="text-slate-600 hover:underline">New workspace</button>
          <button type="button" onClick={signOut} className="text-slate-600 hover:underline">Sign out</button>
          <button type="button" disabled={!workspaceId} onClick={() => {
            const shareUrl = new URL(window.location.href);
            if (workspaceId) shareUrl.searchParams.set("workspace", workspaceId);
            navigator.clipboard.writeText(shareUrl.toString()).then(() => setLinkCopied(true)).catch(() => setLinkCopied(false));
          }} className="text-emerald-800 hover:underline disabled:opacity-50">
            {linkCopied ? "Link copied" : "Share workspace"}
          </button>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <aside className="flex w-64 shrink-0 flex-col border-r border-slate-200 bg-[#fafbfa] sm:w-72">
          <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-500">Files</h2>
            <div className="flex gap-1">
              <button type="button" title="New file" disabled={!canEdit || !workspaceId} onClick={() => openDialog("create-file")} className="px-2 py-1 text-xs text-slate-700 hover:bg-slate-200 disabled:opacity-40">+ File</button>
              <button type="button" title="New folder" disabled={!canEdit || !workspaceId} onClick={() => openDialog("create-folder")} className="px-2 py-1 text-xs text-slate-700 hover:bg-slate-200 disabled:opacity-40">+ Folder</button>
            </div>
          </div>
          <nav aria-label="Workspace files" className="min-h-0 flex-1 overflow-y-auto p-2">
            {renderTree(null)}
            {entries.length === 0 && !loadError && <p className="px-3 py-5 text-sm text-slate-500">No files yet</p>}
          </nav>
          <div className="border-t border-slate-200 px-4 py-2 text-xs text-slate-500">{entries.length} items</div>
          {workspaceRole === "owner" && workspaceId && (
            <form onSubmit={inviteMember} className="space-y-2 border-t border-slate-200 p-3">
              <label htmlFor="invite-user" className="block text-xs font-medium text-slate-600">Add workspace member</label>
              <input id="invite-user" value={inviteName} onChange={(event) => setInviteName(event.target.value)} placeholder="Username" required className="w-full border border-slate-300 px-2 py-1.5 text-sm" />
              <div className="flex gap-2">
                <select aria-label="Member role" value={inviteRole} onChange={(event) => setInviteRole(event.target.value as "editor" | "viewer")} className="min-w-0 flex-1 border border-slate-300 px-2 py-1.5 text-sm">
                  <option value="editor">Editor</option>
                  <option value="viewer">Viewer</option>
                </select>
                <button type="submit" className="bg-emerald-800 px-3 py-1.5 text-xs font-medium text-white">Add</button>
              </div>
              {inviteError && <p role="status" className="text-xs text-slate-600">{inviteError}</p>}
            </form>
          )}
        </aside>

        <section className="flex min-w-0 flex-1 flex-col">
          {loadError && (
            <div role="alert" className="flex items-center justify-between border-b border-red-200 bg-red-50 px-5 py-2 text-sm text-red-800">
              {loadError}
              <button type="button" onClick={() => window.location.reload()} className="font-medium underline">Retry</button>
            </div>
          )}
          {activeEntry ? (
            <>
              <div className="flex h-12 shrink-0 items-center justify-between border-b border-slate-200 px-5">
                <h1 className="truncate text-sm font-medium">{activeEntry.name}</h1>
                <div className="flex gap-1">
                  {canEdit && <button type="button" disabled={busy} onClick={() => openDialog("rename")} className="px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-100 disabled:opacity-50">Rename</button>}
                  {canEdit && <button type="button" disabled={busy} onClick={deleteSelected} className="px-3 py-1.5 text-xs text-red-700 hover:bg-red-50 disabled:opacity-50">Delete</button>}
                </div>
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-8">
                <Editor
                  key={activeEntry.id}
                  username={user.username}
                  fileId={activeEntry.id}
                  workspaceId={workspaceId!}
                  initialContent={activeEntry.content}
                  editable={canEdit}
                  onContentChange={(content) => {
                    setDraft(content);
                    setDirty(true);
                  }}
                />
              </div>
            </>
          ) : selectedEntry?.kind === "folder" ? (
            <>
              <div className="flex h-12 shrink-0 items-center justify-between border-b border-slate-200 px-5">
                <h1 className="truncate text-sm font-medium">{selectedEntry.name}</h1>
                <div className="flex gap-1">
                  {canEdit && <button type="button" disabled={busy} onClick={() => openDialog("rename")} className="px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-100 disabled:opacity-50">Rename</button>}
                  {canEdit && <button type="button" disabled={busy} onClick={deleteSelected} className="px-3 py-1.5 text-xs text-red-700 hover:bg-red-50 disabled:opacity-50">Delete</button>}
                </div>
              </div>
              <div className="grid flex-1 place-items-center p-8 text-center">
                <div>
                  <h1 className="text-lg font-medium">{selectedEntry.name}</h1>
                  <p className="mt-2 text-sm text-slate-500">New items will be created inside this folder.</p>
                </div>
              </div>
            </>
          ) : (
            <div className="grid flex-1 place-items-center p-8 text-center">
              <div>
                <h1 className="text-lg font-medium">{workspaceId ? "Select a file to edit" : "Create a workspace"}</h1>
                <p className="mt-2 text-sm text-slate-500">{workspaceId ? "Create a file or choose one from the workspace." : "Your documents are organized in workspaces."}</p>
                {!workspaceId && <button type="button" onClick={createWorkspace} className="mt-4 bg-emerald-800 px-4 py-2 text-sm font-medium text-white">New workspace</button>}
              </div>
            </div>
          )}
        </section>
      </div>

      {dialog && (
        <div className="fixed inset-0 z-10 grid place-items-center bg-slate-950/30 p-4" role="presentation">
          <form onSubmit={submitDialog} role="dialog" aria-modal="true" aria-labelledby="dialog-title" className="w-full max-w-md border border-slate-200 bg-white p-5 shadow-xl">
            <h2 id="dialog-title" className="text-lg font-semibold">{dialog === "rename" ? "Rename item" : dialog === "create-folder" ? "Create folder" : "Create file"}</h2>
            <label htmlFor="file-name" className="mt-4 block text-sm font-medium text-slate-700">Name</label>
            <input id="file-name" autoFocus value={dialogName} onChange={(event) => setDialogName(event.target.value)} maxLength={100} className="mt-1 w-full border border-slate-300 px-3 py-2 outline-none focus:border-emerald-700 focus:ring-1 focus:ring-emerald-700" />
            {dialogError && <p role="alert" className="mt-2 text-sm text-red-700">{dialogError}</p>}
            <div className="mt-5 flex justify-end gap-2">
              <button type="button" onClick={() => setDialog(null)} className="border border-slate-300 px-3 py-2 text-sm hover:bg-slate-50">Cancel</button>
              <button type="submit" disabled={busy} className="bg-emerald-800 px-3 py-2 text-sm font-medium text-white hover:bg-emerald-900 disabled:opacity-50">{busy ? "Working…" : "Save"}</button>
            </div>
          </form>
        </div>
      )}
    </main>
  );
};

export default App;
