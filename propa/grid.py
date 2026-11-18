"""ProPa grid engine (Python).

Finds a budget grid in a table, reads its sections and line items, checks the
arithmetic, assigns Digital Contract IDs and fingerprints the tagged grid.
Mirrors js/grid.js in the browser prototype.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

HEADERS = [
    ("id", re.compile(r"digital\s*contract\s*id|contract\s*line\s*id|\bdcid\b", re.I)),
    ("price", re.compile(r"unit\s*(price|cost|rate)|\brate\b|price\s*per", re.I)),
    ("unit_type", re.compile(r"unit\s*(type|of\s*measure)|\buom\b|\bbasis\b", re.I)),
    ("total", re.compile(r"total", re.I)),
    ("units", re.compile(r"no\.?\s*of\s*units|\bunits?\b|\bqty\b|quantity|volume", re.I)),
    ("desc", re.compile(r"task|description|activity|service|deliverable|\bitem\b", re.I)),
]
TOTAL_ROW = re.compile(r"^(grand\s*)?(sub\s*)?total\b|^sum\b", re.I)


def norm(v: Any) -> str:
    return re.sub(r"\s+", " ", "" if v is None else str(v)).strip()


def num(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[,$£€₹\s]|USD|INR|EUR|GBP", "", norm(v), flags=re.I)
    if not s or not re.fullmatch(r"-?\d*\.?\d+", s):
        return None
    return float(s)


def classify(cell: Any) -> str | None:
    s = norm(cell)
    if not s or len(s) > 40:
        return None
    for key, rx in HEADERS:
        if rx.search(s):
            return key
    return None


def find_header(rows: list[list[Any]]) -> dict | None:
    for r, row in enumerate(rows[:40]):
        cols: dict[str, int] = {}
        for c, cell in enumerate(row or []):
            k = classify(cell)
            if k and k not in cols:
                cols[k] = c
        if not {"price", "units", "total"} <= cols.keys():
            continue
        if "desc" not in cols:  # heading may sit in a row above, e.g. "Task Description" in A1
            for up in range(r - 1, max(-1, r - 4), -1):
                for c, cell in enumerate(rows[up] or []):
                    if "desc" not in cols and classify(cell) == "desc":
                        cols["desc"] = c
        cols.setdefault("desc", 0)
        lead = norm(row[cols["desc"]]) if cols["desc"] < len(row) else ""
        section0 = lead if lead and classify(lead) != "desc" else ""
        return {"row": r, "cols": cols, "section0": section0}
    return None


def parse_rows(rows: list[list[Any]]) -> dict:
    """Parse a table (list of rows) into budget lines. Row numbers are 0-based table rows."""
    h = find_header(rows)
    if not h:
        return {"ok": False, "error": "No columns for unit price, number of units and total cost."}
    cols = h["cols"]
    section = h["section0"] or "General"
    lines, warnings = [], []
    declared = None

    def g(row, key):
        c = cols.get(key)
        return row[c] if c is not None and c < len(row) else None

    for r in range(h["row"] + 1, len(rows)):
        row = rows[r] or []
        d, p, u, t = norm(g(row, "desc")), num(g(row, "price")), num(g(row, "units")), num(g(row, "total"))
        ut = norm(g(row, "unit_type"))
        if not d and p is None and u is None and t is None:
            continue
        if TOTAL_ROW.search(d):
            if t is not None:
                declared = t
            continue
        if d and p is None and u is None:
            section = d
            continue
        if not d:
            warnings.append({"row": r, "msg": "Figures without a task description were skipped."})
            continue
        if p is None or u is None:
            warnings.append({"row": r, "msg": f'"{d}" has no unit price or number of units, so it was not tagged.'})
            continue
        calc = round(p * u, 2)
        total = calc if t is None else round(t, 2)
        if t is not None and abs(t - calc) > 0.01:
            warnings.append({"row": r, "msg": f'"{d}": total {t:,.2f} is not unit price × units ({calc:,.2f}).'})
        lines.append({"row": r, "section": section, "desc": d, "unit_type": ut, "price": p, "units": u,
                      "total": total, "id_in_file": norm(g(row, "id"))})
    total_sum = round(sum(l["total"] for l in lines), 2)
    if declared is not None and abs(declared - total_sum) > 0.01:
        warnings.append({"row": None, "msg": f"The grid's total row ({declared:,.2f}) differs from the sum of its lines ({total_sum:,.2f})."})
    if not lines:
        return {"ok": False, "error": "A grid header was found, but no priced line items under it."}
    sections = list(dict.fromkeys(l["section"] for l in lines))
    return {"ok": True, "header_row": h["row"], "cols": cols, "lines": lines, "warnings": warnings,
            "declared": declared, "sum": total_sum, "sections": sections}


def section_codes(sections: list[str]) -> dict[str, str]:
    codes, used = {}, set()
    for s in sections:
        base = (re.sub(r"[^A-Za-z]", "", s)[:3] or "GEN").upper()
        code, n = base, 2
        while code in used:
            code = f"{base[:2]}{n}"
            n += 1
        used.add(code)
        codes[s] = code
    return codes


def assign_ids(lines: list[dict], prefix: str) -> list[dict]:
    codes = section_codes(list(dict.fromkeys(l["section"] for l in lines)))
    count: dict[str, int] = {}
    out = []
    for l in lines:
        code = codes[l["section"]]
        count[code] = count.get(code, 0) + 1
        out.append({**l, "id": f"DC-{prefix}-{code}-{count[code]:03d}"})
    return out


def fingerprint(lines: list[dict]) -> str:
    s = "\n".join("|".join([l["id"], l["desc"].lower(), l["unit_type"].lower(), f'{l["price"]:.4f}',
                            f'{l["units"]:.4f}', f'{l["total"]:.2f}']) for l in lines)
    return hashlib.sha256(s.encode()).hexdigest()[:16].upper()


def default_prefix(study: str, vendor: str) -> str:
    digits = (re.findall(r"\d+", study or "") or ["000"])[-1][-3:].zfill(3)
    initials = "".join(w[0] for w in re.findall(r"[A-Za-z]+", vendor or "") if w[0].isupper())[:3] or "V"
    return f"{digits}{initials.upper()}"
