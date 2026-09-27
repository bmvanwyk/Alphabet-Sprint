#!/usr/bin/env python3
"""Alphabet Sprint — backend (FastAPI + SQLite).

Accounts: username + password ONLY. No email. No PII beyond the username.
Scores go to a real SQLite leaderboard (global, all users).
Runs:  uvicorn server:app --host 0.0.0.0 --port 8000

Security notes:
- The HMAC secret (.secret) and the SQLite DB live OUTSIDE the web root
  (DATA_DIR) so no static handler can ever serve them.
- The static handler serves ONLY index.html, never the project directory.
- CORS is env-driven (ALLOWED_ORIGINS); set it to the real frontend origin
  before hosting publicly.
"""
import hashlib
import hmac
import os
import sqlite3
import time
from collections import defaultdict
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

# Data dir is kept out of the web root so it can never be served statically.
DATA_DIR = Path(os.getenv("AS_DATA_DIR", str(Path.home() / ".alphabet-sprint"))).expanduser()
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "sprint.db"
TOKEN_TTL = 60 * 60 * 24 * 30  # 30 days

# CORS: locked down via env in production. Default "*" keeps local dev working
# but MUST be set to the real frontend origin(s) before hosting publicly.
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",") if o.strip()] or ["*"]

app = FastAPI(title="Alphabet Sprint")
app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_methods=["*"], allow_headers=["*"])

# ---------------- schema ----------------
db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.row_factory = sqlite3.Row
db.executescript(
    """
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        pw_hash TEXT NOT NULL,
        salt TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS scores(
        id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        mode TEXT NOT NULL CHECK(mode IN ('sprint','lockout','combo')),
        final REAL NOT NULL,
        raw REAL NOT NULL,
        misses INTEGER NOT NULL,
        ts INTEGER NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_scores_mode ON scores(mode, final);
    """
)
db.commit()


def newSalt() -> str:
    return os.urandom(16).hex()


def hashPw(pw: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 200_000).hex()


# ---------------- models ----------------
class AuthBody(BaseModel):
    username: str
    password: str


class ScoreBody(BaseModel):
    mode: str
    final: float
    raw: float
    misses: int


# ---------------- auth helpers ----------------
SECRET_PATH = DATA_DIR / ".secret"
if SECRET_PATH.exists():
    SECRET = SECRET_PATH.read_bytes()
else:
    SECRET = os.urandom(32)
    SECRET_PATH.write_bytes(SECRET)
    SECRET_PATH.chmod(0o600)


def mkToken(user_id: int) -> str:
    exp = int(time.time()) + TOKEN_TTL
    msg = f"{user_id}:{exp}".encode()
    sig = hmac.new(SECRET, msg, hashlib.sha256).hexdigest()
    return f"{user_id}.{exp}.{sig}"


def parseToken(token: str) -> int:
    try:
        uid, exp, sig = token.split(".")
        msg = f"{uid}:{exp}".encode()
        want = hmac.new(SECRET, msg, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, want) or int(exp) < time.time():
            raise ValueError
        return int(uid)
    except (ValueError, KeyError):
        raise HTTPException(401, "not logged in or session expired")


def currentUser(authorization: str = Header(default="")) -> int:
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "not logged in")
    return parseToken(authorization[7:])


# ---------------- routes ----------------

def _valid_username(u: str) -> bool:
    if not (2 <= len(u) <= 20):
        return False
    return u.isidentifier() or (u.replace("_", "").isalnum() and u[0].isalpha())


# ---------------- rate limiting (in-process token bucket, no deps) ----------------
RATE_LIMITS = {  # path-prefix -> (max_requests, per_seconds)
    "/api/register": (5, 60),   # 5 per minute per IP
    "/api/login": (10, 60),     # 10 per minute per IP
    "/api/score": (30, 60),     # 30 per minute per user-ish IP
}
_buckets: dict = defaultdict(dict)  # ip -> {prefix: [tokens, last]}

def _rate_limit(request: Request):
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    for prefix, (limit, per) in RATE_LIMITS.items():
        if not request.url.path.startswith(prefix):
            continue
        bucket = _buckets[ip].setdefault(prefix, [float(limit), now])
        refill = (now - bucket[1]) * (limit / per)
        bucket[0] = min(float(limit), bucket[0] + refill)
        bucket[1] = now
        if bucket[0] < 1:
            raise HTTPException(429, "too many requests — slow down")
        bucket[0] -= 1
        return
    return


@app.post("/api/register")
def register(body: AuthBody, request: Request):
    _rate_limit(request)
    u = body.username.strip()
    if not _valid_username(u):
        raise HTTPException(400, "username: 2-20 chars, letters/digits/underscore")
    pw = body.password
    if len(pw) < 4:
        raise HTTPException(400, "password: min 4 characters")
    if len(pw) > 200:
        raise HTTPException(400, "password: too long (max 200 characters)")
    try:
        salt = newSalt()
        db.execute("INSERT INTO users(username,pw_hash,salt) VALUES(?,?,?)", (u, hashPw(pw, salt), salt))
        db.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(409, "username taken")
    return {"ok": True, "username": u}


@app.post("/api/login")
def login(body: AuthBody, request: Request):
    _rate_limit(request)
    row = db.execute("SELECT id,pw_hash,salt FROM users WHERE username=?", (body.username.strip(),)).fetchone()
    if not row or not hmac.compare_digest(row["pw_hash"], hashPw(body.password, row["salt"])):
        raise HTTPException(401, "wrong username or password")
    return {"ok": True, "token": mkToken(row["id"]), "username": body.username.strip()}


@app.get("/api/board")
def board(mode: str = "sprint"):
    if mode not in ("sprint", "lockout", "combo"):
        raise HTTPException(400, "unknown mode")
    rows = db.execute(
        """SELECT u.username, s.final, s.raw, s.misses, s.ts
           FROM scores s JOIN users u ON u.id=s.user_id
           WHERE s.mode=? AND s.id IN (
               SELECT MIN(id) FROM scores
               WHERE mode=? GROUP BY user_id, final
           )
           ORDER BY s.final ASC LIMIT 20""",
        (mode, mode),
    ).fetchall()
    # best-per-user: one row per user (their best run in this mode)
    dedup = {}
    for r in rows:
        if r["username"] not in dedup or r["final"] < dedup[r["username"]]["final"]:
            dedup[r["username"]] = dict(r)
    return sorted(dedup.values(), key=lambda x: x["final"])[:20]


@app.post("/api/score")
def submit(body: ScoreBody, request: Request, user_id: int = Depends(currentUser)):
    _rate_limit(request)
    if body.mode not in ("sprint", "lockout", "combo"):
        raise HTTPException(400, "unknown mode")
    if not (0 <= body.final < 3600) or not (0 <= body.misses < 10000):
        raise HTTPException(400, "implausible score")
    # Integrity signal: client claims final == raw + penalty. Lockout has 0 penalty.
    penalty = 0.0 if body.mode == "lockout" else 0.5 * body.misses
    implied = round(body.raw + penalty, 2)
    if abs(implied - body.final) > 0.03:
        raise HTTPException(400, "score does not match misses+penalty")
    db.execute(
        "INSERT INTO scores(user_id,mode,final,raw,misses,ts) VALUES(?,?,?,?,?,?)",
        (user_id, body.mode, body.final, body.raw, body.misses, int(time.time() * 1000)),
    )
    db.commit()
    return {"ok": True}


# ---------------- static frontend (index.html ONLY) ----------------
INDEX = Path(__file__).parent / "index.html"

@app.get("/")
def index():
    return FileResponse(INDEX)
