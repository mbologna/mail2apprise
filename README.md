# mail2apprise

[![CI](https://github.com/mbologna/mail2apprise/actions/workflows/ci.yml/badge.svg)](https://github.com/mbologna/mail2apprise/actions/workflows/ci.yml)

A [Postfix](https://www.postfix.org/) pipe transport, and an SMTP sink, that turn local system
mail (cron output, `unattended-upgrades` reports, smartd warnings) into a push
notification through an [Apprise API](https://github.com/caronc/apprise-api)
server. One Python file, standard library only.

The notification's title is the mail's subject. Its body starts with the
sender and date, followed by the plain-text part of the mail, truncated to
2000 characters. Both go out as plain text (`format: text`), so Apprise
escapes them for HTML targets such as Telegram, which would otherwise reject a
`<root@host>` in a cron subject. If Apprise can't be reached, the script exits 75
(`EX_TEMPFAIL`). Postfix then defers the mail and retries it later, so
nothing is lost.

## Install

```sh
TAG=vX.Y.Z  # the newest release
curl -fsSLo /usr/local/sbin/mail2apprise.py \
  "https://raw.githubusercontent.com/mbologna/mail2apprise/$TAG/src/mail2apprise/__init__.py"
chmod 755 /usr/local/sbin/mail2apprise.py
```

Set `TAG` to the newest [release](https://github.com/mbologna/mail2apprise/releases).
The script lives at `src/mail2apprise/__init__.py` from v1.1.1; up to
v1.1.0 it sits at the repository root, as `mail2apprise.py`. It is still
one self-contained file, so the downloaded copy runs on its own with
`python3`.

From v1.1.1 you can instead install a `mail2apprise` command with
[uv](https://docs.astral.sh/uv/) or
[pipx](https://pipx.pypa.io/). Postfix runs the pipe as an unprivileged
user (`nobody` by default), so install it system-wide rather than under
root's home, and use `/usr/local/bin/mail2apprise` in place of
`/usr/local/sbin/mail2apprise.py` below:

```sh
sudo UV_TOOL_DIR=/opt/uv-tools UV_TOOL_BIN_DIR=/usr/local/bin \
  uv tool install --python /usr/bin/python3 "git+https://github.com/mbologna/mail2apprise@$TAG"
# or, with pipx 1.5 or later:
sudo pipx install --global "git+https://github.com/mbologna/mail2apprise@$TAG"
```

Then pipe the mail you want into it from `/etc/aliases`, and run
`newaliases`:

```
root: sysalert
sysalert: "|/usr/local/sbin/mail2apprise.py http://apprise:8000/notify/system-alerts"
```

The argument is the Apprise notify URL, including the config key. An optional
`--tag TAG` before it sends Apprise's `tag` field, to pick a tagged URL inside
that config; an empty `TAG` sends none.

If Apprise answers with a client error (a `404` for a config key that doesn't
exist), the script exits 67 (`EX_NOUSER`) and Postfix bounces the mail at once:
retrying can't help. Server errors and an unreachable Apprise exit 75 and the
mail waits in the queue.

A Postfix pipe can route by recipient: with a transport for a dedicated domain,
`<key>+<tag>@notify.example` becomes the key and the tag (`${user}` and
`${extension}` in `master.cf`):

```
apprise   unix  -       n       n       -       -       pipe
  flags=Rq user=nobody argv=/usr/local/sbin/mail2apprise.py --tag ${extension} http://apprise:8000/notify/${user}
```

## SMTP sink: `mail2apprise serve`

The same conversion as an SMTP server, for a mail sink that other hosts
relay to (Postfix `relayhost`), without Postfix on the sink. It routes like
the `master.cf` transport above: `<key>[+<tag>]@MAIL2APPRISE_DOMAIN` goes to
`/notify/<key>` with that tag, a local part in that domain that can't be a
key is refused at `RCPT` (550), and every other recipient goes to the
catch-all key. Each Apprise base URL is tried in order. A client error (no
such config key) answers 550, so the sending host bounces the mail; every
URL failing answers 451, so it keeps the mail and retries. One reply covers
the whole mail: with several targets, one deferred defers it all, and the
ones already delivered may arrive twice on the retry.

| Variable | Default | |
|---|---|---|
| `MAIL2APPRISE_URLS` | (required) | Apprise API base URLs, space-separated, tried in order (`http://apprise:8000 http://apprise-2:8000`) |
| `MAIL2APPRISE_DOMAIN` | empty (no routing) | The pseudo-domain whose local parts are config keys |
| `MAIL2APPRISE_CATCHALL_KEY` | `system-alerts` | Config key for every other recipient |
| `MAIL2APPRISE_CATCHALL_TAG` | empty | Its tag |
| `MAIL2APPRISE_LISTEN` | `0.0.0.0` | Listen address |
| `MAIL2APPRISE_PORT` | `2525` | Listen port (unprivileged; map 25 to it) |
| `MAIL2APPRISE_MAX_SIZE` | `1048576` | Largest mail accepted, in bytes (552 above) |
| `MAIL2APPRISE_HOSTNAME` | `mail2apprise` | Name in the greeting |

It speaks the plain SMTP a relaying MTA uses (`EHLO`, `MAIL`, `RCPT`,
`DATA`, `RSET`, `NOOP`, `QUIT`): no TLS, no authentication, and it relays
nothing anywhere but Apprise. Expose it only on a private network (a
tailnet, a cluster), never to the internet.

The image `ghcr.io/mbologna/mail2apprise` (linux/amd64 and linux/arm64,
tagged `X.Y.Z`, `X.Y` and `latest` for each release) runs `serve` as uid
65534 on port 2525 and works with a read-only root filesystem:

```sh
docker run -p 25:2525 -e MAIL2APPRISE_URLS=http://apprise:8000 \
  -e MAIL2APPRISE_DOMAIN=notify.example ghcr.io/mbologna/mail2apprise:X.Y.Z
```

A TCP check on the port is a sufficient readiness and liveness probe.

## Development

```sh
uv run pytest --cov
uv run ruff check . && uv run ruff format --check .
uv run pre-commit run --all-files
```

The skeleton (CI, pre-commit, `pyproject.toml` tooling) comes from
[python-app-template](https://github.com/mbologna/python-app-template).

Development dependencies resolve only releases at least 7 days old
(`exclude-newer` in `pyproject.toml`). A CVE fix released less than 7 days
ago needs a temporary override, for example
`exclude-newer-package = { pytest = false }` under `[tool.uv]`, removed
once the release is a week old.

## Why not an existing tool

- [mailrise](https://github.com/YoRyan/mailrise) is an SMTP server that sends
  each mail to Apprise. It has had no release since July 2023, and it has one
  main maintainer.
- The [`apprise` CLI](https://github.com/caronc/apprise) sends a title and a
  body given on its command line. It can't read an email (the Subject as the
  title, the text/plain part decoded with its charset), and it exits 1 for
  every failure, so a mail server can't tell whether to defer or bounce.
- [ntfy](https://ntfy.sh/) can publish the emails it receives, but to ntfy
  topics, not to Apprise.

Checked 2026-11-23. A planned upstream pull request would add email input to
the `apprise` CLI: [#26](https://github.com/mbologna/mail2apprise/issues/26).

## Versioning

Releases follow SemVer: [auto-release](https://github.com/mbologna/auto-release)
tags `vX.Y.Z` from the Conventional Commit types (`feat` minor; `fix`,
`perf`, `revert` patch; a breaking change major) and publishes a GitHub
Release with the notes, and the tag builds the `serve` image; the script
itself you download or install from the tag. See the
[versioning standard](https://github.com/mbologna/.github/blob/main/VERSIONING.md).
