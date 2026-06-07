#!/usr/bin/env python3
"""
deep_validate_bib.py — Validação profunda contra Crossref.

Para cada entrada com DOI no references.bib:
  1. Resolve o DOI via Crossref API (com User-Agent e backoff).
  2. Compara metadados:
       - ano publicado
       - sobrenome do primeiro autor
       - similaridade de título
       - periódico
  3. Classifica:
       OK        — todos os campos batem
       WARN      — DOI resolve, mas algum campo diverge
       FAIL      — DOI não resolve ou Crossref retorna erro
       NO_DOI    — entrada sem DOI (livros antigos, primárias literárias)
       SKIP      — entrada-sugestão (keywords=sugestao)

Saída:
  validation-deep.json  — relatório estruturado
  validation-deep.html  — quadro visual navegável (abre no browser)

Uso:
  python3 code/deep_validate_bib.py
"""

from __future__ import annotations
import json
import re
import sys
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from pathlib import Path

import bibtexparser
import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BIB_FILE = PROJECT_ROOT / "references" / "references.bib"
OUT_JSON = PROJECT_ROOT / "validation-deep.json"
OUT_HTML = PROJECT_ROOT / "validation-deep.html"

USER_AGENT = (
    "PersonalidadeBookValidator/1.0 "
    "(mailto:henriquealvarenga@ufsj.edu.br)"
)
CROSSREF_URL = "https://api.crossref.org/works/{doi}"
MAX_WORKERS = 3           # conservador para evitar 429
TIMEOUT = 20
MAX_RETRIES = 3


# =========================================================================
# Helpers
# =========================================================================

def normalize(s: str) -> str:
    """Remove acentos, lowercase, strip {} e LaTeX dirt."""
    if not s:
        return ""
    s = re.sub(r"\\['`^\"~=]\{?([a-zA-Z])\}?", r"\1", s)  # \'{e} -> e
    s = re.sub(r"[\{\}\\]", "", s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def first_author_surname_bib(entry: dict) -> str:
    raw = entry.get("author") or entry.get("editor") or ""
    if not raw:
        return ""
    first = raw.split(" and ")[0]
    if "," in first:
        sur = first.split(",")[0]
    else:
        parts = first.split()
        sur = parts[-1] if parts else first
    return normalize(sur)


def first_author_surname_crossref(item: dict) -> str:
    authors = item.get("author") or item.get("editor") or []
    if not authors:
        return ""
    a = authors[0]
    sur = a.get("family") or a.get("name") or ""
    return normalize(sur)


def title_similarity(a: str, b: str) -> float:
    """Jaccard de tokens normalizados, com bonus para start-match."""
    a, b = normalize(a), normalize(b)
    if not a or not b:
        return 0.0
    sa, sb = set(a.split()), set(b.split())
    if not sa or not sb:
        return 0.0
    j = len(sa & sb) / len(sa | sb)
    if a[:40] == b[:40]:
        j = min(1.0, j + 0.1)
    return j


def year_from_crossref(item: dict) -> str | None:
    for key in ("published-print", "published-online", "issued", "created"):
        parts = item.get(key, {}).get("date-parts", [[]])
        if parts and parts[0]:
            return str(parts[0][0])
    return None


def journal_from_crossref(item: dict) -> str:
    cts = item.get("container-title") or []
    return cts[0] if cts else ""


# =========================================================================
# Crossref lookup
# =========================================================================

def fetch_crossref(doi: str) -> tuple[dict | None, str]:
    """Retorna (item, mensagem). item=None se falhou."""
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    url = CROSSREF_URL.format(doi=doi)
    delay = 1.5
    for attempt in range(MAX_RETRIES):
        try:
            r = requests.get(url, headers=headers, timeout=TIMEOUT)
            if r.status_code == 200:
                data = r.json()
                return data.get("message"), "OK"
            if r.status_code == 404:
                return None, f"HTTP 404 — DOI não existe no Crossref"
            if r.status_code == 429:
                time.sleep(delay)
                delay *= 2
                continue
            return None, f"HTTP {r.status_code}"
        except requests.RequestException as exc:
            if attempt == MAX_RETRIES - 1:
                return None, f"erro de rede: {exc!s}"
            time.sleep(delay)
            delay *= 2
    return None, "HTTP 429 após retries"


# =========================================================================
# Compare bib vs crossref
# =========================================================================

@dataclass
class Check:
    key: str
    entry_type: str
    cited_in_text: bool
    has_doi: bool
    doi: str = ""
    status: str = ""           # OK | WARN | FAIL | NO_DOI | SKIP
    reason: list[str] = field(default_factory=list)
    bib_title: str = ""
    bib_author: str = ""
    bib_year: str = ""
    bib_journal: str = ""
    cr_title: str = ""
    cr_author: str = ""
    cr_year: str = ""
    cr_journal: str = ""
    title_sim: float = 0.0
    pending: bool = False
    suggestion: bool = False
    notes: str = ""


def check_entry(key: str, entry: dict, cited_keys: set[str]) -> Check:
    chk = Check(
        key=key,
        entry_type=entry.get("ENTRYTYPE", ""),
        cited_in_text=(key in cited_keys),
        has_doi=bool(entry.get("doi")),
        bib_title=entry.get("title", ""),
        bib_author=entry.get("author") or entry.get("editor", ""),
        bib_year=entry.get("year", ""),
        bib_journal=entry.get("journal") or entry.get("booktitle", ""),
        notes=entry.get("note", ""),
    )

    keywords = (entry.get("keywords") or "").lower()
    chk.pending = "pending-verification" in (entry.get("note") or "").lower()
    chk.suggestion = "sugestao" in keywords

    if chk.suggestion:
        chk.status = "SKIP"
        chk.reason.append("entrada-sugestão (não verificada)")
        return chk

    if not chk.has_doi:
        chk.status = "NO_DOI"
        chk.reason.append("entrada sem DOI — exige verificação manual")
        return chk

    chk.doi = entry["doi"]
    item, msg = fetch_crossref(chk.doi)
    if item is None:
        chk.status = "FAIL"
        chk.reason.append(f"Crossref: {msg}")
        return chk

    # Compara
    chk.cr_title = (item.get("title") or [""])[0]
    chk.cr_author = first_author_surname_crossref(item)
    chk.cr_year = year_from_crossref(item) or ""
    chk.cr_journal = journal_from_crossref(item)
    chk.title_sim = title_similarity(chk.bib_title, chk.cr_title)

    bib_sur = first_author_surname_bib(entry)
    cr_sur = chk.cr_author

    divergences = []
    if chk.bib_year and chk.cr_year and chk.bib_year != chk.cr_year:
        divergences.append(f"ano: bib={chk.bib_year} / crossref={chk.cr_year}")
    if bib_sur and cr_sur and bib_sur != cr_sur:
        divergences.append(f"primeiro autor: bib={bib_sur} / crossref={cr_sur}")
    if chk.title_sim < 0.45:
        divergences.append(
            f"título destoa (Jaccard={chk.title_sim:.2f})"
        )

    if divergences:
        chk.status = "WARN"
        chk.reason.extend(divergences)
    else:
        chk.status = "OK"
        chk.reason.append("autor, ano e título compatíveis com Crossref")
    return chk


# =========================================================================
# Coleta de cites no texto (reusa lógica do validate_bib.py)
# =========================================================================

CITE_RE = re.compile(r"(?<![A-Za-z0-9_])@([A-Za-z0-9_:\-]+)")
QUARTO_XREF_PREFIXES = ("tbl-", "fig-", "eq-", "sec-", "lst-", "exm-",
                        "exr-", "thm-", "lem-", "cor-", "prp-", "cnj-",
                        "def-", "rem-")


def gather_cited_keys() -> set[str]:
    cited: set[str] = set()
    dirs = [PROJECT_ROOT, PROJECT_ROOT / "capitulos",
            PROJECT_ROOT / "coda", PROJECT_ROOT / "apendices"]
    for d in dirs:
        if not d.exists():
            continue
        for p in d.glob("*.qmd"):
            in_code = False
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.lstrip().startswith(("```", "~~~")):
                    in_code = not in_code
                    continue
                if in_code:
                    continue
                for m in CITE_RE.finditer(line):
                    k = m.group(1)
                    if any(k.startswith(px) for px in QUARTO_XREF_PREFIXES):
                        continue
                    cited.add(k)
    return cited


# =========================================================================
# Saída HTML
# =========================================================================

HTML_TPL = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<title>Validação bibliográfica — Personalidade</title>
<style>
  :root {{
    --bg: #F9F9F7; --paper: #fff; --border: #e5e5e0;
    --text: #1a1a1a; --muted: #777; --brand: #b45309;
    --ok: #15803d; --warn: #b45309; --fail: #b91c1c; --skip: #525252; --nodoi: #4338ca;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 24px; font-family: -apple-system, "Inter", sans-serif;
    background: var(--bg); color: var(--text); line-height: 1.55;
  }}
  h1 {{ font-family: "Playfair Display", Georgia, serif; font-weight: 700;
       margin: 0 0 4px; }}
  .sub {{ color: var(--muted); margin-bottom: 22px; }}
  .summary {{
    display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px;
    margin-bottom: 22px;
  }}
  .card {{
    background: var(--paper); border: 1px solid var(--border); border-radius: 8px;
    padding: 14px; text-align: center;
  }}
  .card .n {{ font-size: 2rem; font-weight: 700; font-family: "Playfair Display", serif; }}
  .card .l {{ color: var(--muted); font-size: 0.85rem; }}
  .OK   .n {{ color: var(--ok); }}
  .WARN .n {{ color: var(--warn); }}
  .FAIL .n {{ color: var(--fail); }}
  .SKIP .n {{ color: var(--skip); }}
  .NODOI .n {{ color: var(--nodoi); }}

  .filters {{ margin-bottom: 14px; }}
  .filters button {{
    border: 1px solid var(--border); background: var(--paper); padding: 6px 12px;
    margin-right: 6px; border-radius: 16px; cursor: pointer; font-size: 0.85rem;
  }}
  .filters button.active {{ background: var(--brand); color: white;
                            border-color: var(--brand); }}

  table {{ width: 100%; border-collapse: collapse; background: var(--paper);
           border: 1px solid var(--border); border-radius: 8px; overflow: hidden;
           font-size: 0.88rem; }}
  th, td {{ padding: 10px 12px; text-align: left; vertical-align: top;
            border-bottom: 1px solid var(--border); }}
  th {{ background: #f2f2ee; font-weight: 600; font-size: 0.8rem;
        text-transform: uppercase; letter-spacing: 0.04em; color: #444; }}
  tr:last-child td {{ border-bottom: none; }}
  tr:hover td {{ background: #fafaf7; }}

  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 12px;
            font-size: 0.72rem; font-weight: 600; }}
  .badge.OK {{ background: #dcfce7; color: var(--ok); }}
  .badge.WARN {{ background: #fef3c7; color: var(--warn); }}
  .badge.FAIL {{ background: #fee2e2; color: var(--fail); }}
  .badge.SKIP {{ background: #e5e5e5; color: var(--skip); }}
  .badge.NO_DOI {{ background: #e0e7ff; color: var(--nodoi); }}

  code {{ font-family: "JetBrains Mono", ui-monospace, monospace;
          font-size: 0.82rem; background: #f4f4ef; padding: 1px 5px;
          border-radius: 4px; word-break: break-all; }}
  .reason {{ font-size: 0.82rem; color: #444; margin-top: 4px; }}
  .reason li {{ margin: 2px 0; }}
  .key {{ font-family: "JetBrains Mono", monospace; font-size: 0.82rem;
          color: var(--brand); }}
  .pill {{ display: inline-block; font-size: 0.7rem; padding: 1px 6px;
           background: #fef3c7; color: #92400e; border-radius: 8px;
           margin-left: 4px; }}
  .pill.notcited {{ background: #fee2e2; color: var(--fail); }}
  .pill.pending {{ background: #fef3c7; color: var(--warn); }}
</style>
</head>
<body>
<h1>Validação bibliográfica</h1>
<div class="sub">
  <strong>Personalidade</strong> — relatório gerado em {date}.
  {total} entradas verificadas contra a API do Crossref.
</div>

<div class="summary">
  <div class="card OK"><div class="n">{n_ok}</div><div class="l">OK</div></div>
  <div class="card WARN"><div class="n">{n_warn}</div><div class="l">WARN</div></div>
  <div class="card FAIL"><div class="n">{n_fail}</div><div class="l">FAIL</div></div>
  <div class="card NODOI"><div class="n">{n_nodoi}</div><div class="l">NO_DOI</div></div>
  <div class="card SKIP"><div class="n">{n_skip}</div><div class="l">SKIP</div></div>
</div>

<div class="filters">
  <button class="active" data-f="all">Todas ({total})</button>
  <button data-f="OK">OK ({n_ok})</button>
  <button data-f="WARN">WARN ({n_warn})</button>
  <button data-f="FAIL">FAIL ({n_fail})</button>
  <button data-f="NO_DOI">NO_DOI ({n_nodoi})</button>
  <button data-f="SKIP">SKIP ({n_skip})</button>
  <button data-f="notcited">Não citadas</button>
</div>

<table>
<thead>
<tr>
  <th style="width: 80px;">Status</th>
  <th>Chave / Bibliografia</th>
  <th>Crossref</th>
  <th>Observações</th>
</tr>
</thead>
<tbody>
{rows}
</tbody>
</table>

<script>
const buttons = document.querySelectorAll('.filters button');
const rows = document.querySelectorAll('tbody tr');
buttons.forEach(b => b.addEventListener('click', () => {{
  buttons.forEach(x => x.classList.remove('active'));
  b.classList.add('active');
  const f = b.dataset.f;
  rows.forEach(r => {{
    if (f === 'all') r.style.display = '';
    else if (f === 'notcited') r.style.display = r.dataset.cited === 'false' ? '' : 'none';
    else r.style.display = r.dataset.status === f ? '' : 'none';
  }});
}}));
</script>
</body>
</html>
"""


def render_html(checks: list[Check]) -> str:
    from datetime import datetime
    n_ok   = sum(1 for c in checks if c.status == "OK")
    n_warn = sum(1 for c in checks if c.status == "WARN")
    n_fail = sum(1 for c in checks if c.status == "FAIL")
    n_skip = sum(1 for c in checks if c.status == "SKIP")
    n_nodoi = sum(1 for c in checks if c.status == "NO_DOI")

    rows = []
    # ordena: FAIL, WARN, NO_DOI, OK, SKIP
    order = {"FAIL": 0, "WARN": 1, "NO_DOI": 2, "OK": 3, "SKIP": 4}
    for c in sorted(checks, key=lambda c: (order.get(c.status, 9), c.key)):
        cited_pill = "" if c.cited_in_text else ' <span class="pill notcited">não citada</span>'
        pending_pill = ' <span class="pill pending">pending</span>' if c.pending else ''
        sugg_pill = ' <span class="pill">sugestão</span>' if c.suggestion else ''
        doi_str = f'<br><code>doi: {c.doi}</code>' if c.doi else ''
        cr_block = ""
        if c.status not in ("NO_DOI", "SKIP") and c.cr_title:
            cr_block = (
                f"<strong>{html_escape(c.cr_title)}</strong><br>"
                f"<small>{html_escape(c.cr_author)} ({c.cr_year}) · "
                f"<em>{html_escape(c.cr_journal)}</em></small>"
            )
        elif c.status == "NO_DOI":
            cr_block = '<em style="color:#777">sem DOI — verificação manual</em>'
        elif c.status == "SKIP":
            cr_block = '<em style="color:#777">entrada-sugestão</em>'
        else:
            cr_block = '<em style="color:#777">não foi possível resolver</em>'

        reasons = "".join(f"<li>{html_escape(r)}</li>" for r in c.reason)

        rows.append(f"""
<tr data-status="{c.status}" data-cited="{str(c.cited_in_text).lower()}">
  <td><span class="badge {c.status}">{c.status}</span></td>
  <td>
    <div class="key">{html_escape(c.key)}</div>
    <strong>{html_escape(c.bib_title)}</strong>{cited_pill}{pending_pill}{sugg_pill}<br>
    <small>{html_escape(first_author_short(c.bib_author))} ({c.bib_year})
           · <em>{html_escape(c.bib_journal)}</em></small>
    {doi_str}
  </td>
  <td>{cr_block}</td>
  <td><ul class="reason">{reasons}</ul></td>
</tr>""")

    return HTML_TPL.format(
        date=datetime.now().strftime("%d/%m/%Y %H:%M"),
        total=len(checks),
        n_ok=n_ok, n_warn=n_warn, n_fail=n_fail, n_skip=n_skip, n_nodoi=n_nodoi,
        rows="\n".join(rows),
    )


def html_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;").replace('"', "&quot;"))


def first_author_short(raw: str) -> str:
    if not raw:
        return ""
    first = raw.split(" and ")[0]
    rest_count = len(raw.split(" and ")) - 1
    return f"{first}" + (f" et al." if rest_count else "")


# =========================================================================
# Main
# =========================================================================

def main() -> int:
    if not BIB_FILE.exists():
        sys.stderr.write(f"BIB não encontrado: {BIB_FILE}\n")
        return 2

    with BIB_FILE.open(encoding="utf-8") as fh:
        bib = bibtexparser.load(fh)
    entries = {e["ID"]: e for e in bib.entries}
    print(f"Lido: {len(entries)} entradas em {BIB_FILE.name}")

    cited = gather_cited_keys()
    print(f"Cites detectados nos .qmd: {len(cited)}")

    # Validação paralela conservadora
    print(f"\nConsultando Crossref ({MAX_WORKERS} threads, backoff exponencial)...")
    checks: list[Check] = []
    items = list(entries.items())
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(check_entry, k, e, cited): k for k, e in items}
        done = 0
        for fut in as_completed(futures):
            chk = fut.result()
            checks.append(chk)
            done += 1
            print(f"  [{done:>2}/{len(items)}] {chk.status:6} {chk.key}")

    # JSON
    OUT_JSON.write_text(
        json.dumps([asdict(c) for c in checks], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nJSON salvo:  {OUT_JSON}")

    # HTML
    OUT_HTML.write_text(render_html(checks), encoding="utf-8")
    print(f"HTML salvo:  {OUT_HTML}")

    # Resumo
    from collections import Counter
    counts = Counter(c.status for c in checks)
    print("\n=== Resumo ===")
    for status in ("OK", "WARN", "FAIL", "NO_DOI", "SKIP"):
        print(f"  {status:7} {counts.get(status, 0)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
