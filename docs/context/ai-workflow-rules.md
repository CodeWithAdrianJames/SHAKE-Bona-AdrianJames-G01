# Development Workflow

## Approach

Build this project incrementally using a spec-driven workflow. Context files (`AGENTS.md`, `docs/context/*`) and feature specs define what to build, how to enforce business rules (`BR-01`–`BR-13`), and what the current implementation state is. Always implement against these specs — do not invent unapproved features or external cloud dependencies.

## Scoping Rules

- Work on one feature unit or subsystem at a time.
- Prefer small, verifiable increments over large speculative changes.
- Do not combine unrelated system boundaries in a single implementation step.

## When To Split Work

Split an implementation step if it combines:

- Extraction engine / parser changes and UI template redesigns
- New database schema migrations and REST API endpoint implementations
- Multiple unrelated routes or administrative modules
- Behavior that is not clearly defined in the context files or SDD

If a change cannot be verified end to end quickly via `manage.py test`, the scope is too broad — split it.

## Handling Missing Requirements

- Do not invent product behavior that is not defined in the context files or SDD.
- If a requirement is ambiguous (for example, API token format for `F-11`), resolve it in the relevant context/spec file before implementing.
- If a requirement is missing, add it under `Open Questions` in `docs/context/progress-tracker.md` before continuing.

## Protected Foundation Components

Do not modify established foundation files unless a task explicitly requires it:

- Applied migrations: `accounts/migrations/0001_initial.py`, `contracts/migrations/0001_initial.py`, `contracts/migrations/0002_seed_default_carriers.py`
- Core shared form helpers (`BootstrapFormMixin` and `templates/includes/form_fields.html`)
- Offline engine privacy boundary (never add external HTTP/cloud SDK calls to `contracts/engine/`)

Project-specific extensions must build cleanly on top of existing mixins, services, and normalized models.

## Keeping Docs In Sync

Update the relevant context file whenever implementation changes:

- System architecture, models, or endpoint boundaries (`docs/context/architecture-context.md`)
- Database configuration or storage behavior (`docs/context/architecture-context.md`)
- Code conventions, API rules, or validation patterns (`docs/context/code-standards.md`)
- UI layout, status badges, or navigation (`docs/context/ui-context.md`)
- Feature completion status (`docs/context/progress-tracker.md`)

Progress state must reflect the actual verified state of the codebase, not the intended state.

## Before Moving To The Next Unit

1. The current unit works end to end within its defined scope and passes `manage.py test` under SQLite (and PostgreSQL when `.env` is active).
2. No invariant or business rule (`BR-01`–`BR-13`) defined in `architecture-context.md` was violated.
3. `docs/context/progress-tracker.md` reflects the completed work and updated GitFlow commit/branch state.
