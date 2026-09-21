# Rotinas (crons) do Jarvis
NÃO ligue nenhuma destas antes de rodar cada skill na mão pelo menos 5 vezes
e ficar satisfeito. Rotina automatiza o que já funciona, não conserta o que
ainda não funciona.

Para criar, peça ao Jarvis em linguagem natural, uma de cada vez, e confira
no painel de crons se ficou certo.

## Fase A (depois de uma semana de testes na mão)
- 06:30 todo dia: rodar radar-concorrentes
- 07:00 de segunda a sexta: rodar pauta-matinal e mandar as 3 pautas no
  Telegram. Esperar o Jessé responder com o número da escolhida.
- 22:00 todo dia: fazer commit e push do cérebro (saidas e aprendizados)

## Fase B (depois de duas semanas estáveis)
- 21:30 todo dia: registrar-feedback em modo melhoria diária, propondo
  mudanças nas skills a partir das notas abertas
- 22:30 todo dia: checagem de saúde. Avisar no Telegram se alguma fonte do
  radar falhou, se algum cron não rodou ou se o push falhou.
- domingo 20:00: curadoria de skills. Listar skills criadas automaticamente
  na semana e perguntar ao Jessé quais manter.

## Fora de escopo até segunda ordem
- Publicar sozinho no Instagram
- Responder comentário ou direct
- Qualquer coisa na operação da MelaVitta
