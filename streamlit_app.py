"""ProPa: tag a contract's budget grid with Digital Contract IDs (Streamlit demo).

Upload a final SOW or contract (Word, PDF, Excel or CSV). ProPa finds the budget grid,
checks it, assigns a Digital Contract ID to every line item and returns the SOW with the
IDs written into its budget table, ready for signature. Synthetic data only.
"""
from __future__ import annotations

import hashlib
import io
import re
from pathlib import Path

import pandas as pd
import streamlit as st

from propa import documents as D
from propa import grid as G
from propa import matching as M
from propa import review as R

HERE = Path(__file__).parent
SAMPLES = HERE / "samples"
SAMPLE_DOCX = SAMPLES / "SOW-01_ONC-2026-017_Meridian_FINAL_untagged.docx"
SAMPLE_PDF = SAMPLES / "SOW-01_ONC-2026-017_Meridian_FINAL_untagged.pdf"
SAMPLE_INV_PDF = SAMPLES / "INV-MCR-2026-1043_Meridian_Oct2026.pdf"
SAMPLE_INV_XLSX = SAMPLES / "INV-MCR-2026-1043_Meridian_Oct2026.xlsx"
SAMPLE_PO = "4500123456"
# Units already invoiced on the sample SOW before this invoice (synthetic), keyed by task description.
SAMPLE_HISTORY = {"Project start-up built": 8, "Site initiation visits": 40, "Project management": 9,
                  "On-site monitoring visits": 370, "Remote monitoring visits": 200, "Data management": 9,
                  "Safety case processing": 500}
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

ASSETS = HERE / "assets"
st.set_page_config(page_title="ProPa · Procurement to Payment", page_icon=str(ASSETS / "propa-mark.svg"), layout="wide")
st.logo(str(ASSETS / "propa-logo.svg"), icon_image=str(ASSETS / "propa-mark.svg"), size="large")
st.markdown("""<style>
:root{--pp-navy:#0f1420;--pp-blue:#1f5fd6;--pp-sky:#5b8ef0;--pp-amber:#f0a64b}
.block-container{padding-top:3.6rem;max-width:1200px}
[data-testid=stMetric]{height:100%}
/* brand header */
.pp-hero{position:relative;overflow:hidden;border-radius:18px;padding:30px 36px 28px;margin:0 0 1.6rem;
  background:radial-gradient(1200px 300px at 100% 0%,rgba(91,142,240,.35),transparent 60%),linear-gradient(120deg,#0f1420 0%,#14244d 70%,#1a3378 100%);color:#fff}
.pp-hero:after{content:"";position:absolute;right:-60px;top:-60px;width:260px;height:260px;border-radius:50%;border:38px solid rgba(240,166,75,.12)}
.pp-row{display:flex;align-items:center;gap:18px}
.pp-mark{width:58px;height:58px;flex:0 0 auto}
.pp-word{font-size:3rem;font-weight:800;letter-spacing:-.04em;line-height:1}
.pp-word span{color:var(--pp-sky)}
.pp-exp{font-size:.82rem;font-weight:700;letter-spacing:.18em;text-transform:uppercase;color:#aeb7c6;margin-top:6px}
.pp-exp b{color:var(--pp-amber);font-weight:800}
.pp-tag{font-size:1.45rem;font-weight:600;margin:20px 0 6px;letter-spacing:-.01em}
.pp-sub{color:#c9d0dc;font-size:1rem;max-width:780px;line-height:1.55}
.pp-chips{display:flex;flex-wrap:wrap;gap:8px;margin-top:16px}
.pp-chip{font-size:.82rem;font-weight:600;padding:5px 12px;border-radius:999px;background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.18);color:#e8ecf3}
.pp-chip i{font-style:normal;color:var(--pp-amber);margin-right:6px}
/* steps */
.step{display:inline-flex;align-items:center;gap:8px;font-size:.76rem;font-weight:800;letter-spacing:.08em;text-transform:uppercase;
  color:var(--pp-blue);background:#eaf0fc;border-radius:999px;padding:4px 12px 4px 4px;margin:1.2rem 0 -.2rem}
.step b{background:var(--pp-blue);color:#fff;border-radius:999px;width:22px;height:22px;display:inline-flex;align-items:center;justify-content:center;font-size:.72rem}
h1,h2,h3{letter-spacing:-.015em}
[data-testid=stMetric]{background:#f7f9fd;border:1px solid #e3e9f5;border-left:4px solid var(--pp-blue);border-radius:12px;padding:12px 16px}
.stButton button[kind=primary],.stDownloadButton button[kind=primary]{background:var(--pp-blue);border-color:var(--pp-blue)}
.stButton button[kind=primary]:hover{background:#174cb0;border-color:#174cb0}
[data-testid=stSidebar]{background:linear-gradient(180deg,#f3f6fc 0%,#ffffff 100%);border-right:1px solid #e3e9f5}
.pp-side-tag{color:#5a6475;font-size:.88rem;margin:-.3rem 0 .6rem}
.pp-foot{margin-top:2.5rem;padding-top:1rem;border-top:1px solid #e3e9f5;color:#7c879a;font-size:.82rem}
.pp-foot b{color:var(--pp-navy)} .pp-foot span{color:var(--pp-blue);font-weight:700}
.fp{font-family:ui-monospace,Menlo,Consolas,monospace;background:#eef3fd;padding:1px 6px;border-radius:5px}
</style>""", unsafe_allow_html=True)
MARK_SVG = (ASSETS / "propa-mark.svg").read_text()


def money(x: float) -> str:
    return f"${x:,.2f}"


@st.cache_data(show_spinner=False)
def analyse(name: str, data: bytes):
    contract = D.read_contract(name, data)
    return contract, D.find_grid(contract), D.extract_meta(contract, name)


@st.cache_data(show_spinner=False)
def build_outputs(name: str, data: bytes, kind: str, table_index: int, header_row: int, desc_col: int,
                  lines: tuple, meta: tuple, fp: str, clause: bool):
    lines_l = [dict(l) for l in lines]
    meta_d = dict(meta)
    if kind == "docx":
        doc = D.tagged_docx(data, table_index, header_row, lines_l, meta_d, fp, clause, desc_col)
        doc_name = re.sub(r"(?i)[_-]?untagged", "", Path(name).stem) + "_TAGGED.docx"
        # Self-check: read the tagged contract back and confirm every ID landed on the right line.
        back = D.find_grid(D.read_contract(doc_name, doc))
        found = [l["id_in_file"] for l in back.get("lines", [])]
        check = (found == [l["id"] for l in lines_l]) and abs(back.get("sum", 0) - sum(l["total"] for l in lines_l)) < 0.01
    else:
        doc = D.tagged_appendix_docx(lines_l, meta_d, fp, clause, name)
        doc_name = Path(name).stem + "_Appendix_A_TAGGED.docx"
        check = None
    return doc, doc_name, D.register_xlsx(lines_l, meta_d, fp), D.register_json(lines_l, meta_d, fp), check


# ---------------- sidebar ----------------
with st.sidebar:
    st.markdown('<div class="pp-side-tag">Every contract line, from signature to payment.</div>', unsafe_allow_html=True)
    st.markdown("**How it works**")
    st.markdown("1. Upload the final SOW or contract, before signature.\n"
                "2. ProPa finds the budget grid and checks its totals.\n"
                "3. Every line item gets a Digital Contract ID.\n"
                "4. Download the tagged SOW and send it for signature.\n"
                "5. Upload a vendor invoice: ProPa maps each line to its ID and checks what is left.\n"
                "6. Review the executed contract and the invoice side by side, then approve.")
    st.markdown("**Sample SOW, no IDs**")
    st.download_button("Word version", SAMPLE_DOCX.read_bytes(), SAMPLE_DOCX.name, DOCX_MIME, use_container_width=True)
    st.download_button("PDF version", SAMPLE_PDF.read_bytes(), SAMPLE_PDF.name, "application/pdf", use_container_width=True)
    st.markdown("**Sample vendor invoice, no IDs**")
    st.download_button("Invoice PDF", SAMPLE_INV_PDF.read_bytes(), SAMPLE_INV_PDF.name, "application/pdf", use_container_width=True)
    st.download_button("Invoice Excel", SAMPLE_INV_XLSX.read_bytes(), SAMPLE_INV_XLSX.name, XLSX_MIME, use_container_width=True)
    st.divider()
    st.caption("Prototype on synthetic data. Uploaded files are processed in memory for your session only and are not stored.")

# ---------------- step 1: upload ----------------
st.markdown(f"""<div class="pp-hero">
  <div class="pp-row"><div class="pp-mark">{MARK_SVG}</div>
    <div><div class="pp-word">Pro<span>Pa</span></div><div class="pp-exp"><b>Pro</b>curement to <b>Pa</b>yment</div></div></div>
  <div class="pp-tag">Every contract line, from signature to payment.</div>
  <div class="pp-sub">Tag each budget line of a SOW with a Digital Contract ID before signature, then check every vendor invoice line against it.</div>
  <div class="pp-chips"><span class="pp-chip"><i>&#9679;</i>Digital Contract IDs</span><span class="pp-chip"><i>&#9679;</i>Line-level invoice checks</span>
  <span class="pp-chip"><i>&#9679;</i>Works alongside Ariba</span><span class="pp-chip"><i>&#9679;</i>Synthetic data only</span></div>
</div>""", unsafe_allow_html=True)
st.header("Tag a contract's budget grid")
st.write("Upload the final SOW or contract with its agreed budget grid. ProPa gives every budget line a permanent "
         "**Digital Contract ID** and writes it into the contract, so every later invoice line can be traced, checked and reconciled.")

c_up, c_or = st.columns([3, 1], vertical_alignment="center")
upload = c_up.file_uploader("Final SOW or contract (.docx, .pdf, .xlsx or .csv)", type=["docx", "pdf", "xlsx", "csv"])
if c_or.button("Use the sample SOW", use_container_width=True, type="secondary"):
    st.session_state.use_sample = True

if upload is not None:
    name, data = upload.name, upload.getvalue()
elif st.session_state.get("use_sample"):
    name, data = SAMPLE_DOCX.name, SAMPLE_DOCX.read_bytes()
else:
    st.info("Upload a contract, or click **Use the sample SOW**. You can download the sample from the sidebar to see that it has no IDs.")
    st.stop()

key = hashlib.sha1(data).hexdigest()[:12]
if st.session_state.get("doc_key") != key:
    st.session_state.doc_key = key
    st.session_state.tagged = None

try:
    contract, found, meta = analyse(name, data)
except Exception as e:  # unreadable or unsupported file
    st.error(f"ProPa could not read {name}: {e}")
    st.stop()

if not found["ok"]:
    st.error(f"No budget grid found in {name}. ProPa looks for a table with columns for unit price, number of units and total cost.")
    for s in found["skipped"]:
        st.caption(f"Checked {s}")
    st.stop()

# ---------------- step 2: grid found ----------------
st.markdown('<div class="step"><b>1</b>Step 1</div>', unsafe_allow_html=True)
st.subheader("Budget grid found in the contract")
lines = found["lines"]
total_ok = found["declared"] is not None and abs(found["declared"] - found["sum"]) <= 0.01
m1, m2, m3, m4 = st.columns(4)
m1.metric("Source", name.rsplit(".", 1)[-1].upper(), help=name)
m2.metric("Line items", f"{len(lines)}", f"{len(found['sections'])} sections", delta_color="off")
m3.metric("Contract value", money(found["sum"]))
m4.metric("Grid total row", "Matches" if total_ok else ("Not found" if found["declared"] is None else "Differs"),
          money(found["declared"]) if found["declared"] is not None else None, delta_color="off")
st.caption(f"Found in **{found['table']['label']}**, header on row {found['header_row'] + 1} of that table."
           + (f" Also checked and skipped: {'; '.join(s.split(':')[0] for s in found['skipped'])}." if found["skipped"] else ""))
if found["warnings"]:
    st.warning("**Review before tagging**\n\n" + "\n".join(f"- {('Row ' + str(w['row'] + 1) + ': ') if w['row'] is not None else ''}{w['msg']}" for w in found["warnings"]))

with st.expander("Budget grid as it appears in the contract, with no IDs", expanded=st.session_state.tagged is None):
    st.dataframe(pd.DataFrame([{"Section": l["section"], "Task Description": l["desc"], "Unit type": l["unit_type"],
                                "Unit price": l["price"], "No. of Units": l["units"], "Total costs": l["total"]} for l in lines]),
                 hide_index=True, use_container_width=True,
                 column_config={"Unit price": st.column_config.NumberColumn(format="dollar"),
                                "Total costs": st.column_config.NumberColumn(format="dollar"),
                                "No. of Units": st.column_config.NumberColumn(format="localized")})

# ---------------- step 3: details and tagging ----------------
st.markdown('<div class="step"><b>2</b>Step 2</div>', unsafe_allow_html=True)
st.subheader("Contract details")
st.caption("Read from the contract where possible. Correct anything before assigning IDs.")
a, b, c = st.columns(3)
sponsor = a.text_input("Sponsor", meta["sponsor"], key=f"sp_{key}")
vendor = b.text_input("Service provider", meta["vendor"], key=f"vd_{key}")
study = c.text_input("Study / protocol", meta["study"], key=f"st_{key}")
a, po_col, b, c = st.columns(4)
agreement = a.text_input("Agreement", meta["agreement"] or "SOW-01", key=f"ag_{key}")
po_number = po_col.text_input("PO number", SAMPLE_PO if name == SAMPLE_DOCX.name else "", key=f"po_{key}",
                              help="The single purchase order raised for this SOW. Vendor invoices quote it.").strip()
models = ["FSO", "FSP", "Hybrid", "Other"]
model = b.selectbox("Outsourcing model", models, index=models.index(meta["model"]) if meta["model"] in models else 0, key=f"md_{key}")
prefix = c.text_input("ID prefix", G.default_prefix(study, vendor), key=f"px_{key}", max_chars=10,
                      help="Study number plus provider initials. Must be unique per contract.").strip().upper()
clause = st.checkbox("Add sample invoicing clause after the budget grid (for legal review)", value=True, key=f"cl_{key}")
ack = True
if found["warnings"]:
    ack = st.checkbox("I have reviewed the items flagged above", key=f"ack_{key}")

problems = []
if not re.fullmatch(r"[A-Z0-9]{2,10}", prefix or ""):
    problems.append("The ID prefix must be 2 to 10 letters or digits.")
if not ack:
    problems.append("Tick the review box to confirm the flagged items.")
for p in problems:
    st.error(p)

if st.button("Assign Digital Contract IDs", type="primary", disabled=bool(problems)):
    tagged = G.assign_ids(lines, prefix)
    st.session_state.tagged = {"lines": tagged, "fp": G.fingerprint(tagged), "prefix": prefix,
                               "meta": {"sponsor": sponsor, "vendor": vendor, "study": study, "agreement": agreement, "model": model},
                               "clause": clause}

tg = st.session_state.tagged
if not tg:
    st.stop()
if tg["prefix"] != prefix or tg["clause"] != clause:
    st.info("Details changed since tagging. Click **Assign Digital Contract IDs** again to update the outputs.")

# ---------------- step 4: tagged output ----------------
st.markdown('<div class="step"><b>3</b>Step 3</div>', unsafe_allow_html=True)
st.subheader("Digital Contract IDs assigned")
doc, doc_name, xlsx, js, check = build_outputs(
    name, data, contract["kind"], found["table"]["index"], found["header_row"], found["cols"]["desc"],
    tuple(tuple(sorted(l.items())) for l in tg["lines"]), tuple(sorted(tg["meta"].items())), tg["fp"], tg["clause"])
st.success(f"{len(tg['lines'])} line items tagged, total {money(sum(l['total'] for l in tg['lines']))}. "
           f"Grid fingerprint {tg['fp']}: any later change to a line, unit price or quantity produces a different fingerprint.")
st.dataframe(D.register_frame(tg["lines"]), hide_index=True, use_container_width=True,
             column_config={"Digital Contract ID": st.column_config.TextColumn(width="medium"),
                            "Unit price": st.column_config.NumberColumn(format="dollar"),
                            "Total costs": st.column_config.NumberColumn(format="dollar"),
                            "No. of Units": st.column_config.NumberColumn(format="localized")})
if check is True:
    st.caption("Self-check passed: the tagged SOW was read back, and every ID sits on its own budget line with totals unchanged.")
elif check is False:
    st.error("Self-check failed: the tagged SOW does not read back cleanly. Use the register instead and report the file.")
else:
    st.caption("PDF, Excel and CSV files cannot be edited in place, so ProPa produces a tagged Appendix A to attach to the contract.")

d1, d2, d3 = st.columns(3)
d1.download_button("Download tagged SOW (.docx)" if contract["kind"] == "docx" else "Download tagged Appendix A (.docx)",
                   doc, doc_name, DOCX_MIME, type="primary", use_container_width=True)
d2.download_button("Download ID register (.xlsx)", xlsx, f"{tg['prefix']}_digital_contract_ids.xlsx", XLSX_MIME, use_container_width=True)
d3.download_button("Download register for P2P/ERP (.json)", js, f"{tg['prefix']}_digital_contract_ids.json", "application/json", use_container_width=True)

# ---------------- step 5: map a vendor invoice ----------------
@st.cache_data(show_spinner=False)
def read_invoice(iname: str, idata: bytes):
    ic = D.read_contract(iname, idata)
    return M.parse_invoice(ic), M.invoice_meta(ic, iname)


st.markdown('<div class="step"><b>4</b>Step 4</div>', unsafe_allow_html=True)
st.subheader("Map a vendor invoice to the IDs")
st.caption("The vendor's invoice quotes only the PO number and its own descriptions. ProPa matches each line to its Digital Contract ID "
           "using the description, unit price and unit type, shows why, and checks what is left on that line. The PM confirms anything uncertain.")
c_up, c_s = st.columns([3, 1], vertical_alignment="center")
inv_up = c_up.file_uploader("Vendor invoice (.pdf, .xlsx, .docx or .csv)", type=["pdf", "xlsx", "docx", "csv"], key=f"invup_{key}")
if c_s.button("Use the sample invoice", key=f"invs_{key}", use_container_width=True):
    st.session_state.use_sample_inv = True
if inv_up is not None:
    iname, idata = inv_up.name, inv_up.getvalue()
elif st.session_state.get("use_sample_inv"):
    iname, idata = SAMPLE_INV_PDF.name, SAMPLE_INV_PDF.read_bytes()
else:
    st.info("Upload a vendor invoice, or click **Use the sample invoice**: a PDF from the vendor with descriptions only and no IDs.")
    st.stop()
try:
    pinv, imeta = read_invoice(iname, idata)
except Exception as e:
    st.error(f"ProPa could not read {iname}: {e}")
    st.stop()
if not pinv["ok"]:
    st.error(pinv["error"])
    st.stop()

clines = tg["lines"]
is_sample_sow = set(SAMPLE_HISTORY) <= {l["desc"] for l in clines}
use_hist = st.checkbox("Include billing to date on this SOW (synthetic history for the sample)", value=is_sample_sow,
                       disabled=not is_sample_sow, key=f"hist_{key}")
billed_before = {l["id"]: float(SAMPLE_HISTORY.get(l["desc"], 0)) for l in clines} if use_hist else {}

po_ok = bool(po_number) and imeta["po"].replace(" ", "") == po_number.replace(" ", "")
learned = st.session_state.setdefault("learned", {})
results = M.match_invoice(pinv["lines"], clines, learned)
auto = sum(r["match"]["level"] in ("high", "exact", "learned") for r in results)
st.markdown(f"**Invoice {imeta['invoice_no'] or iname}**" + (f" · service period {imeta['period']}" if imeta["period"] else "")
            + f" · {len(results)} lines, no Digital Contract IDs on the invoice" * (not any(r['id_in_file'] for r in pinv['lines'])))
i2, i3, i4 = st.columns(3)
i2.metric("PO quoted", imeta["po"] or "none", ("matches this SOW" if po_ok else "not this SOW's PO") if imeta["po"] else None,
          delta_color="normal" if po_ok else "inverse", delta_arrow="off")
i3.metric("Invoice total", money(pinv["sum"]))
i4.metric("Matched automatically", f"{auto} of {len(results)}", f"{len(results) - auto} for the PM to confirm", delta_color="off", delta_arrow="off")

label = {l["id"]: f'{l["id"]} · {l["desc"]}' for l in clines}
NONE = "Not in contract"
LEVEL = {"exact": "ID on invoice", "learned": "Confirmed before", "high": "Auto", "check": "PM to confirm", "none": "No match"}
table = pd.DataFrame([{"#": r["n"], "Invoice line": r["desc"], "Qty": r["qty"], "Rate": r["rate"], "Amount": r["amount"],
                       "Mapped to": label.get(r["match"]["id"], NONE), "Match": LEVEL[r["match"]["level"]],
                       "Why": "; ".join(r["match"]["reasons"])} for r in results])
ihash = hashlib.sha1(idata).hexdigest()[:10]
edited_map = st.data_editor(table, hide_index=True, use_container_width=True, key=f"map_{key}_{ihash}_{len(learned)}",
                            disabled=["#", "Invoice line", "Qty", "Rate", "Amount", "Match", "Why"],
                            column_config={"Rate": st.column_config.NumberColumn(format="dollar"),
                                           "Amount": st.column_config.NumberColumn(format="dollar"),
                                           "Mapped to": st.column_config.SelectboxColumn(options=list(label.values()) + [NONE], required=True, width="medium"),
                                           "Why": st.column_config.TextColumn(width="large")})
st.caption("Change **Mapped to** for any line the PM disagrees with. Lines marked *PM to confirm* need a decision before approval.")
back = {v: k for k, v in label.items()}
mapped = [(r, back.get(m)) for r, m in zip(results, edited_map["Mapped to"])]
bal = M.line_balances(mapped, clines, billed_before)
bad = {b_["id"]: b_ for b_ in bal if b_["status"] != "within contract"}
unmapped = [r for r, cid in mapped if cid is None]
held_unmapped = round(sum(r["amount"] for r in unmapped), 2)
held = round(held_unmapped + sum(b_["held"] for b_ in bal), 2)
ok_amt = round(pinv["sum"] - held, 2)

contract_value = sum(l["total"] for l in clines)
before_amt = sum(billed_before.get(l["id"], 0) * l["price"] for l in clines)
po_left = contract_value - before_amt
left_col, right_col = st.columns(2)
with left_col:
    st.markdown("**What a PO-level check sees**")
    st.caption(f"PO {po_number or '(not set)'} · value {money(contract_value)} · invoiced before {money(before_amt)} · remaining {money(po_left)}")
    if pinv["sum"] <= po_left:
        st.success(f"Passes. {money(pinv['sum'])} fits within the PO's remaining {money(po_left)}.")
    else:
        st.error(f"Fails. {money(pinv['sum'])} exceeds the PO's remaining {money(po_left)}.")
with right_col:
    st.markdown("**What ProPa sees, line by line**")
    issues = [f'{b_["id"]} {b_["task"]}: {b_["status"]}' for b_ in bad.values()] + [f'"{r["desc"]}" ({money(r["amount"])}): not in the contract' for r in unmapped]
    if issues:
        st.error("Hold before approval:\n" + "\n".join(f"- {x}" for x in issues))
    else:
        st.success("Every line maps to a contract line, at the contracted price, within what is left.")
reasons_held = [f'{b_["id"]}: {money(b_["held"])}' for b_ in bal if b_["held"] > 0] + ([f"outside the contract: {money(held_unmapped)}"] if held_unmapped else [])
st.markdown(f"**PM decision:** approve **{money(ok_amt)}**, everything within what is left on each line at the contracted price. "
            f"Hold **{money(held)}** ({'; '.join(reasons_held)}) for a change order, correction or credit note."
            if held else f"**PM decision:** approve all **{money(ok_amt)}**.")

st.dataframe(pd.DataFrame([{"Digital Contract ID": b_["id"], "Task": b_["task"], "Contracted": b_["contracted"], "Billed before": b_["before"],
                            "This invoice": b_["this"], "Left after": b_["left"], "Amount": b_["amount"], "Approve": b_["approvable"], "Hold": b_["held"],
                            "Status": b_["status"]} for b_ in bal]),
             hide_index=True, use_container_width=True,
             column_config={"Amount": st.column_config.NumberColumn(format="dollar"), "Approve": st.column_config.NumberColumn(format="dollar"),
                            "Hold": st.column_config.NumberColumn(format="dollar")})

# ---------------- side-by-side review ----------------
st.markdown('<div class="step"><b>5</b>Step 5</div>', unsafe_allow_html=True)
st.subheader("Review the evidence side by side")
st.caption("Pick an invoice line. ProPa opens the executed SOW at the budget line it is linked to, next to the vendor's invoice, "
           "so the PM can check the evidence without searching folders or trackers.")
st.markdown(R.CSS, unsafe_allow_html=True)
opts = [f'Line {r["n"]} · {r["desc"]} → {cid or NONE}' for r, cid in mapped]
price_of = {l["id"]: l["price"] for l in clines}
first_flag = next((i for i, (r, cid) in enumerate(mapped) if cid and abs(r["rate"] - price_of[cid]) > 0.005),
                  next((i for i, (r, cid) in enumerate(mapped) if cid is None or cid in bad), 0))
pick = st.selectbox("Invoice line to review", opts, index=first_flag, key=f"rev_{key}_{ihash}")
r_sel, cid_sel = mapped[opts.index(pick)]
cl_sel = next((l for l in clines if l["id"] == cid_sel), None)
b_sel = next((b_ for b_ in bal if b_["id"] == cid_sel), None)
if b_sel and cl_sel:
    rate_bad = abs(r_sel["rate"] - cl_sel["price"]) > 0.005
    left_bad = b_sel["left"] < 0
    cells = [("Contracted units", f'{b_sel["contracted"]:,.0f}', ""), ("Billed before", f'{b_sel["before"]:,.0f}', ""),
             ("On this invoice", f'{b_sel["this"]:,.0f}', ""), ("Left after", f'{b_sel["left"]:,.0f}', "bad" if left_bad else "good"),
             ("Contract rate / invoiced", f'{money(cl_sel["price"])} / {money(r_sel["rate"])}', "bad" if rate_bad else "good"),
             ("Approve / hold on this ID", f'{money(b_sel["approvable"])} / {money(b_sel["held"])}', "bad" if b_sel["held"] > 0 else "good")]
    st.markdown('<div class="pp-check">' + "".join(f'<div class="{c}"><small>{a}</small><b>{v}</b></div>' for a, v, c in cells) + "</div>",
                unsafe_allow_html=True)
    others = [r["n"] for r, cid in mapped if cid == cid_sel and r["n"] != r_sel["n"]]
    if others:
        st.caption(f"Invoice line{'s' if len(others) > 1 else ''} {', '.join(map(str, others))} also bill{'' if len(others) > 1 else 's'} "
                   f"{cid_sel}, so the unit and amount checks cover all of them together.")
elif cid_sel is None:
    st.error(f'"{r_sel["desc"]}" ({money(r_sel["amount"])}) does not match any line in the executed SOW. Hold it for a change order or credit note.')
rv_l, rv_r = st.columns([1.3, 1], gap="medium")
with rv_l:
    st.markdown("**Executed contract**")
    st.markdown(R.contract_html(clines, tg["meta"], tg["fp"], cid_sel, doc_name, po_number), unsafe_allow_html=True)
with rv_r:
    st.markdown("**Vendor invoice**")
    st.markdown(f'<div class="pp-inv-bar"><span>&#129534; {iname}</span><span>Line {r_sel["n"]} highlighted</span></div>', unsafe_allow_html=True)
    png = R.invoice_page_png(idata, r_sel["desc"]) if iname.lower().endswith(".pdf") else None
    if png:
        st.image(png, use_container_width=True)
    else:
        st.dataframe(table[["#", "Invoice line", "Qty", "Rate", "Amount"]].style.apply(
            lambda row: ["background-color:#ffe39a" if row["#"] == r_sel["n"] else "" for _ in row], axis=1),
            hide_index=True, use_container_width=True)

d1, d2 = st.columns(2)
if d1.button("Confirm mapping and remember this wording", type="primary", use_container_width=True, key=f"learn_{key}_{ihash}"):
    for r, cid in mapped:
        if cid:
            learned[M.norm_phrase(r["desc"])] = cid
    st.session_state.learned = learned
    st.toast("Mapping confirmed. Invoices with the same wording will now map automatically.")
    st.rerun()
out = pd.DataFrame([{"Invoice": imeta["invoice_no"], "PO": imeta["po"], "Line": r["n"], "Description": r["desc"], "Qty": r["qty"],
                     "Rate": r["rate"], "Amount": r["amount"], "Digital Contract ID": cid or "",
                     "Status": "not in contract" if cid is None else bad.get(cid, {}).get("status", "within contract")} for r, cid in mapped])
buf = io.BytesIO()
out.to_excel(buf, index=False)
d2.download_button("Download mapped invoice (.xlsx)", buf.getvalue(), f"{imeta['invoice_no'] or 'invoice'}_mapped.xlsx", XLSX_MIME, use_container_width=True)
if learned:
    st.caption(f"{len(learned)} vendor phrasings remembered in this session.")

st.markdown('<div class="pp-foot"><b>Pro<span>Pa</span></b> &middot; Procurement to Payment &middot; prototype on synthetic data &middot; '
            'not legal or financial advice. The invoicing clause is sample wording for your legal team to review.</div>', unsafe_allow_html=True)
