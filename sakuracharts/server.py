#!/usr/bin/env python3
"""Sakuracharts - a small, self-hosted bar-replay charting app (TradingView-style replay, drawings, paper trading, journal).

Standard library only. Serves one page (static/index.html) plus a tiny JSON API behind a password login.
WARNING: largely AI-generated code ("AI slop"). Not financial advice. Use at your own risk.
"""
import argparse, bisect, csv, hashlib, hmac, io, json, os, secrets, sys, threading, time, webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
STATIC = HERE / "static"
ASSETS = HERE / "assets"
DATA_DIR = Path(os.environ.get("SAKURA_DATA", ROOT / "data"))
HOME = Path(os.environ.get("SAKURA_HOME", Path.home() / ".sakuracharts"))
AUTH_FILE = HOME / "auth.json"
PREFS_FILE = HOME / "prefs.json"
JOURNAL_FILE = HOME / "journal.json"
JOURNAL_SHOTS = HOME / "journal_shots"
STATE = {"bars": [], "name": "SAMPLE"}
LOCK = threading.Lock()
SESS_MAX_AGE = 30 * 86400
COOKIE = "sakura_sess"


# ---------------- data ----------------
def to_utc(s):
    s = s.strip()
    try:
        f = float(s)
        return int(f / 1000 if f > 1e11 else f)
    except ValueError:
        pass
    dt = datetime.fromisoformat(s.replace("Z", "+00:00").replace("T", " "))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def parse_csv(fh):
    """CSV with a time/datetime/timestamp/date column + open, high, low, close [, volume]. Times: ISO-8601 (UTC if no zone) or epoch."""
    out, last = [], None
    r = csv.DictReader(fh)
    cols = {k.lower().strip(): k for k in (r.fieldnames or [])}
    tk = next((cols[k] for k in ("time", "datetime", "timestamp", "date") if k in cols), None)
    if tk is None:
        raise ValueError("CSV needs a time/datetime column")
    for row in r:
        try:
            t = to_utc(row[tk])
            o, h, l, c = (float(row[cols[k]]) for k in ("open", "high", "low", "close"))
            v = float(row[cols["volume"]] or 0) if "volume" in cols else 0.0
        except Exception:
            continue
        if last is not None and t <= last:
            continue
        last = t
        out.append([t, o, h, l, c, v])
    return out


def set_bars(bars, name):
    STATE["bars"], STATE["name"] = bars, name


def load_default():
    sample = DATA_DIR / "sample-1m.csv"
    if not sample.exists():
        sys.path.insert(0, str(ROOT / "tools"))
        import make_sample_data
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with sample.open("w", newline="") as f:
            w = csv.writer(f); w.writerow(["time", "open", "high", "low", "close", "volume"])
            for row in make_sample_data.generate():
                w.writerow(row)
        print(f"generated synthetic sample data: {sample}")
    with sample.open(newline="") as f:
        set_bars(parse_csv(f), "SAMPLE-1M")


# ---------------- auth ----------------
AUTH = {"salt": None, "hash": None, "sess_secret": None}


def _hash(pw, salt):
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 200_000).hex()


def _write_private(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def save_pw(pw):
    salt = secrets.token_hex(16)
    AUTH.update(salt=salt, hash=_hash(pw, salt), sess_secret=secrets.token_hex(32))
    _write_private(AUTH_FILE, dict(AUTH))


def setup_auth():
    if os.environ.get("SAKURA_PASS"):
        AUTH["salt"] = secrets.token_hex(16); AUTH["hash"] = _hash(os.environ["SAKURA_PASS"], AUTH["salt"])
        AUTH["sess_secret"] = secrets.token_hex(32); return
    try:
        disk = json.loads(AUTH_FILE.read_text())
        if disk.get("salt") and disk.get("hash") and disk.get("sess_secret"):
            AUTH.update(disk); return
    except Exception:
        pass
    pw = secrets.token_urlsafe(9)
    save_pw(pw)
    print(f"\n  First run: your Sakuracharts password is:  {pw}\n  (only a salted hash is stored in {AUTH_FILE}; change it under Settings -> Password,\n"
          f"   or start with SAKURA_PASS=... to choose your own)\n")


def check_pw(pw):
    return AUTH["hash"] is not None and hmac.compare_digest(_hash(pw or "", AUTH["salt"]), AUTH["hash"])


def issue_session():
    body = f"{int(time.time()) + SESS_MAX_AGE}.{secrets.token_hex(16)}"
    sig = hmac.new(bytes.fromhex(AUTH["sess_secret"]), body.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{body}.{sig}"


def session_ok(tok):
    try:
        exp_s, nonce, sig = tok.split(".")
        if int(exp_s) < time.time():
            return False
        exp = hmac.new(bytes.fromhex(AUTH["sess_secret"]), f"{exp_s}.{nonce}".encode(), hashlib.sha256).hexdigest()[:32]
        return hmac.compare_digest(sig, exp)
    except Exception:
        return False


# ---------------- prefs + journal (local JSON files) ----------------
def _read(path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def journal_shot_path(i):
    import re
    i = str(i or "")
    return JOURNAL_SHOTS / (i + ".jpg") if re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", i) else None


def journal_merge(j):
    with LOCK:
        cur = _read(JOURNAL_FILE, {"trades": [], "notes": {}, "fee": 1.0})
        T = {t["id"]: t for t in cur.get("trades", []) if isinstance(t, dict) and t.get("id")}
        for t in j.get("trades") or []:
            if isinstance(t, dict) and t.get("id"):
                T[str(t["id"])] = t
        N = cur.get("notes") or {}
        for k, v in (j.get("notes") or {}).items():
            N[str(k)] = v
        for k in j.get("deleted") or []:
            T.pop(str(k), None); N.pop(str(k), None); f = journal_shot_path(k)
            if f and f.exists():
                f.unlink()
        if "fee" in j:
            cur["fee"] = float(j["fee"] or 0)
        cur["trades"] = sorted(T.values(), key=lambda t: t.get("t1") or 0); cur["notes"] = N; cur["saved"] = time.time()
        _write_private(JOURNAL_FILE, cur)
        return {"ok": True, "n": len(T), "saved": cur["saved"]}


def journal_export(fmt):
    J = _read(JOURNAL_FILE, {"trades": [], "notes": {}, "fee": 1.0}); stamp = datetime.now().strftime("%Y%m%d-%H%M")
    if fmt == "json":
        return json.dumps(J, indent=1).encode(), "application/json", f"sakura-trades-{stamp}.json"
    cols = ["id", "sym", "dir", "qty", "t0", "t1", "entry", "exit", "pts", "gross", "why"]
    b = io.StringIO(); w = csv.writer(b); w.writerow(cols)
    for t in J.get("trades", []):
        w.writerow([t.get(c, "") for c in cols])
    return b.getvalue().encode("utf-8-sig"), "text/csv; charset=utf-8", f"sakura-trades-{stamp}.csv"


# ---------------- HTTP ----------------
CT = {".png": "image/png", ".ico": "image/x-icon", ".webp": "image/webp", ".jpg": "image/jpeg"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body, ctype="application/json", code=200, cache="no-store", extra=None):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", cache)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers(); self.wfile.write(b)

    def _json(self, obj, code=200, extra=None):
        self._send(json.dumps(obj, separators=(",", ":")), code=code, extra=extra)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _cookie(self, tok):
        sec = " Secure;" if self.headers.get("X-Forwarded-Proto", "") == "https" else ""
        return f"{COOKIE}={tok}; HttpOnly; Max-Age={SESS_MAX_AGE};{sec} SameSite=Strict; Path=/"

    def _authed(self):
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == COOKIE and v and session_ok(v):
                return True
        return False

    def _deny(self):
        if self.path.startswith("/api/"):
            return self._json({"error": "login required"}, 401)
        self.send_response(302); self.send_header("Location", "/login"); self.send_header("Content-Length", "0"); self.end_headers()

    def _qs(self):
        from urllib.parse import parse_qs
        return {k: v[0] for k, v in parse_qs(self.path.partition("?")[2]).items()}

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/favicon.ico" or p.startswith("/assets/"):
            f = ASSETS / Path(p).name
            if not f.is_file():
                return self.send_error(404)
            return self._send(f.read_bytes(), CT.get(f.suffix, "application/octet-stream"), cache="public, max-age=86400")
        if p == "/login":
            return self._send((STATIC / "login.html").read_text().replace("%ERR%", ""), "text/html; charset=utf-8")
        if p == "/logout":
            self.send_response(302); self.send_header("Set-Cookie", f"{COOKIE}=; Max-Age=0; Path=/"); self.send_header("Location", "/login")
            self.send_header("Content-Length", "0"); self.end_headers(); return
        if not self._authed():
            return self._deny()
        q = self._qs()
        if p in ("/", "/index.html"):
            return self._send((STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
        if p == "/api/bars":
            B = STATE["bars"]
            if q.get("since"):
                t = int(float(q["since"])); B = [b for b in B if b[0] >= t]
            elif q.get("days") and B:
                t = B[-1][0] - float(q["days"]) * 86400; B = B[bisect.bisect_left([b[0] for b in B], t):]
            return self._json({"name": STATE["name"], "bars": B, "n": len(STATE["bars"]), "t0": STATE["bars"][0][0] if STATE["bars"] else None})
        if p == "/api/bars/older":
            before, days = int(float(q["before"])), min(62.0, float(q.get("days", 7)))
            T = [b[0] for b in STATE["bars"]]; i1 = bisect.bisect_left(T, before); i0 = bisect.bisect_left(T, before - days * 86400)
            return self._json({"bars": STATE["bars"][i0:i1], "src": "csv", "basis": 0, "nqStart": T[0] if T else None, "note": "loaded data"})
        if p == "/api/ticks":
            return self._json({"bars": {}})          # no tick data in the public build: replay uses a synthetic intrabar path
        if p == "/api/prefs":
            return self._json(_read(PREFS_FILE, {}))
        if p == "/api/journal":
            return self._json(_read(JOURNAL_FILE, {"trades": [], "notes": {}, "fee": 1.0}))
        if p == "/api/journal/shot":
            f = journal_shot_path(q.get("id"))
            return self._send(f.read_bytes(), "image/jpeg") if f and f.exists() else self.send_error(404)
        if p == "/api/journal/export":
            body, ctype, fn = journal_export(q.get("fmt", "csv"))
            return self._send(body, ctype, extra={"Content-Disposition": f'attachment; filename="{fn}"'})
        self.send_error(404)

    def do_POST(self):
        p, _, qs = self.path.partition("?")
        if p == "/login":
            from urllib.parse import parse_qs
            pw = (parse_qs(self._body().decode()).get("password") or [""])[0]
            time.sleep(0.4)
            if check_pw(pw):
                self.send_response(302); self.send_header("Set-Cookie", self._cookie(issue_session()))
                self.send_header("Location", "/"); self.send_header("Content-Length", "0"); self.end_headers()
            else:
                self._send((STATIC / "login.html").read_text().replace("%ERR%", '<div class="e">Wrong password</div>'), "text/html; charset=utf-8", 401)
            return
        if p == "/api/session":
            try: j = json.loads(self._body() or b"{}")
            except Exception: j = {}
            time.sleep(0.4)
            if not check_pw(j.get("password")):
                return self._json({"error": "wrong password"}, 401)
            return self._json({"ok": True}, extra={"Set-Cookie": self._cookie(issue_session())})
        if not self._authed():
            return self._deny()
        try:
            if p == "/api/password":
                j = json.loads(self._body() or b"{}")
                if os.environ.get("SAKURA_PASS"):
                    raise ValueError("password comes from SAKURA_PASS; change it there")
                if not check_pw(j.get("old", "")):
                    raise ValueError("current password is wrong")
                if len(j.get("new", "")) < 6:
                    raise ValueError("new password too short (min 6)")
                save_pw(j["new"]); return self._json({"ok": True}, extra={"Set-Cookie": self._cookie(issue_session())})
            if p == "/api/prefs":
                j = json.loads(self._body() or b"{}")
                if not isinstance(j, dict) or len(json.dumps(j)) > 200000:
                    raise ValueError("bad prefs")
                with LOCK:
                    cur = _read(PREFS_FILE, {}); cur.update({k: v for k, v in j.items() if k in ("draw", "brackets", "panes", "theme", "legend", "layouts", "ui")})
                    cur["saved"] = time.time(); _write_private(PREFS_FILE, cur)
                return self._json({"ok": True})
            if p == "/api/contracts":
                return self._json({"ok": True})
            if p == "/api/journal":
                raw = self._body() or b"{}"
                if len(raw) > 8_000_000:
                    raise ValueError("journal too large")
                return self._json(journal_merge(json.loads(raw)))
            if p == "/api/journal/shot":
                raw = self._body() or b"{}"
                if len(raw) > 6_000_000:
                    raise ValueError("screenshot too large")
                import base64
                j = json.loads(raw); f = journal_shot_path(j.get("id"))
                if not f:
                    raise ValueError("bad id")
                data = j.get("img", ""); data = data.split(",", 1)[1] if "," in data else data
                f.parent.mkdir(parents=True, exist_ok=True); f.write_bytes(base64.b64decode(data)); return self._json({"ok": True})
            if p == "/api/upload":
                from urllib.parse import parse_qs
                name = (parse_qs(qs).get("name") or ["UPLOAD"])[0]
                bars = parse_csv(io.StringIO(self._body().decode("utf-8", "replace")))
                if len(bars) < 10:
                    raise ValueError("CSV parsed to fewer than 10 bars")
                set_bars(bars, name.upper()[:40]); return self._json({"n": len(bars)})
            if p == "/api/load":
                path = Path(json.loads(self._body())["path"]).expanduser()
                with open(path, newline="") as f:
                    bars = parse_csv(f)
                set_bars(bars, path.stem.upper()[:40]); return self._json({"n": len(bars)})
            self.send_error(404)
        except Exception as ex:
            self._json({"error": f"{type(ex).__name__}: {ex}"})


def main():
    ap = argparse.ArgumentParser(description="Sakuracharts - bar replay charting (AI-generated; not financial advice)")
    ap.add_argument("csv", nargs="?", help="1m OHLCV CSV (default: data/sample-1m.csv, generated if missing)")
    ap.add_argument("--host", default="127.0.0.1"); ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-open", action="store_true", help="do not open a browser tab")
    a = ap.parse_args()
    setup_auth()
    if a.csv:
        with open(a.csv, newline="") as f:
            set_bars(parse_csv(f), Path(a.csv).stem.upper()[:40])
    else:
        load_default()
    print(f"Sakuracharts: {len(STATE['bars'])} bars ({STATE['name']}) on http://{a.host}:{a.port}")
    if a.host not in ("127.0.0.1", "localhost"):
        print("  note: listening beyond localhost. Put it behind HTTPS before exposing it to the internet.")
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    if not a.no_open:
        threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{a.port}/")).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
