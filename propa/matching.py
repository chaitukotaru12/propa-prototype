"""Map vendor invoice lines to Digital Contract IDs.

Vendor invoices usually quote only the PO number, with free-text descriptions. ProPa
matches each invoice line to a contract line using three explainable signals:
the description (with common abbreviations expanded), the unit price, and the unit
type. Every suggestion carries its reasons, and anything uncertain goes to the PM.
"""
from __future__ import annotations

import difflib
import re

from . import grid as G

INV_HEADERS = [
    ("id", re.compile(r"digital\s*contract\s*id|contract\s*line\s*id|\bdcid\b", re.I)),
    ("rate", re.compile(r"unit\s*(price|rate|cost)|\brate\b|\bprice\b", re.I)),
    ("amount", re.compile(r"amount|line\s*total|\bvalue\b|\btotal\b", re.I)),
    ("qty", re.compile(r"\bqty\b|quantity|no\.?\s*of\s*units|\bunits?\b|\bhours\b", re.I)),
    ("desc", re.compile(r"description|service|\bitem\b|task|activity|particulars", re.I)),
]
SKIP_ROW = re.compile(r"^(sub\s*total|total|grand\s*total|total\s*due|tax|vat|gst|amount\s*due|balance)\b", re.I)

ABBREV = {
    "pm": "project management", "mgmt": "management", "mgt": "management", "proj": "project",
    "mon": "monitoring", "mntr": "monitoring", "dm": "data management", "sae": "safety case", "pv": "safety case",
    "db": "database", "siv": "site initiation visit", "csr": "clinical study report", "cov": "close out visit",
    "imv": "monitoring visit", "rmv": "remote monitoring visit", "onsite": "onsite", "start": "start",
}
STOP = {"the", "of", "for", "and", "a", "an", "in", "to", "fee", "fees", "charge", "charges", "service", "services",
        "invoice", "period", "per", "monthly", "month", "months", "cost", "costs", "work", "activity", "activities",
        "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
        "january", "february", "march", "april", "june", "july", "august", "september", "october", "november", "december"}
UNIT_WORDS = {"visit": "visit", "visits": "visit", "month": "month", "monthly": "month", "months": "month", "case": "case",
              "cases": "case", "site": "site", "sites": "site", "report": "report", "reports": "report", "hour": "hour", "hours": "hour"}


def _singular(w: str) -> str:
    return w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w


def tokens(text: str) -> list[str]:
    t = G.norm(text).lower()
    t = re.sub(r"on[\s-]+site", "onsite", t)
    t = re.sub(r"close[\s-]+out", "close out", t)
    t = re.sub(r"start[\s-]+up", "startup", t)
    words = re.findall(r"[a-z]+", t)
    out = []
    for w in words:
        for e in ABBREV.get(w, w).split():
            e = _singular(e)
            if e not in STOP and len(e) > 1:
                out.append(e)
    return out


def unit_hint(text: str) -> set[str]:
    return {UNIT_WORDS[w] for w in re.findall(r"[a-z]+", G.norm(text).lower()) if w in UNIT_WORDS}


def norm_phrase(text: str) -> str:
    return " ".join(tokens(text))


# ---------- reading the invoice ----------
def _find_header(rows):
    for r, row in enumerate(rows[:40]):
        cols = {}
        for c, cell in enumerate(row or []):
            s = G.norm(cell)
            if not s or len(s) > 30:
                continue
            for key, rx in INV_HEADERS:
                if rx.search(s):
                    cols.setdefault(key, c)
                    break
        if "desc" in cols and "amount" in cols and ("qty" in cols or "rate" in cols):
            return r, cols
    return None


def parse_invoice(contract_like: dict) -> dict:
    """contract_like: output of documents.read_contract for the invoice file."""
    for t in contract_like["tables"]:
        h = _find_header(t["rows"])
        if not h:
            continue
        hr, cols = h
        lines, declared = [], None
        for r in range(hr + 1, len(t["rows"])):
            row = t["rows"][r] or []
            g = lambda k: row[cols[k]] if k in cols and cols[k] < len(row) else None
            d = G.norm(g("desc"))
            amt, q, rate = G.num(g("amount")), G.num(g("qty")), G.num(g("rate"))
            if not d and amt is None:
                continue
            if SKIP_ROW.search(d):
                if re.match(r"(?i)(grand\s*)?total|total\s*due|amount\s*due", d) and amt is not None:
                    declared = amt
                continue
            if amt is None and q is not None and rate is not None:
                amt = round(q * rate, 2)
            if amt is None:
                continue
            if q is None and rate is None:
                q, rate = 1.0, amt
            elif q is None:
                q = round(amt / rate, 4) if rate else 1.0
            elif rate is None:
                rate = round(amt / q, 4) if q else amt
            lines.append({"n": len(lines) + 1, "desc": d, "qty": q, "rate": rate, "amount": round(amt, 2),
                          "id_in_file": G.norm(g("id"))})
        if lines:
            return {"ok": True, "label": t["label"], "lines": lines, "declared": declared,
                    "sum": round(sum(l["amount"] for l in lines), 2)}
    return {"ok": False, "error": "No invoice lines found. ProPa looks for a table with description, quantity or rate, and amount."}


def invoice_meta(contract_like: dict, name: str) -> dict:
    kv = {}
    for t in contract_like["tables"]:
        for row in t["rows"]:
            cells = [G.norm(c) for c in row if G.norm(c)]
            if len(cells) == 2:
                kv[cells[0].lower()] = cells[1]
    text = contract_like.get("text", "") + "\n" + name
    def pick(keys, rx):
        for k, v in kv.items():
            if re.fullmatch(keys, k, re.I):
                return v
        m = re.search(rx, text, re.I)
        return m.group(1).strip() if m else ""
    return {
        "invoice_no": pick(r"invoice\s*(no\.?|number|#)", r"invoice\s*(?:no\.?|number|#)\s*[:#]?\s*([A-Z0-9][A-Z0-9-/]{3,30})"),
        "po": pick(r"(po|p\.o\.|purchase\s*order)\s*(no\.?|number|#)?", r"(?:\bPO\b|P\.O\.|purchase\s*order)\s*(?:no\.?|number|#)?\s*[:#]?\s*([A-Z0-9-]{6,20})"),
        "period": pick(r"(service\s*)?period", r"period\s*[:#]?\s*([A-Za-z]+\s+\d{4})"),
        "reference": pick(r"reference|ref\.?|sow|contract", r"(SOW[-\s]?\d+)"),
    }


# ---------- matching ----------
def _text_sim(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    dice = 2 * len(sa & sb) / (len(sa) + len(sb))
    seq = difflib.SequenceMatcher(None, " ".join(sorted(sa)), " ".join(sorted(sb))).ratio()
    return max(dice, 0.9 * seq)


def _price_score(billed: float, contract: float) -> tuple[float, bool]:
    if not contract:
        return 0.0, False
    diff = abs(billed - contract) / contract
    if diff <= 0.005:
        return 1.0, True
    return max(0.0, 1 - diff * 4) * 0.6, False


def match_line(inv: dict, contract_lines: list[dict], learned: dict[str, str] | None = None) -> dict:
    by_id = {l["id"]: l for l in contract_lines}
    if inv.get("id_in_file") in by_id:
        return {"id": inv["id_in_file"], "score": 1.0, "level": "exact", "reasons": ["Digital Contract ID quoted on the invoice"]}
    phrase = norm_phrase(inv["desc"])
    if learned and phrase in learned and learned[phrase] in by_id:
        return {"id": learned[phrase], "score": 1.0, "level": "learned",
                "reasons": ["Same wording was confirmed by the PM on an earlier invoice"]}
    itok, ihint = tokens(inv["desc"]), unit_hint(inv["desc"])
    scored = []
    for l in contract_lines:
        ts = _text_sim(itok, tokens(l["desc"]))
        ps, exact = _price_score(inv["rate"], l["price"])
        lunit = unit_hint(l["unit_type"]) | unit_hint(l["desc"])
        us = 1.0 if ihint and ihint & lunit else 0.0
        score = 0.6 * ts + 0.3 * ps + 0.1 * us
        scored.append((score, ts, exact, us, l))
    scored.sort(key=lambda x: -x[0])
    best = scored[0]
    second = scored[1][0] if len(scored) > 1 else 0.0
    score, ts, exact, us, l = best
    reasons = []
    if ts >= 0.6:
        reasons.append(f'description matches "{l["desc"]}"')
    elif ts >= 0.35:
        reasons.append(f'description partly matches "{l["desc"]}"')
    if exact:
        reasons.append(f"unit price {G_money(l['price'])} matches the contract")
    else:
        reasons.append(f"unit price {G_money(inv['rate'])} differs from the contract's {G_money(l['price'])}")
    if us:
        reasons.append(f"unit ({l['unit_type'] or 'unit'}) fits")
    if score >= 0.8 and exact and score - second >= 0.1:
        level = "high"
    elif score >= 0.45 and ts >= 0.35:
        level = "check"
        if score - second < 0.1:
            reasons.append(f'close to "{scored[1][4]["desc"]}" too')
    else:
        return {"id": None, "score": round(score, 2), "level": "none",
                "reasons": [f'no contract line fits (closest: "{l["desc"]}", {score:.0%})']}
    return {"id": l["id"], "score": round(score, 2), "level": level, "reasons": reasons}


def G_money(x: float) -> str:
    return f"${x:,.2f}"


def match_invoice(invoice_lines: list[dict], contract_lines: list[dict], learned: dict[str, str] | None = None) -> list[dict]:
    return [{**inv, **{"match": match_line(inv, contract_lines, learned)}} for inv in invoice_lines]


def line_balances(mapped: list[tuple[dict, str | None]], contract_lines: list[dict], billed_before: dict[str, float]) -> list[dict]:
    """mapped: (invoice line, chosen ID or None). Returns per-ID balance rows for IDs on this invoice."""
    by_id = {l["id"]: l for l in contract_lines}
    units, amounts, rates = {}, {}, {}
    for inv, cid in mapped:
        if cid in by_id:
            units[cid] = units.get(cid, 0) + inv["qty"]
            amounts[cid] = amounts.get(cid, 0) + inv["amount"]
            rates.setdefault(cid, set()).add(round(inv["rate"], 2))
    rows = []
    for cid, u in units.items():
        l = by_id[cid]
        before = billed_before.get(cid, 0.0)
        left = round(l["units"] - before - u, 4)
        rate_ok = all(abs(r - l["price"]) <= 0.005 * l["price"] for r in rates[cid])
        flags = []
        if left < -1e-9:
            flags.append(f"over by {-left:g} {l['unit_type'] or 'units'}")
        if not rate_ok:
            flags.append(f"rate differs from contract ({', '.join(G_money(r) for r in sorted(rates[cid]) if abs(r - l['price']) > 0.005 * l['price'])} vs {G_money(l['price'])})")
        status = "; ".join(flags) or "within contract"
        allowed = max(0.0, l["units"] - before)
        approvable = round(min(u, allowed) * l["price"], 2)  # within what is left, at the contracted price
        approvable = min(approvable, round(amounts[cid], 2))
        rows.append({"approvable": approvable, "held": round(amounts[cid] - approvable, 2),"id": cid, "task": l["desc"], "contracted": l["units"], "before": before, "this": u,
                     "left": left, "amount": round(amounts[cid], 2), "contract_price": l["price"], "rate_ok": rate_ok, "status": status})
    return rows
