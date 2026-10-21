# mail2apprise

[![CI](https://github.com/mbologna/mail2apprise/actions/workflows/ci.yml/badge.svg)](https://github.com/mbologna/mail2apprise/actions/workflows/ci.yml)

A [Postfix](https://www.postfix.org/) pipe transport that turns local system
mail (cron output, `unattended-upgrades` reports, smartd warnings) into a push
notification through an [Apprise API](https://github.com/caronc/apprise-api)
server. One Python file, standard library only.

The notification's title is the mail's subject. Its body starts with the
sender and date, followed by the plain-text part of the mail, truncated to
2000 characters. If Apprise can't be reached, the script exits 75
(`EX_TEMPFAIL`). Postfix then defers the mail and retries it later, so
nothing bounces or gets lost.

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

The single argument is the Apprise notify URL, including the tag.

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
