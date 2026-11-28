import asyncio
import io
import json
import smtplib
import threading
import time
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


# ── serve ────────────────────────────────────────────────────────────────────


def apprise(statuses):
    """A stand-in Apprise API answering each POST with the next of `statuses`
    (the last one repeats); returns (base URL, received (path, body) pairs)."""
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            self.send_response(statuses.pop(0) if len(statuses) > 1 else statuses[0])
            self.end_headers()

        def log_message(self, *a):
            pass

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{httpd.server_port}", received


@pytest.fixture
def smtp():
    """Start mail2apprise serve on a free port with the given Apprise URLs;
    yields a function returning an smtplib client connected to it."""
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    servers = []

    def start(urls, **overrides):
        config = m.serve_config({"MAIL2APPRISE_URLS": " ".join(urls), "MAIL2APPRISE_DOMAIN": "apprise.example"})
        config.update(host="127.0.0.1", port=0, **overrides)
        srv = asyncio.run_coroutine_threadsafe(m.start_server(config), loop).result()
        servers.append(srv)
        return smtplib.SMTP("127.0.0.1", srv.sockets[0].getsockname()[1], timeout=10)

    yield start

    # On the loop's own thread: asyncio servers are not thread-safe.
    async def stop():
        for srv in servers:
            srv.close()

    asyncio.run_coroutine_threadsafe(stop(), loop).result()
    loop.call_soon_threadsafe(loop.stop)


def send(client, rcpts, msg=PLAIN):
    try:
        client.sendmail("cron@host", rcpts, msg)
        return 250
    except smtplib.SMTPRecipientsRefused as exc:
        return next(iter(exc.recipients.values()))[0]
    except smtplib.SMTPDataError as exc:
        return exc.smtp_code
    finally:
        client.quit()


def test_serve_routes_key_and_tag(smtp):
    base, received = apprise([200])
    assert send(smtp([base]), ["tv-guide+info@apprise.example"]) == 250
    path, body = received[0]
    assert path == "/notify/tv-guide"
    assert body["tag"] == "info"
    assert body["title"] == "Cron <root@host> backup"


def test_serve_catch_all(smtp):
    base, received = apprise([200])
    assert send(smtp([base]), ["root@yankee.example", "michele@yankee.example"]) == 250
    assert [p for p, _ in received] == ["/notify/system-alerts"]
    assert "tag" not in received[0][1]


def test_serve_refuses_a_local_part_that_is_no_key(smtp):
    base, received = apprise([200])
    assert send(smtp([base]), ["not.a.key@apprise.example"]) == 550
    assert received == []


def test_serve_unknown_key_bounces(smtp):
    base, received = apprise([404])
    other, received_other = apprise([200])
    assert send(smtp([base, other]), ["nokey@apprise.example"]) == 550
    assert len(received) == 1 and received_other == []


def test_serve_fails_over_then_defers(smtp):
    down, _ = apprise([503])
    ok, received = apprise([200])
    assert send(smtp([down, ok]), ["email@apprise.example"]) == 250
    assert received[0][0] == "/notify/email"
    assert send(smtp(["http://127.0.0.1:9", down]), ["email@apprise.example"]) == 451


def test_serve_dot_unstuffing_and_size_limit(smtp):
    base, received = apprise([200])
    msg = b"Subject: s\r\n\r\n.leading dot\r\n"
    assert send(smtp([base]), ["x@apprise.example"], msg) == 250
    assert received[0][1]["body"].endswith(".leading dot")


def test_serve_protocol_errors(smtp):
    base, _ = apprise([200])
    client = smtp([base])
    assert client.docmd("RCPT TO:<x@y>")[0] == 503
    assert client.docmd("DATA")[0] == 503
    assert client.docmd("MAIL nope")[0] == 501
    assert client.docmd("MAIL FROM:<a@b>")[0] == 250
    assert client.docmd("RCPT nope")[0] == 501
    assert client.docmd("NOOP")[0] == 250
    assert client.docmd("VRFY x")[0] == 252
    assert client.docmd("RSET")[0] == 250
    assert client.docmd("FOO")[0] == 502
    assert client.helo()[0] == 250
    client.quit()


def test_serve_size_limit(smtp):
    base, received = apprise([200])
    client = smtp([base], max_size=10)
    client.ehlo()
    client.mail("a@b")
    client.rcpt("x@apprise.example")
    code, _ = client.data(b"Subject: s\r\n\r\n" + b"x" * 100)
    client.quit()
    assert code == 552
    assert received == []


def test_serve_needs_urls(capsys):
    assert m.serve({}) == m.EX_USAGE
    assert "MAIL2APPRISE_URLS" in capsys.readouterr().err


def test_route_without_domain():
    config = m.serve_config({})
    assert m.route("<anything@apprise.example>", config) == ("system-alerts", "")


def test_serve_client_gone_during_data(smtp):
    base, received = apprise([200])
    client = smtp([base])
    client.ehlo()
    client.mail("a@b")
    client.rcpt("x@apprise.example")
    client.putcmd("DATA")
    assert client.getreply()[0] == 354
    client.send(b"Subject: s\r\n\r\npartial")
    client.close()
    time.sleep(0.2)
    assert received == []


def test_main_serve_reads_the_environment(monkeypatch, capsys):
    monkeypatch.delenv("MAIL2APPRISE_URLS", raising=False)
    assert m.main(["serve"]) == m.EX_USAGE
    started = []

    async def fake(config):
        started.append(config["urls"])

    monkeypatch.setattr(m, "serve_forever", fake)
    monkeypatch.setenv("MAIL2APPRISE_URLS", "http://a:8000 http://b:8000")
    assert m.main(["serve"]) == 0
    assert started == [["http://a:8000", "http://b:8000"]]


def test_serve_forever_listens_until_cancelled(capsys):
    async def scenario():
        task = asyncio.create_task(
            m.serve_forever(m.serve_config({"MAIL2APPRISE_LISTEN": "127.0.0.1", "MAIL2APPRISE_PORT": "0"}))
        )
        await asyncio.sleep(0.1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert "listening on 127.0.0.1:0" in capsys.readouterr().err
