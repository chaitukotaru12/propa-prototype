"""Side-by-side review: the executed contract's budget grid next to the vendor's invoice line."""
from __future__ import annotations

import html
import io
import re


def invoice_page_png(data: bytes, desc: str, n: int | None = None, resolution: int = 150):
    """Render the invoice PDF page that holds `desc`, with that line highlighted. Returns PNG bytes, or None."""
    try:
        import pdfplumber
    except ImportError:
        return None
    try:
        pdf = pdfplumber.open(io.BytesIO(data))
    except Exception:
        return None
    with pdf:
        for page in pdf.pages:
            hits = (page.search(re.escape(desc) + r"\s+[\d$]", regex=True) or page.search(desc, regex=False)) if desc else []
            if not hits:
                continue
            h = hits[0]
            x0, x1 = 36, page.width - 36
            tables = page.find_tables()
            bottom = max([t.bbox[3] for t in tables] + [h["bottom"]])
            for t in tables:
                bx0, btop, bx1, bbot = t.bbox
                if btop - 2 <= h["top"] <= bbot + 2:
                    x0, x1 = bx0, bx1
                    break
            chars = page.chars or [{"x0": 18, "x1": page.width - 18, "top": 18}]
            cx0 = max(0, min(c["x0"] for c in chars) - 14)
            cx1 = min(page.width, max(c["x1"] for c in chars) + 14)
            ctop = max(0, min(c["top"] for c in chars) - 14)
            view = page.crop((cx0, ctop, cx1, min(page.height, bottom + 30)))
            im = view.to_image(resolution=resolution)
            im.draw_rect((x0 - 2, h["top"] - 4, x1 + 2, h["bottom"] + 4), fill=(255, 196, 61, 90), stroke=(230, 140, 20), stroke_width=3)
            buf = io.BytesIO()
            im.save(buf, format="PNG")
            return buf.getvalue()
    return None


def _m(x: float) -> str:
    return f"${x:,.2f}"


def contract_html(lines: list[dict], meta: dict, fp: str, highlight: str | None, doc_name: str, po: str) -> str:
    """The executed SOW's Appendix A budget grid as a document page, with one Digital Contract ID highlighted."""
    e = html.escape
    rows, section = [], None
    for l in lines:
        if l.get("section") and l["section"] != section:
            section = l["section"]
            rows.append(f'<tr class="sec"><td></td><td colspan="5">{e(section)}</td></tr>')
        cls = ' class="hit"' if l["id"] == highlight else ""
        rows.append(f'<tr{cls}><td class="id">{e(l["id"])}</td><td>{e(l["desc"])}</td><td>{e(str(l.get("unit_type", "")))}</td>'
                    f'<td class="n">{_m(l["price"])}</td><td class="n">{l["units"]:,.0f}</td><td class="n">{_m(l["total"])}</td></tr>')
    total = sum(l["total"] for l in lines)
    rows.append(f'<tr class="tot"><td></td><td colspan="4">Total</td><td class="n">{_m(total)}</td></tr>')
    head = " · ".join(x for x in [meta.get("agreement"), meta.get("study"), meta.get("sponsor"), meta.get("vendor")] if x)
    return f"""<div class="pp-doc">
<div class="pp-doc-bar"><span>&#128196; {e(doc_name)}</span><span class="ok">Executed copy &middot; fingerprint {e(fp)}</span></div>
<div class="pp-page">
<div class="pp-doc-meta">{e(head)}{' &middot; PO ' + e(po) if po else ''}</div>
<div class="pp-doc-h">Appendix A &mdash; Budget grid</div>
<table><thead><tr><th>Digital Contract ID</th><th>Task Description</th><th>Unit type</th><th>Unit price</th><th>No. of Units</th><th>Total costs</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
<div class="pp-doc-note">Digital Contract IDs assigned by ProPa. Each ID is fixed for the life of this SOW.</div>
</div></div>"""


CSS = """<style>
.pp-doc{border:1px solid #d9dfeb;border-radius:12px;overflow:hidden;background:#eef1f6}
.pp-doc-bar{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;font-size:.8rem;padding:8px 12px;background:#0f1420;color:#dfe5ef}
.pp-doc-bar .ok{color:#7fd49b;font-weight:600}
.pp-page{background:#fff;margin:14px;padding:18px 18px 14px;box-shadow:0 2px 10px rgba(15,20,32,.12);font-family:Calibri,Carlito,'Segoe UI',Arial,sans-serif;color:#111}
.pp-doc-meta{font-size:.72rem;color:#6a7385;margin-bottom:4px}
.pp-doc-h{font-size:1.05rem;font-weight:700;color:#2f5496;margin-bottom:8px}
.pp-page table{width:100%;border-collapse:collapse;font-size:.74rem}
.pp-page th{background:#dce6f4;text-align:left;font-weight:700;border:1px solid #333;padding:3px 5px}
.pp-page td{border:1px solid #333;padding:3px 5px}
.pp-page td.n{text-align:right;white-space:nowrap}
.pp-page td.id{font-family:ui-monospace,Consolas,monospace;font-size:.7rem;white-space:nowrap}
.pp-page tr.sec td{background:#f2f4f8;font-weight:700}
.pp-page tr.tot td{font-weight:700}
.pp-page tr.hit td{background:#ffe39a;outline:none}
.pp-page tr.hit td:first-child{box-shadow:inset 4px 0 0 #e68c14}
.pp-doc-note{font-size:.72rem;color:#2f5fd6;font-style:italic;margin-top:8px}
.pp-inv-bar{display:flex;justify-content:space-between;font-size:.8rem;padding:8px 12px;background:#0f1420;color:#dfe5ef;border-radius:12px 12px 0 0}
.pp-check{display:grid;grid-template-columns:1fr 1fr 1fr 1fr 1.5fr 1.7fr;gap:8px;margin:.6rem 0 .4rem}
.pp-check div{background:#f7f9fd;border:1px solid #e3e9f5;border-radius:10px;padding:8px 10px}
.pp-check small{display:block;color:#6a7385;font-size:.72rem}
.pp-check b{font-size:.98rem;white-space:nowrap}
.pp-check .bad{border-color:#f3b4b4;background:#fff3f3} .pp-check .bad b{color:#b42318}
.pp-check .good b{color:#1a7f37}
</style>"""
