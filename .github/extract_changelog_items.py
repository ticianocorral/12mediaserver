#!/usr/bin/env python3
"""Extrai os bullets da seção 'O que muda'/'Correção' do corpo de um PR.

Uso: python3 extract_changelog_items.py "<body do PR>"
Imprime os bullets separados por "|" (formato aceito pelo bump-version.sh).
Fallback: string vazia (o workflow usa o título).
"""
import re
import sys

body = sys.argv[1] if len(sys.argv) > 1 else ""

# Seção-alvo: "## O que muda" / "## Correção" / "## Mudanças" até o próximo "##"
m = re.search(
    r"##\s*(?:O que muda|Corre[cç][aã]o|Mudan[çc]as)\s*\n(.*?)(?=\n##\s|\Z)",
    body,
    re.S | re.I,
)
if m:
    bullets = re.findall(r"^\s*[-*]\s+(.+)$", m.group(1), re.M)
    bullets = [b.strip() for b in bullets if b.strip() and not b.startswith("- [")]
    if bullets:
        print("|".join(bullets))
