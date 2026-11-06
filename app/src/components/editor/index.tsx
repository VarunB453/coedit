import { randomInt } from "remirror";

import { useCallback, useEffect, useMemo, useState } from "react";

import "remirror/styles/all.css";

import * as Y from "yjs";

import { WebsocketProvider } from "y-websocket";

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
  fileId: string;
  workspaceId: string;
  initialContent: Record<string, unknown> | unknown[];
  onContentChange: (content: any) => void;
  editable?: boolean;
}

type EditorSurfaceProps = Props & { provider: WebsocketProvider; seedContent: boolean };

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

const EditorSurface: React.FC<EditorSurfaceProps> = ({
  username,
  initialContent,
  onContentChange,
  editable = true,
  provider,
  seedContent,
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
                onContentChange(json);
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
  const { fileId, workspaceId, editable = true } = props;
  const ydoc = useMemo(() => new Y.Doc(), [fileId]);
  const provider = useMemo(() => {
    const websocketBase = apiBase.replace(/^http/, "ws").replace(/\/$/, "");
    return new WebsocketProvider(`${websocketBase}/ws/editor/${fileId}`, fileId, ydoc);
  }, [fileId, ydoc]);
  const [seedContent, setSeedContent] = useState<boolean | null>(null);

  useEffect(() => {
    provider.awareness.setLocalStateField("user", {
      name: props.username,
      color: colors[randomInt(0, colors.length - 1)],
    });
    return () => {
      provider.destroy();
      ydoc.destroy();
    };
  }, [provider, props.username, ydoc]);

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
          setSeedContent(Boolean(result.initialize));
        } else {
          retryTimer = window.setTimeout(
            requestInitialization,
            Math.min(Math.max(1, result.retry_after ?? 2), 2) * 1000
          );
        }
      } catch {
        if (active) {
          retryTimer = window.setTimeout(requestInitialization, 2000);
        }
      } finally {
        requesting = false;
      }
    };

    const onSync = (synced: boolean) => {
      if (synced) void requestInitialization();
    };
    provider.on("sync", onSync);
    if (provider.synced) void requestInitialization();
    return () => {
      active = false;
      window.clearTimeout(retryTimer);
      provider.off("sync", onSync);
    };
  }, [editable, fileId, provider, workspaceId]);

  if (seedContent === null) {
    return <p className="editor-loading">Waiting for document sync…</p>;
  }

  return <EditorSurface {...props} provider={provider} seedContent={seedContent} />;
};

export default Editor;
