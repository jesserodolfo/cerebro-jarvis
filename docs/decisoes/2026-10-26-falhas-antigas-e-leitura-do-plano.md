# Painel Jarvis: falhas antigas, leitura real do plano e fatia Outros

Data: 2026-10-26. Aprovado pelo Jessé (plano Prumo com GO): "GO nos recomendados: 1a, 2a e 3a."

## Contexto
- O card Jesus é Pop ficava vermelho por um post ES de 08/10 ("Sansón elegía con los ojos") com
  status `failed` no Zernio. A coleta diária regrava a linha no `jarvis_yt.db`, então o alerta nunca
  apagava. O Zernio conectado nesta sessão é outra conta (403 no post).
- O custo da semana era só estimativa (logs do Claude Code em equivalente de API ÷ US$920). Em
  26/10 09:10 o app mostrou 7% real contra 4% estimado: o uso fora do Claude Code (chat do
  claude.ai, onde está o Fable desta semana) não aparece nos logs.
- A fatia Outros (5%) ficava sempre vermelha: gastou uns US$140 (15%) na semana de 18/10. As
  fatias somavam 90%.

## Decisão
1. Falha com mais de 7 dias (`PAINEL_FALHA_DIAS`, padrão 7) sai do alerta, do resumo falado e do
   destaque do card Jesus é Pop. Continua visível como item "Falhas antigas" em `info`, com a data.
2. `config.json/semana.leitura` guarda a última leitura real do plano (`em`, `pct`, `usd` = total
   estimado no momento da leitura). Na mesma semana do plano, o uso vira leitura + (gasto depois
   dela ÷ capacidade). Leitura de semana anterior é ignorada e a conta volta à estimativa pura.
   `painel/anotar_plano.py <pct>` grava a leitura com o total do momento (idempotente). Quem lê o
   % é uma sessão do app (ferramenta get_usage) ou o Jessé pelo print.
3. Fatia Outros de 5% para 15%, usando os 10% sem dono. Fatias somam 100%.

## Descartado
- Apagar ou republicar o post no Zernio: precisa da chave do Jesus é Pop, a linha pode continuar
  `failed` no banco local, e republicar é decisão de conteúdo daquele projeto.
- Recalibrar `capacidade_usd` com a leitura de 7%: um dia de dados, % inteiro (±7% no valor) e
  mistura uso fora do Claude Code. Fica em 920 até uma leitura acima de 20%.
- Ler o token OAuth do Keychain pra chamar a rota interna de uso: credencial e rota sem contrato.
- Ler o IndexedDB do app Claude: quebra em qualquer atualização.

## Como desfazer
`painel/coletores/jesusepop.py.bak-pre-falhas`, `painel/coletores/custos.py.bak-pre-leitura` e
`painel/config.json.bak-pre-leitura`; apagar `painel/anotar_plano.py`; reiniciar com.jarvis.painel.
