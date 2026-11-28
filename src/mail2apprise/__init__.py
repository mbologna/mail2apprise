#!/usr/bin/env python3
"""Postfix pipe transport that turns a mail into an Apprise notification.

Reads one RFC 2822 message on stdin and POSTs its subject, sender, date and
plain-text body to an Apprise API notify URL, for example in /etc/aliases:

    root: "|/usr/local/sbin/mail2apprise.py http://apprise:8000/notify/system-alerts"

An optional --tag TAG before the URL sends Apprise's tag field (an empty TAG
sends none), so a Postfix pipe can pass a recipient's extension through.

Standard library only. If Apprise can't be reached, or answers with a server
error, it exits 75 (EX_TEMPFAIL), so Postfix defers the mail and retries it
later. A client error (404 for a config key that doesn't exist) exits 67
(EX_NOUSER): retrying can't help, so Postfix bounces the mail at once.

`mail2apprise serve` is the same as an SMTP server, for a mail sink that
other hosts relay to: <key>[+<tag>]@MAIL2APPRISE_DOMAIN goes to
/notify/<key> with that tag, any other recipient to the catch-all key, each
Apprise base URL in MAIL2APPRISE_URLS tried in order. A client error answers
550 (the sender bounces), every URL failing 451 (the sender retries). See
serve_config() for the environment it reads.
"""

import asyncio
import email
import email.policy
import json
import os
import re
import sys
import urllib.error
import urllib.request

EX_USAGE = 64
EX_NOUSER = 67
EX_TEMPFAIL = 75
MAX_BODY = 2000


def plain_text(msg):
    """The first text/plain part, decoded, or the whole payload if not multipart."""
    part = msg.get_body(preferencelist=("plain",)) if msg.is_multipart() else msg
    if part is None:
        return ""
    payload = part.get_payload(decode=True) or b""
    return payload.decode(part.get_content_charset() or "utf-8", errors="replace").strip()


def to_notification(raw):
    """Title and body for Apprise, from the raw message bytes."""
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    header = [f"From: {msg.get('From', '(unknown sender)')}"]
    if msg.get("Date"):
        header.append(f"Date: {msg['Date']}")
    body = "\n".join(header) + "\n\n" + (plain_text(msg) or "(empty body)")
    # format=text makes Apprise escape the text for HTML targets: Telegram
    # rejects a raw "<root@host>" (cron subjects, From headers) as an unknown
    # tag, and the notification fails.
    return {
        "title": str(msg.get("Subject", "(no subject)")),
        "body": body[:MAX_BODY],
        "format": "text",
    }


def post(url, notification, timeout=10):
    req = urllib.request.Request(
        url,
        data=json.dumps(notification).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310: URL from the admin's alias/master.cf
        resp.read()


# ── serve: an SMTP sink ──────────────────────────────────────────────────────

KEY_RE = re.compile(r"^(?P<key>[a-z0-9_-]+)(?:\+(?P<tag>[a-z0-9_-]+))?$")
DELIVERED, BOUNCED, DEFERRED = "delivered", "bounced", "deferred"


def serve_config(env=None):
    """The server's settings, from the environment."""
    env = os.environ if env is None else env
    return {
        # Listen address and port: 2525 needs no privilege; a Kubernetes
        # Service or a firewall maps 25 to it.
        "host": env.get("MAIL2APPRISE_LISTEN", "0.0.0.0"),  # nosec B104: a sink listens for other hosts
        "port": int(env.get("MAIL2APPRISE_PORT", "2525")),
        # Apprise API base URLs (http://apprise:8000), space-separated, tried in order.
        "urls": env.get("MAIL2APPRISE_URLS", "").split(),
        # Mail to <key>[+<tag>]@domain goes to that key; empty turns routing off.
        "domain": env.get("MAIL2APPRISE_DOMAIN", "").lower(),
        # Every other recipient.
        "catchall_key": env.get("MAIL2APPRISE_CATCHALL_KEY", "system-alerts"),
        "catchall_tag": env.get("MAIL2APPRISE_CATCHALL_TAG", ""),
        "max_size": int(env.get("MAIL2APPRISE_MAX_SIZE", str(1024 * 1024))),
        "hostname": env.get("MAIL2APPRISE_HOSTNAME", "mail2apprise"),
    }


def route(address, config):
    """(key, tag) for a recipient address, or None for a local part in the
    routing domain that can't be a config key."""
    local, _, domain = address.strip().strip("<>").rpartition("@")
    if config["domain"] and domain.lower() == config["domain"]:
        m = KEY_RE.match(local.lower())
        return (m["key"], m["tag"] or "") if m else None
    return config["catchall_key"], config["catchall_tag"]


def deliver(notification, key, tag, urls, poster=post):
    """Post to /notify/<key> at each base URL in turn: DELIVERED on the first
    success, BOUNCED on a client error (no other server would know the key
    better), DEFERRED when every URL fails otherwise."""
    if tag:
        notification = {**notification, "tag": tag}
    for base in urls:
        try:
            poster(f"{base.rstrip('/')}/notify/{key}", notification)
            return DELIVERED
        except urllib.error.HTTPError as exc:
            print(f"mail2apprise: {base} refused /notify/{key}: {exc}", file=sys.stderr)
            if 400 <= exc.code < 500:
                return BOUNCED
        except (urllib.error.URLError, OSError) as exc:
            print(f"mail2apprise: {base} failed for /notify/{key}: {exc}", file=sys.stderr)
    return DEFERRED


def outcome(results):
    """The SMTP reply to DATA for the per-target results. One mail has one
    reply: any deferred target defers it all (the delivered ones may repeat
    on the retry), only bounced targets bounce it."""
    if DEFERRED in results:
        return "451 4.3.0 Apprise unavailable, try again later"
    if DELIVERED not in results:
        return "550 5.1.1 Apprise has no such config key"
    return "250 2.0.0 Delivered to Apprise"


class SMTPSession:
    """One client connection: the subset of SMTP a relaying MTA uses."""

    def __init__(self, reader, writer, config, poster=post):
        self.reader, self.writer, self.config, self.poster = reader, writer, config, poster
        self.reset()

    def reset(self):
        self.sender, self.targets = None, []

    async def reply(self, line):
        self.writer.write(line.encode() + b"\r\n")
        await self.writer.drain()

    async def run(self):
        await self.reply(f"220 {self.config['hostname']} ESMTP mail2apprise")
        while line := await self.reader.readline():
            verb, _, arg = line.decode("utf-8", "replace").strip().partition(" ")
            handler = getattr(self, "smtp_" + verb.upper(), None)
            if handler is None:
                await self.reply("502 5.5.2 Command not recognized")
            elif await handler(arg.strip()) is False:
                break
        self.writer.close()

    async def smtp_EHLO(self, arg):
        await self.reply(f"250-{self.config['hostname']}")
        await self.reply(f"250-SIZE {self.config['max_size']}")
        await self.reply("250 8BITMIME")

    async def smtp_HELO(self, arg):
        await self.reply(f"250 {self.config['hostname']}")

    async def smtp_MAIL(self, arg):
        if not arg.upper().startswith("FROM:"):
            return await self.reply("501 5.5.4 Syntax: MAIL FROM:<address>")
        self.reset()
        self.sender = arg[5:].split()[0] if arg[5:].split() else "<>"
        await self.reply("250 2.1.0 OK")

    async def smtp_RCPT(self, arg):
        if self.sender is None:
            return await self.reply("503 5.5.1 MAIL first")
        if not arg.upper().startswith("TO:") or not arg[3:].split():
            return await self.reply("501 5.5.4 Syntax: RCPT TO:<address>")
        target = route(arg[3:].split()[0], self.config)
        if target is None:
            return await self.reply("550 5.1.1 Not an Apprise config key")
        if target not in self.targets:
            self.targets.append(target)
        await self.reply("250 2.1.5 OK")

    async def smtp_DATA(self, arg):
        if not self.targets:
            return await self.reply("503 5.5.1 RCPT first")
        await self.reply("354 End data with <CR><LF>.<CR><LF>")
        lines, size = [], 0
        while True:
            line = await self.reader.readline()
            if not line or line.rstrip(b"\r\n") == b".":
                break
            size += len(line)
            if size <= self.config["max_size"]:
                lines.append(line[1:] if line.startswith(b".") else line)
        if not line:
            return False
        if size > self.config["max_size"]:
            self.reset()
            return await self.reply("552 5.3.4 Message too big")
        notification = to_notification(b"".join(lines))
        results = [
            await asyncio.to_thread(deliver, notification, key, tag, self.config["urls"], self.poster)
            for key, tag in self.targets
        ]
        self.reset()
        await self.reply(outcome(results))

    async def smtp_RSET(self, arg):
        self.reset()
        await self.reply("250 2.0.0 OK")

    async def smtp_NOOP(self, arg):
        await self.reply("250 2.0.0 OK")

    async def smtp_VRFY(self, arg):
        await self.reply("252 2.1.5 Cannot verify, send some mail")

    async def smtp_QUIT(self, arg):
        await self.reply("221 2.0.0 Bye")
        return False


async def start_server(config, poster=post):
    async def handle(reader, writer):
        await SMTPSession(reader, writer, config, poster).run()

    return await asyncio.start_server(handle, config["host"], config["port"])


async def serve_forever(config):
    server = await start_server(config)
    print(f"mail2apprise: listening on {config['host']}:{config['port']}", file=sys.stderr)
    async with server:
        await server.serve_forever()


def serve(env=None):
    config = serve_config(env)
    if not config["urls"]:
        print("mail2apprise serve: set MAIL2APPRISE_URLS to one or more Apprise base URLs", file=sys.stderr)
        return EX_USAGE
    asyncio.run(serve_forever(config))
    return 0


def main(argv=None, stdin=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv == ["serve"]:
        return serve()
    tag = ""
    if argv[:1] == ["--tag"]:
        tag, argv = (argv[1], argv[2:]) if len(argv) >= 2 else ("", [])
    if len(argv) != 1:
        print("usage: mail2apprise.py [--tag TAG] <apprise notify URL> | mail2apprise.py serve", file=sys.stderr)
        return EX_USAGE
    raw = (stdin or sys.stdin.buffer).read()
    notification = to_notification(raw)
    if tag:
        notification["tag"] = tag
    try:
        post(argv[0], notification)
    except urllib.error.HTTPError as exc:
        print(f"mail2apprise: Apprise refused the notification: {exc}", file=sys.stderr)
        return EX_NOUSER if 400 <= exc.code < 500 else EX_TEMPFAIL
    except (urllib.error.URLError, OSError) as exc:
        print(f"mail2apprise: failed to notify: {exc}", file=sys.stderr)
        return EX_TEMPFAIL
    return 0


if __name__ == "__main__":
    sys.exit(main())
