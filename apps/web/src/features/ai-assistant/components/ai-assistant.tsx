import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { useCommands, useEditorView } from "@remirror/react";
import { API_BASE, apiFetch, responseError } from "../../../lib/api/client";

type Props = {
  workspaceId: string;
  fileId: string;
  documentName: string;
  editable: boolean;
};

type Provider = { id: string; model: string };
type Action = "chat" | "summarize" | "grammar" | "rewrite" | "generate" | "insights" | "semantic_search" | "edit";
type Message = { role: "user" | "assistant"; content: string };

const actionLabels: Record<Action, string> = {
  chat: "Ask AI",
  summarize: "Summarize",
  grammar: "Fix grammar",
  rewrite: "Rewrite",
  generate: "Generate",
  insights: "Insights",
  semantic_search: "Search document",
  edit: "Edit with instructions",
};

const textToDocument = (text: string) => ({
  type: "doc",
  content: text.split(/\n+/).map((paragraph) => ({
    type: "paragraph",
    ...(paragraph ? { content: [{ type: "text", text: paragraph }] } : {}),
  })),
});

const AI_ASSISTABLE_ACTIONS: Action[] = ["grammar", "rewrite", "generate", "edit"];

const AIAssistant: React.FC<Props> = ({ workspaceId, fileId, documentName, editable }) => {
  const [open, setOpen] = useState(false);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [providerId, setProviderId] = useState("");
  const [providerError, setProviderError] = useState("");
  const [prompt, setPrompt] = useState("");
  const [output, setOutput] = useState("");
  const [outputAction, setOutputAction] = useState<Action | null>(null);
  const [sourceSnapshot, setSourceSnapshot] = useState("");
  const [history, setHistory] = useState<Message[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [stale, setStale] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const view = useEditorView();
  const commands = useCommands();

  useEffect(() => {
    let active = true;
    apiFetch(`${API_BASE}/api/ai/providers/`)
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(await responseError(response, "Could not load AI provider settings."));
        }
        return (await response.json()) as { providers: Provider[] };
      })
      .then((result) => {
        if (!active) return;
        setProviders(result.providers);
        setProviderId((current) => current || result.providers[0]?.id || "");
      })
      .catch((loadError: unknown) => {
        if (active) setProviderError(loadError instanceof Error ? loadError.message : "Could not load AI provider settings.");
      });
    return () => {
      active = false;
      controller.current?.abort();
    };
  }, []);

  const runAction = async (action: Action, instruction = prompt.trim()) => {
    if (!providerId || busy) return;
    const context = view.state.doc.textBetween(0, view.state.doc.content.size, "\n\n");
    const snapshot = JSON.stringify(view.state.doc.toJSON());
    const nextHistory = action === "chat" ? history.slice(-10) : [];
    setBusy(true);
    setError("");
    setStale(false);
    setOutput("");
    setOutputAction(action);
    if (AI_ASSISTABLE_ACTIONS.includes(action)) setSourceSnapshot(snapshot);
    const abortController = new AbortController();
    controller.current = abortController;
    let accumulated = "";

    try {
      const response = await apiFetch(
        `${API_BASE}/api/workspaces/${workspaceId}/files/${fileId}/ai/`,
        {
          method: "POST",
          signal: abortController.signal,
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            provider: providerId,
            action,
            document_name: documentName,
            context,
            prompt: instruction,
            history: nextHistory,
          }),
        }
      );
      if (!response.ok) {
        throw new Error(await responseError(response, "AI request failed."));
      }
      if (!response.body) throw new Error("Streaming is not supported by this connection.");
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let streamComplete = false;
      while (!streamComplete) {
        const { done, value } = await reader.read();
        buffer += decoder.decode(value, { stream: !done });
        const events = buffer.split("\n\n");
        buffer = events.pop() ?? "";
        for (const event of events) {
          const lines = event.split("\n");
          const isError = lines.some((line) => line === "event: error");
          const data = lines.filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trim()).join("\n");
          if (!data) continue;
          const payload = JSON.parse(data) as { text?: string; done?: boolean; error?: string };
          if (isError) throw new Error(payload.error ?? "AI request failed.");
          if (payload.text) {
            accumulated += payload.text;
            setOutput(accumulated);
          }
          if (payload.done) streamComplete = true;
        }
        if (done) streamComplete = true;
      }
      if (!accumulated.trim()) throw new Error("The AI provider returned an empty response.");
      if (action === "chat") {
        setHistory((current) => [
          ...current,
          ...(instruction ? [{ role: "user" as const, content: instruction }] : []),
          { role: "assistant" as const, content: accumulated },
        ].slice(-12));
        setOutput("");
        setOutputAction(null);
      }
      setPrompt("");
    } catch (requestError) {
      setOutput("");
      setOutputAction(null);
      if (!(requestError instanceof Error && requestError.name === "AbortError")) {
        setError(requestError instanceof Error ? requestError.message : "AI request failed.");
      }
    } finally {
      if (controller.current === abortController) controller.current = null;
      setBusy(false);
    }
  };

  const applySuggestion = () => {
    if (JSON.stringify(view.state.doc.toJSON()) !== sourceSnapshot) {
      setStale(true);
      return;
    }
    commands.setContent(textToDocument(output));
    setOutput("");
    setOutputAction(null);
    setStale(false);
  };

  const submitChat = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (prompt.trim()) void runAction("chat", prompt.trim());
  };

  return (
    <div className="ai-assistant">
      <button
        type="button"
        className={`ai-launcher ${open ? "ai-launcher-active" : ""}`}
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
        aria-controls="ai-assistant-panel"
      >
        <span aria-hidden="true">✦</span> AI assistant
      </button>
      {open && (
        <section id="ai-assistant-panel" className="ai-panel" aria-label="AI writing assistant">
          <div className="ai-panel-heading">
            <div>
              <p className="eyebrow">CoEdit AI</p>
              <h2>Work with your document</h2>
            </div>
            <button type="button" className="ai-close-button" onClick={() => setOpen(false)} aria-label="Close AI assistant">×</button>
          </div>
          {providerError ? (
            <p role="alert" className="ai-error">{providerError}</p>
          ) : providers.length === 0 ? (
            <div className="ai-empty-state">
              <strong>AI isn’t configured yet</strong>
              <p>An administrator can enable OpenAI, Anthropic, or Google from the server environment. API keys stay on the server.</p>
            </div>
          ) : (
            <>
              <label className="ai-provider-label" htmlFor="ai-provider">Provider</label>
              <select id="ai-provider" className="ai-provider-select" value={providerId} onChange={(event) => setProviderId(event.target.value)}>
                {providers.map((provider) => <option key={provider.id} value={provider.id}>{provider.id} · {provider.model}</option>)}
              </select>
              <div className="ai-action-grid">
                {(["summarize", "grammar", "rewrite", "generate", "insights", "semantic_search"] as Action[]).map((action) => (
                  <button
                    key={action}
                    type="button"
                    disabled={
                      busy ||
                      (!editable && ["grammar", "rewrite", "generate"].includes(action)) ||
                      (["generate", "semantic_search"].includes(action) && !prompt.trim())
                    }
                    onClick={() => void runAction(
                      action,
                      action === "rewrite"
                        ? prompt.trim() || "Make the writing clearer and more concise."
                        : prompt.trim()
                    )}
                  >
                    {actionLabels[action]}
                  </button>
                ))}
              </div>
              <form className="ai-prompt-form" onSubmit={submitChat}>
                <label htmlFor="ai-prompt" className="ai-provider-label">Ask a question or describe an edit</label>
                <textarea
                  id="ai-prompt"
                  value={prompt}
                  maxLength={4000}
                  onChange={(event) => setPrompt(event.target.value)}
                  placeholder="Ask about this document, generate a section, or tell AI how to revise it…"
                  rows={3}
                />
                <div className="ai-submit-row">
                  <button type="button" className="ai-edit-button" disabled={busy || !editable || !prompt.trim()} onClick={() => void runAction("edit")}>
                    Edit document
                  </button>
                  {busy ? (
                    <button type="button" className="ai-send-button" onClick={() => controller.current?.abort()}>Stop</button>
                  ) : (
                    <button type="submit" className="ai-send-button" disabled={!prompt.trim()}>Ask AI</button>
                  )}
                </div>
              </form>
              {error && <p role="alert" className="ai-error">{error}</p>}
              {history.length > 0 && (
                <div className="ai-conversation" aria-live="polite">
                  {history.map((message, index) => (
                    <p key={`${index}-${message.role}`} className={`ai-message ai-message-${message.role}`}>
                      <strong>{message.role === "user" ? "You" : "AI"}</strong>
                      <span>{message.content}</span>
                    </p>
                  ))}
                </div>
              )}
              {output && (
                <div className="ai-result">
                  <div className="ai-result-heading">
                    <strong>{outputAction ? actionLabels[outputAction] : "AI response"}</strong>
                    <button type="button" onClick={() => { setOutput(""); setOutputAction(null); setStale(false); }}>Discard</button>
                  </div>
                  <pre>{output}</pre>
                  {outputAction && AI_ASSISTABLE_ACTIONS.includes(outputAction) && (
                    <>
                      <p className="ai-apply-note">Applying replaces the whole document. Review the suggestion before continuing.</p>
                      {stale && <p role="alert" className="ai-error">The document changed while this suggestion was being prepared. Run the action again to avoid overwriting newer edits.</p>}
                      <button type="button" className="ai-apply-button" disabled={busy || !editable} onClick={applySuggestion}>
                        Apply suggestion to document
                      </button>
                    </>
                  )}
                </div>
              )}
              {history.length > 0 && !output && (
                <div className="ai-chat-context" aria-live="polite">
                  <span>{history.filter((message) => message.role === "user").length} recent chat messages in context</span>
                  <button type="button" onClick={() => setHistory([])}>Clear chat</button>
                </div>
              )}
            </>
          )}
        </section>
      )}
    </div>
  );
};

export default AIAssistant;
