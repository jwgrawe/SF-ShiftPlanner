"""Login and access (D121), driven through the app's ASGI interface."""
import asyncio
import base64
import shutil
import sys
import tempfile
import unittest
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import auth, db, hr_import, importer, winauth  # noqa: E402


def call(method, path, cookies=None, headers=None, body=b"", client=("127.0.0.1", 50000)):
    """One request straight into the app → (status, headers dict(lists), body text, set cookies)."""
    from app.main import app
    parts = urlsplit(path)
    hdrs = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    if cookies:
        hdrs.append((b"cookie", "; ".join(f"{k}={v}" for k, v in cookies.items()).encode()))
    if body:
        hdrs.append((b"content-type", b"application/x-www-form-urlencoded"))
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method,
             "scheme": "http", "path": parts.path, "raw_path": parts.path.encode(),
             "query_string": parts.query.encode(), "headers": hdrs, "client": client,
             "server": ("127.0.0.1", 8000), "root_path": ""}
    messages, sent = [], False

    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)

    asyncio.run(app(scope, receive, send))
    start = next(m for m in messages if m["type"] == "http.response.start")
    out_headers: dict[str, list[str]] = {}
    for k, v in start["headers"]:
        out_headers.setdefault(k.decode().lower(), []).append(v.decode())
    jar = {}
    for raw in out_headers.get("set-cookie", []):
        c = SimpleCookie()
        c.load(raw)
        jar.update({k: m.value for k, m in c.items()})
    text = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body").decode()
    return start["status"], out_headers, text, jar


class FakeSSPI:
    """Stand-in for Windows: NTLM-like, two rounds on one connection."""

    def step(self, ctx, token):
        if token == b"NEGOTIATE" and ctx is None:
            return False, b"CHALLENGE", "ctx-1", None
        if token == b"AUTHENTICATE" and ctx == "ctx-1":
            return True, b"", None, "SYKEHUS\\Kari"
        raise winauth.AuthError("innloggingen ble avvist (SEC_E_LOGON_DENIED)")

    def drop(self, ctx):
        pass


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


class AccessTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.saved = (db.REAL_DB_PATH, hr_import.INBOX, db.MODE)
        db.REAL_DB_PATH = self.tmp / "t.db"
        hr_import.INBOX = self.tmp / "import"
        hr_import.INBOX.mkdir()
        db.set_mode("real")
        conn = db.get_conn()
        db.init_schema(conn)
        conn.execute("PRAGMA foreign_keys = OFF")
        with conn:
            importer.import_seed(conn, people=False)
        conn.close()
        auth._sessions.clear()
        auth.ROOT_KEY = None
        winauth._server_handshakes = winauth.Handshakes(FakeSSPI())

    def tearDown(self):
        db.REAL_DB_PATH, hr_import.INBOX, mode = self.saved
        db.set_mode(mode)
        winauth._server_handshakes = None
        shutil.rmtree(self.tmp, ignore_errors=True)

    def conn(self):
        return db.get_conn()

    def add(self, account, name):
        conn = self.conn()
        auth.add_admin(conn, account, name, auth.ROOT_USER)
        conn.close()

    def set_method(self, value):
        conn = self.conn()
        auth.set_method(conn, value)
        conn.close()

    # ---------------------------------------------------------------
    def test_open_until_the_first_administrator_then_gated(self):
        status, _, text, _ = call("GET", "/admin")
        self.assertEqual(status, 200)
        self.assertIn("Tilgang er ikke satt opp", text)
        self.add("SYKEHUS\\kari", "Kari H.")
        status, headers, _, _ = call("GET", "/admin/regler?x=1")
        self.assertEqual(status, 303)
        self.assertEqual(headers["location"][0], "/logginn?neste=/admin/regler%3Fx%3D1")
        self.assertEqual(call("GET", "/display")[0], 200)            # the board stays public
        self.assertEqual(call("GET", "/static/app.css")[0], 200)

    def test_windows_single_sign_on_in_two_rounds_on_one_connection(self):
        self.add("sykehus\\kari", "Kari H.")
        status, headers, text, _ = call("GET", "/logginn?neste=/admin")
        self.assertEqual((status, headers["www-authenticate"]), (401, ["Negotiate"]))
        self.assertIn("Logger inn", text)
        conn_a = ("127.0.0.1", 51000)
        status, headers, _, _ = call("GET", "/logginn?neste=/admin", client=conn_a,
                                     headers={"Authorization": f"Negotiate {b64(b'NEGOTIATE')}"})
        self.assertEqual((status, headers["www-authenticate"]), (401, [f"Negotiate {b64(b'CHALLENGE')}"]))
        status, headers, _, jar = call("GET", "/logginn?neste=/admin", client=conn_a,
                                       headers={"Authorization": f"Negotiate {b64(b'AUTHENTICATE')}"})
        self.assertEqual((status, headers["location"]), (303, ["/admin"]))
        status, _, text, _ = call("GET", "/admin", cookies=jar)
        self.assertEqual(status, 200)
        self.assertIn("Kari H.", text)
        self.assertIn("Logg ut", text)

    def test_the_second_round_must_come_on_the_same_connection(self):
        self.add("kari", "Kari H.")
        call("GET", "/logginn", client=("127.0.0.1", 51000),
             headers={"Authorization": f"Negotiate {b64(b'NEGOTIATE')}"})
        status, headers, text, jar = call("GET", "/logginn", client=("127.0.0.1", 52000),
                                          headers={"Authorization": f"Negotiate {b64(b'AUTHENTICATE')}"})
        self.assertEqual(status, 403)
        self.assertNotIn("www-authenticate", headers)                # no endless loop
        self.assertNotIn(auth.SESSION_COOKIE, jar)
        self.assertIn("SEC_E_LOGON_DENIED", text)

    def test_an_account_without_access_is_refused(self):
        self.add("sykehus\\ola", "Ola N.")
        conn_a = ("127.0.0.1", 51000)
        call("GET", "/logginn", client=conn_a, headers={"Authorization": f"Negotiate {b64(b'NEGOTIATE')}"})
        status, _, text, jar = call("GET", "/logginn", client=conn_a,
                                    headers={"Authorization": f"Negotiate {b64(b'AUTHENTICATE')}"})
        self.assertEqual(status, 403)
        self.assertIn("sykehus\\kari har ikke tilgang", text)
        self.assertNotIn(auth.SESSION_COOKIE, jar)

    def test_process_method_and_matching_without_domain(self):
        self.add(auth.process_account().split("\\")[-1], "Driftsbruker")   # no domain: any domain
        self.set_method("prosess")
        status, headers, _, jar = call("GET", "/logginn?neste=/plan")
        self.assertEqual((status, headers["location"]), (303, ["/plan"]))
        self.assertEqual(call("GET", "/plan", cookies=jar)[0], 200)

    def test_root_mode_one_time_key_and_only_root_changes_administrators(self):
        self.add("kari", "Kari H.")
        auth.ROOT_KEY = "nokkel-123"
        self.assertEqual(call("GET", "/rot?nokkel=feil")[0], 403)
        status, headers, _, root = call("GET", "/rot?nokkel=nokkel-123")
        self.assertEqual((status, headers["location"]), (303, ["/admin/tilgang"]))
        self.assertEqual(call("GET", "/rot?nokkel=nokkel-123")[0], 403)   # used up
        status, _, text, _ = call("GET", "/admin/tilgang", cookies=root)
        self.assertIn("ROTMODUS", text)
        call("POST", "/admin/tilgang/legg-til", cookies=root, body=b"account=SYKEHUS%5Cola&name=Ola+N.")
        conn = self.conn()
        self.assertIsNotNone(auth.find_admin(conn, "sykehus\\ola"))
        conn.close()
        # An ordinary administrator can't.
        self.set_method("prosess")
        self.add(auth.process_account(), "Driftsbruker")
        _, _, _, admin = call("GET", "/logginn")
        status, headers, _, _ = call("POST", "/admin/tilgang/legg-til", cookies=admin,
                                     body=b"account=x%5Cy&name=Y")
        self.assertIn("rotmodus", headers["location"][0].lower().replace("%20", " "))
        conn = self.conn()
        self.assertIsNone(auth.find_admin(conn, "x\\y"))
        conn.close()

    def test_the_log_says_who(self):
        self.add(auth.process_account(), "Driftsbruker")
        self.set_method("prosess")
        _, _, _, jar = call("GET", "/logginn")
        call("POST", "/admin/regler/avvik", cookies=jar, body=b"N1=av")
        conn = self.conn()
        who = conn.execute("SELECT who FROM import_log WHERE text LIKE 'Avvik og tiltak%'").fetchone()[0]
        conn.close()
        self.assertEqual(who, "Driftsbruker")

    def test_logout_and_removal_end_the_session(self):
        self.add(auth.process_account(), "Driftsbruker")
        self.set_method("prosess")
        _, _, _, jar = call("GET", "/logginn")
        self.assertEqual(call("GET", "/admin", cookies=jar)[0], 200)
        call("GET", "/loggut", cookies=jar)
        self.assertEqual(call("GET", "/admin", cookies=jar)[0], 303)
        _, _, _, jar = call("GET", "/logginn")
        conn = self.conn()
        auth.remove_admin(conn, auth.process_account())
        conn.close()
        self.add("annen", "Annen")                        # still set up, so gated
        self.assertEqual(call("GET", "/admin", cookies=jar)[0], 303)

    def test_the_board_window_never_reaches_the_login(self):
        self.add("kari", "Kari H.")
        status, headers, _, _ = call("GET", "/admin", cookies={"sf_tavle": "1"})
        self.assertEqual((status, headers["location"]), (303, ["/display"]))

    def test_account_validation(self):
        conn = self.conn()
        for bad in ("", "a\\b\\c", "do main\\x", "\\x"):
            with self.assertRaises(auth.Invalid):
                auth.add_admin(conn, bad, "Navn", auth.ROOT_USER)
        conn.close()


if __name__ == "__main__":
    unittest.main()
