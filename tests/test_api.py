"""End-to-end API test against an isolated SQLite DB (no network, no Stedi calls)."""
import os, tempfile, importlib
os.environ["SQLITE_PATH"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["ADMIN_PASSWORD"] = "test-pass-123"
from cryptography.fernet import Fernet
os.environ["TIN_ENC_KEY"] = Fernet.generate_key().decode()
os.environ.pop("DATABASE_URL", None)
from fastapi.testclient import TestClient
import app.main as m

def client():
    c = TestClient(m.app)
    c.__enter__()
    return c

def test_flow():
    c = client()
    assert c.get("/api/rep/invites").status_code == 401
    assert c.post("/api/rep/login", json={"password": "nope"}).status_code == 401
    assert c.post("/api/rep/login", json={"password": "test-pass-123"}).status_code == 200
    inv = c.post("/api/rep/invites", json={"prospect_name": "Pat Test", "rep_name": "Rep", "practice_name": "Test Clinic"}).json()
    token = inv["link"].rsplit("/", 1)[1]
    assert len(token) >= 40 and "Warm regards," in inv["email"]["body"]
    p = TestClient(m.app)  # prospect has no rep cookie
    assert p.get("/api/rep/invites").status_code == 401
    assert p.get("/api/p/" + "x" * 43).status_code == 404
    g = p.get(f"/api/p/{token}").json()
    assert g["status"] == "not_started" and g["first_name"] == "Pat"
    pay = p.get(f"/api/p/{token}/payers?states=AZ,TX").json()
    names = [x["name"] for grp in pay["groups"] for x in grp["payers"]]
    assert "Medicare Arizona Part B" in names and "Medicaid Arizona" in names
    ans = {"states": ["AZ", "ZZ"], "practice": {"legal_name": "Test LLC", "tin": "12-3456789", "group_npi": "1234567893"},
           "providers": {"count": 2, "list": [{"name": "A B", "credential": "MD", "npi": "1234567890"}]},
           "rcm": {"services": ["credentialing", "rcm"]}, "evil": {"x": 1}}
    r = p.put(f"/api/p/{token}/answers", json={"answers": ans, "step": 3}).json()
    assert r["status"] == "in_progress" and r["answers"]["states"] == ["AZ"] and "evil" not in r["answers"]
    assert r["answers"]["practice"]["tin_masked"].endswith("6789") and "tin" not in r["answers"]["practice"]
    assert r["answers"]["practice"]["group_npi"] == "1234567893"  # valid Luhn
    assert r["answers"]["providers"]["list"][0]["npi"] == ""      # invalid Luhn dropped
    assert r["warnings"]
    s = p.post(f"/api/p/{token}/submit", json={"answers": r["answers"], "step": 8}).json()
    assert s["status"] == "submitted" and s["answers"]["practice"]["tin_on_file"]
    lst = c.get("/api/rep/invites").json()["invites"]
    assert lst[0]["status"] == "submitted" and lst[0]["tin_masked"].endswith("6789") and lst[0]["tin"] is None
    assert c.post(f"/api/rep/invites/{lst[0]['id']}/reveal-tin").json()["tin"] == "12-3456789"
    csvt = c.get(f"/api/rep/invites/{lst[0]['id']}/export.csv").text
    assert "Test LLC" in csvt and "12-3456789" not in csvt and "123456789," not in csvt
    allj = c.get("/api/rep/export.json").json()
    assert allj["count"] == 1 and "tin" not in allj["records"][0]
    c.post(f"/api/rep/invites/{lst[0]['id']}/revoke")
    assert p.get(f"/api/p/{token}").status_code == 404
    h = p.get("/p/" + token)
    assert "default-src 'self'" in h.headers["content-security-policy"] and h.headers["referrer-policy"] == "no-referrer"

def test_login_rate_limit():
    c = client()
    m._buckets.clear()
    codes = [c.post("/api/rep/login", json={"password": "bad"}).status_code for _ in range(12)]
    assert codes.count(429) >= 1
