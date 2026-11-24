"""CHS Prospect Discovery Wizard - FastAPI backend.

Prospect side:  /p/{token}            guided, skippable intake wizard (autosaves server-side)
Rep side:       /rep                  password-protected invite manager + submissions viewer
Secrets (env):  ADMIN_PASSWORD, SESSION_SECRET, TIN_ENC_KEY   (never logged or returned)
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import time
from collections import defaultdict, deque
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import db

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")
DATA = os.path.join(HERE, "data")

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
SESSION_SECRET = (os.environ.get("SESSION_SECRET") or secrets.token_hex(32)).encode()
_tin_key = os.environ.get("TIN_ENC_KEY", "").strip()
FERNET = Fernet(_tin_key.encode()) if _tin_key else None
LINK_DAYS = int(os.environ.get("LINK_EXPIRY_DAYS", "30"))
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
FORCE_HTTPS = os.environ.get("FORCE_HTTPS", "0") == "1"
SESSION_HOURS = 12

PAYERS = json.load(open(os.path.join(DATA, "payers_by_state.json")))
PAYER_INDEX = json.load(open(os.path.join(DATA, "payer_index.json")))
SPECIALTIES = json.load(open(os.path.join(DATA, "specialties.json")))
EHRS = json.load(open(os.path.join(DATA, "ehr_systems.json")))
STATE_NAMES = {k: v["name"] for k, v in PAYERS["states"].items()}

app = FastAPI(title="CHS Prospect Discovery Wizard", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso(d: dt.datetime) -> str:
    return d.astimezone(dt.timezone.utc).isoformat(timespec="seconds")


@app.on_event("startup")
def _startup() -> None:
    db.init()


# --------------------------------------------------------------------------- security middleware
_buckets: dict[tuple[str, str], deque] = defaultdict(deque)
LIMITS = {"login": (10, 900), "miss": (30, 600), "wizard": (240, 60), "rep": (600, 60), "page": (120, 60)}


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return (fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?")) or "?"


def rate_ok(request: Request, kind: str, record: bool = True) -> bool:
    limit, window = LIMITS[kind]
    key = (client_ip(request), kind)
    q = _buckets[key]
    t = time.monotonic()
    while q and t - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        return False
    if record:
        q.append(t)
    return True


def limit(request: Request, kind: str) -> None:
    if not rate_ok(request, kind):
        raise HTTPException(429, "Too many requests. Please wait a few minutes and try again.")


CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; "
       "font-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'")


@app.middleware("http")
async def security(request: Request, call_next):
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    if FORCE_HTTPS and proto == "http":
        return RedirectResponse(str(request.url.replace(scheme="https")), status_code=308)
    response: Response = await call_next(request)
    h = response.headers
    h["Content-Security-Policy"] = CSP
    h["X-Content-Type-Options"] = "nosniff"
    h["X-Frame-Options"] = "DENY"
    h["Referrer-Policy"] = "no-referrer"
    h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), interest-cohort=()"
    h["X-Robots-Tag"] = "noindex, nofollow"
    h["Cross-Origin-Opener-Policy"] = "same-origin"
    if proto == "https":
        h["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if request.url.path.startswith(("/api/", "/p/", "/rep")):
        h["Cache-Control"] = "no-store"
    return response


# --------------------------------------------------------------------------- helpers
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,64}$")
EMAIL_RE = re.compile(r"^[^@\s<>]{1,64}@[^@\s<>]{1,190}\.[A-Za-z]{2,24}$")


def npi_valid(npi: str) -> bool:
    if not re.fullmatch(r"\d{10}", npi or ""):
        return False
    digits = "80840" + npi[:9]
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return (10 - total % 10) % 10 == int(npi[9])


def tin_digits(v: str) -> str:
    return re.sub(r"\D", "", v or "")


def tin_valid(v: str) -> bool:
    d = tin_digits(v)
    return len(d) == 9 and d != "000000000" and not d.startswith("00")


def enc_tin(v: str) -> str:
    if not FERNET:
        raise HTTPException(500, "Server is missing its encryption key.")
    return FERNET.encrypt(v.encode()).decode()


def dec_tin(v: str | None) -> str | None:
    if not v or not FERNET:
        return None
    try:
        return FERNET.decrypt(v.encode()).decode()
    except InvalidToken:
        return None


def fmt_tin(d: str) -> str:
    return f"{d[:2]}-{d[2:]}" if len(d) == 9 else d


def mask_tin(d: str | None) -> str | None:
    return f"••-•••{d[-4:]}" if d and len(d) == 9 else None


def clean(value: Any, depth: int = 0) -> Any:
    """Bound and sanitize arbitrary JSON from the browser."""
    if depth > 6:
        return None
    if isinstance(value, str):
        return value.replace("\x00", "").strip()[:2000]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return value if abs(value) < 1e9 else None
    if isinstance(value, list):
        return [clean(v, depth + 1) for v in value[:300]]
    if isinstance(value, dict):
        out = {}
        for k, v in list(value.items())[:300]:
            if isinstance(k, str) and re.fullmatch(r"[A-Za-z0-9_.:\- ]{1,64}", k):
                out[k] = clean(v, depth + 1)
        return out
    return None


ALLOWED_TOP = {"skipped", "states", "states_unsure", "payers", "practice", "specialty", "providers", "rcm", "contact"}


def validate_answers(ans: dict) -> tuple[dict, list[str]]:
    """Returns (clean answers, list of warnings). Invalid formats are dropped, never fatal."""
    warnings: list[str] = []
    ans = {k: v for k, v in clean(ans).items() if k in ALLOWED_TOP}
    ans["states"] = [s for s in (ans.get("states") or []) if isinstance(s, str) and s in STATE_NAMES][:51]
    practice = ans.get("practice") or {}
    if isinstance(practice, dict):
        npi = re.sub(r"\D", "", str(practice.get("group_npi") or ""))
        if npi and not npi_valid(npi):
            warnings.append("Group NPI didn't pass the check-digit test, so it wasn't saved.")
            practice["group_npi"] = ""
        else:
            practice["group_npi"] = npi
        ans["practice"] = practice
    provs = ans.get("providers") or {}
    if isinstance(provs, dict):
        rows = []
        for p in (provs.get("list") or [])[:200]:
            if not isinstance(p, dict):
                continue
            npi = re.sub(r"\D", "", str(p.get("npi") or ""))
            if npi and not npi_valid(npi):
                warnings.append(f"NPI for {p.get('name') or 'a provider'} didn't pass the check-digit test, so it wasn't saved.")
                npi = ""
            rows.append({"name": str(p.get("name") or "")[:120], "credential": str(p.get("credential") or "")[:40],
                         "npi": npi, "new_to_credentialing": p.get("new_to_credentialing")})
        provs["list"] = rows
        ans["providers"] = provs
    contact = ans.get("contact") or {}
    if isinstance(contact, dict) and contact.get("email") and not EMAIL_RE.match(contact["email"]):
        warnings.append("That email address doesn't look complete, so it wasn't saved.")
        contact["email"] = ""
    if len(json.dumps(ans)) > 200_000:
        raise HTTPException(413, "That's more data than we expected. Please shorten the notes.")
    return ans, warnings


def invite_by_token(request: Request, token: str) -> dict:
    if not TOKEN_RE.match(token or ""):
        rate_ok(request, "miss")
        raise HTTPException(404, "This link isn't valid.")
    if not rate_ok(request, "miss", record=False):
        raise HTTPException(429, "Too many requests. Please wait a few minutes and try again.")
    row = db.one("SELECT * FROM invites WHERE token = ?", (token,))
    if not row or row["revoked"]:
        rate_ok(request, "miss")
        raise HTTPException(404, "This link isn't valid.")
    if dt.datetime.fromisoformat(row["expires_at"]) < now():
        raise HTTPException(410, f"This link has expired. Please ask {row['rep_name'] or 'your CHS contact'} for a fresh one.")
    return row


def event(invite_id: int | None, kind: str, detail: str = "") -> None:
    db.execute("INSERT INTO events (invite_id, at, kind, detail) VALUES (?, ?, ?, ?)", (invite_id, iso(now()), kind, detail[:500]))


HONORIFICS = {"dr", "dr.", "mr", "mr.", "mrs", "mrs.", "ms", "ms.", "mx", "mx.", "prof", "prof."}


def first_name(name: str | None) -> str:
    words = [w for w in (name or "").strip().split() if w.lower() not in HONORIFICS]
    return words[0] if words else ""


def base_url(request: Request) -> str:
    if PUBLIC_BASE_URL:
        return PUBLIC_BASE_URL
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("host", request.url.netloc)
    return f"{proto}://{host}"


# --------------------------------------------------------------------------- pages
def _page(name: str) -> FileResponse:
    return FileResponse(os.path.join(STATIC, name), media_type="text/html")


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    limit(request, "page")
    return _page("home.html")


@app.get("/p/{token}")
def wizard_page(request: Request, token: str):
    limit(request, "page")
    return _page("wizard.html")


@app.get("/rep")
def rep_page(request: Request):
    limit(request, "page")
    return _page("rep.html")


@app.get("/robots.txt", response_class=PlainTextResponse)
def robots():
    return "User-agent: *\nDisallow: /\n"


@app.get("/healthz")
def healthz():
    return {"ok": True}


# --------------------------------------------------------------------------- prospect API
def public_invite(row: dict) -> dict:
    ans = json.loads(row["answers_json"] or "{}")
    tin = dec_tin(row.get("tin_enc"))
    practice = ans.setdefault("practice", {})
    practice["tin_on_file"] = bool(tin)
    practice["tin_masked"] = mask_tin(tin)
    return {
        "first_name": first_name(row["prospect_name"]),
        "practice_name": row["practice_name"] or "",
        "rep_name": row["rep_name"] or "your CHS contact",
        "rep_email": row["rep_email"] or "",
        "status": row["status"],
        "current_step": row["current_step"],
        "expires_at": row["expires_at"],
        "submitted_at": row["submitted_at"],
        "answers": ans,
    }


@app.get("/api/p/{token}")
def get_invite(request: Request, token: str):
    limit(request, "wizard")
    row = invite_by_token(request, token)
    if not row["opened_at"]:
        db.execute("UPDATE invites SET opened_at = ? WHERE id = ?", (iso(now()), row["id"]))
        event(row["id"], "opened")
    return public_invite(row)


def _save(row: dict, body: dict, submit: bool) -> dict:
    answers, warnings = validate_answers(body.get("answers") or {})
    practice = answers.get("practice") or {}
    tin_enc = row.get("tin_enc")
    if "tin" in practice:
        raw = str(practice.pop("tin") or "")
        if raw.strip():
            if tin_valid(raw):
                tin_enc = enc_tin(tin_digits(raw))
            else:
                warnings.append("The TIN/EIN should be 9 digits (like 12-3456789), so it wasn't saved.")
        elif practice.get("tin_clear"):
            tin_enc = None
    for k in ("tin_clear", "tin_on_file", "tin_masked"):
        practice.pop(k, None)
    answers["practice"] = practice
    step = body.get("step")
    step = int(step) if isinstance(step, int) and 0 <= step <= 20 else row["current_step"]
    status = row["status"]
    t = iso(now())
    if submit:
        status = "submitted"
    elif status == "not_started":
        status = "in_progress"
    db.execute(
        "UPDATE invites SET answers_json = ?, tin_enc = ?, current_step = ?, status = ?, last_activity_at = ?"
        + (", submitted_at = ?" if submit else "") + " WHERE id = ?",
        (json.dumps(answers), tin_enc, step, status, t) + ((t,) if submit else ()) + (row["id"],),
    )
    if submit:
        event(row["id"], "submitted")
    fresh = db.one("SELECT * FROM invites WHERE id = ?", (row["id"],))
    out = public_invite(fresh)
    out["warnings"] = warnings
    out["saved_at"] = t
    return out


@app.put("/api/p/{token}/answers")
async def save_answers(request: Request, token: str):
    limit(request, "wizard")
    row = invite_by_token(request, token)
    body = await _json(request)
    return _save(row, body, submit=False)


@app.post("/api/p/{token}/submit")
async def submit(request: Request, token: str):
    limit(request, "wizard")
    row = invite_by_token(request, token)
    body = await _json(request)
    return _save(row, body, submit=True)


async def _json(request: Request) -> dict:
    raw = await request.body()
    if len(raw) > 300_000:
        raise HTTPException(413, "Request too large.")
    try:
        body = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid request.")
    if not isinstance(body, dict):
        raise HTTPException(400, "Invalid request.")
    return body


@app.get("/api/p/{token}/payers")
def payers_for_states(request: Request, token: str, states: str = ""):
    limit(request, "wizard")
    invite_by_token(request, token)
    wanted = [s for s in states.upper().split(",") if s in PAYERS["states"]][:10]
    merged: dict[str, dict] = {}
    order: list[str] = []
    for st in wanted:
        for g in PAYERS["states"][st]["groups"]:
            if g["group"] not in merged:
                merged[g["group"]] = {"group": g["group"], "payers": {}}
                order.append(g["group"])
            bucket = merged[g["group"]]["payers"]
            for p in g["payers"]:
                if p["key"] in bucket:
                    bucket[p["key"]]["states"].append(st)
                else:
                    bucket[p["key"]] = {**p, "states": [st]}
    groups = [{"group": name, "payers": list(merged[name]["payers"].values())} for name in order]
    info = {st: {"name": PAYERS["states"][st]["name"], "mac": PAYERS["states"][st]["mac"],
                 "mco_verified": PAYERS["states"][st]["mco_verified"]} for st in wanted}
    return {"states": info, "groups": groups, "source": PAYERS["meta"]["source"], "generated_at": PAYERS["meta"]["generated_at"]}


@app.get("/api/p/{token}/payer-search")
def payer_search(request: Request, token: str, q: str = "", states: str = ""):
    limit(request, "wizard")
    invite_by_token(request, token)
    q = q.strip().lower()[:60]
    if len(q) < 2:
        return {"results": []}
    wanted = set(s for s in states.upper().split(",") if s in STATE_NAMES)
    res = []
    for sid, name, sts in PAYER_INDEX:
        if q in name.lower() and (not wanted or not sts or "NATIONAL" in sts or wanted & set(sts)):
            res.append({"key": sid, "name": name, "stedi_payer_id": sid, "states": [s for s in sts if s in wanted] or sts[:3]})
            if len(res) >= 15:
                break
    return {"results": res}


@app.get("/api/lists")
def lists(request: Request):
    limit(request, "wizard")
    return {"states": STATE_NAMES, "specialties": SPECIALTIES, "ehrs": EHRS}


# --------------------------------------------------------------------------- rep auth
def _sign(exp: int) -> str:
    sig = hmac.new(SESSION_SECRET, f"rep:{exp}".encode(), hashlib.sha256).hexdigest()
    return f"{exp}.{sig}"


def require_rep(request: Request) -> None:
    limit(request, "rep")
    cookie = request.cookies.get("chs_rep", "")
    try:
        exp_s, sig = cookie.split(".", 1)
        exp = int(exp_s)
    except ValueError:
        raise HTTPException(401, "Please sign in.")
    if exp < time.time() or not hmac.compare_digest(_sign(exp), cookie):
        raise HTTPException(401, "Please sign in.")


@app.post("/api/rep/login")
async def rep_login(request: Request):
    limit(request, "login")
    body = await _json(request)
    pw = str(body.get("password") or "")
    if not ADMIN_PASSWORD or not hmac.compare_digest(pw.encode(), ADMIN_PASSWORD.encode()):
        event(None, "rep_login_failed", client_ip(request))
        raise HTTPException(401, "That password didn't match.")
    exp = int(time.time()) + SESSION_HOURS * 3600
    resp = JSONResponse({"ok": True})
    secure = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    resp.set_cookie("chs_rep", _sign(exp), max_age=SESSION_HOURS * 3600, httponly=True, secure=secure,
                    samesite="strict", path="/")
    event(None, "rep_login", client_ip(request))
    return resp


@app.post("/api/rep/logout")
def rep_logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("chs_rep", path="/")
    return resp


@app.get("/api/rep/me")
def rep_me(request: Request):
    require_rep(request)
    ephemeral = not db.IS_PG and bool(os.environ.get("RENDER"))
    return {"ok": True, "link_days": LINK_DAYS, "storage": "postgres" if db.IS_PG else "sqlite", "storage_ephemeral": ephemeral}


# --------------------------------------------------------------------------- rep invites
def email_template(prospect_name: str, practice: str, rep_name: str, link: str, expires: str) -> dict:
    fn = first_name(prospect_name) or "there"
    exp_date = dt.datetime.fromisoformat(expires).strftime("%B %-d, %Y")
    subject = "A quick, skippable checklist for your credentialing & billing quote"
    body = (
        f"Hi {fn},\n\n"
        f"Thanks for talking with me about {practice or 'your practice'}. To put together an accurate credentialing "
        f"and billing quote, I made you a short guided checklist. It takes about 5 minutes:\n\n"
        f"{link}\n\n"
        "Every question is optional. If you don't know an answer or haven't decided yet, just tap \"Not sure\" and keep "
        "going. Your answers save as you go, so you can stop and come back with the same link. It doesn't ask for any "
        "patient information.\n\n"
        f"The link is just for you and works until {exp_date}. Once you're done, I'll follow up with your quote and "
        "next steps.\n\n"
        "Warm regards,"
    )
    return {"subject": subject, "body": body}


def rep_view(row: dict, request: Request, reveal: bool = False) -> dict:
    ans = json.loads(row["answers_json"] or "{}")
    tin = dec_tin(row.get("tin_enc"))
    link = f"{base_url(request)}/p/{row['token']}"
    expired = dt.datetime.fromisoformat(row["expires_at"]) < now()
    status = "revoked" if row["revoked"] else ("expired" if expired and row["status"] != "submitted" else row["status"])
    return {
        "id": row["id"], "link": link, "prospect_name": row["prospect_name"], "prospect_email": row["prospect_email"],
        "practice_name": row["practice_name"], "rep_name": row["rep_name"], "rep_email": row["rep_email"],
        "created_at": row["created_at"], "expires_at": row["expires_at"], "opened_at": row["opened_at"],
        "last_activity_at": row["last_activity_at"], "submitted_at": row["submitted_at"],
        "status": status, "raw_status": row["status"], "current_step": row["current_step"], "is_test": bool(row["is_test"]),
        "tin_masked": mask_tin(tin), "tin": fmt_tin(tin) if (reveal and tin) else None,
        "answers": ans,
        "email": email_template(row["prospect_name"], row["practice_name"], row["rep_name"], link, row["expires_at"]),
    }


@app.post("/api/rep/invites")
async def create_invite(request: Request):
    require_rep(request)
    b = clean(await _json(request))
    prospect_name = str(b.get("prospect_name") or "")[:120]
    prospect_email = str(b.get("prospect_email") or "")[:200]
    rep_name = str(b.get("rep_name") or "")[:120]
    if not prospect_name or not rep_name:
        raise HTTPException(400, "Prospect name and rep name are required.")
    if prospect_email and not EMAIL_RE.match(prospect_email):
        raise HTTPException(400, "Prospect email doesn't look valid.")
    rep_email = str(b.get("rep_email") or "")[:200]
    if rep_email and not EMAIL_RE.match(rep_email):
        raise HTTPException(400, "Rep email doesn't look valid.")
    days = b.get("expires_days") or LINK_DAYS
    days = max(1, min(int(days) if isinstance(days, (int, float)) else LINK_DAYS, 90))
    token = secrets.token_urlsafe(32)
    t = now()
    new_id = db.execute(
        "INSERT INTO invites (token, prospect_name, prospect_email, practice_name, rep_name, rep_email, created_at, expires_at, is_test) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (token, prospect_name, prospect_email, str(b.get("practice_name") or "")[:200], rep_name, rep_email,
         iso(t), iso(t + dt.timedelta(days=days)), 1 if b.get("is_test") else 0),
    )
    event(new_id, "invite_created", f"by rep {rep_name}")
    return rep_view(db.one("SELECT * FROM invites WHERE id = ?", (new_id,)), request)


def _summary(row: dict, request: Request) -> dict:
    v = rep_view(row, request)
    a = v.pop("answers")
    v.pop("email")
    sel = ((a.get("payers") or {}).get("selected") or {})
    v["states"] = a.get("states") or []
    v["payer_count"] = len(sel)
    v["provider_count"] = (a.get("providers") or {}).get("count") or len(((a.get("providers") or {}).get("list") or []))
    v["services"] = (a.get("rcm") or {}).get("services") or []
    return v


@app.get("/api/rep/invites")
def list_invites(request: Request):
    require_rep(request)
    rows = db.query("SELECT * FROM invites ORDER BY id DESC")
    return {"invites": [_summary(r, request) for r in rows]}


def _get(invite_id: int) -> dict:
    row = db.one("SELECT * FROM invites WHERE id = ?", (invite_id,))
    if not row:
        raise HTTPException(404, "Not found.")
    return row


@app.get("/api/rep/invites/{invite_id}")
def invite_detail(request: Request, invite_id: int):
    require_rep(request)
    return rep_view(_get(invite_id), request)


@app.post("/api/rep/invites/{invite_id}/reveal-tin")
def reveal_tin(request: Request, invite_id: int):
    require_rep(request)
    row = _get(invite_id)
    event(invite_id, "tin_revealed", client_ip(request))
    return {"tin": rep_view(row, request, reveal=True)["tin"]}


@app.post("/api/rep/invites/{invite_id}/extend")
def extend(request: Request, invite_id: int):
    require_rep(request)
    _get(invite_id)
    db.execute("UPDATE invites SET expires_at = ?, revoked = 0 WHERE id = ?", (iso(now() + dt.timedelta(days=LINK_DAYS)), invite_id))
    event(invite_id, "extended")
    return rep_view(_get(invite_id), request)


@app.post("/api/rep/invites/{invite_id}/revoke")
def revoke(request: Request, invite_id: int):
    require_rep(request)
    _get(invite_id)
    db.execute("UPDATE invites SET revoked = 1 WHERE id = ?", (invite_id,))
    event(invite_id, "revoked")
    return rep_view(_get(invite_id), request)


# --------------------------------------------------------------------------- exports
def flatten(row: dict, request: Request) -> list[tuple[str, str, str]]:
    v = rep_view(row, request)
    a = v["answers"]
    out: list[tuple[str, str, str]] = []
    add = lambda s, f, val: out.append((s, f, "" if val is None else (", ".join(map(str, val)) if isinstance(val, list) else str(val))))
    for f in ("prospect_name", "prospect_email", "practice_name", "rep_name", "status", "created_at", "submitted_at"):
        add("invite", f, v[f])
    add("states", "states", [STATE_NAMES.get(s, s) for s in a.get("states") or []])
    add("states", "unsure", a.get("states_unsure"))
    pay = a.get("payers") or {}
    for key, p in (pay.get("selected") or {}).items():
        add("payers", p.get("name") or key, f"group={p.get('group','')}; stedi_id={p.get('stedi_payer_id') or ''}; in_network={p.get('in_network') or 'unanswered'}")
    add("payers", "other_payers", pay.get("other"))
    add("payers", "unsure", pay.get("unsure"))
    pr = a.get("practice") or {}
    for f in ("legal_name", "dba", "group_npi"):
        add("practice", f, pr.get(f))
    add("practice", "tin", v["tin_masked"] or "")
    addr = pr.get("address") or {}
    add("practice", "address", ", ".join(x for x in [addr.get("street"), addr.get("city"), addr.get("state"), addr.get("zip")] if x))
    add("practice", "unsure", [k for k, val in (pr.get("unsure") or {}).items() if val])
    sp = a.get("specialty") or {}
    for f in ("specialties", "practice_stage", "practice_size", "care_setting"):
        add("specialty", f, sp.get(f))
    pv = a.get("providers") or {}
    add("providers", "count", pv.get("count"))
    for i, p in enumerate(pv.get("list") or [], 1):
        add("providers", f"provider_{i}", f"{p.get('name','')} | {p.get('credential','')} | NPI {p.get('npi') or '-'} | new to credentialing: {p.get('new_to_credentialing') or 'unanswered'}")
    r = a.get("rcm") or {}
    for f in ("services", "billing_setup", "ehr", "monthly_claims", "monthly_collections", "go_live"):
        add("rcm", f, r.get(f))
    c = a.get("contact") or {}
    for f in ("name", "title", "email", "phone", "best_time", "method", "notes"):
        add("contact", f, c.get(f))
    return out


@app.get("/api/rep/invites/{invite_id}/export.csv")
def export_one_csv(request: Request, invite_id: int):
    require_rep(request)
    row = _get(invite_id)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["section", "field", "value"])
    w.writerows(flatten(row, request))
    name = re.sub(r"[^A-Za-z0-9]+", "_", row["practice_name"] or row["prospect_name"] or "prospect").strip("_")
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{name}_discovery_{invite_id}.csv"'})


def export_record(row: dict, request: Request) -> dict:
    v = rep_view(row, request)
    v.pop("email")
    v.pop("tin")
    v.pop("link")
    return {"schema": "chs.prospect_discovery.v1", **v}


@app.get("/api/rep/invites/{invite_id}/export.json")
def export_one_json(request: Request, invite_id: int):
    require_rep(request)
    return export_record(_get(invite_id), request)


@app.get("/api/rep/export.json")
def export_all_json(request: Request, submitted_only: int = 0):
    require_rep(request)
    rows = db.query("SELECT * FROM invites ORDER BY id")
    recs = [export_record(r, request) for r in rows if not submitted_only or r["status"] == "submitted"]
    return {"schema": "chs.prospect_discovery.v1", "exported_at": iso(now()), "count": len(recs), "records": recs}


@app.get("/api/rep/export.csv")
def export_all_csv(request: Request):
    require_rep(request)
    rows = db.query("SELECT * FROM invites ORDER BY id")
    buf = io.StringIO()
    w = csv.writer(buf)
    cols = ["id", "status", "is_test", "prospect_name", "prospect_email", "practice_name", "rep_name", "created_at",
            "submitted_at", "states", "payers", "other_payers", "legal_name", "dba", "tin_masked", "group_npi",
            "specialties", "practice_stage", "practice_size", "care_setting", "provider_count", "providers",
            "services", "billing_setup", "ehr", "monthly_claims", "monthly_collections", "go_live",
            "contact_name", "contact_email", "contact_phone", "notes"]
    w.writerow(cols)
    for r in rows:
        v = rep_view(r, request)
        a = v["answers"]
        pr, sp, pv, rc, c = (a.get(k) or {} for k in ("practice", "specialty", "providers", "rcm", "contact"))
        sel = (a.get("payers") or {}).get("selected") or {}
        w.writerow([v["id"], v["status"], v["is_test"], v["prospect_name"], v["prospect_email"], v["practice_name"], v["rep_name"],
                    v["created_at"], v["submitted_at"], ";".join(a.get("states") or []),
                    "; ".join(f"{p.get('name')} ({p.get('in_network') or '?'})" for p in sel.values()),
                    (a.get("payers") or {}).get("other", ""), pr.get("legal_name", ""), pr.get("dba", ""), v["tin_masked"] or "",
                    pr.get("group_npi", ""), "; ".join(sp.get("specialties") or []), sp.get("practice_stage", ""),
                    sp.get("practice_size", ""), sp.get("care_setting", ""), pv.get("count", ""),
                    "; ".join(f"{p.get('name')} {p.get('credential')}".strip() for p in pv.get("list") or []),
                    "; ".join(rc.get("services") or []), rc.get("billing_setup", ""), rc.get("ehr", ""),
                    rc.get("monthly_claims", ""), rc.get("monthly_collections", ""), rc.get("go_live", ""),
                    c.get("name", ""), c.get("email", ""), c.get("phone", ""), c.get("notes", "")])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="prospect_discovery_all.csv"'})
