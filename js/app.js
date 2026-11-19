/* ProPa prototype: contract-to-invoice control loop.
   Procurement team tags the agreed budget grid -> contract executed with the tagged grid
   -> vendor invoices only against tagged lines -> approver sees each bucket -> finance pays and reconciles.
   State lives in the browser (localStorage). Synthetic data only. */
(function () {
  'use strict';
  const G = window.ProPaGrid;
  const r2 = G.r2;
  const $ = s => document.querySelector(s);
  const cur = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' });
  const money = n => cur.format(r2(n || 0));
  const qty = n => r2(n).toLocaleString('en-US', { maximumFractionDigits: 2 });
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const today = () => new Date().toISOString().slice(0, 10);
  const thisMonth = () => new Date().toISOString().slice(0, 7);
  const stamp = iso => new Date(iso).toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
  const dateLabel = d => new Date(d + 'T00:00:00').toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });
  const monthLabel = m => { const [y, mo] = m.split('-'); return new Date(+y, +mo - 1, 1).toLocaleString('en-GB', { month: 'short', year: 'numeric' }); };

  /* ---------- state ---------- */
  const KEY = 'propa-contract-to-invoice-v1';
  function fresh() {
    return {
      contracts: [], invoices: [], log: [], invSeq: {}, blocked: {},
      ui: {
        tab: 'om', draft: null, qty: {}, period: thisMonth(), vendor: '', vendorContract: '', invoiceSel: '', financeContract: '', execOpen: '',
        form: { study: 'ONC-2026-017', title: 'Phase III NSCLC study', vendor: 'Meridian Clinical', agree: 'SOW-01, full-service', model: 'FSO' }
      }
    };
  }
  function load() {
    try { const t = localStorage.getItem(KEY); if (t) { const s = JSON.parse(t); const f = fresh(); return Object.assign(f, s, { ui: Object.assign(f.ui, s.ui || {}) }); } } catch (e) { /* storage unavailable */ }
    return fresh();
  }
  function save() { try { localStorage.setItem(KEY, JSON.stringify(S)); } catch (e) { /* storage unavailable */ } }
  let S = load();
  const ROLE = { om: 'Procurement team', vp: 'Vendor', ap: 'Approver', fi: 'Finance', sys: 'ProPa' };
  function log(role, text) { S.log.unshift({ t: new Date().toISOString(), role, text }); }

  /* ---------- derived figures ---------- */
  const contract = k => S.contracts.find(c => c.prefix === k);
  const lineOf = (c, id) => c.lines.find(l => l.id === id);
  function usage(c, lineId, exceptRef) {
    let aU = 0, pU = 0, aA = 0, pA = 0;
    for (const inv of S.invoices) {
      if (inv.contract !== c.prefix) continue;
      for (const l of inv.lines) {
        if (l.lineId !== lineId) continue;
        if (l.status === 'approved') { aU += l.units; aA += l.amount; }
        else if (l.status === 'pending' && inv.ref !== exceptRef) { pU += l.units; pA += l.amount; }
      }
    }
    return { aU: r2(aU), pU: r2(pU), aA: r2(aA), pA: r2(pA) };
  }
  const remainingUnits = (c, l, exceptRef) => { const u = usage(c, l.id, exceptRef); return r2(l.units - u.aU - u.pU); };
  const contractValue = c => r2(c.lines.reduce((s, l) => s + l.total, 0));
  const invTotal = inv => r2(inv.lines.reduce((s, l) => s + l.amount, 0));
  const invApproved = inv => r2(inv.lines.filter(l => l.status === 'approved').reduce((s, l) => s + l.amount, 0));
  const invDenied = inv => r2(inv.lines.filter(l => l.status === 'denied').reduce((s, l) => s + l.amount, 0));
  function invStatus(inv) {
    const s = inv.lines.map(l => l.status);
    if (s.includes('pending')) return s.some(x => x !== 'pending') ? 'in review' : 'awaiting approval';
    if (s.every(x => x === 'approved')) return 'approved';
    if (s.every(x => x === 'denied')) return 'rejected';
    return 'partly approved';
  }
  const statusChip = st => {
    const cls = { 'approved': 'good', 'paid': 'good', 'executed': 'good', 'rejected': 'bad', 'denied': 'bad', 'partly approved': 'warn', 'in review': 'warn', 'awaiting approval': 'info', 'pending': 'info', 'tagged': 'info', 'draft': 'mute' }[st] || 'mute';
    return `<span class="chip ${cls}">${esc(st)}</span>`;
  };

  /* ---------- shell ---------- */
  const TABS = [['om', 'Procurement team', 'Sponsor'], ['vp', 'Vendor portal', 'CRO or vendor'], ['ap', 'Approver', 'Sponsor PM'], ['fi', 'Finance', 'Payables and reconciliation'], ['log', 'Audit log', 'Everyone']];
  function renderTabs() {
    $('#tabs').innerHTML = TABS.map(([k, label, who]) =>
      `<button data-tab="${k}" class="${S.ui.tab === k ? 'on' : ''}"><span>${label}</span><small>${who}</small></button>`).join('');
  }
  function renderProgress() {
    const c = S.contracts[S.contracts.length - 1];
    const inv = S.invoices.filter(i => !c || i.contract === c.prefix);
    const steps = [
      ['Draft run in ProPa', !!(S.ui.draft || S.contracts.length)],
      ['IDs locked', S.contracts.length > 0],
      ['Contract executed', S.contracts.some(x => x.status === 'executed')],
      ['Invoice raised in portal', inv.length > 0],
      ['Approver decided', inv.some(i => i.lines.some(l => l.status !== 'pending'))],
      ['Paid and reconciled', inv.some(i => i.paid > 0)]
    ];
    const next = steps.findIndex(s => !s[1]);
    $('#progress').innerHTML = steps.map((s, i) =>
      `<div class="step ${s[1] ? 'done' : (i === next ? 'now' : '')}"><span class="dot">${s[1] ? '&#10003;' : i + 1}</span>${s[0]}</div>`).join('');
  }
  function head(title, sub) { return `<div class="vhead"><h1>${title}</h1><p>${sub}</p></div>`; }
  function render() {
    renderTabs(); renderProgress();
    const V = { om: vOM, vp: vVendor, ap: vApprover, fi: vFinance, log: vLog }[S.ui.tab] || vOM;
    $('#view').innerHTML = V();
    save();
  }
  let toastTimer;
  function toast(msg) {
    const t = $('#toast'); t.textContent = msg; t.classList.add('show');
    clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove('show'), 3200);
  }
  function download(name, rows) {
    const csv = rows.map(r => r.map(v => { const s = v == null ? '' : String(v); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; }).join(',')).join('\r\n');
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
    a.download = name; document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  }

  /* ---------- 1. procurement team ---------- */
  function vOM() {
    const f = S.ui.form;
    const field = (k, label, ph) => `<label class="fld"><span>${label}</span><input data-field="${k}" id="om-${k}" value="${esc(f[k])}" placeholder="${ph || ''}"></label>`;
    let html = head('Run the agreed draft contract',
      'Once both parties agree to go for signature, run the draft through ProPa. It finds the budget grid, gives every line item a Digital Contract ID and locks the grid, so the contract is executed with the IDs in it.');
    html += `<section class="card"><h2>Draft contract <small>FSO, FSP or hybrid: any agreement with a budget grid</small></h2>
      <div class="grid4">${field('study', 'Study')}${field('title', 'Study title')}${field('vendor', 'Vendor')}${field('agree', 'Agreement')}</div>
      <div class="row gap">
        <label class="fld"><span>Outsourcing model</span><select data-field="model" id="om-model">${['FSO', 'FSP', 'Hybrid'].map(m => `<option ${f.model === m ? 'selected' : ''}>${m}</option>`).join('')}</select></label>
        <label class="fld grow"><span>Budget grid from the draft (.xlsx, .xls or .csv)</span><input type="file" id="om-file" accept=".xlsx,.xls,.csv"></label>
      </div>
      <div class="row gap mt"><button class="btn primary" data-act="run">Run draft contract</button><button class="btn" data-act="sample">Use the sample draft</button><span class="hint">The sample uses the same layout as a typical CRO budget grid: sections, unit type, unit price, number of units, total.</span></div>
      <div class="err" id="om-err" role="alert"></div></section>`;
    if (S.ui.draft) html += draftCard(S.ui.draft);
    html += contractsCard();
    return html;
  }

  function draftCard(d) {
    const p = d.parsed;
    const totalNote = p.declared == null ? 'No total row in the grid'
      : Math.abs(p.declared - p.sum) <= 0.01 ? `<span class="okc">&#10003; Matches the grid's total row</span>` : `<span class="badc">Differs from the grid's total row</span>`;
    const rows = p.lines.map(l => `<tr><td class="id strong">${esc(l.id)}</td><td class="muted">${esc(l.section)}</td><td>${esc(l.desc)}</td><td>${esc(l.unitType)}</td>
      <td class="num">${money(l.price)}</td><td class="num">${qty(l.units)}</td><td class="num">${money(l.total)}</td><td class="num muted">${l.row}</td></tr>`).join('');
    const warn = p.warnings.length ? `<div class="warnbox"><b>${p.warnings.length} item${p.warnings.length > 1 ? 's' : ''} to review before locking</b><ul>${p.warnings.map(w => `<li>${w.row ? 'Row ' + w.row + ': ' : ''}${esc(w.msg)}</li>`).join('')}</ul>
      <label class="check"><input type="checkbox" id="om-ack"> I have reviewed these items</label></div>` : '';
    return `<section class="card accent" id="draft-card"><h2>Grid found and tagged <small>${esc(d.source)}</small></h2>
      <div class="facts">
        <div><span>Location</span><b>Sheet "${esc(p.sheet)}", header row ${p.headerRow}</b></div>
        <div><span>Found</span><b>${p.sections.length} sections, ${p.lines.length} line items</b></div>
        <div><span>Contract value</span><b>${money(p.sum)}</b><em>${totalNote}</em></div>
        <div><span>Grid fingerprint</span><b class="mono">${d.fingerprint}</b></div>
      </div>${warn}
      <div class="tablewrap"><table><thead><tr><th>Digital Contract ID</th><th>Section</th><th>Task description</th><th>Unit type</th><th class="num">Unit price</th><th class="num">Units</th><th class="num">Total</th><th class="num">Source row</th></tr></thead><tbody>${rows}</tbody></table></div>
      <div class="row gap mt"><button class="btn primary" data-act="lock">Confirm and lock IDs</button><button class="btn" data-act="discard">Discard</button>
      <span class="hint">Check that the lines and total match the agreed budget. Locked IDs cannot change; an amendment adds new versions.</span></div>
      <div class="err" id="lock-err" role="alert"></div></section>`;
  }

  function contractsCard() {
    if (!S.contracts.length) return `<section class="card"><h2>Contracts in ProPa</h2><p class="empty">No contracts yet. Run a draft contract above.</p></section>`;
    const rows = S.contracts.slice().reverse().map(c => {
      const open = S.ui.execOpen === c.prefix && c.status === 'tagged';
      const actions = `<button class="btn sm" data-act="dlgrid" data-k="${c.prefix}">Download tagged grid</button>` +
        (c.status === 'tagged' ? ` <button class="btn sm primary" data-act="execopen" data-k="${c.prefix}">Record execution</button>` : '');
      let tr = `<tr><td class="id strong">${esc(c.prefix)}</td><td>${esc(c.study)}<div class="muted sm">${esc(c.title)}</div></td><td>${esc(c.vendor)}<div class="muted sm">${esc(c.agree)} &middot; ${esc(c.model)}</div></td>
        <td class="num">${c.lines.length}</td><td class="num">${money(contractValue(c))}</td><td>${statusChip(c.status)}${c.executedOn ? `<div class="muted sm">${dateLabel(c.executedOn)}</div>` : ''}</td><td class="actions">${actions}</td></tr>`;
      if (open) tr += `<tr class="expand"><td colspan="7">${execPanel(c)}</td></tr>`;
      return tr;
    }).join('');
    return `<section class="card"><h2>Contracts in ProPa</h2><div class="tablewrap"><table><thead><tr><th>ID prefix</th><th>Study</th><th>Vendor and agreement</th><th class="num">Lines</th><th class="num">Value</th><th>Status</th><th></th></tr></thead><tbody>${rows}</tbody></table></div></section>`;
  }

  function execPanel(c) {
    const v = c.verify;
    const vmsg = !v ? '<span class="muted">Optional: upload the executed copy\'s budget grid to confirm nothing changed after tagging.</span>'
      : v.ok ? `<span class="okc">&#10003; ${esc(v.name)} matches the tagged grid line for line.</span>`
        : `<div class="warnbox"><b>${esc(v.name)} does not match the tagged grid. Re-run the executed version before recording execution.</b><ul>${v.diffs.slice(0, 6).map(x => `<li>${esc(x)}</li>`).join('')}</ul></div>`;
    return `<div class="exec"><h3>Record execution of ${esc(c.agree)} with ${esc(c.vendor)}</h3>
      <div class="row gap">
        <label class="fld"><span>Execution date</span><input type="date" id="exec-date" value="${today()}"></label>
        <label class="fld grow"><span>Executed copy's budget grid (optional check)</span><input type="file" id="exec-file" data-change="verify" data-k="${c.prefix}" accept=".xlsx,.xls,.csv"></label>
      </div>
      <div class="mt">${vmsg}</div>
      <label class="check mt"><input type="checkbox" id="exec-ok"> The executed contract contains this tagged grid (fingerprint <span class="mono">${c.fingerprint}</span>)</label>
      <div class="row gap mt"><button class="btn primary" data-act="execute" data-k="${c.prefix}" ${v && !v.ok ? 'disabled' : ''}>Mark as executed</button><button class="btn" data-act="execclose">Cancel</button></div>
      <div class="err" id="exec-err" role="alert"></div></div>`;
  }

  function prefixFor(study, vendor) {
    const digits = (String(study).match(/\d+/g) || ['000']).pop().slice(-3).padStart(3, '0');
    const initials = String(vendor).split(/\s+/).filter(Boolean).map(w => w[0]).join('').toUpperCase().replace(/[^A-Z]/g, '').slice(0, 3) || 'V';
    let p = digits + initials, n = 2;
    while (contract(p)) p = digits + initials + n++;
    return p;
  }

  function startDraft(parsed, source) {
    const f = S.ui.form;
    const err = $('#om-err');
    if (!parsed.ok) { err.textContent = parsed.error; return; }
    const prefix = prefixFor(f.study, f.vendor);
    G.assignIds(parsed.lines, prefix);
    S.ui.draft = { prefix, source, parsed, fingerprint: G.fingerprint(parsed.lines), study: f.study.trim(), title: f.title.trim(), vendor: f.vendor.trim(), agree: f.agree.trim(), model: f.model };
    log('om', `Ran draft ${f.agree.trim()} (${source}) for ${f.study.trim()} with ${f.vendor.trim()}: ${parsed.lines.length} lines found and tagged ${prefix}.`);
    render();
    const card = $('#draft-card'); if (card) card.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
  function checkForm() {
    const f = S.ui.form, err = $('#om-err');
    if (!f.study.trim() || !f.vendor.trim() || !f.agree.trim()) { err.textContent = 'Enter the study, vendor and agreement first.'; return false; }
    err.textContent = ''; return true;
  }

  /* ---------- 2. vendor portal ---------- */
  function vVendor() {
    const exec = S.contracts.filter(c => c.status === 'executed');
    let html = head('Raise an invoice', 'Vendors invoice inside ProPa, against the lines of their executed contract. Unit prices come from the contract, and no line can be billed beyond what is left on it.');
    if (!exec.length) return html + `<section class="card"><p class="empty">No executed contracts yet. The procurement team runs the draft, locks the IDs and records execution first.</p></section>`;
    const vendors = [...new Set(exec.map(c => c.vendor))];
    if (!vendors.includes(S.ui.vendor)) S.ui.vendor = vendors[0];
    const mine = exec.filter(c => c.vendor === S.ui.vendor);
    if (!mine.some(c => c.prefix === S.ui.vendorContract)) S.ui.vendorContract = mine[0].prefix;
    const c = contract(S.ui.vendorContract);
    const q = S.ui.qty[c.prefix] || {};
    const seq = (S.invSeq[c.prefix] || 0) + 1;
    const rows = c.lines.map(l => {
      const u = usage(c, l.id), rem = r2(l.units - u.aU - u.pU);
      const v = q[l.id] || '';
      const chk = checkQty(c, l, v);
      return `<tr class="${chk.ok ? '' : 'rowerr'}"><td class="id strong">${esc(l.id)}</td><td>${esc(l.desc)}<div class="muted sm">${esc(l.section)}</div></td><td>${esc(l.unitType)}</td>
        <td class="num">${money(l.price)} <span class="lock" title="Set by the contract">&#128274;</span></td><td class="num">${qty(l.units)}</td><td class="num">${qty(u.aU + u.pU)}</td>
        <td class="num strong" id="rem-${l.id}">${qty(rem)}</td>
        <td class="num"><input class="qty" inputmode="decimal" data-line="${l.id}" id="q-${l.id}" value="${esc(v)}" placeholder="0" aria-label="Units of ${esc(l.desc)} this invoice" ${rem <= 0 ? 'disabled' : ''}></td>
        <td class="num" id="amt-${l.id}">${chk.units ? money(chk.units * l.price) : '&mdash;'}</td></tr>
        <tr class="errrow" id="er-${l.id}" ${chk.ok ? 'hidden' : ''}><td colspan="9">${esc(chk.msg || '')}</td></tr>`;
    }).join('');
    html += `<section class="card"><div class="row gap">
        <label class="fld"><span>Signed in as</span><select data-change="vendor" id="vp-vendor">${vendors.map(v => `<option ${v === S.ui.vendor ? 'selected' : ''}>${esc(v)}</option>`).join('')}</select></label>
        <label class="fld grow"><span>Contract</span><select data-change="vcontract" id="vp-contract">${mine.map(x => `<option value="${x.prefix}" ${x.prefix === c.prefix ? 'selected' : ''}>${esc(x.study)} &middot; ${esc(x.agree)} (${x.prefix})</option>`).join('')}</select></label>
        <label class="fld"><span>Service period</span><input type="month" id="vp-period" data-field-ui="period" value="${esc(S.ui.period)}"></label>
      </div>
      <div class="facts mt"><div><span>New invoice</span><b class="mono">INV-${c.prefix}-${String(seq).padStart(3, '0')}</b></div><div><span>Study</span><b>${esc(c.study)}</b></div><div><span>Contract</span><b>${esc(c.agree)}, executed ${dateLabel(c.executedOn)}</b></div><div><span>This invoice</span><b id="vp-total">${money(draftTotal(c))}</b></div></div>
      <div class="tablewrap mt"><table><thead><tr><th>Digital Contract ID</th><th>Task description</th><th>Unit type</th><th class="num">Unit price</th><th class="num">Contracted</th><th class="num">Billed so far</th><th class="num">Remaining</th><th class="num">Units this invoice</th><th class="num">Amount</th></tr></thead><tbody>${rows}</tbody></table></div>
      <div class="row gap mt"><button class="btn primary" data-act="submit">Submit invoice to sponsor</button><span class="hint">Work outside these lines cannot be invoiced here. Ask the sponsor for a change order, which adds new tagged lines.</span></div>
      <div class="err" id="vp-err" role="alert"></div></section>`;
    html += vendorHistory();
    return html;
  }
  function checkQty(c, l, raw, exceptRef) {
    const s = String(raw == null ? '' : raw).trim();
    if (!s) return { ok: true, units: 0 };
    if (!/^\d*\.?\d+$/.test(s)) return { ok: false, units: 0, msg: 'Enter a number of units, 0 or more.' };
    if ((s.split('.')[1] || '').length > 2) return { ok: false, units: 0, msg: 'Use at most two decimal places.' };
    const n = Number(s), rem = remainingUnits(c, l, exceptRef);
    if (n > rem + 1e-9) return { ok: false, units: 0, over: true, msg: `Only ${qty(rem)} ${l.unitType || 'units'} remain on ${l.id}. Billing more needs an approved change order.` };
    return { ok: true, units: n };
  }
  function draftTotal(c) {
    const q = S.ui.qty[c.prefix] || {};
    return r2(c.lines.reduce((s, l) => { const k = checkQty(c, l, q[l.id]); return s + (k.ok ? k.units * l.price : 0); }, 0));
  }
  function vendorHistory() {
    const inv = S.invoices.filter(i => i.vendor === S.ui.vendor).slice().reverse();
    if (!inv.length) return `<section class="card"><h2>My invoices</h2><p class="empty">No invoices submitted yet.</p></section>`;
    return `<section class="card"><h2>My invoices <small>decisions and reasons are visible to the vendor</small></h2>${inv.map(i => {
      const c = contract(i.contract);
      return `<div class="hist"><div class="row between"><div><b class="mono">${i.ref}</b> &middot; ${esc(c.study)} &middot; ${monthLabel(i.period)}</div><div>${money(invTotal(i))} ${statusChip(i.paid > 0 ? 'paid' : invStatus(i))}</div></div>
        <ul>${i.lines.map(l => `<li><span class="mono">${l.lineId}</span> ${esc(lineOf(c, l.lineId).desc)}: ${qty(l.units)} &times; ${money(l.price)} = ${money(l.amount)} ${statusChip(l.status)}${l.reason ? ` <span class="muted">&ldquo;${esc(l.reason)}&rdquo;</span>` : ''}</li>`).join('')}</ul></div>`;
    }).join('')}</section>`;
  }

  /* ---------- 3. approver ---------- */
  function vApprover() {
    let html = head('Approve or deny', 'Every invoice arrives already matched to its study, contract and line items. For each line, the approver sees what the contract allows, what has been billed and what will be left.');
    if (!S.invoices.length) return html + `<section class="card"><p class="empty">No invoices yet. Vendors raise them in the vendor portal.</p></section>`;
    const order = S.invoices.slice().sort((a, b) => {
      const pa = a.lines.some(l => l.status === 'pending') ? 0 : 1, pb = b.lines.some(l => l.status === 'pending') ? 0 : 1;
      return pa - pb || b.submittedAt.localeCompare(a.submittedAt);
    });
    if (!S.invoices.some(i => i.ref === S.ui.invoiceSel)) S.ui.invoiceSel = order[0].ref;
    const queue = order.map(i => {
      const c = contract(i.contract);
      return `<button class="qitem ${i.ref === S.ui.invoiceSel ? 'sel' : ''}" data-act="pick" data-ref="${i.ref}"><div class="row between"><b class="mono">${i.ref}</b>${statusChip(i.paid > 0 ? 'paid' : invStatus(i))}</div>
        <div class="muted sm">${esc(i.vendor)} &middot; ${esc(c.study)} &middot; ${monthLabel(i.period)}</div><div class="strong">${money(invTotal(i))}</div></button>`;
    }).join('');
    return html + `<div class="split"><aside class="card queue"><h2>Invoice queue</h2>${queue}</aside><section class="card">${invoiceDetail(S.invoices.find(i => i.ref === S.ui.invoiceSel))}</section></div>`;
  }
  function autoChecks(inv, c) {
    const allIds = inv.lines.every(l => !!lineOf(c, l.lineId));
    const prices = inv.lines.every(l => lineOf(c, l.lineId) && lineOf(c, l.lineId).price === l.price);
    const within = inv.lines.filter(l => l.status === 'pending').every(l => l.units <= remainingUnits(c, lineOf(c, l.lineId), inv.ref) + 1e-9);
    return [
      [true, `Raised in the ProPa portal against ${c.agree} (${c.prefix}), study ${c.study}`],
      [c.status === 'executed', `Contract executed ${c.executedOn ? dateLabel(c.executedOn) : ''}, grid fingerprint ${c.fingerprint}`],
      [allIds, 'Every line carries a Digital Contract ID from the executed grid'],
      [prices, 'Unit prices are the contracted prices'],
      [within, 'No line exceeds what is left on its contract line']
    ];
  }
  function invoiceDetail(inv) {
    const c = contract(inv.contract);
    const checks = autoChecks(inv, c).map(([ok, t]) => `<li class="${ok ? 'ok' : 'no'}">${ok ? '&#10003;' : '&#10007;'} ${esc(t)}</li>`).join('');
    const pending = inv.lines.filter(l => l.status === 'pending').length;
    const lines = inv.lines.map((l, i) => {
      const cl = lineOf(c, l.lineId);
      const u = usage(c, l.lineId, inv.ref);
      const thisAmt = l.status === 'approved' ? 0 : (l.status === 'pending' ? l.amount : 0);
      const approvedOther = l.status === 'approved' ? r2(u.aA - l.amount) : u.aA;
      const left = r2(cl.total - u.aA - u.pA - thisAmt);
      const pct = x => Math.max(0, Math.min(100, x / cl.total * 100));
      const bar = `<div class="bar"><i class="b-app" style="width:${pct(approvedOther)}%"></i><i class="b-pen" style="width:${pct(u.pA)}%"></i><i class="b-this ${l.status}" style="width:${pct(l.amount)}%"></i></div>`;
      const decision = l.status === 'pending'
        ? `<div class="decide"><input id="ap-reason-${i}" class="reason" placeholder="Reason (required to deny)" aria-label="Reason for ${esc(l.lineId)}">
            <div class="row gap"><button class="btn sm good" data-act="approve" data-i="${i}">Approve</button><button class="btn sm bad" data-act="deny" data-i="${i}">Deny</button></div><div class="err" id="ap-err-${i}" role="alert"></div></div>`
        : `${statusChip(l.status)}${l.reason ? `<div class="muted sm">&ldquo;${esc(l.reason)}&rdquo;</div>` : ''}<div class="muted sm">${stamp(l.decidedAt)}</div>`;
      return `<tr><td><b class="mono">${l.lineId}</b><div>${esc(cl.desc)}</div><div class="muted sm">${qty(l.units)} ${esc(cl.unitType)} &times; ${money(l.price)}</div></td>
        <td class="num strong">${money(l.amount)}</td>
        <td><div class="bucket"><span>Contracted <b>${money(cl.total)}</b></span><span>Approved before <b>${money(approvedOther)}</b></span>${u.pA ? `<span>Other pending <b>${money(u.pA)}</b></span>` : ''}<span>Left after <b class="${left < 0 ? 'badc' : ''}">${money(left)}</b></span></div>${bar}</td>
        <td>${decision}</td></tr>`;
    }).join('');
    return `<div class="row between"><div><h2 class="mono">${inv.ref}</h2><div class="muted">${esc(inv.vendor)} &middot; ${esc(c.study)}, ${esc(c.title)} &middot; ${esc(c.agree)} &middot; service period ${monthLabel(inv.period)} &middot; submitted ${stamp(inv.submittedAt)}</div></div>
      <div class="big">${money(invTotal(inv))}</div></div>
      <div class="checks"><h3>Verified automatically</h3><ul>${checks}</ul></div>
      <div class="tablewrap"><table class="lines"><thead><tr><th>Line</th><th class="num">This invoice</th><th>Contract line balance</th><th>Decision</th></tr></thead><tbody>${lines}</tbody></table></div>
      <div class="legend"><span><i class="b-app"></i>approved before</span><span><i class="b-pen"></i>other pending</span><span><i class="b-this pending"></i>this invoice</span></div>
      ${pending ? `<div class="row gap mt"><button class="btn good" data-act="approveall">Approve all ${pending} pending line${pending > 1 ? 's' : ''}</button><span class="hint">Approved lines go to finance for payment with this evidence attached.</span></div>` : `<p class="mt">${statusChip(invStatus(inv))} Review complete. ${inv.paid > 0 ? 'Paid by finance.' : 'With finance for payment.'}</p>`}`;
  }

  /* ---------- 4. finance ---------- */
  function vFinance() {
    let html = head('Pay and reconcile', 'Finance pays what approvers approved and sees every contract line\'s balance at any moment, so reconciliation is a view rather than a project.');
    const cs = S.contracts.filter(c => c.status === 'executed');
    if (!cs.length) return html + `<section class="card"><p class="empty">No executed contracts yet.</p></section>`;
    if (!cs.some(c => c.prefix === S.ui.financeContract)) S.ui.financeContract = cs[cs.length - 1].prefix;
    const c = contract(S.ui.financeContract);
    const inv = S.invoices.filter(i => i.contract === c.prefix);
    const value = contractValue(c);
    const approved = r2(inv.reduce((s, i) => s + invApproved(i), 0));
    const paid = r2(inv.reduce((s, i) => s + (i.paid || 0), 0));
    const pending = r2(inv.reduce((s, i) => s + i.lines.filter(l => l.status === 'pending').reduce((a, l) => a + l.amount, 0), 0));
    const remaining = r2(value - approved - pending);
    const overLines = c.lines.filter(l => { const u = usage(c, l.id); return u.aU + u.pU > l.units + 1e-9; }).length;
    const lineRows = c.lines.map(l => {
      const u = usage(c, l.id), rem = r2(l.total - u.aA - u.pA), used = (u.aA + u.pA) / l.total * 100;
      return `<tr><td class="id strong">${l.id}</td><td>${esc(l.desc)}<div class="muted sm">${esc(l.section)}</div></td><td class="num">${money(l.total)}</td><td class="num">${money(u.aA)}</td><td class="num">${u.pA ? money(u.pA) : '&mdash;'}</td><td class="num strong">${money(rem)}</td>
        <td><div class="bar small"><i class="b-app" style="width:${Math.min(100, u.aA / l.total * 100)}%"></i><i class="b-pen" style="width:${Math.min(100, u.pA / l.total * 100)}%"></i></div><div class="muted sm">${used.toFixed(0)}% used</div></td></tr>`;
    }).join('');
    const invRows = inv.length ? inv.slice().reverse().map(i => {
      const st = invStatus(i), ap = invApproved(i), open = st !== 'awaiting approval' && st !== 'in review';
      const pay = i.paid > 0 ? `<span class="okc">Paid ${dateLabel(i.paidOn)}</span>` : (open && ap > 0 ? `<button class="btn sm primary" data-act="pay" data-ref="${i.ref}">Record payment of ${money(ap)}</button>` : (open ? 'Nothing to pay' : '<span class="muted">Awaiting approver</span>'));
      return `<tr><td class="mono strong">${i.ref}</td><td>${monthLabel(i.period)}</td><td class="num">${money(invTotal(i))}</td><td class="num">${money(ap)}</td><td class="num">${invDenied(i) ? money(invDenied(i)) : '&mdash;'}</td><td>${statusChip(i.paid > 0 ? 'paid' : st)}</td><td>${pay}</td></tr>`;
    }).join('') : `<tr><td colspan="7" class="empty">No invoices on this contract yet.</td></tr>`;
    html += `<section class="card"><div class="row gap"><label class="fld grow"><span>Contract</span><select data-change="fcontract" id="fi-contract">${cs.map(x => `<option value="${x.prefix}" ${x.prefix === c.prefix ? 'selected' : ''}>${esc(x.study)} &middot; ${esc(x.vendor)} &middot; ${esc(x.agree)} (${x.prefix})</option>`).join('')}</select></label>
      <button class="btn" data-act="export">Download reconciliation (CSV)</button></div>
      <div class="tiles mt">
        <div class="tile"><span>Contract value</span><b>${money(value)}</b></div>
        <div class="tile"><span>Approved</span><b>${money(approved)}</b><em>${money(paid)} paid</em></div>
        <div class="tile"><span>Awaiting approval</span><b>${money(pending)}</b></div>
        <div class="tile"><span>Remaining on contract</span><b>${money(remaining)}</b></div>
        <div class="tile ${overLines ? 'bad' : 'good'}"><span>Lines billed above contract</span><b>${overLines}</b><em>${S.blocked[c.prefix] || 0} over-billing attempt${(S.blocked[c.prefix] || 0) === 1 ? '' : 's'} blocked at source</em></div>
      </div>
      <p class="recon">${money(value)} contracted = ${money(paid)} paid + ${money(r2(approved - paid))} approved, not yet paid + ${money(pending)} awaiting approval + ${money(remaining)} remaining <span class="okc">&#10003; reconciles</span></p></section>
      <section class="card"><h2>Invoices <small>${esc(c.vendor)}</small></h2><div class="tablewrap"><table><thead><tr><th>Invoice</th><th>Period</th><th class="num">Invoiced</th><th class="num">Approved</th><th class="num">Denied</th><th>Status</th><th>Payment</th></tr></thead><tbody>${invRows}</tbody></table></div></section>
      <section class="card"><h2>Contract line balances <small>${esc(c.agree)}, fingerprint ${c.fingerprint}</small></h2><div class="tablewrap"><table><thead><tr><th>Digital Contract ID</th><th>Task description</th><th class="num">Contracted</th><th class="num">Approved</th><th class="num">Awaiting</th><th class="num">Remaining</th><th>Used</th></tr></thead><tbody>${lineRows}</tbody></table></div></section>`;
    return html;
  }

  /* ---------- 5. audit log ---------- */
  function vLog() {
    const html = head('Audit log', 'Every run, lock, execution, invoice, decision and payment, with who did it and when.');
    if (!S.log.length) return html + `<section class="card"><p class="empty">Nothing has happened yet.</p></section>`;
    return html + `<section class="card"><div class="tablewrap"><table><thead><tr><th>When</th><th>Who</th><th>What happened</th></tr></thead><tbody>${S.log.map(e => `<tr><td class="nowrap muted">${stamp(e.t)}</td><td class="nowrap">${ROLE[e.role] || e.role}</td><td>${esc(e.text)}</td></tr>`).join('')}</tbody></table></div></section>`;
  }

  /* ---------- actions ---------- */
  function decide(inv, i, ok, reason) {
    const l = inv.lines[i], c = contract(inv.contract);
    if (l.status !== 'pending') return true;
    if (!ok && !reason) { const e = $('#ap-err-' + i); if (e) e.textContent = 'Enter a reason for the vendor before denying.'; const r = $('#ap-reason-' + i); if (r) r.focus(); return false; }
    if (ok && l.units > remainingUnits(c, lineOf(c, l.lineId), inv.ref) + 1e-9) { const e = $('#ap-err-' + i); if (e) e.textContent = 'This line now exceeds what is left on the contract line. It needs a change order.'; return false; }
    l.status = ok ? 'approved' : 'denied'; l.reason = reason || ''; l.decidedAt = new Date().toISOString();
    log('ap', `${ok ? 'Approved' : 'Denied'} ${inv.ref} line ${l.lineId} (${money(l.amount)})${reason ? ': "' + reason + '"' : ''}.`);
    return true;
  }

  const ACT = {
    run() {
      if (!checkForm()) return;
      const file = $('#om-file').files[0];
      if (!file) { $('#om-err').textContent = 'Choose the budget grid file from the draft contract, or use the sample draft.'; return; }
      G.readFile(file).then(p => startDraft(p, file.name)).catch(e => { $('#om-err').textContent = e.message; });
    },
    sample() {
      if (!checkForm()) return;
      startDraft(G.parseRows(JSON.parse(JSON.stringify(window.PROPA_SAMPLE.rows)), 'Budget'), window.PROPA_SAMPLE.name);
    },
    discard() { S.ui.draft = null; render(); },
    lock() {
      const d = S.ui.draft; if (!d) return;
      const ack = $('#om-ack');
      if (ack && !ack.checked) { $('#lock-err').textContent = 'Review the flagged items and tick the box before locking the IDs.'; return; }
      S.contracts.push({ prefix: d.prefix, study: d.study, title: d.title, vendor: d.vendor, agree: d.agree, model: d.model, source: d.source,
        lines: d.parsed.lines.map(({ id, section, desc, unitType, price, units, total, row }) => ({ id, section, desc, unitType, price, units, total, row })),
        fingerprint: d.fingerprint, status: 'tagged', taggedAt: new Date().toISOString(), executedOn: null, verify: null });
      log('om', `Locked ${d.parsed.lines.length} Digital Contract IDs for ${d.agree} (${d.prefix}), value ${money(d.parsed.sum)}, fingerprint ${d.fingerprint}.`);
      S.ui.draft = null; S.ui.execOpen = d.prefix; render(); toast('IDs locked. Record execution once the contract is signed.');
    },
    dlgrid(el) {
      const c = contract(el.dataset.k);
      const rows = [[`ProPa tagged budget grid`], [`Study`, c.study], [`Vendor`, c.vendor], [`Agreement`, c.agree], [`Grid fingerprint`, c.fingerprint], [],
        ['Digital Contract ID', 'Section', 'Task Description', 'Unit type', 'Unit price', 'No. of Units', 'Total costs']]
        .concat(c.lines.map(l => [l.id, l.section, l.desc, l.unitType, l.price.toFixed(2), l.units, l.total.toFixed(2)]))
        .concat([[], ['', '', 'Total', '', '', '', contractValue(c).toFixed(2)]]);
      download(`${c.prefix}_tagged_budget_grid.csv`, rows);
      log('om', `Downloaded the tagged grid for ${c.prefix} for the contract's budget appendix.`); save();
    },
    execopen(el) { S.ui.execOpen = el.dataset.k; render(); },
    execclose() { S.ui.execOpen = ''; render(); },
    execute(el) {
      const c = contract(el.dataset.k), date = $('#exec-date').value, ok = $('#exec-ok').checked, err = $('#exec-err');
      if (!date) { err.textContent = 'Enter the execution date.'; return; }
      if (!ok) { err.textContent = 'Confirm that the executed contract contains this tagged grid.'; return; }
      if (c.verify && !c.verify.ok) { err.textContent = 'The executed copy does not match the tagged grid.'; return; }
      c.status = 'executed'; c.executedOn = date; S.ui.execOpen = '';
      log('om', `Recorded execution of ${c.agree} (${c.prefix}) on ${dateLabel(date)}${c.verify ? ', executed copy checked against the tagged grid' : ''}. Invoicing opened to ${c.vendor}.`);
      render(); toast(`Contract executed. ${c.vendor} can now invoice against its ${c.lines.length} lines.`);
    },
    submit() {
      const c = contract(S.ui.vendorContract), q = S.ui.qty[c.prefix] || {}, err = $('#vp-err');
      const period = $('#vp-period').value;
      if (!period) { err.textContent = 'Choose the service period.'; return; }
      const checks = c.lines.map(l => [l, checkQty(c, l, q[l.id])]);
      const bad = checks.filter(([, k]) => !k.ok);
      if (bad.length) {
        if (bad.some(([, k]) => k.over)) {
          S.blocked[c.prefix] = (S.blocked[c.prefix] || 0) + 1;
          log('sys', `Blocked an invoice from ${c.vendor} on ${c.prefix}: ${bad.filter(([, k]) => k.over).map(([l]) => l.id).join(', ')} above the remaining contract units.`); save();
        }
        err.textContent = `Fix ${bad.length} line${bad.length > 1 ? 's' : ''} before submitting.`;
        const f = $('#q-' + bad[0][0].id); if (f) f.focus();
        return;
      }
      const lines = checks.filter(([, k]) => k.units > 0).map(([l, k]) => ({ lineId: l.id, units: k.units, price: l.price, amount: r2(k.units * l.price), status: 'pending', reason: '', decidedAt: null }));
      if (!lines.length) { err.textContent = 'Enter units on at least one line.'; return; }
      S.invSeq[c.prefix] = (S.invSeq[c.prefix] || 0) + 1;
      const ref = `INV-${c.prefix}-${String(S.invSeq[c.prefix]).padStart(3, '0')}`;
      const inv = { ref, contract: c.prefix, vendor: c.vendor, period, submittedAt: new Date().toISOString(), lines, paid: 0, paidOn: null };
      S.invoices.push(inv);
      log('vp', `${c.vendor} submitted ${ref} for ${monthLabel(period)}: ${lines.length} line${lines.length > 1 ? 's' : ''}, ${money(invTotal(inv))}, routed to the approver for ${c.study}.`);
      S.ui.qty[c.prefix] = {}; S.ui.invoiceSel = ref;
      render(); toast(`${ref} submitted and routed to the approver.`);
    },
    pick(el) { S.ui.invoiceSel = el.dataset.ref; render(); },
    approve(el) { const inv = S.invoices.find(x => x.ref === S.ui.invoiceSel); if (decide(inv, +el.dataset.i, true, ($('#ap-reason-' + el.dataset.i) || {}).value?.trim())) render(); },
    deny(el) { const inv = S.invoices.find(x => x.ref === S.ui.invoiceSel); if (decide(inv, +el.dataset.i, false, ($('#ap-reason-' + el.dataset.i) || {}).value?.trim())) render(); },
    approveall() {
      const inv = S.invoices.find(x => x.ref === S.ui.invoiceSel);
      let ok = true;
      inv.lines.forEach((l, i) => { if (l.status === 'pending') ok = decide(inv, i, true, ($('#ap-reason-' + i) || {}).value?.trim()) && ok; });
      render(); if (ok) toast(`${inv.ref} approved and sent to finance.`);
    },
    pay(el) {
      const inv = S.invoices.find(x => x.ref === el.dataset.ref);
      inv.paid = invApproved(inv); inv.paidOn = today();
      log('fi', `Paid ${money(inv.paid)} on ${inv.ref}, exactly the approved lines.`);
      render(); toast(`Payment of ${money(inv.paid)} recorded.`);
    },
    export() {
      const c = contract(S.ui.financeContract);
      const rows = [['Digital Contract ID', 'Section', 'Task Description', 'Contracted', 'Approved', 'Awaiting approval', 'Remaining']]
        .concat(c.lines.map(l => { const u = usage(c, l.id); return [l.id, l.section, l.desc, l.total.toFixed(2), u.aA.toFixed(2), u.pA.toFixed(2), (l.total - u.aA - u.pA).toFixed(2)]; }));
      download(`${c.prefix}_reconciliation_${today()}.csv`, rows);
      log('fi', `Exported the reconciliation for ${c.prefix}.`); save();
    },
    reset(el) {
      if (el.dataset.armed !== '1') { el.dataset.armed = '1'; el.textContent = 'Click again to clear all data'; setTimeout(() => { el.dataset.armed = ''; el.textContent = 'Reset demo'; }, 3000); return; }
      S = fresh(); el.dataset.armed = ''; el.textContent = 'Reset demo'; render(); toast('Demo data cleared.');
    }
  };

  async function verifyExecuted(input) {
    const c = contract(input.dataset.k), file = input.files[0];
    if (!file) return;
    try {
      const p = await G.readFile(file);
      if (!p.ok) { c.verify = { ok: false, name: file.name, diffs: [p.error] }; }
      else { const r = G.compare(c.lines, p.lines); c.verify = { ok: r.ok, name: file.name, diffs: r.diffs }; }
      log('om', `Checked executed copy ${file.name} against ${c.prefix}: ${c.verify.ok ? 'matches' : 'does not match'} the tagged grid.`);
    } catch (e) { c.verify = { ok: false, name: file.name, diffs: [e.message] }; }
    render();
  }

  /* ---------- events ---------- */
  document.addEventListener('click', e => {
    const tab = e.target.closest('[data-tab]');
    if (tab) { S.ui.tab = tab.dataset.tab; render(); window.scrollTo(0, 0); return; }
    const a = e.target.closest('[data-act]');
    if (a && !a.disabled && ACT[a.dataset.act]) ACT[a.dataset.act](a, e);
  });
  document.addEventListener('change', e => {
    const el = e.target;
    if (el.dataset.field) { S.ui.form[el.dataset.field] = el.value; save(); }
    if (el.dataset.fieldUi) { S.ui[el.dataset.fieldUi] = el.value; save(); }
    const k = el.dataset.change;
    if (k === 'vendor') { S.ui.vendor = el.value; S.ui.vendorContract = ''; render(); }
    if (k === 'vcontract') { S.ui.vendorContract = el.value; render(); }
    if (k === 'fcontract') { S.ui.financeContract = el.value; render(); }
    if (k === 'verify') verifyExecuted(el);
  });
  document.addEventListener('input', e => {
    const el = e.target;
    if (el.dataset.field) { S.ui.form[el.dataset.field] = el.value; save(); return; }
    if (el.classList.contains('reason')) { const i = el.id.split('-').pop(); const er = $('#ap-err-' + i); if (er) er.textContent = ''; return; }
    if (!el.classList.contains('qty')) return;
    const c = contract(S.ui.vendorContract), l = lineOf(c, el.dataset.line);
    (S.ui.qty[c.prefix] = S.ui.qty[c.prefix] || {})[l.id] = el.value;
    const k = checkQty(c, l, el.value);
    const row = el.closest('tr'), er = $('#er-' + l.id);
    row.classList.toggle('rowerr', !k.ok);
    er.hidden = k.ok; er.firstElementChild.textContent = k.msg || '';
    $('#amt-' + l.id).innerHTML = k.ok && k.units ? money(k.units * l.price) : '&mdash;';
    $('#vp-total').textContent = money(draftTotal(c));
    $('#vp-err').textContent = '';
    save();
  });

  window.ProPaApp = { state: () => S, render };
  render();
})();
