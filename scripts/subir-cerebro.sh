#!/usr/bin/env bash
# Roda no SEU COMPUTADOR, dentro da pasta cerebro-jarvis.
# Sobe o cérebro para o repositório privado no GitHub.
set -e
REPO="https://github.com/jesserodolfo/cerebro-jarvis.git"

if [ ! -f SOUL.md ] || [ ! -f mapa.md ]; then
  echo "Rode este script de dentro da pasta cerebro-jarvis."; exit 1
fi
if grep -rIl --exclude-dir=.git -E "(sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|[0-9]{8,}:[A-Za-z0-9_-]{30,})" . ; then
  echo "PARE: achei algo parecido com chave ou token nos arquivos acima."; exit 1
fi

git init -q 2>/dev/null || true
git add .
git commit -qm "cerebro inicial do Jarvis" || echo "nada novo para commitar"
git branch -M main
git remote remove origin 2>/dev/null || true
git remote add origin "$REPO"
git push -u origin main
echo "Pronto. Confira no navegador: github.com/jesserodolfo/cerebro-jarvis"
