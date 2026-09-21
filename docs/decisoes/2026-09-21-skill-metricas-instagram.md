# Decisão: skill metricas-instagram
Data: 2026-09-21

## Problema
O diagnostico.md registra como PENDENTE: não existe registro de alcance,
salvamento, compartilhamento por post nem por semana. A pauta é escolhida
sem saber o que o público respondeu. O aprendizado hoje só vem da nota do
Jessé.

## Decisão
Skill nova dentro do Jarvis, não um agente novo.
Motivo: a métrica só serve se cair no mesmo cérebro que escreve a pauta.
Agente novo teria outro SOUL e outra memória para manter.

## Desenho
1. scripts/puxar-metricas.py lê a API do Zernio (GET /v1/analytics),
   enxuga e calcula. Saída: saidas/metricas/AAAA-MM-DD-posts.md.
   Motivo do script: cada post cru tem cerca de 3 KB. 72 posts crus por
   rodada gastariam a cota do modelo só para ler JSON. Conta é trabalho de
   código, interpretação é trabalho do Jarvis.
2. A skill lê a tabela, classifica cada post por linha, crença e ângulo, e
   compara grupos.
3. A skill reescreve do zero contexto/desempenho.md (idempotente: rodar 10
   vezes no mesmo dia dá o mesmo arquivo).
4. pauta-matinal passa a ler contexto/desempenho.md.
5. diagnostico.md continua curado à mão. A skill só propõe mudança nele.

## Dois ciclos de aprendizado, separados
| ciclo | quem julga | onde grava |
|---|---|---|
| qualidade | o Jessé, com a nota | aprendizados/APRENDIZADOS.md |
| desempenho | o público, com a métrica | contexto/desempenho.md |

Métrica propõe, o Jessé aprova. Com alcance de 400 a 1.000 por post, um
post isolado é ruído. Só vale conclusão com grupo de 4 posts ou mais.

## Segurança
- Chave do Zernio somente leitura (permission: read), criada só para o
  Jarvis. Com ela a API recusa publicar, agendar ou apagar.
- A chave mora em ~/.hermes/profiles/jarvis/.env como ZERNIO_API_KEY.
  Nunca no cérebro, nunca no chat.
- O script só faz GET.

### Atualização no mesmo dia
O Jessé criou a chave com leitura e escrita, para não precisar trocar
quando a publicação pelo Zernio for construída. Consequência: a barreira
contra publicar deixa de ser técnica e passa a ser só regra escrita (SOUL,
regra dura 1, e a regra final da skill). O script continua fazendo só GET.
Para voltar à barreira técnica: criar chave com permission read no painel
do Zernio, regravar ZERNIO_API_KEY e revogar a atual.

## Número de Instagram não é prova
Alcance, curtida e taxa de pulo vivem só em contexto/desempenho.md e nos
relatórios. Nunca entram em post. Número de post continua saindo só de
provas.md.

## Ligação entre post e pauta
saidas/publicados.md: quando o Jessé avisar que postou, o Jarvis anota data,
pauta de origem, crença e link. Sem isso a análise por crença depende de
adivinhar pela legenda.

## Frequência
Semanal, rodada na mão. Nenhum cron até a skill rodar 5 vezes com resultado
bom (regra do ROTINAS.md).

## Fora desta decisão
Publicar ou agendar pelo Zernio. Fica para depois da validação, em decisão
própria.

## Como reverter
Apagar skills/metricas-instagram, scripts/puxar-metricas.py,
contexto/desempenho.md, tirar a linha de desempenho.md da pauta-matinal e
revogar a chave no painel do Zernio.
