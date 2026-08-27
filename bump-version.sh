#!/usr/bin/env bash
# bump-version.sh — Atualiza a versão do TicianoFlix (SemVer: MAJOR.MINOR.PATCH)
#
# Uso:
#   ./bump-version.sh <major|minor|patch|none> "Título do changelog" ["item1|item2|item3"]
#
# Regras (padrão de mercado / SemVer):
#   major  → quebra de compatibilidade (ex: 1.5.1 → 2.0.0)
#   minor  → nova funcionalidade          (ex: 1.5.1 → 1.6.0)
#   patch  → correção de bug              (ex: 1.5.1 → 1.5.2)
#   none   → sem mudança de versão (docs/chore/refactor)
#
# Atualiza os 3 lugares que exibem a versão:
#   1. Badge na sidebar (index.html: logo-version)
#   2. Changelog do app (_CHANGELOG em static/app.js)
#   3. README.md (Changelog)
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
INDEX="$DIR/index.html"
APPJS="$DIR/static/app.js"
README="$DIR/README.md"

TYPE="${1:-none}"
TITLE="${2:-}"
ITEMS_RAW="${3:-}"

if [ -z "$TITLE" ] && [ "$TYPE" != "none" ]; then
  echo "✗ Uso: ./bump-version.sh <major|minor|patch|none> \"Título\" [\"item1|item2\"]" >&2
  exit 1
fi

# ─── Toda a lógica em Python (portável macOS/Linux) ─────────
NEW_VERSION="$(TYPE="$TYPE" TITLE="$TITLE" ITEMS="$ITEMS_RAW" INDEX="$INDEX" APPJS="$APPJS" README="$README" python3 <<'PY'
import os, re, sys

index_path = os.environ["INDEX"]
appjs_path = os.environ["APPJS"]
readme_path = os.environ["README"]
bump_type = os.environ["TYPE"]
title = os.environ["TITLE"]
items_raw = os.environ["ITEMS"]

html = open(index_path).read()
appjs = open(appjs_path).read()      # o _CHANGELOG mora aqui desde o split do frontend
readme = open(readme_path).read()

# 1. Versão atual (badge na sidebar)
m = re.search(r'logo-version"[^>]*>v([0-9]+)\.([0-9]+)(?:\.([0-9]+))?', html)
if not m:
    print("ERRO: versão atual não encontrada no badge", file=sys.stderr)
    sys.exit(1)
major, minor = int(m.group(1)), int(m.group(2))
patch = int(m.group(3)) if m.group(3) else 0
print(f"Versão atual: v{major}.{minor}.{patch}", file=sys.stderr)

# 2. Calcular nova
if bump_type == "major":
    major, minor, patch = major + 1, 0, 0
elif bump_type == "minor":
    minor, patch = minor + 1, 0
elif bump_type == "patch":
    patch += 1
elif bump_type != "none":
    print(f"ERRO: tipo inválido '{bump_type}' (use major|minor|patch|none)", file=sys.stderr)
    sys.exit(1)

new_full = f"{major}.{minor}.{patch}"
display = new_full if not new_full.endswith(".0") else new_full[:-2]
print(f"Nova versão: v{new_full} (exibida como v{display})", file=sys.stderr)

if bump_type == "none":
    print("SEM_MUDANCA")
    sys.exit(0)

# 3. Badge
html_new = re.sub(r'(logo-version"[^>]*>v)[0-9.]+', rf'\g<1>{display}', html, count=1)
assert html_new != html, "badge não substituído"
html = html_new

# 4. _CHANGELOG (insere nova entrada no topo)
items = [i.strip() for i in items_raw.split("|") if i.strip()] if items_raw else []
changes = "".join(f"        '{i.replace(chr(39), chr(92)+chr(39))}',\n" for i in items)
entry = (
    "    {\n"
    f"      version: '{new_full}',\n"
    f"      title: '{title.replace(chr(39), chr(92)+chr(39))}',\n"
    "      changes: [\n" + changes + "      ],\n"
    "    },\n"
)
marker = "const _CHANGELOG = [\n"
assert marker in appjs, "marker _CHANGELOG não encontrado em static/app.js"
appjs = appjs.replace(marker, marker + entry, 1)

# 5. README changelog
block = f"### v{display} — {title}\n"
for i in items:
    block += f"\n- {i}\n"
rmarker = "## 📋 Changelog\n"
assert rmarker in readme, "marker Changelog não encontrado"
readme = readme.replace(rmarker, rmarker + "\n" + block + "\n", 1)

open(index_path, "w").write(html)
open(appjs_path, "w").write(appjs)
open(readme_path, "w").write(readme)
print("OK")
PY
)"

echo "$NEW_VERSION"
if [ "$NEW_VERSION" = "SEM_MUDANCA" ]; then
  echo "ℹ️ Tipo 'none' — versão inalterada."
  exit 0
fi
if [ "$NEW_VERSION" != "OK" ]; then
  exit 1
fi
echo ""
echo "✅ Feito. Commit sugerido:"
CUR_DISPLAY="$(python3 -c "
import re
html = open('$INDEX').read()
m = re.search(r'logo-version\"[^>]*>v([0-9.]+)', html)
print('v' + m.group(1) if m else '?')
")"
echo "   git add index.html static/app.js README.md && git commit -m \"chore: $CUR_DISPLAY — $TITLE\""
