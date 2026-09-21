#!/usr/bin/env bash
# Roda NA VPS, logado como o usuário do agente (NÃO root).
# Cria a chave de acesso ao repositório e clona o cérebro em ~/cerebro.
set -e
if [ "$(id -u)" = "0" ]; then echo "Não rode como root. Entre como o usuário do agente."; exit 1; fi

KEY="$HOME/.ssh/cerebro_jarvis"
mkdir -p "$HOME/.ssh" && chmod 700 "$HOME/.ssh"

if [ ! -f "$KEY" ]; then
  ssh-keygen -t ed25519 -C "jarvis-vps" -f "$KEY" -N ""
fi

if ! grep -q "Host github-cerebro" "$HOME/.ssh/config" 2>/dev/null; then
cat >> "$HOME/.ssh/config" << CFG
Host github-cerebro
  HostName github.com
  User git
  IdentityFile $KEY
  IdentitiesOnly yes
CFG
chmod 600 "$HOME/.ssh/config"
fi

echo ""
echo "=== COPIE A LINHA ABAIXO ==="
cat "$KEY.pub"
echo "============================"
echo "Cole em: GitHub, repositório cerebro-jarvis, Settings, Deploy keys,"
echo "Add deploy key. Marque Allow write access. Depois aperte Enter aqui."
read -r _

ssh -o StrictHostKeyChecking=accept-new -T git@github-cerebro 2>&1 | grep -qi "successfully authenticated" \
  && echo "Chave aceita pelo GitHub." \
  || { echo "O GitHub ainda não aceitou a chave. Confira a deploy key e rode de novo."; exit 1; }

if [ -d "$HOME/cerebro/.git" ]; then
  cd "$HOME/cerebro" && git pull
else
  git clone git@github-cerebro:jesserodolfo/cerebro-jarvis.git "$HOME/cerebro"
fi
chmod +x "$HOME/cerebro/scripts/"*.sh
echo "Cérebro em $HOME/cerebro"
ls "$HOME/cerebro/contexto"
