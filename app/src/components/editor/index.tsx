import { useCallback, useEffect, useMemo, useState } from "react";

import "remirror/styles/all.css";

import * as Y from "yjs";

import { WebsocketProvider } from "y-websocket";
import { IndexeddbPersistence } from "y-indexeddb";

import { InvalidContentHandler } from "remirror";
import {
  BoldExtension,
  ItalicExtension,
  CalloutExtension,
  CodeBlockExtension,
  CodeExtension,
  HistoryExtension,
  LinkExtension,
  UnderlineExtension,
  HeadingExtension,
  OrderedListExtension,
  ListItemExtension,
  BulletListExtension,
  FontSizeExtension,
  CollaborationExtension,
  YjsExtension,
} from "remirror/extensions";

import {
  Remirror,
  useRemirror,
  EditorComponent,
  OnChangeJSON,
} from "@remirror/react";

export interface Props {
  username: string;
  userId: number;
  fileId: string;
  workspaceId: string;
  initialContent: Record<string, unknown> | unknown[];
  onSyncStatusChange?: (status: SyncStatus) => void;
  editable?: boolean;
}

type SyncStatus = "connecting" | "synced" | "offline" | "error";
type EditorSurfaceProps = Props & {
  provider: WebsocketProvider;
  seedContent: boolean;
  presence: PresenceUser[];
};
type PresenceUser = { id: number; name: string; color: string };

const colors = [
  "#CC444B",
  "#32292F",
  "#8A4FFF",
  "#0B2027",
  "#F21B3F",
  "#FF9914",
  "#1F2041",
  "#4B3F72",
  "#FFC857",
];

const userColor = (userId: number) => colors[userId % colors.length];

const EditorSurface: React.FC<EditorSurfaceProps> = ({
  username,
  initialContent,
  editable = true,
  provider,
  seedContent,
  presence,
}) => {
  const onError: InvalidContentHandler = useCallback(
    ({ json, invalidContent, transformers }: any) => {
      return transformers.remove(json, invalidContent);
    },
    []
  );

  const { manager, state, onChange } = useRemirror({
    extensions: () => [
      new BoldExtension(),
      new ItalicExtension(),
      new UnderlineExtension(),
      new HeadingExtension({ levels: [1, 2, 3] }),
      new FontSizeExtension({ defaultSize: "16", unit: "px" }),
      new OrderedListExtension(),
      new ListItemExtension(),
      new BulletListExtension({ enableSpine: true }),
      new CalloutExtension({ defaultType: "warn" }),
      new CodeBlockExtension(),
      new CodeExtension(),
      new HistoryExtension(),
      new LinkExtension({ autoLink: true }),
      new CollaborationExtension({
        clientID: username,
      }),
      new YjsExtension({
        getProvider: () => provider,
        cursorBuilder: (user) => {
          const cursor = document.createElement("span");
          cursor.className = "collaboration-cursor";
          cursor.style.borderColor = typeof user.color === "string" ? user.color : "#1b5e52";
          cursor.textContent = typeof user.name === "string" ? user.name : "Collaborator";
          return cursor;
        },
      }),
    ],
    content: seedContent ? (initialContent as any) : undefined,
    selection: "start",
    onError,
  });

  return (
    <div className="editor-shell">
      <div className="editor-surface-panel">
        <div className="editor-toolbar-row">
          <span className="editor-toolbar-pill">
            <span className="toolbar-indicator" />
            Live sync
          </span>
          <span className="editor-toolbar-caption">{editable ? "Editing enabled" : "Read only"}</span>
          <div className="collaborator-presence" aria-label="People in this document">
            {presence.slice(0, 3).map((user) => (
              <span
                key={user.id}
                className="collaborator-avatar"
                title={user.name}
                style={{ backgroundColor: user.color }}
              >
                {user.name.slice(0, 1).toUpperCase()}
              </span>
            ))}
            {presence.length > 3 && (
              <span className="collaborator-overflow" title={presence.slice(3).map((user) => user.name).join(", ")}>
                +{presence.length - 3}
              </span>
            )}
            <span className="sr-only" aria-live="polite">
              {presence.length} {presence.length === 1 ? "person" : "people"} in this document
            </span>
          </div>
        </div>

        <Remirror
          manager={manager}
          initialContent={state}
          editable={editable}
          placeholder="Start typing...Please be respectful :)"
          classNames={[
            "editor-content",
            "scrollbar-hide",
          ]}
        >
          <div className="editor-inner-surface">
            <EditorComponent />
            <OnChangeJSON
              onChange={(json) => {
                onChange(json as any);
              }}
            />
          </div>
        </Remirror>
      </div>
    </div>
  );
};

const apiBase =
  import.meta.env.VITE_API_URL ??
  (window.location.hostname === "localhost"
    ? "http://localhost:8000"
    : window.location.origin);

const Editor: React.FC<Props> = (props) => {
  const { fileId, userId, workspaceId, editable = true, onSyncStatusChange } = props;
  const ydoc = useMemo(() => new Y.Doc(), [fileId]);
  const persistence = useMemo(
    () => new IndexeddbPersistence(`coedit:${userId}:${fileId}`, ydoc),
    [fileId, userId, ydoc]
  );
  const provider = useMemo(() => {
    const websocketBase = apiBase.replace(/^http/, "ws").replace(/\/$/, "");
    return new WebsocketProvider(`${websocketBase}/ws/editor/${fileId}`, fileId, ydoc, {
      connect: false,
      maxBackoffTime: 10000,
    });
  }, [fileId, ydoc]);
  const [seedContent, setSeedContent] = useState<boolean | null>(null);
  const [presence, setPresence] = useState<PresenceUser[]>([]);

  useEffect(() => {
    provider.awareness.setLocalStateField("user", {
      id: userId,
      name: props.username,
      color: userColor(userId),
    });
    const updatePresence = () => {
      const users = new Map<number, PresenceUser>();
      for (const state of provider.awareness.getStates().values()) {
        const user = state.user;
        if (
          user &&
          typeof user.id === "number" &&
          typeof user.name === "string" &&
          typeof user.color === "string"
        ) {
          users.set(user.id, { id: user.id, name: user.name, color: user.color });
        }
      }
      setPresence(Array.from(users.values()));
    };
    provider.awareness.on("change", updatePresence);
    updatePresence();
    return () => {
      provider.awareness.off("change", updatePresence);
      provider.destroy();
      void persistence.destroy().finally(() => ydoc.destroy());
    };
  }, [persistence, provider, props.username, userId, ydoc]);

  useEffect(() => {
    let active = true;
    const connect = () => {
      if (active) provider.connect();
    };
    void persistence.whenSynced.then(connect).catch((error: unknown) => {
      console.error("Could not restore local document data.", error);
      if (active) onSyncStatusChange?.("error");
    });
    return () => {
      active = false;
    };
  }, [onSyncStatusChange, persistence, provider]);

  useEffect(() => {
    const updatePresence = () => {
      const users = new Map<number, PresenceUser>();
      for (const state of provider.awareness.getStates().values()) {
        const user = state.user;
        if (
          user &&
          typeof user.id === "number" &&
          typeof user.name === "string" &&
          typeof user.color === "string"
        ) {
          users.set(user.id, { id: user.id, name: user.name, color: user.color });
        }
      }
      setPresence(Array.from(users.values()));
    };
    const onStatus = ({ status }: { status: string }) => {
      onSyncStatusChange?.(status === "connected" ? "connecting" : "offline");
    };
    const onSync = (synced: boolean) => {
      onSyncStatusChange?.(synced ? "synced" : "connecting");
    };
    provider.awareness.on("change", updatePresence);
    provider.on("status", onStatus);
    provider.on("sync", onSync);
    return () => {
      provider.awareness.off("change", updatePresence);
      provider.off("status", onStatus);
      provider.off("sync", onSync);
    };
  }, [onSyncStatusChange, provider]);

  useEffect(() => {
    let active = true;
    let complete = false;
    let requesting = false;
    let retryTimer = 0;

    const requestInitialization = async () => {
      if (!active || complete || requesting) return;
      requesting = true;
      try {
        const method = editable ? "POST" : "GET";
        const headers = new Headers();
        if (editable) {
          const csrfResponse = await fetch(`${apiBase}/api/csrf/`, { credentials: "include" });
          if (!csrfResponse.ok) throw new Error("Could not establish a secure session.");
          const { csrfToken } = await csrfResponse.json();
          headers.set("X-CSRFToken", csrfToken);
        }
        const response = await fetch(
          `${apiBase}/api/workspaces/${workspaceId}/files/${fileId}/initialize/`,
          { method, headers, credentials: "include" }
        );
        if (!response.ok) throw new Error("Could not initialize document sync.");
        const result = await response.json();
        if (!active) return;
        if (result.ready) {
          complete = true;
          setSeedContent(Boolean(result.initialize) && ydoc.share.size === 0);
        } else {
          retryTimer = window.setTimeout(
            requestInitialization,
            Math.min(Math.max(1, result.retry_after ?? 2), 2) * 1000
          );
        }
      } catch (error) {
        console.error("Could not initialize document sync.", error);
        if (active) {
          setSeedContent((current) => current ?? (ydoc.share.size === 0));
          retryTimer = window.setTimeout(requestInitialization, 2000);
        }
      } finally {
        requesting = false;
      }
    };

    const onSync = (synced: boolean) => {
      if (synced) void requestInitialization();
    };
    const onOffline = () => {
      setSeedContent((current) => current ?? (ydoc.share.size === 0));
      onSyncStatusChange?.("offline");
    };
    const onOnline = () => {
      onSyncStatusChange?.("connecting");
      if (provider.synced) void requestInitialization();
    };
    provider.on("sync", onSync);
    window.addEventListener("offline", onOffline);
    window.addEventListener("online", onOnline);
    if (provider.synced) void requestInitialization();
    return () => {
      active = false;
      window.clearTimeout(retryTimer);
      provider.off("sync", onSync);
      window.removeEventListener("offline", onOffline);
      window.removeEventListener("online", onOnline);
    };
  }, [editable, fileId, onSyncStatusChange, provider, workspaceId, ydoc]);

  if (seedContent === null) {
    return <p className="editor-loading">Waiting for document sync…</p>;
  }

  return (
    <EditorSurface
      {...props}
      provider={provider}
      seedContent={seedContent}
      presence={presence}
    />
  );
};

export default Editor;
