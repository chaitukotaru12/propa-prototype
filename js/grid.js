/* ProPa grid engine
   Finds the budget grid inside a contract's budget sheet, reads its line items,
   assigns Digital Contract IDs, fingerprints the tagged grid, and compares an
   executed copy against what was tagged. Pure functions: no DOM, no storage. */
(function () {
  'use strict';

  const norm = v => (v == null ? '' : String(v).replace(/\s+/g, ' ').trim());
  const r2 = n => Math.round(n * 100) / 100;

  function num(v) {
    if (typeof v === 'number' && isFinite(v)) return v;
    const s = norm(v).replace(/[,$£€₹\s]/g, '');
    if (!s || !/^-?\d*\.?\d+$/.test(s)) return null;
    return Number(s);
  }

  // Order matters: "Unit type" must not be read as units, "Unit price" not as units.
  const HEADERS = [
    ['id', /digital\s*contract\s*id|contract\s*line\s*id|\bdcid\b/i],
    ['price', /unit\s*(price|cost|rate)|\brate\b|price\s*per/i],
    ['unitType', /unit\s*(type|of\s*measure)|\buom\b|\bbasis\b/i],
    ['total', /total/i],
    ['units', /no\.?\s*of\s*units|\bunits?\b|\bqty\b|quantity|volume/i],
    ['desc', /task|description|activity|service|deliverable|\bitem\b/i]
  ];
  function classify(cell) {
    const s = norm(cell);
    if (!s || s.length > 40) return null;
    for (const [key, re] of HEADERS) if (re.test(s)) return key;
    return null;
  }

  function findHeader(rows) {
    const limit = Math.min(rows.length, 40);
    for (let r = 0; r < limit; r++) {
      const row = rows[r] || [];
      const cols = {};
      row.forEach((cell, c) => {
        const k = classify(cell);
        if (k && cols[k] == null) cols[k] = c;
      });
      if (cols.price == null || cols.units == null || cols.total == null) continue;
      // The description heading may sit on this row or a row above (e.g. "Task Description" in A1).
      if (cols.desc == null) {
        for (let up = r - 1; up >= Math.max(0, r - 3) && cols.desc == null; up--) {
          (rows[up] || []).forEach((cell, c) => { if (cols.desc == null && classify(cell) === 'desc') cols.desc = c; });
        }
      }
      if (cols.desc == null) {
        const first = Math.min(...['price', 'units', 'total', 'unitType'].filter(k => cols[k] != null).map(k => cols[k]));
        cols.desc = first > 0 ? 0 : 0;
      }
      // A label sharing the header row in the description column is the first section (e.g. "Start-up").
      const lead = norm(row[cols.desc]);
      const section0 = lead && classify(lead) !== 'desc' ? lead : '';
      return { row: r, cols, section0 };
    }
    return null;
  }

  function parseRows(rows, sheetName) {
    const h = findHeader(rows);
    if (!h) {
      return { ok: false, error: 'No budget grid found. ProPa looks for columns for unit price, number of units and total cost.' };
    }
    let section = h.section0 || 'General';
    const lines = [], warnings = [];
    let declared = null;
    for (let r = h.row + 1; r < rows.length; r++) {
      const row = rows[r] || [];
      const g = k => (h.cols[k] == null ? null : row[h.cols[k]]);
      const d = norm(g('desc')), p = num(g('price')), u = num(g('units')), t = num(g('total')), ut = norm(g('unitType'));
      if (!d && p == null && u == null && t == null) continue;
      if (/^(grand\s*)?(sub\s*)?total\b|^sum\b/i.test(d)) { if (t != null) declared = t; continue; }
      if (d && p == null && u == null) { section = d; continue; }
      if (!d) { warnings.push({ row: r + 1, msg: 'Figures without a task description were skipped.' }); continue; }
      if (p == null || u == null) { warnings.push({ row: r + 1, msg: `"${d}" has no unit price or number of units, so it was not tagged.` }); continue; }
      const calc = r2(p * u);
      const total = t == null ? calc : r2(t);
      if (t != null && Math.abs(t - calc) > 0.01) {
        warnings.push({ row: r + 1, msg: `"${d}": total ${t.toFixed(2)} is not unit price × units (${calc.toFixed(2)}).` });
      }
      lines.push({ row: r + 1, section, desc: d, unitType: ut, price: p, units: u, total, idInFile: norm(g('id')) });
    }
    const sum = r2(lines.reduce((s, l) => s + l.total, 0));
    if (declared != null && Math.abs(declared - sum) > 0.01) {
      warnings.push({ row: null, msg: `The grid's total row (${declared.toFixed(2)}) differs from the sum of its lines (${sum.toFixed(2)}).` });
    }
    if (!lines.length) return { ok: false, error: 'A grid header was found, but no priced line items under it.' };
    const sections = [...new Set(lines.map(l => l.section))];
    return { ok: true, sheet: sheetName || '', headerRow: h.row + 1, lines, warnings, declared, sum, sections };
  }

  function assignIds(lines, prefix) {
    const codes = {}, used = new Set(), count = {};
    for (const l of lines) {
      if (!codes[l.section]) {
        let base = (l.section.replace(/[^A-Za-z]/g, '').slice(0, 3) || 'GEN').toUpperCase();
        let code = base, n = 2;
        while (used.has(code)) code = base.slice(0, 2) + n++;
        used.add(code); codes[l.section] = code;
      }
      const code = codes[l.section];
      count[code] = (count[code] || 0) + 1;
      l.id = `DC-${prefix}-${code}-${String(count[code]).padStart(3, '0')}`;
    }
    return lines;
  }

  // FNV-1a, run twice with different seeds: a short, deterministic fingerprint of the tagged grid.
  function fnv(str, seed) {
    let h = seed >>> 0;
    for (let i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619) >>> 0; }
    return h.toString(16).padStart(8, '0');
  }
  function fingerprint(lines) {
    const s = lines.map(l => [l.id, l.desc.toLowerCase(), l.unitType.toLowerCase(), l.price, l.units, r2(l.total)].join('|')).join('\n');
    return (fnv(s, 2166136261) + fnv(s, 3735928559)).toUpperCase();
  }

  // Compare the tagged grid with the grid parsed from the executed copy.
  function compare(tagged, executed) {
    const diffs = [];
    if (tagged.length !== executed.length) {
      diffs.push(`${tagged.length} lines were tagged; the executed copy has ${executed.length}.`);
    }
    const n = Math.min(tagged.length, executed.length);
    for (let i = 0; i < n; i++) {
      const a = tagged[i], b = executed[i];
      const f = [];
      if (a.desc.toLowerCase() !== b.desc.toLowerCase()) f.push(`task "${b.desc}"`);
      if (a.unitType.toLowerCase() !== b.unitType.toLowerCase()) f.push(`unit type "${b.unitType}"`);
      if (a.price !== b.price) f.push(`unit price ${b.price}`);
      if (a.units !== b.units) f.push(`units ${b.units} (tagged ${a.units})`);
      if (b.idInFile && b.idInFile !== a.id) f.push(`ID ${b.idInFile}`);
      if (f.length) diffs.push(`${a.id} ${a.desc}: ${f.join(', ')}`);
    }
    return { ok: diffs.length === 0, diffs };
  }

  // Minimal CSV reader, used only if the spreadsheet library is unavailable.
  function parseCsv(text) {
    const rows = []; let row = [], cell = '', q = false;
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (q) {
        if (c === '"' && text[i + 1] === '"') { cell += '"'; i++; }
        else if (c === '"') q = false;
        else cell += c;
      } else if (c === '"') q = true;
      else if (c === ',') { row.push(cell); cell = ''; }
      else if (c === '\n' || c === '\r') {
        if (c === '\r' && text[i + 1] === '\n') i++;
        row.push(cell); rows.push(row); row = []; cell = '';
      } else cell += c;
    }
    if (cell || row.length) { row.push(cell); rows.push(row); }
    return rows;
  }

  // Read a File into rows, choosing the first sheet that contains a budget grid.
  function readFile(file) {
    return new Promise((resolve, reject) => {
      const isCsv = /\.csv$/i.test(file.name);
      const fr = new FileReader();
      fr.onerror = () => reject(new Error('The file could not be read.'));
      fr.onload = () => {
        try {
          if (window.XLSX) {
            const wb = isCsv ? XLSX.read(fr.result, { type: 'string' }) : XLSX.read(new Uint8Array(fr.result), { type: 'array' });
            let fallback = null;
            for (const name of wb.SheetNames) {
              const rows = XLSX.utils.sheet_to_json(wb.Sheets[name], { header: 1, raw: true, blankrows: true, defval: null });
              const parsed = parseRows(rows, name);
              if (parsed.ok) return resolve(parsed);
              if (!fallback) fallback = parsed;
            }
            return resolve(fallback || { ok: false, error: 'The workbook has no sheets.' });
          }
          if (isCsv) return resolve(parseRows(parseCsv(fr.result), 'CSV'));
          reject(new Error('Excel support did not load. Save the budget as CSV and try again.'));
        } catch (e) { reject(new Error('The file is not a readable spreadsheet.')); }
      };
      if (isCsv) fr.readAsText(file); else fr.readAsArrayBuffer(file);
    });
  }

  window.ProPaGrid = { parseRows, assignIds, fingerprint, compare, readFile, num, r2 };
})();
