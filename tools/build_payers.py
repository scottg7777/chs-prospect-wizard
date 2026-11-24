"""Build the per-state payer dataset served by the wizard.

Inputs (server-side only):
  data/raw/stedi_payers.json  - full Stedi Payer Network list (GET /payers), fetched with
                                 STEDI_API_KEY via tools/fetch_stedi_payers.py. Never committed.
  /workspace/customer-sat/exports/payer_options/*.csv - verified Medicaid MCO rows from the
                                 earlier payer-selection work (9 states).
Output:
  app/data/payers_by_state.json - curated groups for 50 states + DC
  app/data/payer_index.json     - compact name/state index for the "search more payers" box
Nothing here invents a payer: every entry with a stedi_payer_id is looked up in the Stedi list.
"""
from __future__ import annotations
import csv, glob, json, os, sys, datetime
sys.path.insert(0, os.path.dirname(__file__))
from states import STATES

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw", "stedi_payers.json")
OUT = os.path.join(ROOT, "app", "data")
CSV_GLOB = "/workspace/customer-sat/exports/payer_options/*.csv"

items = json.load(open(RAW))["items"]
BY_ID = {i["stediId"]: i for i in items}

# Medicare Part B MAC jurisdictions (CMS A/B MAC map).
MAC = {
    "JE": ("Noridian Healthcare Solutions", ["CA", "HI", "NV"]),
    "JF": ("Noridian Healthcare Solutions", ["AK", "AZ", "ID", "MT", "ND", "OR", "SD", "UT", "WA", "WY"]),
    "JH": ("Novitas Solutions", ["AR", "CO", "LA", "MS", "NM", "OK", "TX"]),
    "JL": ("Novitas Solutions", ["DE", "DC", "MD", "NJ", "PA"]),
    "J5": ("Wisconsin Physicians Service (WPS)", ["IA", "KS", "MO", "NE"]),
    "J8": ("Wisconsin Physicians Service (WPS)", ["IN", "MI"]),
    "J6": ("National Government Services (NGS)", ["IL", "MN", "WI"]),
    "JK": ("National Government Services (NGS)", ["CT", "ME", "MA", "NH", "NY", "RI", "VT"]),
    "J15": ("CGS Administrators", ["KY", "OH"]),
    "JJ": ("Palmetto GBA", ["AL", "GA", "TN"]),
    "JM": ("Palmetto GBA", ["NC", "SC", "VA", "WV"]),
    "JN": ("First Coast Service Options", ["FL"]),
}
MAC_BY_STATE = {st: (j, c) for j, (c, sts) in MAC.items() for st in sts}

# Medicaid fee-for-service payer per state where the name match is ambiguous or non-standard.
MEDICAID_OVERRIDE = {"CO": "IEMTN", "NJ": "FADQP", "IL": "PACIU", "LA": "TYVLW", "MI": "RFUPF",
                     "MS": "TZXRM", "NV": "FCJKG", "NM": "MVZBO", "OH": "SMZIL", "SD": "GTRFT",
                     "TN": "CRSWV", "TX": "MHBFC"}
MEDICAID_NOTES = {"CO": "Health First Colorado (Colorado Medicaid).", "NJ": "NJ FamilyCare (New Jersey Medicaid).",
                  "TN": "TennCare. Most members are in TennCare managed care plans.",
                  "TX": "Texas Medicaid acute care (TMHP). Most members are in STAR managed care plans.",
                  "CA": "Medi-Cal fee-for-service.", "AZ": "AHCCCS fee-for-service."}

# State Blue Cross Blue Shield licensee(s), resolved to Stedi payer IDs (verified in the Stedi list).
BCBS = {
    "AL": ["DCIYM"], "AK": ["FKAUR"], "AZ": ["CAXSY"], "AR": ["GESBC"], "CA": ["LAESW", "JDGWJ"],
    "CO": ["TBEZC"], "CT": ["DRWRY"], "DE": ["ILQUL"], "DC": ["OUVRH", "GBPZQ"], "FL": ["ULXRI"],
    "GA": ["VDCLI"], "HI": ["WKDLP"], "ID": ["HAOYV", "THTLS"], "IL": ["DTQAZ"], "IN": ["AOQAR"],
    "IA": ["PYJGI"], "KS": ["VESYH", "OKDNG"], "KY": ["DXTYZ"], "LA": ["RQBKH"], "ME": ["YJHSX"],
    "MD": ["GBPZQ"], "MA": ["EWDCI"], "MI": ["KRPCH"], "MN": ["WLKCN"], "MS": ["AGBDX"],
    "MO": ["XUAZF", "OKDNG"], "MT": ["DBFST"], "NE": ["OIAZC"], "NV": ["ERSOT"], "NH": ["QCFIB"],
    "NJ": ["NRHDN"], "NM": ["UDVWS"], "NY": ["OLQXL", "HIANX", "SRICT"], "NC": ["UPICO"],
    "ND": ["AWBDZ"], "OH": ["BHNXS"], "OK": ["XOFIC"], "OR": ["VSAZE"],
    "PA": ["GUFCO", "DACBS", "KUHOB"], "RI": ["ZINQS"], "SC": ["NYNYD"], "SD": ["PYJGI"],
    "TN": ["EZKYS"], "TX": ["QDTRP"], "UT": ["HNRTE"], "VT": ["BIUKV"], "VA": ["DGOYK", "GBPZQ"],
    "WA": ["BSNZF", "LSJBA"], "WV": ["QWJLP"], "WI": ["VLFZU"], "WY": ["XVMEF"],
}
BCBS_NOTES = {"VA": "Anthem covers most of Virginia; CareFirst covers Northern Virginia (Arlington, Fairfax, Alexandria).",
              "MO": "Anthem covers most of Missouri; Blue KC covers the Kansas City area.",
              "KS": "BCBS of Kansas covers most of Kansas; Blue KC covers Johnson and Wyandotte counties.",
              "PA": "Highmark (western/central), Independence (Philadelphia area) and Capital Blue Cross (central PA).",
              "NY": "Empire/Anthem (downstate), Excellus (upstate/Rochester), Highmark (Western & Northeastern NY).",
              "WA": "Premera and Regence both operate statewide.", "ID": "Blue Cross of Idaho and Regence BlueShield of Idaho.",
              "CA": "Anthem Blue Cross and Blue Shield of California.", "DC": "CareFirst BlueCross BlueShield."}

NATIONALS = ["HPQRS", "HGJLR", "KMQTZ", "UYORK"]  # Aetna, Cigna, UnitedHealthcare, Humana
REGIONAL_IF_OPERATING = ["TAZWT"]  # Oscar Health (included only where Stedi lists the state)
KAISER = {"CA": ["RNMGY", "OHKFC"], "CO": ["ZECTW"], "GA": ["HXIKH"], "HI": ["TGZKH"], "MD": ["NOQOP"],
          "VA": ["NOQOP"], "DC": ["NOQOP"], "OR": ["GJUXI"], "WA": ["ASLGA", "GJUXI"]}
BEHAVIORAL = [("SWTRT", "Behavioral health network often used as a carve-out (formerly Beacon Health Options)."),
              ("XJWMR", "Behavioral health network often used as a carve-out."),
              ("YDIVO", "EAP / behavioral health.")]
TRICARE = {"IYHIG": "TRICARE East (Humana Military)", "TJPRF": "TRICARE West (TriWest)"}

TX_LABEL = {"SUPPORTED": "Supported", "ENROLLMENT_REQUIRED": "Enrollment required", "NOT_SUPPORTED": "Not supported"}


def entry(sid: str, note: str = "", name: str | None = None) -> dict:
    p = BY_ID[sid]
    ts = p.get("transactionSupport") or {}
    return {
        "key": sid,
        "name": name or p["displayName"],
        "stedi_payer_id": sid,
        "primary_payer_id": p.get("primaryPayerId"),
        "note": note,
        "eligibility_270": TX_LABEL.get(ts.get("eligibilityCheck"), ""),
        "claims_837p": TX_LABEL.get(ts.get("professionalClaimSubmission"), ""),
        "era_835": TX_LABEL.get(ts.get("claimPayment"), ""),
    }


def medicare_partb(st: str) -> list[dict]:
    name = STATES[st]
    out = []
    for p in items:
        n = p["displayName"]
        if "Part B" in n and n.startswith("Medicare") and (p.get("operatingStates") or []) == [st]:
            out.append(p)
    if st == "NY":  # Stedi lists Downstate without "Part B" in the name
        out += [BY_ID["FAKJR"]]
    return out


def medicaid_ffs(st: str):
    if st in MEDICAID_OVERRIDE:
        return BY_ID[MEDICAID_OVERRIDE[st]]
    name = STATES[st].lower()
    for p in items:
        n = p["displayName"].lower().strip()
        if (p.get("operatingStates") or []) == [st] and "MEDICAID" in (p.get("programs") or []) and \
                n in (f"medicaid {name}", f"{name} medicaid", f"medicaid california medi-cal"):
            return p
    return None


def load_verified_mcos() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for f in glob.glob(CSV_GLOB):
        rows = list(csv.DictReader(open(f)))
        gov = [r for r in rows if r["group"] == "Government" and r["programs"] == "MEDICARE"]
        if not gov:
            continue
        st = gov[0]["operating_states"].strip()
        for r in rows:
            if r["group"] != "Medicaid managed care":
                continue
            sid = r["stedi_payer_id"]
            if sid not in BY_ID:
                continue
            out.setdefault(st, [])
            if all(e["key"] != sid for e in out[st]):
                out[st].append(entry(sid, r["notes"], name=r["payer_name"]))
    return out


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    mcos = load_verified_mcos()
    states = {}
    gaps = []
    for st, name in STATES.items():
        j, contractor = MAC_BY_STATE[st]
        gov = []
        mb = medicare_partb(st)
        for p in mb:
            gov.append(entry(p["stediId"], f"Medicare Part B MAC: {contractor}, Jurisdiction {j}."))
        if not mb and st == "HI":
            gov.append(entry("MERIG", f"Medicare Part B MAC: {contractor}, Jurisdiction {j}. Stedi carries Hawaii's Part B payer ID 01312 as an alias on this Noridian JE payer.", name="Medicare Hawaii Part B (Noridian JE)"))
        elif not mb:
            gov.append({"key": f"MEDICARE-B-{st}", "name": f"Medicare Part B ({name})", "stedi_payer_id": None,
                        "primary_payer_id": None, "note": f"Medicare Part B MAC: {contractor}, Jurisdiction {j}. Not listed as a separate payer in the Stedi network; enrollment goes through the MAC.",
                        "eligibility_270": "", "claims_837p": "", "era_835": ""})
            gaps.append(f"{st}: no Stedi Medicare Part B payer")
        mcd = medicaid_ffs(st)
        if mcd:
            gov.append(entry(mcd["stediId"], MEDICAID_NOTES.get(st, f"{name} Medicaid fee-for-service.")))
        else:
            gaps.append(f"{st}: no Stedi Medicaid FFS payer")
        for sid, label in TRICARE.items():
            if st in (BY_ID[sid].get("operatingStates") or []):
                gov.append(entry(sid, f"{label}. Stedi lists {name} in this region."))
        groups = [{"group": "Government", "payers": gov}]
        if st in mcos:
            groups.append({"group": "Medicaid managed care", "payers": mcos[st]})
        com = []
        for sid in BCBS.get(st, []):
            com.append(entry(sid, BCBS_NOTES.get(st, f"State Blue Cross Blue Shield plan for {name}.")))
        for sid in KAISER.get(st, []):
            if all(e["key"] != sid for e in com):
                com.append(entry(sid, "Regional Kaiser Permanente plan (Stedi-listed for this state)."))
        for sid in NATIONALS:
            com.append(entry(sid, "National commercial plan."))
        for sid in REGIONAL_IF_OPERATING:
            if st in (BY_ID[sid].get("operatingStates") or []):
                com.append(entry(sid, f"Stedi lists {name} as an operating state."))
        groups.append({"group": "Commercial", "payers": com})
        groups.append({"group": "Behavioral health & other", "payers": [entry(s, n) for s, n in BEHAVIORAL]})
        states[st] = {"name": name, "mac": {"jurisdiction": j, "contractor": contractor},
                      "mco_verified": st in mcos, "groups": groups}
    meta = {"generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "source": "Stedi Payer Network (GET /payers), CMS A/B MAC jurisdiction map, CHS-verified Medicaid MCO lists",
            "stedi_payer_count": len(items)}
    json.dump({"meta": meta, "states": states}, open(os.path.join(OUT, "payers_by_state.json"), "w"), indent=1)
    index = [[p["stediId"], p["displayName"], p.get("operatingStates") or []] for p in items
             if set(p.get("coverageTypes") or ["medical"]) & {"medical", "behavioral"} or not p.get("coverageTypes")]
    json.dump(index, open(os.path.join(OUT, "payer_index.json"), "w"), separators=(",", ":"))
    for st in states:
        c = sum(len(g["payers"]) for g in states[st]["groups"])
        print(st, c, "MCO" if states[st]["mco_verified"] else "")
    print("gaps:", gaps)
    print("index size", len(index))


if __name__ == "__main__":
    main()
