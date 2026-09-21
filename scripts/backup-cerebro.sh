#!/usr/bin/env bash
# Roda NA VPS. Salva no GitHub o que o Jarvis produziu e aprendeu no dia.
set -e
cd "$HOME/cerebro"
git pull --rebase -q || true
git add saidas aprendizados
if git diff --cached --quiet; then echo "Nada novo."; exit 0; fi
git commit -qm "jarvis: $(date +%Y-%m-%d)"
git push -q
echo "Backup feito: $(date)"
