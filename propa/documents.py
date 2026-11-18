"""Read contracts (Word, PDF, Excel, CSV), find the budget grid, and write tagged outputs."""
from __future__ import annotations

import copy
import csv
import io
import json
import re
from datetime import date

import pandas as pd
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from . import grid as G

ID_COL_CM = 3.3


# ---------- reading ----------
def _docx_tables(doc) -> list[dict]:
    """Tables in body order, each labelled with the nearest heading above it."""
    out, heading, idx = [], "", 0
    for el in doc.element.body.iterchildren():
        if el.tag == qn("w:p"):
            style = el.find(qn("w:pPr") + "/" + qn("w:pStyle"))
            text = "".join(t.text or "" for t in el.iter(qn("w:t"))).strip()
            if text and style is not None and re.match(r"(Heading|Title)", style.get(qn("w:val")) or ""):
                heading = text
        elif el.tag == qn("w:tbl"):
            table = doc.tables[idx]
            rows = [[c.text for c in r.cells] for r in table.rows]
            out.append({"index": idx, "label": f"Table {idx + 1}" + (f' under "{heading}"' if heading else ""), "rows": rows})
            idx += 1
    return out


def read_contract(name: str, data: bytes) -> dict:
    ext = name.lower().rsplit(".", 1)[-1]
    if ext == "docx":
        doc = Document(io.BytesIO(data))
        tables = _docx_tables(doc)
        text = "\n".join(p.text for p in doc.paragraphs)
        return {"kind": "docx", "tables": tables, "text": text}
    if ext == "pdf":
        import pdfplumber
        tables, text = [], []
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for pn, page in enumerate(pdf.pages, 1):
                text.append(page.extract_text() or "")
                for tn, t in enumerate(page.extract_tables(), 1):
                    tables.append({"index": len(tables), "label": f"Page {pn}, table {tn}", "rows": t})
        return {"kind": "pdf", "tables": tables, "text": "\n".join(text)}
    if ext in ("xlsx", "xlsm"):
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(data), data_only=True, read_only=True)
        tables = [{"index": i, "label": f'Sheet "{ws.title}"', "rows": [list(r) for r in ws.iter_rows(values_only=True)]}
                  for i, ws in enumerate(wb.worksheets)]
        return {"kind": "xlsx", "tables": tables, "text": ""}
    if ext == "csv":
        rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig", errors="replace"))))
        return {"kind": "csv", "tables": [{"index": 0, "label": "CSV", "rows": rows}], "text": ""}
    raise ValueError("Upload a .docx, .pdf, .xlsx or .csv file.")


def find_grid(contract: dict) -> dict:
    skipped = []
    for t in contract["tables"]:
        parsed = G.parse_rows(t["rows"])
        if parsed["ok"]:
            return {**parsed, "table": t, "skipped": skipped}
        skipped.append(f'{t["label"]}: {parsed["error"]}')
    return {"ok": False, "error": "No budget grid found in this file.", "skipped": skipped}


KEYS = {
    "sponsor": r"sponsor( name)?",
    "vendor": r"(service provider|vendor|supplier|cro|contractor)( name)?",
    "study": r"protocol|study|protocol\s*/\s*study|study\s*/\s*protocol|protocol (no\.?|number)",
    "title": r"study title|title",
    "agreement": r"sow|sow no\.?|statement of work|work order|agreement",
    "model": r"outsourcing model|model",
}


def extract_meta(contract: dict, name: str) -> dict:
    meta = {k: "" for k in KEYS}
    for t in contract["tables"]:  # two-column key/value tables, e.g. the SOW cover table
        for row in t["rows"]:
            cells = [G.norm(c) for c in row if G.norm(c)]
            if len(cells) != 2:
                continue
            for k, rx in KEYS.items():
                if not meta[k] and re.fullmatch(rx, cells[0], re.I):
                    meta[k] = cells[1]
    text = contract.get("text", "") + " " + name
    if not meta["study"]:
        m = re.search(r"(?<![A-Za-z0-9])([A-Z]{2,6}-\d{3,4}-\d{2,4})(?![0-9])", text)
        meta["study"] = m.group(1) if m else ""
    m = re.search(r"(?<![A-Za-z])(SOW[-\s]?\d+|WO[-\s]?\d+|CO[-\s]?\d+)(?![0-9])", text, re.I)
    if m:
        meta["agreement"] = m.group(1).upper().replace(" ", "-")
    if re.search(r"\bFSP\b|functional service", meta["model"] + text, re.I) and not re.search(r"\bFSO\b|full[- ]service", meta["model"], re.I):
        meta["model"] = "FSP"
    elif re.search(r"\bFSO\b|full[- ]service", meta["model"] + text, re.I):
        meta["model"] = "FSO"
    return meta


# ---------- writing ----------
def register_frame(lines: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([{"Digital Contract ID": l["id"], "Section": l["section"], "Task Description": l["desc"],
                          "Unit type": l["unit_type"], "Unit price": l["price"], "No. of Units": l["units"],
                          "Total costs": l["total"]} for l in lines])


def register_xlsx(lines: list[dict], meta: dict, fp: str) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        register_frame(lines).to_excel(xw, sheet_name="Tagged budget grid", index=False)
        pd.DataFrame([("Sponsor", meta.get("sponsor")), ("Service provider", meta.get("vendor")), ("Study", meta.get("study")),
                      ("Agreement", meta.get("agreement")), ("Outsourcing model", meta.get("model")),
                      ("Lines tagged", len(lines)), ("Contract value", round(sum(l["total"] for l in lines), 2)),
                      ("Grid fingerprint", fp), ("Tagged on", date.today().isoformat())],
                     columns=["Field", "Value"]).to_excel(xw, sheet_name="Contract", index=False)
        for ws in xw.book.worksheets:
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = max(12, min(48, max(len(str(c.value or "")) for c in col) + 2))
    return buf.getvalue()


def register_json(lines: list[dict], meta: dict, fp: str) -> bytes:
    payload = {"contract": {**meta, "fingerprint": fp, "tagged_on": date.today().isoformat(),
                            "value": round(sum(l["total"] for l in lines), 2)},
               "lines": [{"digital_contract_id": l["id"], "section": l["section"], "task": l["desc"], "unit_type": l["unit_type"],
                          "unit_price": l["price"], "units": l["units"], "total": l["total"]} for l in lines]}
    return json.dumps(payload, indent=2).encode()


CLAUSE = ("Invoicing against Digital Contract IDs (sample wording for legal review). Each invoice line issued under this SOW "
          "shall cite the Digital Contract ID of the Appendix A line to which it relates. Units invoiced against a line, "
          "together with units previously invoiced against it, shall not exceed the units for that line unless increased by an "
          "executed change order, which shall add or version the relevant Digital Contract IDs. Invoice lines without a valid "
          "Digital Contract ID may be returned unpaid.")


def _run(p_el, text, bold=False, mono=False, size=9):
    r = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")
    if bold:
        rpr.append(OxmlElement("w:b"))
    if mono:
        f = OxmlElement("w:rFonts")
        for a in ("w:ascii", "w:hAnsi", "w:cs"):
            f.set(qn(a), "Consolas")
        rpr.append(f)
    sz = OxmlElement("w:sz")
    sz.set(qn("w:val"), str(int(size * 2)))
    rpr.append(sz)
    r.append(rpr)
    t = OxmlElement("w:t")
    t.text = text
    t.set(qn("xml:space"), "preserve")
    r.append(t)
    p_el.append(r)


def _span(tc) -> int:
    gs = tc.tcPr.find(qn("w:gridSpan")) if tc.tcPr is not None else None
    return int(gs.get(qn("w:val"))) if gs is not None else 1


def _add_id_column(table, ids_by_row: dict[int, str], desc_col: int = 0) -> None:
    """Insert a Digital Contract ID column on the left. Space comes mostly from the description column,
    so amounts keep their width; the table may grow by up to 1 cm."""
    tbl = table._tbl
    grid_el = tbl.tblGrid
    cols = grid_el.findall(qn("w:gridCol"))
    widths = [int(c.get(qn("w:w")) or 0) for c in cols]
    new_w = int(Cm(ID_COL_CM).twips)
    need = new_w
    new = list(widths)
    if 0 <= desc_col < len(new):
        take = min(need, max(0, new[desc_col] - int(Cm(4.0).twips)))
        new[desc_col] -= take
        need -= take
    grow = min(need, int(Cm(1.0).twips))
    need -= grow
    others = [i for i in range(len(new)) if i != desc_col]
    pool = sum(new[i] for i in others) or 1
    for i in others:
        new[i] = int(new[i] * (pool - need) / pool)
    for c, w in zip(cols, new):
        c.set(qn("w:w"), str(w))
    gc = OxmlElement("w:gridCol")
    gc.set(qn("w:w"), str(new_w))
    grid_el.insert(0, gc)
    for r_idx, tr in enumerate(tbl.tr_lst):
        tcs = tr.tc_lst
        pos = 0
        for tc in tcs:  # reset each existing cell's width from the new grid
            span = _span(tc)
            tcw = tc.get_or_add_tcPr().find(qn("w:tcW"))
            if tcw is None:
                tcw = OxmlElement("w:tcW")
                tc.tcPr.insert(0, tcw)
            tcw.set(qn("w:w"), str(sum(new[pos:pos + span])))
            tcw.set(qn("w:type"), "dxa")
            pos += span
        first = tcs[0]
        tc = OxmlElement("w:tc")
        tcpr = copy.deepcopy(first.tcPr) if first.tcPr is not None else OxmlElement("w:tcPr")
        for tag in ("w:gridSpan", "w:vMerge", "w:hMerge"):
            for e in tcpr.findall(qn(tag)):
                tcpr.remove(e)
        w = tcpr.find(qn("w:tcW"))
        if w is None:
            w = OxmlElement("w:tcW")
            tcpr.insert(0, w)
        w.set(qn("w:w"), str(new_w))
        w.set(qn("w:type"), "dxa")
        tc.append(tcpr)
        p = OxmlElement("w:p")
        if r_idx in ids_by_row:
            hdr = ids_by_row[r_idx] == "Digital Contract ID"
            _run(p, ids_by_row[r_idx], bold=hdr, mono=not hdr, size=10 if hdr else 7.5)
        tc.append(p)
        first.addprevious(tc)
    tblpr = tbl.tblPr
    tw = tblpr.find(qn("w:tblW"))
    if tw is not None:
        tw.set(qn("w:type"), "auto")
        tw.set(qn("w:w"), "0")
    for e in tblpr.findall(qn("w:tblLayout")):
        tblpr.remove(e)
    lay = OxmlElement("w:tblLayout")
    lay.set(qn("w:type"), "fixed")
    tblpr.append(lay)


def _note_paragraphs(doc, after_el, meta, lines, fp, clause):
    texts = [(f"Digital Contract IDs assigned by ProPa on {date.today():%d %B %Y}: {len(lines)} lines, "
              f"total {sum(l['total'] for l in lines):,.2f}. Grid fingerprint {fp}. Each ID is fixed for the life of this SOW.", False)]
    if clause:
        texts.append((CLAUSE, True))
    anchor = after_el
    for text, is_clause in texts:
        p = doc.add_paragraph()
        r = p.add_run(text)
        r.font.size = Pt(9)
        r.italic = not is_clause
        p.paragraph_format.space_before = Pt(6)
        if not is_clause:
            r.font.color.rgb = RGBColor(0x1F, 0x5F, 0xD6)
        anchor.addnext(p._p)
        anchor = p._p


def tagged_docx(original: bytes, table_index: int, header_row: int, lines: list[dict], meta: dict, fp: str, clause: bool,
                desc_col: int = 0) -> bytes:
    doc = Document(io.BytesIO(original))
    table = doc.tables[table_index]
    ids = {l["row"]: l["id"] for l in lines}
    ids[header_row] = "Digital Contract ID"
    _add_id_column(table, ids, desc_col)
    _note_paragraphs(doc, table._tbl, meta, lines, fp, clause)
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def tagged_appendix_docx(lines: list[dict], meta: dict, fp: str, clause: bool, source: str) -> bytes:
    """For PDF, Excel or CSV input: a Word appendix carrying the tagged grid, ready to attach to the contract."""
    doc = Document()
    doc.styles["Normal"].font.name = "Calibri"
    doc.styles["Normal"].font.size = Pt(10)
    doc.add_heading("Appendix A — Budget grid with Digital Contract IDs", level=1)
    doc.add_paragraph(f"{meta.get('agreement') or 'Agreement'} · {meta.get('study') or ''} · {meta.get('vendor') or ''} · source: {source}")
    t = doc.add_table(rows=1, cols=6)
    t.style = "Table Grid"
    for i, h in enumerate(["Digital Contract ID", "Task Description", "Unit type", "Unit price", "No. of Units", "Total costs"]):
        t.rows[0].cells[i].text = ""
        t.rows[0].cells[i].paragraphs[0].add_run(h).bold = True
    section = None
    for l in lines:
        if l["section"] != section:
            section = l["section"]
            c = t.add_row().cells
            m = c[0].merge(c[5])
            m.text = ""
            m.paragraphs[0].add_run(section).bold = True
        c = t.add_row().cells
        c[0].text = ""
        _run(c[0].paragraphs[0]._p, l["id"], mono=True)
        c[1].text, c[2].text = l["desc"], l["unit_type"]
        c[3].text, c[4].text, c[5].text = f"{l['price']:,.2f}", f"{l['units']:,.2f}".rstrip("0").rstrip("."), f"{l['total']:,.2f}"
    c = t.add_row().cells
    m = c[0].merge(c[4])
    m.text = ""
    m.paragraphs[0].add_run("Total").bold = True
    c[5].text = f"{sum(l['total'] for l in lines):,.2f}"
    c[5].paragraphs[0].alignment = 2
    t.autofit = False
    widths = [Cm(3.9), Cm(5.0), Cm(1.9), Cm(2.3), Cm(2.0), Cm(2.6)]
    for gc, w in zip(t._tbl.tblGrid.findall(qn("w:gridCol")), widths):
        gc.set(qn("w:w"), str(int(w.twips)))
    for row in t.rows:
        for i, cell in enumerate(row.cells):
            cell.width = widths[i]
            merged = cell._tc is row.cells[0]._tc and i > 0
            if i >= 3 and not merged and len({id(c._tc) for c in row.cells}) == 6:
                for par in cell.paragraphs:
                    par.alignment = 2
    _note_paragraphs(doc, t._tbl, meta, lines, fp, clause)
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()
