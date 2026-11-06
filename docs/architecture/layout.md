# Repository layout

This tree separates application areas while preserving the currently working React/Vite frontend and Django/Channels backend.

## Implemented code

- `apps/web/src/App.tsx` and `apps/web/src/components/` contain the current frontend.
- `apps/server/src/core/` and `apps/server/src/editor/` contain the Django project, API, collaboration services, and tests. The editor app currently owns several capabilities that may later be split into domain modules.
- `.github/workflows/ci.yml` is the active CI workflow for both applications.

## Scaffolded extension points

The remaining feature, shared-package, infrastructure, and test directories are extension points only. They are intentionally empty; no runtime behavior or TypeScript backend is implied by their presence. Move or implement code there when a feature has a concrete design and tests.

The frontend feature areas are reserved for auth, documents, collaboration, comments, and AI assistant code. The backend module areas are reserved for domain-oriented Django modules; the existing `editor` app remains authoritative until a module is migrated with its models, migrations, routes, and tests together.

Deployment manifests, browser/integration/performance tests, shared packages, and proxy/container configuration are not yet implemented.

The Dockerfiles and Compose file provide a local development stack only; they are not production deployment assets. A `LICENSE` file is intentionally omitted until the repository owner selects a license.
