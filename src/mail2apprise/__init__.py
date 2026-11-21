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
"""

import email
import email.policy
import json
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


def main(argv=None, stdin=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    tag = ""
    if argv[:1] == ["--tag"]:
        tag, argv = (argv[1], argv[2:]) if len(argv) >= 2 else ("", [])
    if len(argv) != 1:
        print("usage: mail2apprise.py [--tag TAG] <apprise notify URL>", file=sys.stderr)
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
