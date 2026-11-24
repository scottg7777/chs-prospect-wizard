# CHS Practice Discovery Wizard

A friendly, skippable, multi-step web wizard that Continuant Healthcare Solutions (CHS) sales reps email to
prospective credentialing and RCM customers. It collects what we need for a credentialing + RCM quote without
being a burden. **Every question is optional**, and each one has a clear "Not sure" option.

- **Prospect link:** `https://<host>/p/<token>`. The token is personal, random (256-bit) and expires (30 days by default).
- **Rep console:** `https://<host>/rep`, password protected.

## What the prospect sees

| # | Step | What it collects |
|---|------|------------------|
| 0 | Welcome | Rep name, practice, privacy note, time estimate |
| 1 | Where you practice | One or more states (filterable chips) |
| 2 | Insurance payers | Payers for the chosen states, grouped: Government (Medicare Part B MAC, state Medicaid, TRICARE), Medicaid managed care (verified states only), Commercial (state BCBS, Kaiser where it operates, Aetna, Cigna, UHC, Humana, Oscar where listed), Behavioral health. "Already in network? Yes / No / Not sure" for each selected payer, a search across the whole Stedi network, and free-text "other plans" |
| 3 | Practice details | Legal name, DBA, TIN/EIN (masked input, format check, **encrypted at rest**), group NPI (Luhn check), address |
| 4 | Specialty & setup | Specialty type-ahead (free text allowed), new vs. established, solo vs. group, in person / telehealth / both |
| 5 | Providers | Count stepper, then a row per provider: name, credential, optional NPI (Luhn check), new to credentialing? |
| 6 | Billing & timing | Services wanted, current billing setup, EHR/PM (type-ahead), monthly claims and collections ranges, go-live timing |
| 7 | Contact | Name, title, email, phone, preferred method, best time, notes |
| 8 | Review | Summary with an Edit button per section and a count of skipped items, then Submit |
| 9 | Thank you | Confetti 🎉 and next steps. The prospect can reopen and edit until the link expires |

Answers autosave to the server (debounced, and again when the tab is hidden). Reopening the same link resumes
where the prospect left off. Each step also has a "Skip for now" button.

## Rep console

- Create an invite with the prospect's name and email, the practice, the rep's name and email, and how long the link lasts. You get the secure link plus a ready-to-send email (see `email_template.md`) with Copy and Open-in-email-app buttons. **The app never sends email.**
- The invite list shows status (Not started / In progress / Submitted / Expired / Revoked), the step reached, states, payer and provider counts, and last activity.
- The detail view shows the full submission. The TIN stays masked until a rep clicks **Reveal**, and every reveal is logged in `events`. You can also extend or revoke a link from here.
- Exports: one prospect or all prospects as CSV/JSON (`/api/rep/export.json` uses schema `chs.prospect_discovery.v1`, which the CS agent can import into `customers.db` later). Exports include only the masked TIN.

## Security

- HTTPS on Render, with a forced redirect (`FORCE_HTTPS=1`) and HSTS.
- Unguessable tokens from `secrets.token_urlsafe(32)`. Links expire and can be revoked. Every invalid-token lookup counts toward a per-IP limit, to stop enumeration.
- In-memory rate limits per IP: login 10 per 15 min, failed token lookups 30 per 10 min, wizard API 240/min, rep API 600/min.
- Rep session: an HMAC-signed, HttpOnly, SameSite=Strict, Secure cookie that lasts 12 hours. Passwords are compared in constant time.
- Strict CSP (`default-src 'self'`), no third-party scripts, fonts, analytics or trackers. Also `Referrer-Policy: no-referrer` (keeps the token out of referrers), `X-Frame-Options: DENY`, `noindex`, and `no-store` on API and page responses.
- Server-side validation: allow-listed answer keys, length and size limits, state codes checked against the list, NPI Luhn check, TIN format check, email format check.
- The TIN is encrypted with Fernet (`TIN_ENC_KEY`) and never appears in exports in full.
- Access logs are off (`--no-access-log`), so tokens don't land in logs.
- No PHI. The wizard asks only about the practice and tells prospects not to enter patient information.
- The Stedi API key is **never** used by the running app or the browser. The payer list is a static JSON file built offline (below).

## Payer data (Stedi network)

- `tools/fetch_stedi_payers.py` pulls the full Stedi Payer Network (`GET https://payers.us.stedi.com/2024-04-01/payers`) into `data/raw/` (gitignored). It reads `STEDI_API_KEY` from the environment, the same variable `/workspace/provider-status-api` uses, and never prints it.
- `tools/build_payers.py` builds `app/data/payers_by_state.json` (50 states + DC) and `app/data/payer_index.json` (for search). Sources:
  - Medicare Part B payer per state from Stedi, labeled with the CMS A/B MAC jurisdiction. Hawaii uses the Noridian JE payer that carries Hawaii's 01312 alias.
  - State Medicaid fee-for-service payer from Stedi, with manual picks where names are ambiguous (CO Health First Colorado, NJ FamilyCare, TX acute care, and so on).
  - TRICARE East/West, using the states Stedi lists for each region.
  - Medicaid MCOs **only** for the 9 states verified earlier in `customer-sat/exports/payer_options` (AZ, CA, CO, IL, MS, NY, NC, TX, VA). Other states show government plans, nationals and their state BCBS, plus search across the whole network.
  - State BCBS licensees, mapped by hand to Stedi payer IDs (every ID is checked against the Stedi list). Kaiser where it operates. National carriers. Oscar where Stedi lists the state. Behavioral carve-outs.
- `PAYER_COVERAGE.md` shows the per-state counts. To refresh: `python tools/fetch_stedi_payers.py && python tools/build_payers.py`, then commit `app/data/`.

## Run locally

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
# secrets live in .secrets/admin.env (ADMIN_PASSWORD, SESSION_SECRET, TIN_ENC_KEY), gitignored, chmod 600
./run_local.sh          # http://127.0.0.1:8090  (SQLite at var/wizard.db)
.venv/bin/python -m pytest -q tests                       # API end-to-end tests
.venv/bin/python tests/ui_e2e.py http://127.0.0.1:8090    # browser e2e + screenshots-review/
```

## Deploy (Render)

- Web service from GitHub `scottg7777/chs-prospect-wizard`, Python runtime.
  - Build: `pip install -r requirements.txt`
  - Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT --no-access-log --proxy-headers --forwarded-allow-ips=*`
- Env vars: `ADMIN_PASSWORD`, `SESSION_SECRET`, `TIN_ENC_KEY`, `DATABASE_URL` (Render Postgres internal URL), `FORCE_HTTPS=1`, `PUBLIC_BASE_URL`, and optionally `LINK_EXPIRY_DAYS`.
- Storage: Render Postgres when `DATABASE_URL` is set, otherwise SQLite (`SQLITE_PATH`).
- Auto-deploys on every push to `main`.

**Important:** if `TIN_ENC_KEY` changes, stored TINs can no longer be decrypted. Keep it stable.
