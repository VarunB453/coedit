import { useCallback, useEffect, useMemo, useRef, useState } from "react";

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
import AIAssistant from "./ai-assistant";

export interface Props {
  username: string;
  userId: number;
  fileId: string;
  documentName: string;
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
          const color = typeof user.color === "string" ? user.color : "#1b5e52";
          cursor.style.borderColor = color;
          cursor.style.setProperty("--cursor-color", color);
          cursor.dataset.user = typeof user.name === "string" ? user.name : "Collaborator";
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
          <AIAssistant
            workspaceId={props.workspaceId}
            fileId={props.fileId}
            documentName={props.documentName}
            editable={editable}
          />
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
  const ydoc = useMemo(() => new Y.Doc(), [fileId, userId]);
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
  const localPersistenceFailed = useRef(false);

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
    const onStatus = ({ status }: { status: string }) => {
      onSyncStatusChange?.(
        status === "connected" ? "connecting" : localPersistenceFailed.current ? "error" : "offline"
      );
    };
    const onSync = (synced: boolean) => {
      onSyncStatusChange?.(synced ? "synced" : "connecting");
    };
    provider.awareness.on("change", updatePresence);
    provider.on("status", onStatus);
    provider.on("sync", onSync);
    updatePresence();
    return () => {
      provider.awareness.off("change", updatePresence);
      provider.off("status", onStatus);
      provider.off("sync", onSync);
      provider.destroy();
      void persistence
        .destroy()
        .catch((error: unknown) => console.error("Could not close local document storage.", error))
        .finally(() => ydoc.destroy());
    };
  }, [onSyncStatusChange, persistence, provider, props.username, userId, ydoc]);

  useEffect(() => {
    let active = true;
    const connect = () => {
      if (!active) return;
      if (!navigator.onLine) {
        onSyncStatusChange?.("offline");
        setSeedContent((current) => current ?? (ydoc.share.size === 0));
      } else {
        onSyncStatusChange?.("connecting");
      }
      provider.connect();
    };
    void persistence.whenSynced.then(connect).catch((error: unknown) => {
      console.error("Could not restore local document data.", error);
      if (active) {
        localPersistenceFailed.current = true;
        onSyncStatusChange?.("error");
        setSeedContent((current) => current ?? (ydoc.share.size === 0));
        provider.connect();
      }
    });
    return () => {
      active = false;
    };
  }, [onSyncStatusChange, persistence, provider, ydoc]);

  useEffect(() => {
    let active = true;
    let complete = false;
    let requesting = false;
    let initializationErrorReported = false;
    let retryTimer = 0;

    const requestInitialization = async () => {
      if (!active || complete || requesting) return;
      if (!navigator.onLine) {
        setSeedContent((current) => current ?? (ydoc.share.size === 0));
        return;
      }
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
        initializationErrorReported = false;
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
        if (!initializationErrorReported) {
          console.error("Could not initialize document sync.", error);
          initializationErrorReported = true;
        }
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
      onSyncStatusChange?.(localPersistenceFailed.current ? "error" : "offline");
    };
    const onOnline = () => {
      onSyncStatusChange?.("connecting");
      if (provider.synced) void requestInitialization();
    };
    provider.on("sync", onSync);
    window.addEventListener("offline", onOffline);
    window.addEventListener("online", onOnline);
    if (provider.synced) void requestInitialization();
    void persistence.whenSynced.then(() => requestInitialization()).catch((error: unknown) => {
      console.error("Could not initialize document sync.", error);
    });
    return () => {
      active = false;
      window.clearTimeout(retryTimer);
      provider.off("sync", onSync);
      window.removeEventListener("offline", onOffline);
      window.removeEventListener("online", onOnline);
    };
  }, [editable, fileId, onSyncStatusChange, persistence, provider, workspaceId, ydoc]);

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
