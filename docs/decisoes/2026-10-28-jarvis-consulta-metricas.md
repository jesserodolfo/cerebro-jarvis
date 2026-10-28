# Painel Jarvis: consultar métricas e agenda por voz, sem gastar IA

Data: 2026-10-28. Pedido do Jessé: "de início eu quero só que ele consiga consultar tudo. Quando
eu for melhorar alguma coisa, as postagens, conforme a análise, eu vou na sessão específica no
Claude Code. O resto pode fazer tudo para deixar visível para mim lá."

## Contexto
- O Jessé quer perguntar ao Jarvis "métricas do YouTube", "métricas do TikTok", "como estão as
  postagens" e ver a resposta na tela, sem abrir uma sessão do Claude Code pra cada consulta.
- Os números do YouTube já existem: a coleta diária do Jesus é Pop grava PT e ES no
  `Jesusepop/jarvis_yt.db` (canal_dia, video, video_dia) desde 06/10.
- O Zernio libera métricas (`GET analytics` e `GET accounts/follower-stats`) nas duas chaves:
  jessé.ia (TikTok) e jesse.rodolfo (Instagram) na chave do Jessé; vendaepop (TikTok) na da loja.
- Custo medido no `painel/logs/uso-api.jsonl`: pergunta no modo rápido (Haiku 5.5) sai por
  ~US$ 0,001; no profundo (Opus 5.5) ~US$ 0,05. Comando reconhecido no próprio painel: US$ 0.

## Decisão
1. O Jarvis só consulta. Melhorar post, roteiro ou vídeo continua na sessão do projeto no Claude
   Code; a regra "o modelo nunca dispara ação" (2026-10-27) continua valendo.
2. Três coletores novos, só leitura, no contrato de sempre:
   - `youtube.py`: inscritos e ganho em 7 dias, views 7 dias contra a semana anterior, views e
     horas em 28 dias, publicados na semana, progresso da regra de monetização e os 3 vídeos que
     mais puxam de cada canal, com link.
   - `metricas_tiktok.py` e `metricas_instagram.py` (lógica comum em `_metricas_zernio.py`):
     seguidores e ganho em 7 dias, posts, views e engajamento da semana e os 3 posts com mais
     views em 28 dias, com link. `_base.zernio_get` ganhou `chave=` opcional pra ler a conta da loja.
   - Validade de 15 min no cache dos dois do Zernio (seguidores mudam uma vez por dia).
3. Comandos de voz resolvidos no navegador, sem IA: pedido de número ("métricas", "como está",
   "views", "seguidores") com a rede no texto fala o `resumo` do bloco e abre a gaveta. "Métricas das
   redes" fala as três e abre a aba Projetos. "Agenda de hoje", "o que sai amanhã" e "agenda da
   semana" falam a contagem por rede e o próximo post, e abrem a aba Agenda.
4. Pergunta de análise ("por que o ES cresceu?", "o que melhorar?") vai pro modo rápido, que já
   recebe os itens e a lista de cada bloco no prompt.
5. Jesus é Pop: a coleta passa das 06:00 para as 07:00 e ganha `com.jesusepop.coleta-login`
   (roda no login só se já passou das 07:00 e a coleta do dia não começou). O botão "Rodar a
   coleta de novo" continua forçando pelo `kickstart`, sem trava.

## Descartado
- Métricas dentro dos blocos que já existem (jesusepop, tiktok, instagram): a gaveta ficaria
  longa e misturaria operação (agenda, falhas) com desempenho.
- Mandar toda pergunta de métrica pro Haiku: custa pouco, mas o número pronto do coletor é exato,
  instantâneo e grátis.
- Corrigir o 409 do `copiar_agenda_fb.py` agora: é melhoria de postagem, fica pra sessão do
  Jesus é Pop.
- Bia, Júlia e Gustavo na VPS: ficam pra sessão do MelaVitta; o painel só mostra.

## Verificação
- Cada coletor roda com `python3 -I` e devolve ok; números do YouTube conferidos com SQL direto.
- `/api/briefing?bloco=youtube` (e os dois do Zernio) devolve o resumo falado.
- No navegador, "métricas do YouTube" abre a gaveta e não chama `/api/chat`.
- `launchctl print` da coleta mostra 07:00; a trava sai sem rodar quando a coleta do dia já começou.
