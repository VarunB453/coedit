# Contributing

## Development setup

- Frontend: run `npm ci --prefix apps/web`, then `npm run dev`.
- Backend: install `apps/server/requirements.txt`, copy the needed settings from `.env.example` to `apps/server/.env`, then run `python apps/server/manage.py runserver`.

The root `package.json` provides shortcuts for common frontend and backend commands. The Django test suite is `python apps/server/manage.py test editor`.

## Before opening a pull request

Run `npm run build`, `python apps/server/manage.py check`, `python apps/server/manage.py makemigrations --check`, and `python apps/server/manage.py test editor` for relevant changes. Keep changes focused, add or update tests for behavior changes, and never commit credentials, local databases, or build output.

The CI workflow runs the frontend build and backend checks and tests on pushes and pull requests.
