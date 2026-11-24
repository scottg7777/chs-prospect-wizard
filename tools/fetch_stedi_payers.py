"""Refresh data/raw/stedi_payers.json from Stedi. Reads STEDI_API_KEY from the environment; never prints it."""
import json, os, urllib.request
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
key = (os.environ.get("STEDI_API_KEY") or "").strip()
if not key:
    raise SystemExit("STEDI_API_KEY is not set")
req = urllib.request.Request("https://payers.us.stedi.com/2024-04-01/payers",
                             headers={"Authorization": key, "Accept": "application/json"})
with urllib.request.urlopen(req, timeout=120) as r:
    data = json.load(r)
os.makedirs(os.path.join(ROOT, "data", "raw"), exist_ok=True)
json.dump(data, open(os.path.join(ROOT, "data", "raw", "stedi_payers.json"), "w"))
print("payers:", len(data.get("items") or []))
