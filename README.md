# CoEdit

CoEdit is a collaborative editor with a React/Vite frontend and a Django/Channels backend.

## Repository layout

- `apps/web/` contains the frontend application.
- `apps/web/src/app/` composes the application; `src/features/` groups auth, documents, workspaces, editing, collaboration, notifications, and AI UI by domain.
- `apps/server/` contains the Django backend. `src/core/` owns Django configuration, `src/editor/` keeps the stable models/migrations and compatibility view facade, and `src/modules/` contains domain views and shared request/validation helpers.

## Development

Install frontend dependencies with `npm ci --prefix apps/web`, then start the frontend with `npm run dev`. Root-level `npm run build` and `npm run preview` proxy to the frontend scripts.

Install backend dependencies with `pip install -r apps/server/requirements.txt`. Run Django commands from `apps/server`, for example `python manage.py check` or `DEBUG=true python manage.py runserver`. The backend's configuration and production guidance are in [apps/server/README.md](./apps/server/README.md).

For a containerized local development environment, run `docker compose up --build`; the frontend, Django/Channels backend, and Redis are exposed on ports 5173, 8000, and 6379. The development compose file uses a local-only fallback key; configure a private `SECRET_KEY` for any shared or deployed environment.

The CI workflow builds the frontend and runs Django checks and tests. See [CONTRIBUTING.md](./CONTRIBUTING.md) for setup and validation, and [SECURITY.md](./SECURITY.md) for vulnerability reporting. Dockerfiles for local development are kept alongside each application.
