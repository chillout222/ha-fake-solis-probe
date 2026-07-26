# Contributing to ha-fake-solis-probe

Thank you for your interest in contributing! This is a small community project, so
contributions are welcome — especially from people running different Solis models or
Tibber setups.

## Bug Reports

Please use the [bug report template](.github/ISSUE_TEMPLATE/bug_report.md).
Before filing, check existing issues to avoid duplicates.

**Important:** Remove all IP addresses, sensor entity IDs, and any personally
identifiable information before posting logs or configuration snippets.

## Feature Requests

Use the [feature request template](.github/ISSUE_TEMPLATE/feature_request.md).

## Pull Requests

- Keep PRs small and focused — one change per PR
- Follow [PEP 8](https://pep8.org/) for Python code
- Update `CHANGELOG.md` under `[Unreleased]` with a short description of your change
- Run the development checks before submitting (see below)
- Do not commit personal information (IP addresses, entity IDs, tokens, real names unless you choose to)

## Development Checks

Install the development-only tools, then run the same checks as CI:

```sh
python -m pip install --requirement requirements-dev.txt
python -m ruff check .
python -m ruff format --check .
python -m pytest
```

Ruff and pytest are development dependencies only. The Home Assistant add-on
continues to use only the Python standard library at runtime.

## Testing Locally

1. Copy `fake_solis_probe/` to your HA `/addons/` via Samba
2. Reload the addon store and install
3. Configure sensors and start the addon
4. Verify in the Log tab and `events.jsonl` that polling works
5. Confirm Tibber Bridge connects and reads data

## Code Style

- Python 3.11+, standard library only (no external dependencies)
- Type hints on all public functions
- Log events via `log_event()` — do not use `print()` except in `load_options()` before logging is available
- All Modbus logic goes through `ModbusHandler` — do not add protocol handling elsewhere

## What We're Not Looking For

- Dependencies on external Python packages (keep it stdlib-only)
- Changes that forward any data to external services
- Hardcoded IP addresses, tokens, or entity IDs
