# CoEdit AI

The editor's AI assistant sends the active document text to an authenticated Django endpoint and streams generated text back with server-sent events. It supports contextual chat, summaries, grammar correction, rewriting, generation, document insights, semantic search within the active document, and natural-language editing instructions. Generated edits are previews; the user must apply them, and application is blocked if the document changed while the suggestion was being generated.

Provider credentials are configured only in the server environment. The browser receives provider names and model labels, never API keys.

| Provider | API key variable | Optional model variable | Optional API base variable |
| --- | --- | --- | --- |
| OpenAI | `AI_OPENAI_API_KEY` | `AI_OPENAI_MODEL` | `AI_OPENAI_BASE_URL` |
| Anthropic | `AI_ANTHROPIC_API_KEY` | `AI_ANTHROPIC_MODEL` | `AI_ANTHROPIC_BASE_URL` |
| Google Gemini | `AI_GOOGLE_API_KEY` | `AI_GOOGLE_MODEL` | `AI_GOOGLE_BASE_URL` |

Set one or more API keys in the server's environment (or its existing `.env` file), then restart the Django service. Default models and provider API URLs are defined in `editor/ai.py`. Do not put provider keys in frontend environment variables or commit them to source control.

The `GET /api/ai/providers/` endpoint reports configured providers to signed-in users. The `POST /api/workspaces/{workspace_id}/files/{file_id}/ai/` endpoint requires an authenticated workspace member, Django CSRF protection, and a valid provider/action. It streams text using SSE and enforces prompt, history, and document-context size limits. Provider requests are made server-to-server with a bounded timeout.
