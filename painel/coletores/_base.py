"""Peças comuns dos coletores do painel. Só biblioteca padrão, só leitura."""
import datetime
import json
import os
import sqlite3
import sys
import urllib.parse
import urllib.request
from pathlib import Path

PAINEL = Path(__file__).resolve().parent.parent
DOCS = Path.home() / "Documents"
MKT = DOCS / "03-Marketing"
ENV_PAINEL = PAINEL / ".env"
ENV_HERMES = Path.home() / ".hermes/profiles/jarvis/.env"
ZERNIO = "https://zernio.com/api/v1"
FUSO = datetime.timezone(datetime.timedelta(hours=-3))  # BRT


def agora():
    return datetime.datetime.now(FUSO)


def segredo(nome):
    """Ambiente, depois painel/.env, depois .env do perfil jarvis. Vale a última linha."""
    valor = os.environ.get(nome, "").strip()
    if valor:
        return valor
    for arq in (ENV_PAINEL, ENV_HERMES):
        if arq.exists():
            achado = ""
            for linha in arq.read_text().splitlines():
                if linha.startswith(nome + "="):
                    achado = linha.split("=", 1)[1].strip().strip('"').strip("'")
            if achado:
                return achado
    return ""


def zernio_get(caminho, **params):
    """GET no Zernio. Levanta exceção se faltar chave ou a API falhar."""
    chave = segredo("ZERNIO_API_KEY")
    if not chave:
        raise RuntimeError("falta ZERNIO_API_KEY")
    url = f"{ZERNIO}/{caminho.lstrip('/')}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {chave}"})
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read())


def sqlite_ro(caminho):
    return sqlite3.connect(f"file:{caminho}?mode=ro", uri=True, timeout=3)


def ok(dados, resumo):
    """resumo: 1 frase em pt-BR que o Jarvis pode falar."""
    return {"ok": True, "atualizado": agora().isoformat(timespec="seconds"),
            "resumo": resumo, "dados": dados}


def erro(msg):
    return {"ok": False, "atualizado": agora().isoformat(timespec="seconds"), "erro": str(msg)}


def rodar(coletar):
    """Uso no fim de cada coletor: if __name__ == '__main__': rodar(coletar)"""
    try:
        saida = coletar()
    except Exception as e:  # o coletor nunca derruba o painel
        saida = erro(f"{type(e).__name__}: {e}")
    json.dump(saida, sys.stdout, ensure_ascii=False, indent=2)
    print()
