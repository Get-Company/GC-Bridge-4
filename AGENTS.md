# AGENTS Instructions

These rules are mandatory for all contributors and tools.

- Keep secrets out of git. Use `.env` locally; never commit it.
- Use the provided base classes (`BaseModel`, `BaseAdmin`, `BaseService`) as the default foundation for new code.
- Keep settings and dependencies in sync across `pyproject.toml`, `requirements.txt`, and `uv.lock`.
- Prefer `uv sync` for dependency updates and keep changes minimal.
- Do not introduce new tools or frameworks without explicit approval.
