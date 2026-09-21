---
name: metricas-instagram
description: Lê as métricas reais do Instagram do Jessé pelo Zernio e transforma em padrões que alimentam a pauta. Use quando o pedido for métricas, desempenho, o que funcionou, análise do Instagram, relatório da semana, ou quando o Jessé avisar que postou algo.
---

# Métricas do Instagram

## Entradas
- scripts/puxar-metricas.py (só leitura no Zernio)
- contexto/subcrencas.md (para classificar cada post por crença)
- contexto/estrategia-conteudo.md (linhas: cultura, inteligência, demanda)
- contexto/diagnostico.md (histórico publicado e ângulos queimados)
- saidas/publicados.md (ligação entre post e pauta, se existir)
- aprendizados/APRENDIZADOS.md

## Passos
1. Rode no terminal, a partir da pasta do cérebro:
   python3 scripts/puxar-metricas.py
   Na primeira rodada use --dias 364 para pegar o histórico.
   Se o script disser que falta a chave, pare e avise o Jessé. Não peça a
   chave na conversa.
2. Leia o arquivo gerado em saidas/metricas/. Não leia JSON cru da API.
3. Classifique cada post por linha, crença e ângulo, usando a legenda,
   saidas/publicados.md e o histórico de diagnostico.md. Se não der para
   classificar com segurança, marque como sem classificação. Não chute.
4. Compare grupos: por linha, por crença, por ângulo, por formato, por
   duração e por tipo de gancho (pergunta, afirmação forte, história, lista).
   Use a coluna valor como sinal principal, depois pulo e tempo assistido
   nos Reels, depois alcance. Curtida é o sinal mais fraco.
5. Só conclua sobre grupo com 4 posts ou mais. Abaixo disso escreva amostra
   insuficiente e transforme em hipótese para testar.
6. Reescreva contexto/desempenho.md do zero, no formato abaixo.
7. Se algum ângulo queimado performou bem, ou algum tema novo performou mal
   de forma consistente, proponha a mudança em diagnostico.md. Não edite
   diagnostico.md: ele é curado pelo Jessé.

## Formato de contexto/desempenho.md
    # Desempenho do Instagram
    Atualizado em AAAA-MM-DD. Gerado pela skill metricas-instagram.
    Base: N posts, de AAAA-MM-DD a AAAA-MM-DD.

    ## O que o público respondeu melhor (grupo com 4 posts ou mais)
    - padrão, com os números medianos e quantos posts sustentam

    ## O que o público ignorou ou pulou
    - padrão, com os números

    ## Formato e duração
    - o que os números dizem sobre carrossel, reels, card e duração

    ## Hipóteses para testar (amostra insuficiente)
    - hipótese, e qual post resolveria a dúvida

    ## Recomendação para as próximas pautas
    - até 5 linhas, práticas

## Quando o Jessé avisar que postou
Acrescente uma linha em saidas/publicados.md:
    AAAA-MM-DD | arquivo da pauta de origem | linha | crença | formato | link
Se ele não disser o link, pergunte.

## Saída
Salve o relatório em saidas/relatorios/AAAA-MM-DD-metricas.md e mande na
conversa só: os 3 padrões mais fortes, as 2 hipóteses mais úteis e o que
muda na pauta de amanhã.

## Autoavaliação (obrigatória)
Confira: toda conclusão tem grupo de 4 posts ou mais? Todo número veio do
arquivo do script? Alguma recomendação contradiz contexto/marca-voz.md ou
o SOUL? Diga em uma linha se a skill performou bem. Se falhou, registre em
aprendizados/APRENDIZADOS.md no formato [data] o que falhou -> regra nova.

## Regras
- Sem travessões.
- Número de Instagram nunca entra em post. Número de post sai só de
  provas.md.
- Um post isolado não é padrão.
- O Jessé usa Reels de teste do Instagram. O script marca a cópia de teste
  como reels-teste. Ela não é repost e não entra em nenhuma comparação de
  Reels. Só olhe a tabela Reels de teste e a versão oficial para dizer se o
  teste está entregando alcance ou não.
- Antes de chamar algo de padrão, pergunte se pode ser artefato da coleta:
  duplicata, métrica que o Instagram não mediu, post recém publicado.
  Na dúvida, vira hipótese, não padrão.
- Métrica não manda na voz nem na crença. Se o que performa for conteúdo
  que o SOUL proíbe (motivacional, guru, promessa), registre o dado e não
  recomende.
- Você só lê o Zernio. Não publica, não agenda, não apaga, não responde
  comentário.
