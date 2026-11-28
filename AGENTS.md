# AGENTS.md: mail2apprise

A Postfix pipe transport that turns a mail into an Apprise notification.
User-facing docs: [README.md](README.md).

## Layout

- `src/mail2apprise/__init__.py`: the whole program; `mail2apprise:main`
  is the console script `mail2apprise`. Hosts also download this one file
  from a release tag and run it with `python3`, so keep it a single
  self-contained file: standard library imports only, no imports from
  sibling modules, and keep the shebang and the
  `if __name__ == "__main__":` entry. `dependencies` stays empty.
- `tests/`: pytest. Keep I/O out of the logic so it tests without mocks.
- `Dockerfile`: the image of `mail2apprise serve` (the SMTP sink): the
  one file on the official Python image, uid 65534, port 2525.

## Conventions

- Conventional Commits, header at most 72 characters. The commit subjects
  that reach main are the changelog: `feat`/`fix`/`perf` release, `refactor`,
  `test`, `docs`, `ci`, `chore` don't (a dependency update to runtime files
  goes into the weekly maintenance release). CI lints every commit with
  [commitlint-config-mbologna](https://github.com/mbologna/commitlint-config)
  and rejects `fixup!` commits; pull requests merge with a merge commit.
- Coverage may not drop below `fail_under` in `pyproject.toml`; raise it
  when tests are added.
- Dependencies: `uv add <pkg>`; uv.lock is committed and CI installs it
  with `--locked`. `exclude-newer` keeps releases younger than 7 days out.
- `requires-python` is `>=3.10`, and ruff's `target-version` matches it.
  CI tests on Python 3.15 only: keep syntax and standard library features
  newer than 3.10 out of the code.

## Versioning

Plain SemVer, per the
[versioning standard](https://github.com/mbologna/.github/blob/main/VERSIONING.md):
`vX.Y.Z` tags with a GitHub Release each, a changelog of the commit
subjects. Each tag builds the image `ghcr.io/mbologna/mail2apprise` as
`X.Y.Z`, `X.Y` and `latest`; hosts download `src/mail2apprise/__init__.py`
at the tag, or install the console script from the repository.

- Never create, move or delete tags, and never edit a version number to cut
  a release: auto-release tags from the commit types (`feat` minor; `fix`,
  `perf`, `revert` patch; `!` or a `BREAKING CHANGE:` footer major).
- Write Conventional Commit subjects; they decide the next version.
- `version` in `pyproject.toml` is a placeholder and stays `0.0.0`.

## Template

The skeleton comes from https://github.com/mbologna/python-app-template
(`.copier-answers.yml`). Renovate's copier manager opens a pull request
for each template release; resolve conflicts in favour of this project's
code. By hand: `uvx copier update`, then `uv lock` if dependencies changed.
To change an answer: `uvx copier update -d <question>=<value>`.
