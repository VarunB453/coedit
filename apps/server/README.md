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

## Collaboration and account features

CoEdit uses Django's authenticated sessions and CSRF protection for browser mutations. Workspace owners can manage editor/viewer memberships, update workspace settings, and create expiring invite links. Invite tokens are random, stored only as SHA-256 digests, and carried in the URL fragment so they are not sent in HTTP requests. Owners can revoke active links.

Workspace members can search accessible documents, comment on files, and view document snapshots. Editors' changes continue to autosave through the durable Yjs update stream and browser IndexedDB; periodic document snapshots are retained separately for history previews. Search, comments, snapshots, and notifications are scoped to the signed-in user and/or a workspace the user belongs to. Account profile and password changes are available at `GET`/`PATCH /api/auth/profile/`; password changes require the current password and Django's configured validators.

## Production configuration

The application requires a production `SECRET_KEY`; `DEBUG` defaults to `false`. Set `ALLOWED_HOSTS` to the exact host names served by Django. Set `CORS_ALLOWED_ORIGINS` and `CSRF_TRUSTED_ORIGINS` to the exact browser origin(s), including scheme and port. Their localhost development defaults are disabled when `DEBUG=false`. Session and CSRF cookies are secure and HTTP-only outside debug mode. Production defaults redirect to HTTPS and enable one-year HSTS; set `SECURE_HSTS_SECONDS=0` only when HTTPS is not yet guaranteed, and enable subdomains or preload only after confirming the domain-wide policy.

For a single-process local development setup, SQLite is used by default. For production, install `psycopg` and set `DATABASE_ENGINE=postgresql`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, and optionally `POSTGRES_PORT` and `DATABASE_CONN_MAX_AGE`. Persistent connections default to disabled for ASGI workers; use a managed pooler before increasing the connection age. SQLite is not appropriate for multiple application workers or replicas.

The Channels layer uses `REDIS_URL` (default `redis://127.0.0.1:6379/0`). Production workers must share a durable Redis service. Serve the ASGI application (for example, `daphne core.asgi:application`) behind an HTTPS-terminating reverse proxy that overwrites `X-Forwarded-Proto`, run `python manage.py migrate` and `python manage.py collectstatic`, and serve the frontend's production build. Do not expose Django directly when relying on the forwarded-protocol header. Configure `VITE_API_URL` at frontend build time when the API is hosted on another origin. Application logs go to standard output; `LOG_LEVEL` controls their minimum level.

CI runs the Django checks, migration consistency check, Django tests, and TypeScript/Vite production build on pushes and pull requests.

## Remaining operational risks

- Durable Yjs updates and document snapshots are retained without compaction or a retention policy; storage and reconnect replay costs grow with usage.
- The application has no built-in per-user/IP API rate limiting. Add limits at a trusted proxy or API gateway, especially for registration and AI requests.
- No application-level response cache is configured; introduce shared caching only for measured read hotspots with explicit invalidation.
- The repository does not include browser-level interaction tests, a deployment manifest, or automated database/Redis backups. Configure and exercise backups and restore procedures before production use.
- Monitor the production build's lazy editor chunk and update the browser compatibility dataset when dependencies are refreshed.
- HSTS subdomain coverage and browser preload are intentionally not enabled by default; `check --deploy` reports those policy choices so they can be reviewed against the deployed domain.
