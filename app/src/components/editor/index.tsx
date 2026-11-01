import { randomInt } from "remirror";

import { useCallback, useEffect, useMemo } from "react";

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
  initialContent: Record<string, unknown> | unknown[];
  onContentChange: (content: any) => void;
}

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

const Editor: React.FC<Props> = (props) => {
  const { username, fileId, initialContent, onContentChange } = props;

  // remirror error handler
  const onError: InvalidContentHandler = useCallback(
    ({ json, invalidContent, transformers }: any) => {
      // Automatically remove all invalid nodes and marks.
      return transformers.remove(json, invalidContent);
    },
    []
  );

  const ydoc = useMemo(() => new Y.Doc(), [fileId]);
  const provider = useMemo(() => {
    const apiBase =
      import.meta.env.VITE_API_URL ??
      (window.location.hostname === "localhost"
        ? "http://localhost:8000"
        : window.location.origin);
    const websocketBase = apiBase.replace(/^http/, "ws").replace(/\/$/, "");
    return new WebsocketProvider(`${websocketBase}/ws/editor/${fileId}`, fileId, ydoc);
  }, [fileId, ydoc]);

  useEffect(() => {
    provider.awareness.setLocalStateField("user", {
      name: username,
      color: colors[randomInt(0, colors.length - 1)],
    });
    return () => {
      provider.destroy();
      ydoc.destroy();
    };
  }, [provider, username, ydoc]);

  // TODO: reset form when room changes
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
    content: initialContent as any,
    selection: "start",
    onError,
  });

  return (
    <div className="mt-2 mb-4">
      <Remirror
        manager={manager}
        initialContent={state}
        placeholder="Start typing...Please be respectful :)"
        classNames={[
          "p-4 focus:outline-none h-96 overflow-y-auto scrollbar-hide prose lg:prose-xl prose-p:m-0",
        ]}
      >
        <div className="rounded-md border">
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
  );
};

export default Editor;
