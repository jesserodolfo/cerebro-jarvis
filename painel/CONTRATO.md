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
