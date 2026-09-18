# Contributing

Thanks for helping improve Draper Marketing Pipeline.

## Development Setup

```bash
git clone https://github.com/your-org/draper.git
cd draper
uv venv
uv pip install -e ".[dev]"
source .venv/bin/activate
cp .env.example .env
```

Do not commit real credentials, generated runtime data, or customer/project secrets. Runtime
state belongs under `data/` and is ignored by default.

## Quality Gates

Run these before opening a pull request:

```bash
python -m ruff check .
python -m pytest
python -m build
```

Use `python -m ruff format .` for formatting-only changes.

## Pull Requests

- Keep changes scoped to one problem or feature.
- Include tests for behavior changes and bug fixes.
- Update README or docs when commands, configuration, security behavior, or public APIs change.
- Prefer existing service boundaries in `services/`, `feedback/`, `projects/`, and `integrations/`
  before adding more dashboard route-side logic.

## Security

Report security issues privately through the process in [`SECURITY.md`](SECURITY.md).
