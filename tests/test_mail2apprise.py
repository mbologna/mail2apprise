import io
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import mail2apprise as m

PLAIN = b"""From: cron@host
Subject: Cron <root@host> backup
Date: Sun, 18 Oct 2026 03:00:00 +0200
Content-Type: text/plain; charset=utf-8

restic exited 1
"""

MULTIPART = b"""From: a@b
Subject: =?utf-8?q?Caf=C3=A9_alert?=
MIME-Version: 1.0
Content-Type: multipart/alternative; boundary="X"

--X
Content-Type: text/html

<p>html</p>
--X
Content-Type: text/plain; charset=utf-8
Content-Transfer-Encoding: quoted-printable

plain caf=C3=A9
--X--
"""


def test_plain_message():
    n = m.to_notification(PLAIN)
    assert n["title"] == "Cron <root@host> backup"
    assert n["format"] == "text"
    assert n["body"] == "From: cron@host\nDate: Sun, 18 Oct 2026 03:00:00 +0200\n\nrestic exited 1"


def test_multipart_prefers_plain_and_decodes_headers():
    n = m.to_notification(MULTIPART)
    assert n["title"] == "Café alert"
    assert n["body"].endswith("plain café")
    assert "Date:" not in n["body"]


def test_defaults_and_truncation():
    n = m.to_notification(b"\n" + b"x" * 5000)
    assert n["title"] == "(no subject)"
    assert n["body"].startswith("From: (unknown sender)\n\n")
    assert len(n["body"]) == m.MAX_BODY


def test_empty_body():
    assert m.to_notification(b"Subject: s\n\n")["body"].endswith("(empty body)")


@pytest.fixture
def server():
    received = []
    status = [200]

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(status[0])
            self.end_headers()

        def log_message(self, *a):
            pass

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}/notify/x", received, status
    httpd.shutdown()


def test_main_posts(server):
    url, received, _ = server
    assert m.main([url], io.BytesIO(PLAIN)) == 0
    assert received[0]["title"] == "Cron <root@host> backup"
    assert "tag" not in received[0]


def test_tag_is_sent(server):
    url, received, _ = server
    assert m.main(["--tag", "info", url], io.BytesIO(PLAIN)) == 0
    assert received[0]["tag"] == "info"


def test_empty_tag_sends_none(server):
    url, received, _ = server
    assert m.main(["--tag", "", url], io.BytesIO(PLAIN)) == 0
    assert "tag" not in received[0]


def test_unknown_key_bounces(server, capsys):
    url, _, status = server
    status[0] = 404
    assert m.main([url], io.BytesIO(PLAIN)) == m.EX_NOUSER
    assert "refused" in capsys.readouterr().err


def test_server_error_defers(server):
    url, _, status = server
    status[0] = 503
    assert m.main([url], io.BytesIO(PLAIN)) == m.EX_TEMPFAIL


def test_unreachable_defers(capsys):
    assert m.main(["http://127.0.0.1:9/notify/x"], io.BytesIO(PLAIN)) == m.EX_TEMPFAIL
    assert "failed to notify" in capsys.readouterr().err


def test_usage():
    assert m.main([], io.BytesIO(b"")) == m.EX_USAGE
    assert m.main(["--tag"], io.BytesIO(b"")) == m.EX_USAGE
