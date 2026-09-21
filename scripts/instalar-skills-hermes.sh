#!/usr/bin/env bash
# Roda no Mac. Copia SOUL.md e as skills de ~/cerebro para o perfil jarvis do
# Hermes. Idempotente: apaga a categoria jarvis e recria. Rode depois de todo
# git pull que mexer em SOUL.md ou em skills/.
set -e
CEREBRO="${CEREBRO:-$HOME/cerebro}"
PERFIL="${PERFIL:-$HOME/.hermes/profiles/jarvis}"

[ -f "$CEREBRO/SOUL.md" ] || { echo "Não achei $CEREBRO/SOUL.md"; exit 1; }
[ -d "$PERFIL" ] || { echo "Não achei o perfil em $PERFIL"; exit 1; }

cp "$CEREBRO/SOUL.md" "$PERFIL/SOUL.md"
rm -rf "$PERFIL/skills/jarvis"
mkdir -p "$PERFIL/skills/jarvis"

for dir in "$CEREBRO"/skills/*/; do
  nome=$(basename "$dir")
  cp -R "$dir" "$PERFIL/skills/jarvis/$nome"
  # O Hermes pede version no frontmatter. O corpo da skill não muda.
  python3 - "$PERFIL/skills/jarvis/$nome/SKILL.md" <<'PY'
import re, sys
p = sys.argv[1]
t = open(p, encoding="utf-8").read()
m = re.match(r"^---\n(.*?)\n---\n", t, re.S)
fm = m.group(1)
if "version:" not in fm:
    fm += "\nversion: 1.0.0\nmetadata:\n  hermes:\n    category: jarvis"
open(p, "w", encoding="utf-8").write("---\n" + fm + "\n---\n" + t[m.end():])
PY
  echo "ok $nome"
done
echo "SOUL e $(ls "$PERFIL/skills/jarvis" | wc -l | tr -d ' ') skills instalados em $PERFIL"
echo "Sessão aberta do Jarvis só enxerga a mudança depois de: jarvis gateway restart"
