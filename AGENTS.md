# AGENTS Instructions

These rules are mandatory for all contributors and tools.

- PLease do not run any database operations, since this is only a repository. All code is tested on the server. No databse is running locally - only if started and intended.
- Keep secrets out of git. Use `.env` locally; never commit it.
- Mandatory: all new models MUST inherit `BaseModel`, all new admin classes MUST inherit `BaseAdmin`, and all new services MUST inherit `BaseService` unless an explicit exception is agreed to in advance.
- Keep settings and dependencies in sync across `pyproject.toml`, `requirements.txt`, and `uv.lock`.
- Prefer `uv sync` for dependency updates and keep changes minimal.
- Do not introduce new tools or frameworks without explicit approval.
- Always use the .venv directory
- Always let django makemigartions create the migration files. Do not wrcodexite the migrations by yourself.
- For Django Unfold admin buttons and entry points, prefer the most appropriate native Unfold action type (especially changelist actions for model-wide operations) instead of custom template buttons whenever feasible. Reference: https://unfoldadmin.com/docs/actions/introduction/

## Bridge web UI

- The Bridge runs at `http://10.0.0.165/`; its admin UI is at `http://10.0.0.165/admin/`.
- Interpret requests such as "öffne die Bridge" or "geh in die Bridge" as requests to open this web UI.
- For requests to open or work on rules, use the graphical `Microtech → Regel-Mappings` page at `/admin/microtech/microtechorderrule/builder/`.

## Release tags

- By default, increment only the patch version (the last number) for release/deployment tags, e.g. `v1.17.0` -> `v1.17.1`.
- Increase minor or major versions only when the user explicitly requests it.

## graphify

This project has a graphify knowledge graph at graphify-out/.

Rules:
- Before answering architecture or codebase questions, read graphify-out/GRAPH_REPORT.md for god nodes and community structure
- If graphify-out/wiki/index.md exists, navigate it instead of reading raw files
- For cross-module "how does X relate to Y" questions, prefer `graphify query "<question>"`, `graphify path "<A>" "<B>"`, or `graphify explain "<concept>"` over grep — these traverse the graph's EXTRACTED + INFERRED edges instead of scanning files
- After modifying code files in this session, run `graphify update .` to keep the graph current (AST-only, no API cost)
