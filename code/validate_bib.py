#!/usr/bin/env python3
"""
validate_bib.py — Validador bibliográfico para o livro Personalidade.

O que faz:
  1.  Lê references.bib e indexa todas as chaves disponíveis.
  2.  Varre todos os .qmd (capitulos/, coda/, apendices/, *.qmd raiz)
      atrás de citações no estilo Pandoc: @chave, [@chave], -@chave,
      [@chave1; @chave2], etc.
  3.  Reporta:
        * chaves citadas que não existem no .bib   (ERRO)
        * chaves no .bib não citadas em lugar nenhum (AVISO)
        * entradas .bib sem campos obrigatórios para ABNT (ERRO)
        * DOIs no .bib que não resolvem no doi.org   (AVISO/ERRO,
          configurável)
        * entradas marcadas como pending-verification (RELATÓRIO)
        * entradas marcadas como sugestao=true ainda no .bib       (AVISO)

Uso:
  python validate_bib.py                      # validação completa
  python validate_bib.py --no-doi             # pula checagem de DOI (offline)
  python validate_bib.py --fail-on-pending    # falha se houver pending-verification
  python validate_bib.py --json relatorio.json
  python validate_bib.py --quiet              # só erros

Códigos de saída:
  0  tudo certo (ou apenas avisos)
  1  erros encontrados
  2  uso incorreto / erro interno
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Iterable

try:
    import bibtexparser  # type: ignore
except ImportError:
    sys.stderr.write(
        "Erro: o pacote 'bibtexparser' é necessário.\n"
        "Instale com:  pip install bibtexparser==1.4.1\n"
    )
    sys.exit(2)

try:
    import requests  # type: ignore
    HAVE_REQUESTS = True
except ImportError:
    HAVE_REQUESTS = False


# =========================================================================
# Configuração
# =========================================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BIB_FILE = PROJECT_ROOT / "references" / "references.bib"
QMD_DIRS = [PROJECT_ROOT, PROJECT_ROOT / "capitulos",
            PROJECT_ROOT / "coda", PROJECT_ROOT / "apendices"]

# Campos mínimos por tipo BibTeX para uma referência ABNT decente
REQUIRED_FIELDS: dict[str, set[str]] = {
    "article":       {"author", "title", "journal", "year"},
    "book":          {"title", "year", "publisher"},  # author OR editor
    "incollection":  {"author", "title", "booktitle", "year", "publisher"},
    "inproceedings": {"author", "title", "booktitle", "year"},
    "misc":          {"title", "year"},
}

# Tipos para os quais aceitamos `editor` em vez de `author`
EDITOR_OK_TYPES = {"book", "proceedings"}

# Regex para citações Pandoc.
# Cobre: @chave, [@chave], -@chave, [@chave, p. 12], [@a; @b], {@chave}
# O lookbehind exclui:
#   [A-Za-z0-9_]  → evita matchear emails/handles ("user@host")
#   \\            → respeita escape Pandoc/Markdown ("\@usuario") usado para
#                   exibir literalmente uma arroba sem que seja tratada como cite
#   /             → URLs ("unsplash.com/@usuario", "github.com/@user")
CITE_RE = re.compile(r"(?<![A-Za-z0-9_\\/])@([A-Za-z0-9_:\-]+)")

# Prefixos do Quarto que NÃO são citações bibliográficas, são cross-refs:
# @tbl-... , @fig-... , @eq-... , @sec-... , @lst-... , @thm-... etc.
QUARTO_XREF_PREFIXES = (
    "tbl-", "fig-", "eq-", "sec-", "lst-", "exm-", "exr-", "thm-",
    "lem-", "cor-", "prp-", "cnj-", "def-", "rem-",
)


def _is_quarto_xref(key: str) -> bool:
    return any(key.startswith(p) for p in QUARTO_XREF_PREFIXES)

# Padrão de chave do projeto: autor_palavra_ano  (ASCII, snake_case)
KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*_[a-z0-9]+_(\d{4}|nd)$")


# =========================================================================
# Modelos
# =========================================================================

@dataclass
class Issue:
    level: str          # "ERROR" | "WARNING" | "INFO"
    category: str       # "orphan_cite" | "missing_field" | ...
    key: str | None
    message: str
    file: str | None = None
    line: int | None = None

    def fmt(self) -> str:
        loc = ""
        if self.file:
            loc = f"  [{Path(self.file).relative_to(PROJECT_ROOT)}"
            loc += f":{self.line}]" if self.line else "]"
        return f"  {self.level:7} {self.category:20} {self.key or '-':35} {self.message}{loc}"


@dataclass
class Report:
    issues: list[Issue] = field(default_factory=list)
    bib_keys: int = 0
    cited_keys: int = 0
    pending_count: int = 0
    suggestion_count: int = 0

    @property
    def has_errors(self) -> bool:
        return any(i.level == "ERROR" for i in self.issues)

    def add(self, *args, **kwargs) -> None:
        self.issues.append(Issue(*args, **kwargs))


# =========================================================================
# Leitura do .bib
# =========================================================================

def load_bib(path: Path) -> dict[str, dict]:
    if not path.exists():
        sys.stderr.write(f"Erro: {path} não encontrado.\n")
        sys.exit(2)
    with path.open(encoding="utf-8") as fh:
        bib_db = bibtexparser.load(fh)
    return {entry["ID"]: entry for entry in bib_db.entries}


# =========================================================================
# Leitura dos .qmd e extração de cites
# =========================================================================

def iter_qmd_files(dirs: Iterable[Path]) -> Iterable[Path]:
    seen: set[Path] = set()
    for d in dirs:
        if not d.exists():
            continue
        if d.is_file() and d.suffix == ".qmd":
            if d not in seen:
                seen.add(d)
                yield d
            continue
        # rglob = recursivo (procura também em subpastas, ex.: capitulos/parte-1-fundamentos/)
        for p in d.rglob("*.qmd"):
            if p not in seen:
                seen.add(p)
                yield p


def extract_cites(qmd_files: Iterable[Path]) -> dict[str, list[tuple[Path, int]]]:
    """
    Retorna {chave: [(arquivo, linha), ...]}.
    Ignora linhas dentro de blocos de código.
    """
    cites: dict[str, list[tuple[Path, int]]] = {}
    for qmd in qmd_files:
        in_code = False
        with qmd.open(encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, start=1):
                stripped = line.lstrip()
                if stripped.startswith("```"):
                    in_code = not in_code
                    continue
                if in_code:
                    continue
                for m in CITE_RE.finditer(line):
                    key = m.group(1)
                    if _is_quarto_xref(key):
                        continue  # cross-ref de tabela/figura, não é citação
                    cites.setdefault(key, []).append((qmd, lineno))
    return cites


# =========================================================================
# Validações estruturais
# =========================================================================

def check_orphan_cites(cites: dict, bib: dict, report: Report) -> None:
    for key, occurrences in cites.items():
        if key not in bib:
            for path, lineno in occurrences:
                report.add(
                    "ERROR", "orphan_cite", key,
                    "chave citada não existe em references.bib",
                    file=str(path), line=lineno,
                )


def check_unused_keys(cites: dict, bib: dict, report: Report) -> None:
    cited = set(cites.keys())
    for key, entry in bib.items():
        if key in cited:
            continue
        # Sugestões (keyword sugestao) podem ficar sem ser usadas
        if "sugestao" in (entry.get("keywords") or ""):
            continue
        report.add(
            "WARNING", "unused_entry", key,
            "entrada no .bib não é citada por nenhum capítulo",
        )


def check_required_fields(bib: dict, report: Report) -> None:
    for key, entry in bib.items():
        entry_type = entry.get("ENTRYTYPE", "").lower()
        required = REQUIRED_FIELDS.get(entry_type)
        if not required:
            continue
        missing = required - set(entry.keys())
        # books com `editor` em vez de `author`
        if entry_type in EDITOR_OK_TYPES and "author" in missing and "editor" in entry:
            missing.discard("author")
        for field_name in sorted(missing):
            report.add(
                "ERROR", "missing_field", key,
                f"campo obrigatório ausente para tipo @{entry_type}: '{field_name}'",
            )


def check_key_pattern(bib: dict, report: Report) -> None:
    for key in bib:
        if not KEY_PATTERN.match(key):
            report.add(
                "WARNING", "key_pattern", key,
                "chave foge ao padrão autor_palavra_ano (snake_case ASCII)",
            )


def collect_pending_and_suggestions(bib: dict, report: Report) -> None:
    for key, entry in bib.items():
        note = (entry.get("note") or "").lower()
        keywords = (entry.get("keywords") or "").lower()
        if "pending-verification" in note:
            report.pending_count += 1
            report.add(
                "INFO", "pending_verification", key,
                "entrada marcada como pending-verification",
            )
        if "sugestao" in keywords:
            report.suggestion_count += 1
            report.add(
                "WARNING", "suggestion_still_in_bib", key,
                "entrada-sugestão ainda no .bib — promover para uso ou remover",
            )


# =========================================================================
# Validação online de DOIs
# =========================================================================

def _check_one_doi(doi: str, timeout: int = 10) -> tuple[str, bool, str]:
    """Retorna (doi, ok, mensagem)."""
    if not HAVE_REQUESTS:
        return doi, False, "requests não instalado"
    url = f"https://doi.org/{doi}"
    try:
        # Crossref content negotiation: pede JSON pra ser barato
        headers = {"Accept": "application/vnd.citationstyles.csl+json"}
        r = requests.get(url, headers=headers, timeout=timeout,
                         allow_redirects=True)
        if r.status_code == 200:
            return doi, True, "OK"
        return doi, False, f"HTTP {r.status_code}"
    except requests.RequestException as exc:
        return doi, False, f"erro de rede: {exc!s}"


def check_dois(bib: dict, report: Report,
               max_workers: int = 8, fail_on_bad: bool = False) -> None:
    if not HAVE_REQUESTS:
        report.add(
            "WARNING", "doi_skip", None,
            "pacote 'requests' ausente — checagem de DOIs pulada",
        )
        return
    doi_to_keys: dict[str, list[str]] = {}
    for key, entry in bib.items():
        doi = (entry.get("doi") or "").strip()
        if doi:
            doi_to_keys.setdefault(doi, []).append(key)
    if not doi_to_keys:
        return

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_check_one_doi, doi): doi for doi in doi_to_keys}
        for fut in as_completed(futures):
            doi, ok, msg = fut.result()
            if ok:
                continue
            level = "ERROR" if fail_on_bad else "WARNING"
            for key in doi_to_keys[doi]:
                report.add(
                    level, "doi_unresolved", key,
                    f"DOI '{doi}' não resolveu ({msg})",
                )


# =========================================================================
# Saída
# =========================================================================

def print_report(report: Report, quiet: bool) -> None:
    counts = {"ERROR": 0, "WARNING": 0, "INFO": 0}
    for issue in report.issues:
        counts[issue.level] += 1
    if not quiet:
        # imprime issues agrupadas por nível
        for level in ("ERROR", "WARNING", "INFO"):
            level_issues = [i for i in report.issues if i.level == level]
            if not level_issues:
                continue
            print(f"\n=== {level} ({len(level_issues)}) ===")
            for issue in level_issues:
                print(issue.fmt())

    print("\n--- Resumo ---")
    print(f"  Entradas no .bib:           {report.bib_keys}")
    print(f"  Chaves citadas:             {report.cited_keys}")
    print(f"  Pending verification:       {report.pending_count}")
    print(f"  Sugestões ainda no .bib:    {report.suggestion_count}")
    print(f"  Erros:                      {counts['ERROR']}")
    print(f"  Avisos:                     {counts['WARNING']}")
    print(f"  Informações:                {counts['INFO']}")


def write_json(report: Report, path: Path) -> None:
    data = {
        "bib_keys": report.bib_keys,
        "cited_keys": report.cited_keys,
        "pending_count": report.pending_count,
        "suggestion_count": report.suggestion_count,
        "issues": [asdict(i) for i in report.issues],
    }
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                    encoding="utf-8")


# =========================================================================
# Main
# =========================================================================

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bib", type=Path, default=BIB_FILE)
    parser.add_argument("--no-doi", action="store_true",
                        help="Pular checagem de DOIs (modo offline)")
    parser.add_argument("--fail-on-bad-doi", action="store_true",
                        help="Tratar DOI que não resolve como ERRO")
    parser.add_argument("--fail-on-pending", action="store_true",
                        help="Tratar pending-verification como ERRO")
    parser.add_argument("--fail-on-warning", action="store_true",
                        help="Tratar qualquer AVISO como ERRO")
    parser.add_argument("--json", type=Path, default=None,
                        help="Gerar relatório JSON")
    parser.add_argument("--quiet", action="store_true",
                        help="Imprimir só o resumo, sem listar issues")
    args = parser.parse_args()

    bib = load_bib(args.bib)
    qmds = list(iter_qmd_files(QMD_DIRS))
    cites = extract_cites(qmds)

    report = Report(bib_keys=len(bib), cited_keys=len(cites))

    check_orphan_cites(cites, bib, report)
    check_unused_keys(cites, bib, report)
    check_required_fields(bib, report)
    check_key_pattern(bib, report)
    collect_pending_and_suggestions(bib, report)
    if not args.no_doi:
        check_dois(bib, report, fail_on_bad=args.fail_on_bad_doi)

    # Promove pending para ERROR, se solicitado
    if args.fail_on_pending:
        for issue in report.issues:
            if issue.category == "pending_verification":
                issue.level = "ERROR"

    print_report(report, quiet=args.quiet)

    if args.json:
        write_json(report, args.json)
        print(f"\nRelatório JSON salvo em {args.json}")

    has_errors = any(i.level == "ERROR" for i in report.issues)
    has_warnings = any(i.level == "WARNING" for i in report.issues)
    if has_errors:
        return 1
    if args.fail_on_warning and has_warnings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
