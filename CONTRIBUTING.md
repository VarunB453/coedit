# Contributing

## Development setup

- Frontend: run `npm ci --prefix apps/web`, then `npm run dev`.
- Backend: install `apps/server/requirements.txt`, copy the needed settings from `.env.example` to `apps/server/.env`, then run `python apps/server/manage.py runserver`.

The root `package.json` provides shortcuts for common frontend and backend commands. The Django test suite is `python apps/server/manage.py test editor`.

## Before opening a pull request

Run `npm run build`, `python apps/server/manage.py check`, `python apps/server/manage.py makemigrations --check`, and `python apps/server/manage.py test editor` for relevant changes. Keep changes focused, add or update tests for behavior changes, and never commit credentials, local databases, or build output.

The CI workflow runs the frontend build and backend checks and tests on pushes and pull requests.

## Code conventions

- Use Python `snake_case` for modules, functions, and variables; use four spaces for indentation. Use TypeScript `camelCase`, PascalCase React component symbols, and kebab-case component filenames.
- Keep code in its domain feature/module. Keep Django models and migrations in the existing `editor` app unless a migration is planned to preserve the app label and schema history.
- Return API errors through `modules.shared.http.error` with the established `{"error": "..."}` body and appropriate HTTP status. Parse JSON request bodies with `parse_json_object`; catch only expected errors, and do not hide unexpected failures behind success-shaped responses.
- Frontend request helpers should reject unsuccessful responses with the server error message when available; UI boundaries should catch and display actionable errors.
