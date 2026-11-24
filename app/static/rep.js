(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const STATUS = { not_started: "Not started", in_progress: "In progress", submitted: "Submitted", expired: "Expired", revoked: "Revoked" };
  const STEPN = ["Welcome", "States", "Payers", "Practice", "Specialty", "Providers", "Billing", "Contact", "Review", "Done"];
  const fmt = (iso) => (iso ? new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "–");
  async function api(method, path, body) {
    const r = await fetch(path, { method, credentials: "same-origin", headers: body ? { "Content-Type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined });
    const d = await r.json().catch(() => ({}));
    if (r.status === 401 && path !== "/api/rep/login") { showLogin(); throw new Error("Please sign in."); }
    if (!r.ok) throw new Error(d.detail || "Request failed");
    return d;
  }
  function showLogin() { $("#login").classList.remove("hidden"); $("#dash").classList.add("hidden"); $("#logout").classList.add("hidden"); }
  let showDash = function () { $("#login").classList.add("hidden"); $("#dash").classList.remove("hidden"); $("#logout").classList.remove("hidden"); const n = localStorage.getItem("chs_rep_name"); if (n && !$("#i-rn").value) $("#i-rn").value = n; const e = localStorage.getItem("chs_rep_email"); if (e && !$("#i-re").value) $("#i-re").value = e; load(); };
  $("#login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try { await api("POST", "/api/rep/login", { password: $("#pw").value }); $("#pw").value = ""; showDash(); }
    catch (err) { $("#login-msg").textContent = err.message; }
  });
  $("#logout").addEventListener("click", async () => { await api("POST", "/api/rep/logout"); showLogin(); });
  $("#refresh").addEventListener("click", load);

  function copy(text, btn) {
    const done = () => { const o = btn.textContent; btn.textContent = "Copied ✓"; setTimeout(() => (btn.textContent = o), 1500); };
    if (navigator.clipboard) navigator.clipboard.writeText(text).then(done, () => fallback());
    else fallback();
    function fallback() { const t = document.createElement("textarea"); t.value = text; document.body.appendChild(t); t.select(); document.execCommand("copy"); t.remove(); done(); }
  }
  function emailBlock(inv) {
    const mail = `mailto:${encodeURIComponent(inv.prospect_email || "")}?subject=${encodeURIComponent(inv.email.subject)}&body=${encodeURIComponent(inv.email.body)}`;
    return `<div class="callout"><strong>Secure link</strong><div class="pre" id="lk">${esc(inv.link)}</div><div class="toolbar"><button class="btn btn-teal btn-small" data-copy="link" type="button">Copy link</button><button class="btn btn-ghost btn-small" data-copy="email" type="button">Copy email text</button><a class="btn btn-ghost btn-small" href="${esc(mail)}">Open in my email app</a></div></div>
      <h3>Email to send</h3><p class="muted">Subject: <strong>${esc(inv.email.subject)}</strong></p><div class="pre">${esc(inv.email.body)}</div>`;
  }
  let current = null;
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-copy],[data-view],[data-act]");
    if (!b) return;
    if (b.dataset.copy && current) copy(b.dataset.copy === "link" ? current.link : `Subject: ${current.email.subject}\n\n${current.email.body}`, b);
    if (b.dataset.view) view(+b.dataset.view);
    if (b.dataset.act) act(b.dataset.act, +b.dataset.id, b);
  });
  $("#invite-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = { prospect_name: $("#i-pn").value, prospect_email: $("#i-pe").value, practice_name: $("#i-pr").value, rep_name: $("#i-rn").value, rep_email: $("#i-re").value, expires_days: +$("#i-days").value, is_test: $("#i-test").checked };
    try {
      const inv = await api("POST", "/api/rep/invites", body);
      localStorage.setItem("chs_rep_name", body.rep_name); localStorage.setItem("chs_rep_email", body.rep_email);
      current = inv;
      $("#new-result").innerHTML = `<h2>Link ready for ${esc(inv.prospect_name)} 🎉</h2>` + emailBlock(inv);
      $("#new-result").classList.remove("hidden");
      ["#i-pn", "#i-pe", "#i-pr"].forEach((s) => ($(s).value = "")); $("#i-test").checked = false;
      load();
    } catch (err) { alert(err.message); }
  });
  async function load() {
    try {
      const d = await api("GET", "/api/rep/invites");
      if (!d.invites.length) { $("#list").innerHTML = `<p class="muted">No invites yet.</p>`; return; }
      $("#list").innerHTML = `<div class="tablewrap"><table class="inv"><thead><tr><th>Prospect</th><th>Status</th><th>Progress</th><th>States</th><th>Payers</th><th>Providers</th><th>Last activity</th><th>Expires</th><th></th></tr></thead><tbody>${d.invites.map((i) => `<tr>
        <td><strong>${esc(i.prospect_name)}</strong>${i.is_test ? '<span class="test-flag">TEST</span>' : ""}<br><span class="muted">${esc(i.practice_name || "")}</span><br><span class="muted">${esc(i.prospect_email || "")}</span><br><span class="muted">Rep: ${esc(i.rep_name)}</span></td>
        <td><span class="status ${i.status}">${STATUS[i.status] || i.status}</span></td>
        <td>${i.status === "submitted" ? "Done" : i.raw_status === "not_started" ? (i.opened_at ? "Opened" : "–") : esc(STEPN[i.current_step] || "")}</td>
        <td>${esc((i.states || []).join(", "))}</td><td>${i.payer_count || "–"}</td><td>${i.provider_count || "–"}</td>
        <td>${fmt(i.last_activity_at || i.opened_at)}</td><td>${fmt(i.expires_at)}</td>
        <td><button class="btn btn-ghost btn-small" data-view="${i.id}" type="button">View</button></td></tr>`).join("")}</tbody></table></div>`;
    } catch (e) { /* login shown */ }
  }
  const LBL = { new: "New practice", existing: "Established practice", solo: "Solo", group: "Group", in_person: "In person", telehealth: "Telehealth", both: "In person & telehealth", credentialing: "Credentialing", rcm: "Billing / RCM", consulting: "Consulting", in_house: "In-house staff", other_company: "Another billing company", none: "No billing yet", none_yet: "None yet", asap: "ASAP", "1-3m": "1–3 months", "3-6m": "3–6 months", "6m+": "6+ months", unsure: "Not sure", email: "Email", phone: "Phone call", text: "Text", video: "Video call", mornings: "Mornings", afternoons: "Afternoons", evenings: "Evenings", yes: "Yes", no: "No" };
  const L = (v) => (Array.isArray(v) ? v.map((x) => LBL[x] || x).join(", ") : LBL[v] || (v ?? ""));
  function kv(rows) { return `<dl class="kv">${rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v === undefined || v === null || v === "" || (Array.isArray(v) && !v.length) ? '<span class="muted">–</span>' : esc(L(v))}</dd>`).join("")}</dl>`; }
  async function view(id) {
    const inv = await api("GET", `/api/rep/invites/${id}`);
    current = inv;
    const a = inv.answers || {}, pr = a.practice || {}, sp = a.specialty || {}, pv = a.providers || {}, rc = a.rcm || {}, c = a.contact || {};
    const uns = (sec) => Object.entries((a[sec] || {}).unsure || {}).filter(([, v]) => v).map(([k]) => k);
    const addr = pr.address || {};
    const sel = Object.entries((a.payers || {}).selected || {});
    $("#detail").innerHTML = `<div class="toolbar"><h1 class="grow">${esc(inv.prospect_name)}${inv.is_test ? '<span class="test-flag">TEST</span>' : ""}</h1><span class="spacer"></span><span class="status ${inv.status}">${STATUS[inv.status]}</span></div>
      <p class="muted">${esc(inv.practice_name || "")} · created ${fmt(inv.created_at)} · submitted ${fmt(inv.submitted_at)} · expires ${fmt(inv.expires_at)}</p>
      <div class="toolbar"><a class="btn btn-ghost btn-small" href="/api/rep/invites/${id}/export.csv">Export CSV</a><a class="btn btn-ghost btn-small" href="/api/rep/invites/${id}/export.json">Export JSON</a><button class="btn btn-ghost btn-small" data-act="extend" data-id="${id}" type="button">Extend 30 days</button><button class="btn btn-ghost btn-small" data-act="revoke" data-id="${id}" type="button">Revoke link</button></div>
      <h2>States</h2>${kv([["States", a.states], ["Not sure", a.states_unsure ? "Yes" : ""]])}
      <h2>Payers (${sel.length})</h2>${sel.length ? `<table class="inv"><thead><tr><th>Payer</th><th>Group</th><th>Stedi ID</th><th>Already in network?</th></tr></thead><tbody>${sel.map(([k, p]) => `<tr><td>${esc(p.name)}</td><td>${esc(p.group)}</td><td>${esc(p.stedi_payer_id || "")}</td><td>${esc(L(p.in_network) || "–")}</td></tr>`).join("")}</tbody></table>` : '<p class="muted">None selected.</p>'}
      ${kv([["Other payers / notes", (a.payers || {}).other], ["Unsure about payers", (a.payers || {}).unsure ? "Yes" : ""]])}
      <h2>Practice</h2>${kv([["Legal name", pr.legal_name], ["DBA", pr.dba], ["Group NPI", pr.group_npi], ["Address", [addr.street, addr.city, addr.state, addr.zip].filter(Boolean).join(", ")], ["Marked not sure", uns("practice")]])}
      <dl class="kv"><dt>TIN / EIN</dt><dd id="tin-cell">${inv.tin_masked ? `${esc(inv.tin_masked)} <button class="btn btn-ghost btn-small" data-act="reveal" data-id="${id}" type="button">Reveal</button>` : '<span class="muted">–</span>'}</dd></dl>
      <h2>Specialty & setup</h2>${kv([["Specialties", sp.specialties], ["Stage", sp.practice_stage], ["Size", sp.practice_size], ["Care setting", sp.care_setting], ["Marked not sure", uns("specialty")]])}
      <h2>Providers</h2>${kv([["Count", pv.count]])}${(pv.list || []).length ? `<table class="inv"><thead><tr><th>Name</th><th>Credential</th><th>NPI</th><th>New to credentialing</th></tr></thead><tbody>${pv.list.map((p) => `<tr><td>${esc(p.name)}</td><td>${esc(p.credential)}</td><td>${esc(p.npi)}</td><td>${esc(L(p.new_to_credentialing || ""))}</td></tr>`).join("")}</tbody></table>` : ""}
      <h2>Billing & timing</h2>${kv([["Services", rc.services], ["Current billing", rc.billing_setup], ["EHR / PM", rc.ehr], ["Claims / month", rc.monthly_claims], ["Collections / month", rc.monthly_collections], ["Go-live", rc.go_live], ["Marked not sure", uns("rcm")]])}
      <h2>Contact</h2>${kv([["Name", c.name], ["Title", c.title], ["Email", c.email], ["Phone", c.phone], ["Preferred", c.method], ["Best time", c.best_time], ["Notes", c.notes]])}
      ${kv([["Steps skipped", Object.keys(a.skipped || {})]])}
      <h2>Resend</h2>${emailBlock(inv)}`;
    $("#detail").classList.remove("hidden");
    $("#detail").scrollIntoView({ behavior: "smooth" });
  }
  async function act(kind, id, b) {
    if (kind === "reveal") { if (!confirm("Reveal the full tax ID? This is logged.")) return; const r = await api("POST", `/api/rep/invites/${id}/reveal-tin`); $("#tin-cell").textContent = r.tin || "–"; return; }
    if (kind === "revoke" && !confirm("Revoke this link? The prospect won't be able to open it.")) return;
    await api("POST", `/api/rep/invites/${id}/${kind}`); await view(id); load();
  }
  function storageBanner(me) {
    if (!me || !me.storage_ephemeral || $("#storage-warn")) return;
    const d = document.createElement("div"); d.id = "storage-warn"; d.className = "warnings";
    d.textContent = "Heads up: this server is using temporary storage (no DATABASE_URL set). Invites and answers will be lost when it restarts. Connect the Render Postgres database before sending real links.";
    $("#dash").prepend(d);
  }
  const _show = showDash;
  showDash = function () { _show(); api("GET", "/api/rep/me").then(storageBanner, () => {}); };
  api("GET", "/api/rep/me").then(() => showDash(), showLogin);
})();
