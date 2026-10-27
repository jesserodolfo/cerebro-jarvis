# Painel Jarvis: ações com confirmação, gavetas dos botões e agenda real do TikTok

Data: 2026-10-27. Aprovado pelo Jessé (plano Prumo com GO): "GO no plano todo: ações, gavetas e
agenda do TikTok."

## Contexto
- Crítico "Última coleta 26/10 · erro em pt_canal": em 26/10 06:00 a conexão com o YouTube esgotou o
  tempo (rede); em 27/10 a coleta das 06:00 não rodou porque o Mac só ligou às 06:37. Resolve
  rodando a coleta de novo. O Jessé quer falar com o Jarvis e ele mesmo mandar o comando.
- Os botões RESUMO DO DIA, AGENTES e NOTÍCIAS só falavam. Ele quer ver o conteúdo, com o link de
  cada notícia.
- A linha TikTok da agenda vinha só do Zernio. O jessé.ia posta todo dia pelo fluxo do Telegram
  (rotina 8h gera, ele aprova, o post sai no mesmo dia); o registro fica em
  tiktok-video-ia/saida/<data>-<slug>/post.json e banco/clipes.csv. Os dias à frente ficavam vazios.

## Decisão
1. Ações (Fase 2, v1). `config.json/acoes` é uma lista fechada; cada ação tem id, rótulo, pergunta
   falada, o comando fixo (lista de argumentos, sem shell) e os itens de alerta onde aparece. v1 tem
   uma: `jesusepop.coleta` = `launchctl kickstart gui/<uid>/com.jesusepop.coleta`.
   - `POST /api/acao {"id": ...}`: só ids da lista; só aceita pedido com Origin do próprio painel
     (http://127.0.0.1:8790 ou http://localhost:8790) e corpo JSON; responde 400/403 no resto.
     Registro em painel/logs/acoes.jsonl.
   - Confirmação sempre do Jessé: clique no botão "Rodar de novo" (card Críticos e gaveta) ou "sim",
     "pode", "manda" até 20 s depois de o Jarvis perguntar. O modelo (Haiku/Opus) nunca dispara ação:
     notícia e título de vídeo entram no prompt e poderiam trazer um comando escondido.
   - Depois de rodar, o painel relê só os blocos do alerta a cada 30 s e fala quando o alerta sair,
     quando o serviço terminar com o alerta ainda lá, ou depois de `espera_min` (coleta: 50, porque
     ela leva de 8 a 46 min). "Rodando" vem do processo do serviço no launchd (`servico`); o painel
     recarregado retoma a espera e não oferece a ação de novo enquanto ela roda.
   - Quem paga: ninguém, é comando local. VPS fora da v1.
2. Gavetas: RESUMO DO DIA abre uma gaveta com uma linha por projeto (clique abre o card); AGENTES e
   NOTÍCIAS falam e abrem a gaveta do bloco, com as manchetes clicáveis em aba nova.
3. Agenda do TikTok (coletores/tiktok.py): posts das pastas de saida/ (publicado com link em verde,
   agendado em cinza), clipes do dia esperando OK no Telegram em amarelo, e dias à frente com uma
   linha "previsto" da rotina 8h. Evento com `previsto: true` não conta como post (contrato novo).
   "agendados no Zernio 0" deixa de ser atenção; atenção só se passar das 16h sem nada aprovado.

## Descartado
- Dar ferramenta de execução ao modelo: injeção por notícia ou título de vídeo.
- Abrir sessão do Claude Code pelo painel: gasta plano e pede modo de permissão. Fica pra v2.
- Ações na VPS: fora da v1.

## Como desfazer
Backups `.bak-pre-acoes` de servidor.py, index.html, config.json, CONTRATO.md e coletores/tiktok.py;
reiniciar com.jarvis.painel.
