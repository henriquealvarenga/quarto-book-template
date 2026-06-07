#!/usr/bin/env python3
"""Para uma lista de entradas suspeitas, busca no Crossref por título+autor
e sugere o DOI provavelmente correto."""

import sys
import time
import requests
import bibtexparser
from pathlib import Path

BIB = Path(__file__).resolve().parent.parent / "references" / "references.bib"
UA = "PersonalidadeValidator/1.0 (mailto:henriquealvarenga@ufsj.edu.br)"

SUSPECT_KEYS = [
    # FAIL (DOI 404)
    "berrios_european_1993",
    "magallonneri_stigmatization_2013",
    # WARN com DOI apontando para artigo errado
    "cloninger_conceptual_2009",
    "kitamura_precedents_1999",
    "hadjipavlou_promising_2010",
    "gross_watching_2018",
]


def search(title: str, author: str) -> list[dict]:
    """Busca no Crossref por título + sobrenome do autor."""
    q = title[:120]
    params = {
        "query.bibliographic": q,
        "query.author": author.split(",")[0] if author else "",
        "rows": 5,
        "select": "DOI,title,author,issued,container-title,type",
    }
    r = requests.get("https://api.crossref.org/works",
                     params=params,
                     headers={"User-Agent": UA, "Accept": "application/json"},
                     timeout=20)
    r.raise_for_status()
    return r.json().get("message", {}).get("items", [])


def main() -> int:
    with BIB.open(encoding="utf-8") as fh:
        bib = bibtexparser.load(fh)
    entries = {e["ID"]: e for e in bib.entries}

    for key in SUSPECT_KEYS:
        e = entries.get(key)
        if not e:
            print(f"\n!! {key} — não encontrado no .bib")
            continue
        print(f"\n=== {key} ===")
        print(f"  bib title : {e.get('title', '')}")
        print(f"  bib author: {e.get('author', '')}")
        print(f"  bib year  : {e.get('year', '')}")
        print(f"  bib DOI atual: {e.get('doi', '(nenhum)')}")
        try:
            results = search(e.get('title', ''), e.get('author', ''))
        except Exception as exc:
            print(f"  ERRO ao buscar: {exc}")
            continue
        print(f"  --- top {len(results)} candidatos no Crossref ---")
        for i, r in enumerate(results[:3], 1):
            t = (r.get("title") or [""])[0]
            yr = r.get("issued", {}).get("date-parts", [[""]])[0][0]
            au = ""
            if r.get("author"):
                au = r["author"][0].get("family", "")
            jr = (r.get("container-title") or [""])[0]
            print(f"  [{i}] {r.get('DOI')}")
            print(f"      title : {t[:110]}")
            print(f"      author: {au} | year: {yr} | type: {r.get('type')}")
            print(f"      journal: {jr}")
        time.sleep(1)  # polite delay
    return 0


if __name__ == "__main__":
    sys.exit(main())
