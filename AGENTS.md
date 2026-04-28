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

## graphify

This project has a graphify knowledge graph at graphify-out/.

Rules:
- Before answering architecture or codebase questions, read graphify-out/GRAPH_REPORT.md for god nodes and community structure
- If graphify-out/wiki/index.md exists, navigate it instead of reading raw files
- For cross-module "how does X relate to Y" questions, prefer `graphify query "<question>"`, `graphify path "<A>" "<B>"`, or `graphify explain "<concept>"` over grep — these traverse the graph's EXTRACTED + INFERRED edges instead of scanning files
- After modifying code files in this session, run `graphify update .` to keep the graph current (AST-only, no API cost)
