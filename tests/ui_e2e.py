"""Browser end-to-end run of the prospect flow + review screenshots.
Usage: python tests/ui_e2e.py BASE_URL PREFIX   (reads the admin password from .secrets/admin.env; never prints it)
Uses a fake test prospect. NPI lookups hit the public CMS NPPES registry (public directory data, not PHI)."""
import sys, os, json
from playwright.sync_api import sync_playwright
BASE = sys.argv[1].rstrip("/")
prefix = sys.argv[2] if len(sys.argv) > 2 else "local"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "screenshots-review")
os.makedirs(OUT, exist_ok=True)
pw_ = dict(l.strip().split("=", 1) for l in open(os.path.join(ROOT, ".secrets", "admin.env")) if "=" in l)["ADMIN_PASSWORD"]
errors, checks = [], {}

def shot(pg, name, top=True):
    if top:
        pg.evaluate("window.scrollTo(0,0)")
    pg.wait_for_timeout(700)
    pg.screenshot(path=f"{OUT}/{prefix}-{name}.png", full_page=False)

with sync_playwright() as p:
    b = p.chromium.launch()
    rp = b.new_context(viewport={"width": 1280, "height": 900}).new_page()
    rp.on("console", lambda m: m.type == "error" and "401" not in m.text and errors.append("rep: " + m.text))
    rp.goto(BASE + "/rep"); rp.fill("#pw", pw_); rp.click("#login-form button"); rp.wait_for_selector("#dash:not(.hidden)")
    rp.fill("#i-pn", "Taylor Testwell (TEST)"); rp.fill("#i-pe", "taylor.testwell@example.com"); rp.fill("#i-pr", "")
    rp.fill("#i-rn", "Scott Graham"); rp.fill("#i-re", "scottg@continuant.com"); rp.check("#i-test")
    rp.click("#invite-form button[type=submit]"); rp.wait_for_selector("#new-result:not(.hidden)")
    link = rp.inner_text("#lk").strip()

    pg = b.new_context(viewport={"width": 414, "height": 860}, device_scale_factor=2, is_mobile=True, has_touch=True).new_page()
    pg.on("console", lambda m: m.type == "error" and errors.append("wiz: " + m.text))
    pg.goto(link); pg.wait_for_selector("[data-bind='contact.name']")
    checks["name_prefilled_from_invite"] = pg.input_value("[data-bind='contact.name']")
    pg.fill("[data-bind='contact.name']", "Taylor Testwell"); pg.fill("[data-bind='contact.email']", "taylor.testwell@example.com")
    shot(pg, "n01-welcome-name-email")
    pg.click("[data-action=start]"); pg.wait_for_selector("[data-bind='practice.clinic_name']")
    pg.fill("[data-bind='practice.clinic_name']", "Mayo Clinic")
    pg.fill("#state-filter", "ariz"); pg.click("[data-state=AZ]"); pg.fill("#state-filter", "")
    shot(pg, "n02-clinic-and-states")
    pg.click("#next"); pg.wait_for_selector("#lk-org")
    pg.wait_for_selector("#lk-organization .npi-card", timeout=30000)
    pg.fill("#lk-first", "John"); pg.fill("#lk-last", "Smith"); pg.click("[data-action=lk-search][data-kind=individual]")
    pg.wait_for_selector("#lk-individual .npi-card", timeout=30000)
    shot(pg, "n03-npi-lookup-results")
    pg.locator("#lk-organization [data-npisel]").first.click(); pg.wait_for_timeout(300)
    pg.locator("#lk-individual [data-npisel]").first.click(); pg.wait_for_timeout(300)
    checks["selected_cards"] = pg.locator(".npi-card.on").count()
    shot(pg, "n04-npi-lookup-selected")
    pg.click("#next"); pg.wait_for_selector(".payer")
    pg.locator(".payer", has_text="Medicare Arizona Part B").first.locator("input[type=checkbox]").check(); pg.wait_for_timeout(200)
    pg.locator(".payer", has_text="Aetna").first.locator("input[type=checkbox]").check(); pg.wait_for_timeout(200)
    shot(pg, "n05-payers")
    pg.click("#next"); pg.wait_for_selector("[data-field='practice.legal_name']")
    checks["practice_prefilled_fields"] = pg.locator(".field.prefilled").count()
    checks["group_npi_prefilled"] = pg.locator("[data-field='practice.group_npi'].prefilled").count() == 1
    pg.click("[data-unsure='practice.tin']")  # skip TIN
    shot(pg, "n06-practice-prefilled")
    pg.locator("[data-field='practice.phone'] [data-action=edit-prefill]").click()
    pg.fill("[data-bind='practice.phone']", "(555) 010-0000")  # prospect updates to current
    pg.click("#next"); pg.wait_for_selector("[data-field='specialty.specialties']")
    pg.click("[data-choice='specialty.practice_stage'][data-value=existing]")
    pg.click("#next"); pg.wait_for_selector("#prov-list")
    checks["providers_from_registry"] = pg.locator("#prov-list .badge-ok").count()
    shot(pg, "n07-providers-prefilled")
    pg.click("#next"); pg.wait_for_selector("[data-multi='rcm.services']")
    pg.click("[data-multi='rcm.services'][data-value=credentialing]")
    pg.wait_for_timeout(1200); pg.reload(); pg.wait_for_selector("[data-multi='rcm.services']")
    checks["resume_ok"] = pg.get_attribute("[data-multi='rcm.services'][data-value=credentialing]", "aria-pressed") == "true"
    pg.click("#next"); pg.wait_for_selector("[data-field='contact.title']")
    checks["contact_name_collapsed"] = pg.locator("[data-field='contact.name'].prefilled").count() == 1
    pg.click("#skip"); pg.wait_for_selector("text=Here's what you shared")
    shot(pg, "n08-review")
    pg.click("[data-action=submit]"); pg.wait_for_selector("text=All set")
    shot(pg, "n09-thank-you", top=False)

    rp.click("#refresh"); rp.wait_for_timeout(1000); rp.locator("[data-view]").first.click(); rp.wait_for_selector("#detail:not(.hidden)")
    checks["rep_status"] = rp.inner_text("#detail .status")
    checks["rep_npi_rows"] = rp.locator("#detail h2:has-text('NPI registry') + table tbody tr").count()
    rp.locator("#detail h2:has-text('NPI registry')").scroll_into_view_if_needed(); rp.wait_for_timeout(500)
    rp.screenshot(path=f"{OUT}/{prefix}-n10-rep-npi-records.png", full_page=False)
    b.close()
print(json.dumps({"link": link, "checks": checks, "console_errors": errors}, indent=1))
