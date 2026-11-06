# CoEdit

CoEdit is a collaborative editor with a React/Vite frontend and a Django/Channels backend.

## Repository layout

- `apps/web/` contains the frontend application.
- `apps/server/` contains the Django backend. Its project and Django app are in `src/core/` and `src/editor/`.

## Development

Install frontend dependencies with `npm ci --prefix apps/web`, then start the frontend with `npm run dev`. Root-level `npm run build` and `npm run preview` proxy to the frontend scripts.

Install backend dependencies with `pip install -r apps/server/requirements.txt`. Run Django commands from `apps/server`, for example `python manage.py check` or `python manage.py runserver`. The backend's configuration and production guidance are in [apps/server/README.md](./apps/server/README.md).

The CI workflow builds the frontend and runs Django checks and tests.
