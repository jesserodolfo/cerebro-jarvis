"""Coletor Jesus é Pop (YouTube + Facebook, PT e ES). Lê o jarvis_yt.db só pra leitura."""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import datetime

from _base import FUSO, MKT, agora, erro, ok, rodar, sqlite_ro

DB = MKT / "Jesusepop/jarvis_yt.db"
NOMES = {"pt": "Jesus é Pop", "es": "Jesús es Pop"}
PAINEL = "http://127.0.0.1:8787"


def brt(iso_utc):
    return datetime.datetime.fromisoformat(iso_utc.replace("Z", "+00:00")).astimezone(FUSO)


def num(n):
    return f"{n:,}".replace(",", ".")


def coletar():
    if not DB.exists():
        return erro(f"banco não encontrado: {DB}")
    c = sqlite_ro(DB)
    c.row_factory = lambda cur, row: {d[0]: v for d, v in zip(cur.description, row)}
    itens, lista = [], []
    agora_utc = datetime.datetime.now(datetime.timezone.utc)
    ini = agora_utc.isoformat()
    fim7 = (agora_utc + datetime.timedelta(days=7)).isoformat()
    agendados7 = {}

    for conta in ("pt", "es"):
        nome = NOMES[conta]
        a = c.execute("SELECT * FROM canal_dia WHERE conta=? ORDER BY data DESC LIMIT 1", (conta,)).fetchone()
        if a:
            itens.append({"rotulo": f"{nome} · inscritos", "valor": num(a["inscritos"] or 0), "estado": "info"})
            itens.append({"rotulo": f"{nome} · views 7 dias", "valor": num(a["views7"] or 0), "estado": "info"})
        else:
            itens.append({"rotulo": f"{nome} · YouTube", "valor": "sem coleta", "estado": "atencao"})
        fb = c.execute("SELECT seguidores s, data FROM fb_pagina WHERE conta=? ORDER BY data DESC LIMIT 1", (conta,)).fetchone()
        if fb is None or not fb["s"]:
            itens.append({"rotulo": f"{nome} · seguidores FB", "valor": "sem leitura", "estado": "atencao"})
        else:
            itens.append({"rotulo": f"{nome} · seguidores FB", "valor": num(fb["s"]), "estado": "info"})
        n7 = c.execute("SELECT count(*) n FROM agenda WHERE conta=? AND status='scheduled' AND quando_utc BETWEEN ? AND ?",
                       (conta, ini, fim7)).fetchone()["n"]
        agendados7[conta] = n7
        itens.append({"rotulo": f"{nome} · agendados 7 dias", "valor": str(n7), "estado": "ok" if n7 else "atencao"})

    falhas = c.execute("SELECT * FROM agenda WHERE status='failed' ORDER BY quando_utc DESC").fetchall()
    itens.append({"rotulo": "Falhas na agenda", "valor": str(len(falhas)), "estado": "erro" if falhas else "ok"})

    ult = c.execute("SELECT max(data) d FROM coleta").fetchone()["d"]
    if ult:
        col = c.execute("SELECT conta, ok, erro FROM coleta WHERE data=?", (ult,)).fetchall()
        ruins = [x["conta"] for x in col if not x["ok"]]
        itens.append({"rotulo": "Última coleta", "valor": f"{ult[8:10]}/{ult[5:7]}" + (f" · erro em {', '.join(ruins)}" if ruins else " · ok"),
                      "estado": "erro" if ruins else ("ok" if ult == str(agora().date()) else "atencao")})
    else:
        itens.append({"rotulo": "Última coleta", "valor": "nunca", "estado": "erro"})

    prod = c.execute("SELECT * FROM producao ORDER BY atualizado DESC LIMIT 1").fetchone()
    if prod:
        est = {"ok": "ok", "erro": "erro", "rodando": "atencao"}.get(prod["estado"], "info")
        itens.append({"rotulo": "Produção", "valor": f"{prod['historia']} · {prod['etapa']} ({prod['estado']})", "estado": est})

    for f in falhas[:5]:
        lista.append({"quando": f"{brt(f['quando_utc']):%d/%m %H:%M}", "estado": "erro",
                      "texto": f"FALHOU · {f['conta'].upper()} · {f['tipo']} · {f['titulo'][:70]}"})
    prox = c.execute("SELECT * FROM agenda WHERE status='scheduled' AND quando_utc>=? ORDER BY quando_utc LIMIT ?",
                     (ini, 15 - len(lista))).fetchall()
    for r in prox:
        lista.append({"quando": f"{brt(r['quando_utc']):%d/%m %H:%M}", "estado": "info",
                      "texto": f"{r['conta'].upper()} · {r['tipo']} · {r['titulo'][:70]}"})
    c.close()

    resumo = (f"Jesus é Pop tem {agendados7['pt']} posts agendados nos próximos 7 dias no canal em português "
              f"e {agendados7['es']} no espanhol.")
    resumo += f" Atenção: {len(falhas)} post com falha na agenda." if len(falhas) == 1 else (
        f" Atenção: {len(falhas)} posts com falha na agenda." if falhas else " Nenhuma falha na agenda.")

    dados = {"titulo": "Jesus é Pop", "itens": itens, "lista": lista,
             "links": [{"rotulo": "Painel completo", "url": f"{PAINEL}/"},
                       {"rotulo": "Calendário", "url": f"{PAINEL}/calendario"}]}
    return ok(dados, resumo)


if __name__ == "__main__":
    rodar(coletar)
