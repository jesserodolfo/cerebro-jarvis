# Cérebro do Jarvis
Agente de conteúdo do Jessé Machado, rodando em Hermes Agent.

## Ordem para colocar no ar
1. No seu computador, dentro desta pasta: `bash scripts/subir-cerebro.sh`
2. Na VPS, como usuário do agente: baixe e rode `scripts/instalar-na-vps.sh`
   (ou siga o PROMPT-DEPLOY.md no Claude Code)
3. Aponte o Hermes para `~/cerebro` e carregue o `SOUL.md` como identidade
4. Instale as skills de `skills/` no diretório de skills do Hermes
5. Conecte o Telegram e trave para responder só ao Jessé
6. Rode o TESTE DO CÉREBRO (abaixo) antes de qualquer rotina

## Skill watch (vídeo)
`skills/watch` veio de https://github.com/bradautomates/claude-video (MIT, v0.3.2).
Precisa de `python3`, `ffmpeg` e `yt-dlp` na máquina do Hermes
(Mac: `brew install ffmpeg yt-dlp`). Na primeira vez, a skill roda um
assistente de setup. Com `GEMINI_API_KEY` em `~/.config/watch/.env` o Gemini
assiste o vídeo; sem chave, ela extrai frames e legenda localmente.
Para atualizar, copie de novo a pasta `skills/watch` do repositório original.

## Teste do cérebro
Mande ao Jarvis:

    Leia o mapa.md e a pasta contexto. Rode a skill pauta-matinal e me mostre
    o resultado bruto.

Passou se as 3 pautas citam caso real do Jessé (Logzz, GM, Marcelo, MelaVitta,
casas de ração) e nenhuma cai nos ângulos queimados.
Falhou se aparecer conteúdo genérico. Aí o problema é contexto, não skill.

## O que ainda está pendente no contexto
- precos-DECISAO.md: preço da auditoria
- referencias-modelagem.md: o que observar em cada perfil de referência
- subcrencas.md: 8 em quarentena esperando confirmação
- provas.md: casas de ração com +43% de lucro (caso separado ou não)
