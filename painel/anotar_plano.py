"""Grava a leitura real do plano em config.json/semana.leitura (decisão 2026-10-26).

Uso: painel/.venv/bin/python painel/anotar_plano.py 7
     (o % "semanal, todos os modelos" do app, lido agora)

O total dos logs no momento vai junto: o painel mostra a leitura + o que os logs somarem
depois dela. Rodar de novo troca a leitura anterior; o resto do config.json fica intacto.
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "coletores"))
import json
import os
import re

import custos
from _base import agora

LEITURA = re.compile(r'"leitura": \{[^{}\n]*\}')
CALIBRADO = re.compile(r'("calibrado_em": "[^"\n]*")')


def main():
    if len(sys.argv) != 2:
        sys.exit("uso: anotar_plano.py <% semanal, todos os modelos>")
    pct = float(sys.argv[1].replace(",", ".").rstrip("%"))
    if not 0 <= pct <= 100:
        sys.exit("o % precisa estar entre 0 e 100")
    pct = int(pct) if pct.is_integer() else pct

    r = custos.coletar()
    if not r.get("ok"):
        sys.exit(f"coletor de custos falhou: {r}")
    leitura = {"em": agora().isoformat(timespec="minutes"), "pct": pct, "usd": r["dados"]["total_usd"]}
    nova = '"leitura": ' + json.dumps(leitura, ensure_ascii=False)

    texto = custos.CONFIG.read_text()
    if LEITURA.search(texto):
        texto = LEITURA.sub(lambda m: nova, texto, count=1)
    else:
        texto, n = CALIBRADO.subn(lambda m: m.group(1) + ",\n    " + nova, texto, count=1)
        if not n:
            sys.exit("não achei semana.calibrado_em no config.json; nada gravado")
    if json.loads(texto)["semana"].get("leitura") != leitura:
        sys.exit("o config.json ficaria inválido; nada gravado")

    tmp = custos.CONFIG.with_suffix(".tmp")
    tmp.write_text(texto)
    os.replace(tmp, custos.CONFIG)
    print(f"leitura gravada: {pct}% em {leitura['em']}, US$ {leitura['usd']:.2f} nos logs até agora")


if __name__ == "__main__":
    main()
