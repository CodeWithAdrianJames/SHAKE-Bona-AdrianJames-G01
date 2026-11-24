# SHAKE — Agent & Development Context Rules

This project is **SHAKE (Structured Handling and Automated Knowledge Extraction)**, an offline-first Django + Bootstrap 5 web application backed by a normalized relational database (PostgreSQL via `DATABASE_URL`, with automatic local SQLite `db.sqlite3` fallback). Follow the project architecture, business rules (`BR-01`–`BR-13`), and GitFlow conventions defined below rather than generic defaults.

## Application Building Context

Read the following files in order before implementing or making any architectural decision:

1. `docs/context/project-overview.md` — product definition, goals, features, and scope
2. `docs/context/architecture-context.md` — system structure, boundaries, storage model, and invariants
3. `docs/context/ui-context.md` — theme, colors, typography, visual conventions, and component guidelines
4. `docs/context/code-standards.md` — implementation rules and conventions
5. `docs/context/ai-workflow-rules.md` — development workflow, scoping rules, and delivery approach
6. `docs/context/progress-tracker.md` — current phase, completed work, open questions, and next steps

Update `docs/context/progress-tracker.md` after each meaningful implementation change.

If implementation changes the architecture, scope, or standards documented in the context files, update the relevant file before continuing.
