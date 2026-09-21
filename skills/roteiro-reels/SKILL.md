---
name: roteiro-reels
description: Escreve roteiro de Reels falado pelo Jessé, de 30 a 60 segundos, a partir de uma pauta aprovada. Use quando o pedido for reels, vídeo curto, roteiro ou quando a pauta escolhida tiver formato reels.
---

# Roteiro de Reels

Dado de referência: nos números de abril, os posts em que o Jessé aparece
falando foram os que mais performaram.

## Entradas
- a pauta escolhida
- contexto/marca-voz.md (principalmente as 5 referências de texto dele)
- contexto/provas.md
- aprendizados/APRENDIZADOS.md

## Estrutura
- Gancho (0 a 3 segundos): uma frase. Se não prender aqui, o resto não existe.
- Situação (3 a 15 segundos): a história real, com um detalhe concreto.
- Raciocínio (15 a 45 segundos): como ele pensou, em 2 ou 3 passos.
- Fecho (últimos segundos): a conclusão e a chamada.

## Formato de saída
    GANCHO
    [fala] ...
    [texto na tela] ...

    SITUAÇÃO
    [fala] ...

    RACIOCÍNIO
    [fala] ...

    FECHO
    [fala] ...
    [texto na tela] palavra chave ou pergunta

    LEGENDA
    3 a 5 linhas curtas, sem link.

## Regras
- Escreva como se fala, não como se escreve. Frase de respiração curta.
- Nada que ele não diria em voz alta. Leia em voz alta mentalmente: travou,
  reescreva.
- Marque pausas com (pausa) quando ajudar o ritmo.
- Sem travessões.

## Saída
Salve em saidas/posts/AAAA-MM-DD-reels-slug.md.

## Autoavaliação (obrigatória)
Rode aprendizados/eval.md. Registre falhas em aprendizados/APRENDIZADOS.md.
