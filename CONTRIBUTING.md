# Contributing to Stella

Contributions of all sizes are welcome, from documentation fixes to new features.

## Language policy

To keep the project accessible to a global community, **please write issues,
pull requests, code comments, and commit messages in English.**

> 为方便全球开发者协作，请尽量使用**英文**提交 issue、PR、代码注释与
> commit message。不必担心英文不完美——表达清楚即可，工具翻译也完全没问题。感谢理解 ❤️

## Reporting issues

Found a bug or have an idea? [Open an issue](https://github.com/starpickerr/Stella/issues/new/choose).

Before opening one, please search existing issues (including closed ones) to
avoid duplicates, and make sure you're on the latest version.

## Submitting a pull request

1. **Fork** the repo and create a branch from `develop`
   (e.g. `feat/web-search`, `fix/telegram-reconnect`). Use `feat/` for new
   features and `fix/` for bug fixes; use `docs/`, `refactor/`, or `chore/`
   when those better describe the change.
2. Make your change. Keep it focused — one logical change per PR.
3. Follow the existing code style. Write comments and docstrings in English.
4. Run the app locally to confirm your change works.
5. Open a PR targeting `develop`, with a clear title and a short description of
   **what** and **why**. If your branch depends on another open PR, mention that
   dependency and update the target after the earlier PR merges.

`develop` holds integrated work before release. `main` is the release branch:
when a version is ready, open a PR from `develop` into `main`, verify the
release, and tag the release from `main`.

We keep the bar friendly: clear, focused, and working is enough. Maintainers are
happy to help polish details during review.

### Commit & PR titles

Use a short, imperative summary. The [Conventional Commits](https://www.conventionalcommits.org/)
style is preferred but not required:

```
feat: add web search tool
fix: reconnect Telegram websocket on timeout
docs: clarify desktop setup
```

## Development setup

See [Build from Source](docs/guide.md) for prerequisites and Windows commands. From a source checkout:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip setuptools
.venv/bin/python -m pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m playwright install chromium
npm --prefix desktop ci
npm --prefix desktop run dev
```

See [Desktop development](desktop/README.md) for hot reload and packaging.

## Quality checks

Run checks appropriate to your changes:

```bash
.venv/bin/python scripts/quality_check.py incremental
```

The runner selects checks from changed files, isolates Stella state in a temporary directory, and prints PASS/FAIL/SKIP. Use `--files path/to/changed.py` to check specific paths. For the full Python and frontend suite, build, and browser checks:

```bash
.venv/bin/python scripts/quality_check.py full --report /tmp/stella-quality-report.md
```

On Windows, use `.venv\Scripts\python.exe` and choose a writable report path. The runner resolves native npm and Python executables and cleans up the private renderer process tree.

Tests use temporary user data. Manual app launches share `~/.stella` with the installed app, so back up your data before testing changes that affect storage.

## Code of conduct

Be respectful and constructive. We want Stella to be a welcoming place for everyone.
