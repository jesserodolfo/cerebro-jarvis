# Painel Jarvis: agentes, abas e voz do ElevenLabs

Data: 2026-10-20. Aprovado pelo Jessé (plano Prumo com GO): "GO na especificação completa.
Dr. Felipe em vermelho, voz pelas 3 amostras via API, teto de 2.000 créditos por dia."
Visual: "pode ser em azul mantendo a cor que fechamos".

## Contexto
O painel mostrava os agentes só como "no ar" ou "fora". O Jessé quer ver cada agente e rotina
com status, última atividade e erro, e depois controlar tudo por voz (fase 2, fora deste
trabalho). Ele achou o visual "bem embolado, muito ruim, bem confuso": cards de texto, alertas
repetidos, Second Brain ocupando meia tela.

## Decisão
1. Agentes, só leitura (fase 1).
   - `coletores/agentes.py`: agentes do Mac (Jarvis Telegram, rotinas com.jesusepop.*, rotina
     TikTok 8h, FabIA) com status, última atividade e último erro. Lê launchctl, logs, o
     state.db do Hermes em mode=ro (só hora, nunca texto) e o scheduled-tasks.json.
   - `coletores/melavitta.py`: agentes da VPS por uma única chamada SSH só leitura com comando
     fixo no código (`docker inspect` e `pm2 jlist`), cache de 5 min. Nunca lê log de
     container, banco ou conteúdo de conversa.
   - Dr. Felipe parado aparece em vermelho.
2. Painel em 5 abas no mesmo `index.html`, mantendo o azul atual: Visão geral (orbe com 4
   números, conversa como legenda, linha do tempo de hoje, só os 3 alertas críticos), Agenda
   (semana × redes), Projetos (1 número grande por projeto, detalhe em gaveta), Cérebro (grafo
   em tela cheia) e Custos (semana por projeto contra a fatia). HTML único, sem CDN, sem fonte
   externa. Orbe em Canvas 2D.
3. Voz: ElevenLabs Flash v2.5 em streaming, frase a frase, pela rota `POST /api/voz` do
   servidor. Chave e id da voz em `painel/.env` (ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID),
   nunca no navegador. Voz criada no Voice Design pela API (3 amostras, o Jessé escolhe).
   Teto de 2.000 créditos por dia em `config.json`; estourou ou falhou, a fala vai pra voz do
   navegador. O resumo do dia fica curto pra caber no teto.

## Descartado
- Disparar rotina ou conversar com agente pelo painel: fica pra fase 2, com decisão própria.
- Consultar o banco do Chatwoot pra última mensagem por agente: bloqueado e tem dado de cliente.
- Ler logs dos containers: o último log é de quando subiram (16/10) e pode ter dado pessoal.
- Three.js (openclaw-jarvis-ui, licença ISC): exige CDN ou build. Só a ideia da orbe foi usada.
- Código do cam-hm/jarvis: sem licença. A voz dele imita ator.
- Voz de ator ou dublador real (Tony Stark, Jarvis do filme): só o estilo, nunca cópia.
- Chave do ElevenLabs no navegador ou lida de `~/.jesusepop_*`.
- Lista com todos os alertas na tela principal: repetia os cards.

## Consequências
- O painel continua sem rota que publica, apaga ou dispara algo. `/api/voz` só gasta crédito
  de voz, dentro do teto.
- A conta Creator do ElevenLabs é a mesma do Jesus é Pop (que hoje narra pelo Edge). O teto
  protege a narração.
- Fase 2 (controle por voz, ex.: "cria uma sessão no projeto tal") precisa de decisão nova:
  rota de escrita, modo de permissão, quem paga, confirmação e se a VPS entra.
