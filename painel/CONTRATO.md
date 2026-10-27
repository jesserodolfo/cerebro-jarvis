# Contrato dos coletores

Cada arquivo `painel/coletores/<nome>.py` segue isto:

- Só biblioteca padrão do Python. Só leitura: nunca escreve em pasta de projeto,
  banco ou API. Zernio só por `_base.zernio_get` (GET).
- Topo do arquivo, antes de qualquer import local:
  `import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))`
  e depois `from _base import ...` (precisa funcionar com `python3 -I`).
- Expõe `coletar() -> dict` que devolve `_base.ok(dados, resumo)` ou `_base.erro(msg)`.
  - `resumo`: 1 ou 2 frases em pt-BR, sem travessão, que o Jarvis fala em voz alta.
  - `dados`: JSON pequeno (menos de 20 KB) que o front desenha em card.
    Campos obrigatórios em `dados`: `titulo` (str), `itens` (lista de
    `{rotulo, valor, estado}` com estado em `ok|atencao|erro|info`) e, se houver,
    `lista` (lista de `{quando, texto, estado, link?}`, no máximo 15, mais próximos primeiro)
    e `links` (lista de `{rotulo, url}`).
- Termina com `if __name__ == "__main__": rodar(coletar)`.
- Roda em menos de 5 s. Falha de uma fonte vira item `estado: erro`, não exceção.
- Datas exibidas em BRT (`_base.FUSO`), formato `dd/mm HH:MM`.
- Nunca imprime nem devolve valor de chave.

## Campos opcionais do painel em abas (2026-10-20)
Opcionais e retrocompatíveis: `titulo`, `itens`, `lista` e `links` continuam iguais e viram o
detalhe da gaveta lateral. Decisão em `docs/decisoes/2026-10-20-agentes-abas-voz.md`.

- `itens[].id`: id fixo do item, minúsculo, com ponto e hífen (`jesusepop.coleta`, `vps.bia`).
  Serve pra gaveta agora e pras ações da fase 2 depois. Não muda de uma coleta pra outra.
- `destaque`: `{valor, rotulo, estado}`. O número grande do bloco na aba Projetos.
  `valor` curto, até 8 caracteres (`33%`, `4`, `6/7`, `US$ 129`). `rotulo` até 32 caracteres.
- `frase`: 1 frase de até 90 caracteres, sem travessão, com o ponto principal do bloco.
  Não repete o `destaque` palavra por palavra.
- `agenda`: lista de `{quando, rede, conta, texto, estado, link?}`, de hoje 00:00 até
  hoje + 6 dias 23:59 BRT, em ordem crescente, no máximo 60.
  - `quando`: ISO 8601 com fuso, `2026-10-21T06:00:00-03:00`. Sem hora conhecida: 12:00.
  - `rede`: `tiktok`, `instagram`, `youtube`, `facebook` ou `rotina`.
  - `conta`: rótulo curto, até 24 caracteres (`jessé.ia`, `@mirian.dicas1`, `Jesus é Pop PT`).
  - `texto`: até 70 caracteres.
  - `estado`: `ok` publicado ou rodou, `info` agendado ou vai rodar, `atencao`, `erro` falhou.
  - `previsto` (opcional, desde 2026-10-27): `true` em linha que não é post (rotina prevista,
    clipes esperando OK). Aparece apagada e não entra na contagem de posts.
- `fatias` (só `custos`): `[{id, rotulo, gasto_usd, fatia_usd, pct_usado, pct_fatia, estado}]`.

Ações (desde 2026-10-27, decisão 2026-10-27-acoes-e-agenda-tiktok): coletor continua só leitura.
O servidor liga alerta a ação pelo `id` do item (`config.json/acoes[].itens`) e devolve
`acao` em cada alerta e `acoes` (sem o comando) em `/api/estado`. Só `POST /api/acao` executa,
com a lista fechada de `config.json/acoes`, e só depois do clique ou do "sim" do Jessé.

Exceção ao "só leitura por arquivo e HTTP": `melavitta.py` faz uma única chamada
`ssh -o BatchMode=yes` à VPS com comando fixo no código (`docker inspect` e `pm2 jlist`),
sem log de container, sem banco e sem conteúdo de conversa.
