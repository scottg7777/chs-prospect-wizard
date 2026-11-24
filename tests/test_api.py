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


def test_npi_search_and_lookup_storage(monkeypatch):
    c = client()
    m._buckets.clear()
    c.post("/api/rep/login", json={"password": "test-pass-123"})
    inv = c.post("/api/rep/invites", json={"prospect_name": "Fake Person", "rep_name": "Rep"}).json()
    token = inv["link"].rsplit("/", 1)[1]
    seen = {}

    async def fake_search(kind, **kw):
        seen.update(kind=kind, **kw)
        return [{"npi": "1234567893", "type": kind, "name": "Fake Clinic", "address": {"state": "AZ"}}]
    monkeypatch.setattr(m.nppes, "search", fake_search)
    r = c.get(f"/api/p/{token}/npi-search?kind=organization&org=Fake%20Clinic&states=AZ,ZZ").json()
    assert r["results"][0]["npi"] == "1234567893" and seen["states"] == ["AZ"]
    assert c.get(f"/api/p/{token}/npi-search?kind=bogus").status_code == 400
    ans = {"lookup": {"selected": [{"npi": "1234567893", "type": "organization", "name": "Fake Clinic"},
                                   {"npi": "1234567890", "type": "individual", "name": "Bad Luhn"}]}}
    s = c.put(f"/api/p/{token}/answers", json={"answers": ans, "step": 2}).json()
    assert [x["npi"] for x in s["answers"]["lookup"]["selected"]] == ["1234567893"]
    detail = c.get(f"/api/rep/invites/{s and inv['id']}").json()
    assert detail["answers"]["lookup"]["selected"][0]["name"] == "Fake Clinic"
    assert "npi_registry" in c.get(f"/api/rep/invites/{inv['id']}/export.csv").text


def test_nppes_parse():
    from app import nppes
    rec = nppes.parse({"number": 1902877855, "enumeration_type": "NPI-2",
                       "basic": {"organization_name": "MAYO CLINIC ARIZONA", "status": "A"},
                       "addresses": [{"address_purpose": "LOCATION", "address_1": "5777 E MAYO BLVD", "city": "PHOENIX", "state": "AZ", "postal_code": "850544502", "telephone_number": "480-301-0881"}],
                       "taxonomies": [{"desc": "Clinic", "code": "261Q00000X", "primary": True}]})
    assert rec["name"] == "Mayo Clinic Arizona" and rec["address"]["zip"] == "85054-4502" and rec["phone"] == "(480) 301-0881"
