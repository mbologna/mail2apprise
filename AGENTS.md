# AGENTS.md

Notes for coding agents working in this repository. [README.md](README.md) covers what it does and how to use it.

## Versioning

Plain SemVer: `vX.Y.Z` tags, each a GitHub Release from which users install
`mail2apprise.py` (nothing is built or published), per the
[versioning standard](https://github.com/mbologna/.github/blob/main/VERSIONING.md).

- Never create, move or delete tags, and never edit a version number to cut
  a release: auto-release tags from the commit types (`feat` minor; `fix`,
  `perf`, `revert` patch; `!` or a `BREAKING CHANGE:` footer major).
- Write Conventional Commit subjects; they decide the next version.
- `version` in `pyproject.toml` is a placeholder and stays `0.0.0`: the
  project is not packaged (`package = false`) and nothing reads it. Tags are
  the version.
