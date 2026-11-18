# mail2apprise

[![CI](https://github.com/mbologna/mail2apprise/actions/workflows/ci.yml/badge.svg)](https://github.com/mbologna/mail2apprise/actions/workflows/ci.yml)

A [Postfix](https://www.postfix.org/) pipe transport that turns local system
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
curl -fsSLo /usr/local/sbin/mail2apprise.py \
  https://raw.githubusercontent.com/mbologna/mail2apprise/v1.0.0/mail2apprise.py
chmod 755 /usr/local/sbin/mail2apprise.py
```

Then pipe the mail you want into it from `/etc/aliases`, and run `newaliases`:

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

## Development

```sh
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

Development dependencies resolve only releases at least 7 days old
(`exclude-newer` in `pyproject.toml`). A CVE fix released less than 7 days
ago needs a temporary override, for example
`exclude-newer-package = { pytest = false }` under `[tool.uv]`, removed
once the release is a week old.
