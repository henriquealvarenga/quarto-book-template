#!/usr/bin/env python3
"""
unwrap_paragraphs.py — Remove quebras de linha 'hard' dentro de parágrafos
de arquivos .qmd, preservando blocos estruturais (YAML front matter,
tabelas, listas, citações, código, callouts, cabeçalhos).

Uso:
    python code/unwrap_paragraphs.py FILE [FILE ...]   # edita in-place
    python code/unwrap_paragraphs.py --dry FILE        # mostra diff
"""

from __future__ import annotations
import argparse
import difflib
import re
import sys
from pathlib import Path


# Prefixos que indicam "não desfazer wrap" — a linha tem semântica própria
PROTECTED_PREFIXES = (
    "#",     # cabeçalho ATX
    ">",     # blockquote (mantém uma quebra por linha)
    "|",     # tabela
    "- ",    # lista
    "* ",    # lista
    "+ ",    # lista
    ":::",   # callout / fenced div
    "::",    # raw
    "---",   # separador / setext / YAML
    "===",   # setext h1
    "```",   # code fence
    "~~~",   # code fence
    "    ",  # bloco de código indentado (4 espaços) — conservador
    "\t",    # tab idem
)

# Listas numeradas: 1. / 2. / 10. etc.
NUMBERED_RE = re.compile(r"^\d+\.\s")
# Sublinhas de continuação de lista (recuo)
INDENTED_CONT_RE = re.compile(r"^( {2,}|\t)\S")


def is_protected(line: str) -> bool:
    stripped = line.lstrip()
    if not stripped:
        return False
    if stripped.startswith(PROTECTED_PREFIXES):
        return True
    if NUMBERED_RE.match(stripped):
        return True
    return False


def split_yaml_front_matter(text: str) -> tuple[str, str]:
    """Se houver YAML front matter no início, retorna (yaml, body)."""
    if not text.startswith("---\n") and not text.startswith("---\r\n"):
        return "", text
    lines = text.splitlines(keepends=True)
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].rstrip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return "", text
    yaml = "".join(lines[: end_idx + 1])
    body = "".join(lines[end_idx + 1 :])
    return yaml, body


def unwrap_paragraphs(text: str) -> str:
    yaml, body = split_yaml_front_matter(text)
    out_lines: list[str] = []
    in_code = False
    para_buf: list[str] = []

    def flush_para():
        if not para_buf:
            return
        joined = " ".join(s.rstrip() for s in para_buf)
        # colapsa múltiplos espaços que possam ter surgido
        joined = re.sub(r"  +", " ", joined).strip()
        out_lines.append(joined + "\n")
        para_buf.clear()

    for raw in body.splitlines(keepends=False):
        # toggle code fence
        if raw.lstrip().startswith(("```", "~~~")):
            flush_para()
            out_lines.append(raw + "\n")
            in_code = not in_code
            continue
        if in_code:
            out_lines.append(raw + "\n")
            continue

        if raw.strip() == "":
            flush_para()
            out_lines.append("\n")
            continue

        if is_protected(raw) or INDENTED_CONT_RE.match(raw):
            # Linha estrutural: descarrega parágrafo pendente e mantém a linha intacta.
            flush_para()
            out_lines.append(raw + "\n")
            continue

        # Linha "normal" — acumula no parágrafo
        para_buf.append(raw)

    flush_para()

    # remove triplas linhas em branco
    new_body = "".join(out_lines)
    new_body = re.sub(r"\n{3,}", "\n\n", new_body)
    return yaml + new_body


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--dry", action="store_true",
                    help="Mostra diff sem editar arquivos")
    args = ap.parse_args()

    changed = 0
    for path in args.files:
        if not path.exists():
            print(f"!! pulado (não existe): {path}", file=sys.stderr)
            continue
        original = path.read_text(encoding="utf-8")
        rewritten = unwrap_paragraphs(original)
        if original == rewritten:
            print(f"OK (sem mudanças): {path}")
            continue
        changed += 1
        if args.dry:
            diff = difflib.unified_diff(
                original.splitlines(keepends=True),
                rewritten.splitlines(keepends=True),
                fromfile=str(path), tofile=f"{path} (unwrapped)",
            )
            sys.stdout.writelines(diff)
        else:
            path.write_text(rewritten, encoding="utf-8")
            print(f"reescrito: {path}")

    print(f"\nTotal alterado: {changed}/{len(args.files)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
