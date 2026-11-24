"""Server-side CMS NPPES NPI Registry lookups (public data, no key). The browser never calls NPPES directly."""
from __future__ import annotations

import asyncio
import re
import time
from typing import Any

import httpx

NPPES_URL = "https://npiregistry.cms.hhs.gov/api/"
_cache: dict[tuple, tuple[float, list[dict]]] = {}
CACHE_SECONDS = 600
SUFFIXES = {"LLC", "PLLC", "PC", "PA", "INC", "CORP", "LTD", "LLP", "LP", "PSC", "SC", "CO"}
TITLES = {"DR", "MR", "MRS", "MS", "MD", "DO", "NP", "PA", "PHD", "PSYD", "LCSW", "LPC", "FNP", "APRN", "DPM", "DC"}


def _clean(v: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^A-Za-z0-9&' \-]", " ", v or "")).strip()


def _phone(p: str | None) -> str:
    d = re.sub(r"\D", "", p or "")
    return f"({d[:3]}) {d[3:6]}-{d[6:10]}" if len(d) == 10 else (p or "")


def _zip(z: str | None) -> str:
    z = re.sub(r"\D", "", z or "")
    return f"{z[:5]}-{z[5:]}" if len(z) == 9 else z


def _title(s: str | None) -> str:
    if not s:
        return ""
    return " ".join(w if (len(w) <= 3 and w.isupper() and w in SUFFIXES) else w.capitalize() for w in s.split())


def parse(r: dict[str, Any]) -> dict[str, Any]:
    b = r.get("basic") or {}
    etype = r.get("enumeration_type")
    addrs = r.get("addresses") or []
    loc = next((a for a in addrs if a.get("address_purpose") == "LOCATION"), addrs[0] if addrs else {})
    taxes = r.get("taxonomies") or []
    prim = next((t for t in taxes if t.get("primary")), taxes[0] if taxes else {})
    if etype == "NPI-1":
        name = " ".join(x for x in [b.get("first_name"), b.get("middle_name"), b.get("last_name")] if x)
        name = _title(name)
    else:
        name = _title(b.get("organization_name"))
    other = [_title(o.get("organization_name")) for o in (r.get("other_names") or []) if o.get("organization_name")]
    return {
        "npi": str(r.get("number")),
        "type": "individual" if etype == "NPI-1" else "organization",
        "name": name,
        "first_name": _title(b.get("first_name")),
        "last_name": _title(b.get("last_name")),
        "credential": (b.get("credential") or "").replace(".", "").strip(),
        "other_names": other[:3],
        "status": b.get("status") or "",
        "enumeration_date": b.get("enumeration_date") or "",
        "last_updated": b.get("last_updated") or "",
        "address": {
            "street": _title(" ".join(x for x in [loc.get("address_1"), loc.get("address_2")] if x)),
            "city": _title(loc.get("city")),
            "state": loc.get("state") or "",
            "zip": _zip(loc.get("postal_code")),
        },
        "phone": _phone(loc.get("telephone_number")),
        "taxonomy": prim.get("desc") or "",
        "taxonomy_code": prim.get("code") or "",
        "taxonomies": [t.get("desc") for t in taxes if t.get("desc")][:4],
    }


async def _query(client: httpx.AsyncClient, params: dict[str, str]) -> list[dict]:
    key = tuple(sorted(params.items()))
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    r = await client.get(NPPES_URL, params={"version": "2.1", "limit": "25", **params})
    r.raise_for_status()
    data = r.json() or {}
    results = [parse(x) for x in (data.get("results") or [])]
    _cache[key] = (time.time(), results)
    if len(_cache) > 2000:
        _cache.clear()
    return results


async def search(kind: str, *, first: str = "", last: str = "", org: str = "", states: list[str]) -> list[dict]:
    states = states[:5] or [""]
    calls = []
    if kind == "organization":
        words = [w for w in _clean(org).split() if w.upper() not in SUFFIXES]
        if len("".join(words)) < 2:
            return []
        name = " ".join(words)
        for st in states:
            p = {"enumeration_type": "NPI-2", "organization_name": name + "*"}
            if st:
                p["state"] = st
            calls.append(p)
    else:
        first = " ".join(w for w in _clean(first).split() if w.upper().rstrip(".") not in TITLES)
        last = " ".join(w for w in _clean(last).split() if w.upper().rstrip(".") not in TITLES)
        if len(last) < 2:
            return []
        for st in states:
            p = {"enumeration_type": "NPI-1", "last_name": last}
            if len(first) >= 2:
                p["first_name"] = first + "*"
            if st:
                p["state"] = st
            calls.append(p)
    async with httpx.AsyncClient(timeout=12, headers={"User-Agent": "CHS-Practice-Discovery/1.0"}) as client:
        batches = await asyncio.gather(*[_query(client, p) for p in calls], return_exceptions=True)
    seen, out = set(), []
    errors = [b for b in batches if isinstance(b, Exception)]
    for b in batches:
        if isinstance(b, Exception):
            continue
        for rec in b:
            if rec["npi"] not in seen:
                seen.add(rec["npi"])
                out.append(rec)
    if errors and not out:
        raise RuntimeError("The NPI registry didn't respond. Please try again in a moment.")
    # Active records first, then those located in a chosen state.
    want = set(s for s in states if s)
    out.sort(key=lambda r: (r["status"] != "A", r["address"]["state"] not in want if want else False, r["name"]))
    return out[:25]
