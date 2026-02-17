# AGENTS Instructions

These rules are mandatory for all contributors and tools.

- Keep secrets out of git. Use `.env` locally; never commit it.
- Mandatory: all new models MUST inherit `BaseModel`, all new admin classes MUST inherit `BaseAdmin`, and all new services MUST inherit `BaseService` unless an explicit exception is agreed to in advance.
- Keep settings and dependencies in sync across `pyproject.toml`, `requirements.txt`, and `uv.lock`.
- Prefer `uv sync` for dependency updates and keep changes minimal.
- Do not introduce new tools or frameworks without explicit approval.
- Always use the .venv directory
- Always let django makemigartions create the migration files. Do not wrcodexite the migrations by yourself.