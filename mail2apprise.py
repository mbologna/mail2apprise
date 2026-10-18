#!/usr/bin/env python3
"""Postfix pipe transport that turns a mail into an Apprise notification.

Reads one RFC 2822 message on stdin and POSTs its subject, sender, date and
plain-text body to an Apprise API notify URL, for example in /etc/aliases:

    root: "|/usr/local/sbin/mail2apprise.py http://apprise:8000/notify/system-alerts"

Standard library only. If Apprise can't be reached it exits 75 (EX_TEMPFAIL),
so Postfix defers the mail and retries it later instead of bouncing it.
"""

import email
import email.policy
import json
import sys
import urllib.error
import urllib.request

EX_USAGE = 64
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
    return {"title": str(msg.get("Subject", "(no subject)")), "body": body[:MAX_BODY]}


def post(url, notification, timeout=10):
    req = urllib.request.Request(
        url,
        data=json.dumps(notification).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        resp.read()


def main(argv=None, stdin=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: mail2apprise.py <apprise notify URL>", file=sys.stderr)
        return EX_USAGE
    raw = (stdin or sys.stdin.buffer).read()
    try:
        post(argv[0], to_notification(raw))
    except (urllib.error.URLError, OSError) as exc:
        print(f"mail2apprise: failed to notify: {exc}", file=sys.stderr)
        return EX_TEMPFAIL
    return 0


if __name__ == "__main__":
    sys.exit(main())
