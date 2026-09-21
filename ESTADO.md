# Estado do Jarvis
Atualizado em 2026-09-21. Descreve como o agente está instalado de verdade.
O PROMPT-DEPLOY.md previa VPS; a instalação real ficou no Mac.

## Como o Hermes está instalado
- Máquina: Mac do Jessé (8 GB de RAM). A VPS 103.199.187.109 não tem Hermes
  e não foi alterada.
- Hermes Agent v0.21.3, instalação direta via git em ~/.hermes/hermes-agent.
  Sem Docker.
- Perfil dedicado: jarvis. O perfil default (Hermes desktop) não foi alterado.
- Atalho: `jarvis` equivale a `hermes -p jarvis`.
- No app Hermes desktop: ícone J no canto inferior esquerdo.

## Onde está cada coisa
| o quê | onde |
|---|---|
| cérebro, pasta de edição | ~/Documents/cerebro-jarvis |
| cérebro, pasta que o Jarvis lê | ~/cerebro (clone do mesmo repositório) |
| repositório | github.com/jesserodolfo/cerebro-jarvis, privado, via HTTPS |
| perfil | ~/.hermes/profiles/jarvis |
| identidade | ~/.hermes/profiles/jarvis/SOUL.md (cópia de ~/cerebro/SOUL.md) |
| identidade original | ~/.hermes/profiles/jarvis/soul-original.md |
| skills | ~/.hermes/profiles/jarvis/skills/jarvis/ (6 skills) |
| configuração | ~/.hermes/profiles/jarvis/config.yaml |
| segredos | ~/.hermes/profiles/jarvis/.env (token do Telegram). Nunca no cérebro |
| serviço do gateway | ~/Library/LaunchAgents/ai.hermes.gateway-jarvis.plist |
| logs | ~/.hermes/profiles/jarvis/logs/gateway.log e gateway.error.log |

## Configuração aplicada
- terminal.cwd = /Users/dmelo/cerebro
- compression.threshold = 0.8
- agent.agent_cache.memory_high_mb = 2560
- modelo: claude-opus-4-8, provedor anthropic, login pela conta Claude do
  Jessé. O Hermes lê a credencial do Claude Code, não guarda token no .env.
- Telegram: bot @jarvis_jesse_bot, TELEGRAM_ALLOWED_USERS com 1 único ID
  (o do Jessé). Sem acesso aberto.

## Adaptação feita nas skills
Só no frontmatter da cópia instalada no perfil. O corpo é idêntico ao do
cérebro. Linhas acrescentadas em cada SKILL.md:

    version: 1.0.0
    metadata:
      hermes:
        category: jarvis

A cópia no perfil não acompanha o git pull. Mudou skill ou SOUL no
repositório: reinstalar no perfil.

## Como reiniciar o agente
    jarvis gateway restart     # reinicia
    jarvis gateway status      # confere
    jarvis gateway stop        # para
    jarvis gateway start       # liga
Não afeta o Hermes desktop nem o perfil default.

## Limite de memória e como reverter
No macOS não existe MemoryMax (é do systemd, Linux). Ficou só o teto
flexível: acima de 2560 MB o gateway descarta cache de conversa antiga.
Não mata o processo.

Reverter:

    jarvis config set agent.agent_cache.memory_high_mb auto

Na migração para VPS: MemoryMax=2.5G na unit do systemd.

## Como desfazer tudo
    jarvis gateway stop
    jarvis gateway uninstall
    hermes profile delete jarvis
O cérebro continua no GitHub e em ~/cerebro.

## Pendente
1. Segurança: o token OAuth da conta Claude (sk-ant-oat01, validade 1 ano)
   apareceu em um print no dia 2026-09-21. Decisão do Jessé: aceitar o
   risco. O login vence em 2027-09-21. Lembrete de renovação na agenda
   em 2027-08-20 (sexta), com o passo a passo na descrição.
2. Custo: conferir em claude.ai, Configurações, Uso, se "extra usage" está
   ligado e pôr limite de gasto. O Jarvis divide a cota de 5 horas do Max
   com o Claude Code.
3. BotFather: /setjoingroups em Disable para o @jarvis_jesse_bot.
4. Teste do cérebro: PASSOU em 2026-09-21. pauta-matinal pelo Telegram,
   3 pautas com caso real (Logzz duas vezes, Marcelo), notas 86, 80 e 78,
   nenhum ângulo queimado, número conferido em provas.md. Saída em
   saidas/relatorios/2026-09-21-pauta.md. Rodada 1 de 5 antes de cron.
   Observação: a resposta no Telegram usou travessão nos títulos
   ("Pauta 1", traço, "Nota"), o que o SOUL proíbe. O arquivo salvo saiu
   limpo. Candidato a regra via registrar-feedback.
5. As 75 skills embutidas vieram junto no perfil (imessage, email,
   computer-use). Decidir quais desabilitar depois da validação.
6. WhatsApp: só depois de validar o conteúdo, e só com chip dedicado.
   O WhatsApp do Hermes usa Baileys: risco de ban e acesso às conversas
   do número pareado.
7. Zernio: não existe skill. Construir só depois da validação, entregando
   rascunho para aprovação, nunca publicação direta.
7b. Skill metricas-instagram instalada em 2026-09-21 (7 skills no perfil).
   Falta: chave do Zernio SOMENTE LEITURA gravada como ZERNIO_API_KEY em
   ~/.hermes/profiles/jarvis/.env, e a primeira rodada com --dias 366.
   O script foi testado só com amostra local, ainda não contra a API.
   Depois de mudar skill ou SOUL no repositório:
   git -C ~/cerebro pull && bash ~/cerebro/scripts/instalar-skills-hermes.sh
8. Crons do ROTINAS.md: nenhum criado. Regra: cada skill rodada na mão
   pelo menos 5 vezes antes.
9. Migração para VPS: instalar Hermes lá do zero, usuário não root,
   systemd com MemoryMax. A VPS tem cerca de 3 GB livres.
10. Contexto ainda incompleto: ver a lista no README.md.
11. scripts/instalar-na-vps.sh não foi usado. Vale para a migração.
