"""Coletor Jesus é Pop (YouTube + Facebook, PT e ES). Lê o jarvis_yt.db só pra leitura."""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import datetime
import json
import os
import re

from _base import FUSO, MKT, agora, erro, ok, rodar, sqlite_ro

DB = MKT / "Jesusepop/jarvis_yt.db"
# falha mais velha que isso sai do alerta e vira "Falhas antigas" (info); decisão 2026-10-26
FALHA_DIAS = int(os.environ.get("PAINEL_FALHA_DIAS", "7"))
# youtube_id -> facebook_id, gravado pelo copiar_agenda_fb.py (a cópia vai pro Facebook no mesmo horário)
FB_COPIAS = MKT / "Jesusepop/JesusEPop_producao/jarvis/fb_copiados.json"
NOMES = {"pt": "Jesus é Pop", "es": "Jesús es Pop"}
PAINEL = "http://127.0.0.1:8787"


def brt(iso_utc):
    return datetime.datetime.fromisoformat(iso_utc.replace("Z", "+00:00")).astimezone(FUSO)


def num(n):
    return f"{n:,}".replace(",", ".")


def limpa(txt):
    """Tira travessão de texto que vem de fora (título de vídeo)."""
    return re.sub(r"\s*[\u2014\u2013]\s*", ", ", txt or "")


def corta(txt, n):
    txt = " ".join(limpa(txt).split())
    return txt if len(txt) <= n else txt[: n - 1].rstrip() + "…"


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
    fb_sem_leitura = []

    for conta in ("pt", "es"):
        nome = NOMES[conta]
        a = c.execute("SELECT * FROM canal_dia WHERE conta=? ORDER BY data DESC LIMIT 1", (conta,)).fetchone()
        if a:
            itens.append({"id": f"jesusepop.{conta}.inscritos", "rotulo": f"{nome} · inscritos",
                          "valor": num(a["inscritos"] or 0), "estado": "info"})
            itens.append({"id": f"jesusepop.{conta}.views7", "rotulo": f"{nome} · views 7 dias",
                          "valor": num(a["views7"] or 0), "estado": "info"})
        else:
            itens.append({"id": f"jesusepop.{conta}.youtube", "rotulo": f"{nome} · YouTube",
                          "valor": "sem coleta", "estado": "atencao"})
        fb = c.execute("SELECT seguidores s, data FROM fb_pagina WHERE conta=? ORDER BY data DESC LIMIT 1", (conta,)).fetchone()
        if fb is None or not fb["s"]:
            itens.append({"id": f"jesusepop.{conta}.fb", "rotulo": f"{nome} · seguidores FB",
                          "valor": "sem leitura", "estado": "atencao"})
            fb_sem_leitura.append(conta.upper())
        else:
            itens.append({"id": f"jesusepop.{conta}.fb", "rotulo": f"{nome} · seguidores FB",
                          "valor": num(fb["s"]), "estado": "info"})
        n7 = c.execute("SELECT count(*) n FROM agenda WHERE conta=? AND status='scheduled' AND quando_utc BETWEEN ? AND ?",
                       (conta, ini, fim7)).fetchone()["n"]
        agendados7[conta] = n7
        itens.append({"id": f"jesusepop.{conta}.agendados", "rotulo": f"{nome} · agendados 7 dias",
                      "valor": str(n7), "estado": "ok" if n7 else "atencao"})

    todas = c.execute("SELECT * FROM agenda WHERE status='failed' ORDER BY quando_utc DESC").fetchall()
    corte_falha = agora_utc - datetime.timedelta(days=FALHA_DIAS)
    falhas = [f for f in todas if brt(f["quando_utc"]) >= corte_falha]
    antigas = [f for f in todas if brt(f["quando_utc"]) < corte_falha]
    itens.append({"id": "jesusepop.falhas", "rotulo": "Falhas na agenda", "valor": str(len(falhas)),
                  "estado": "erro" if falhas else "ok"})
    if antigas:
        datas = ", ".join(f"{f['conta'].upper()} {brt(f['quando_utc']):%d/%m}" for f in antigas[:3])
        itens.append({"id": "jesusepop.falhas-antigas", "rotulo": f"Falhas antigas (mais de {FALHA_DIAS} dias)",
                      "valor": f"{len(antigas)} · {datas}", "estado": "info"})

    ult = c.execute("SELECT max(data) d FROM coleta").fetchone()["d"]
    ruins = []
    if ult:
        col = c.execute("SELECT conta, ok, erro FROM coleta WHERE data=?", (ult,)).fetchall()
        ruins = [x["conta"] for x in col if not x["ok"]]
        itens.append({"id": "jesusepop.coleta", "rotulo": "Última coleta", "valor": f"{ult[8:10]}/{ult[5:7]}" + (f" · erro em {', '.join(ruins)}" if ruins else " · ok"),
                      "estado": "erro" if ruins else ("ok" if ult == str(agora().date()) else "atencao")})
    else:
        itens.append({"id": "jesusepop.coleta", "rotulo": "Última coleta", "valor": "nunca", "estado": "erro"})

    prod = c.execute("SELECT * FROM producao ORDER BY atualizado DESC LIMIT 1").fetchone()
    if prod:
        est = {"ok": "ok", "erro": "erro", "rodando": "atencao"}.get(prod["estado"], "info")
        itens.append({"id": "jesusepop.producao", "rotulo": "Produção",
                      "valor": f"{prod['historia']} · {prod['etapa']} ({prod['estado']})", "estado": est})

    for f in falhas[:5]:
        lista.append({"quando": f"{brt(f['quando_utc']):%d/%m %H:%M}", "estado": "erro",
                      "texto": f"FALHOU · {f['conta'].upper()} · {f['tipo']} · {f['titulo'][:70]}"})
    prox = c.execute("SELECT * FROM agenda WHERE status='scheduled' AND quando_utc>=? ORDER BY quando_utc LIMIT ?",
                     (ini, 15 - len(lista))).fetchall()
    for r in prox:
        lista.append({"quando": f"{brt(r['quando_utc']):%d/%m %H:%M}", "estado": "info",
                      "texto": f"{r['conta'].upper()} · {r['tipo']} · {r['titulo'][:70]}"})

    # agenda do painel em abas: hoje 00:00 até hoje+6 23:59 BRT. A tabela só guarda YouTube; o Facebook sai
    # do fb_copiados.json (só leitura). O status da cópia no Facebook não é lido: fica "info".
    try:
        copias_fb = json.loads(FB_COPIAS.read_text())
    except (OSError, ValueError):
        copias_fb = {}
    hoje = agora().date()
    ini_ag = datetime.datetime.combine(hoje, datetime.time(0), FUSO)
    fim_ag = datetime.datetime.combine(hoje + datetime.timedelta(days=6), datetime.time(23, 59, 59), FUSO)
    margem = lambda d: d.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    linhas = c.execute("SELECT * FROM agenda WHERE status IN ('scheduled','published','failed') "
                       "AND quando_utc>=? AND quando_utc<=? ORDER BY quando_utc",
                       (margem(ini_ag - datetime.timedelta(days=1)), margem(fim_ag + datetime.timedelta(days=1)))).fetchall()
    agenda = []
    for r in linhas:
        q = brt(r["quando_utc"])
        if not (ini_ag <= q <= fim_ag):
            continue
        agenda.append({"quando": q.isoformat(timespec="seconds"), "rede": "youtube",
                       "conta": f"{NOMES.get(r['conta'], r['conta'])} {r['conta'].upper()}",
                       "texto": corta(f"{r['tipo']} · {r['titulo']}", 70),
                       "estado": {"scheduled": "info", "published": "ok", "failed": "erro"}[r["status"]]})
        if r["post_id"] in copias_fb and r["status"] != "failed":
            agenda.append({"quando": q.isoformat(timespec="seconds"), "rede": "facebook",
                           "conta": f"{NOMES.get(r['conta'], r['conta'])} {r['conta'].upper()}",
                           "texto": corta(f"cópia · {r['titulo']}", 70), "estado": "info"})
    agenda = sorted(agenda, key=lambda e: e["quando"])[:60]
    c.close()

    resumo = (f"Jesus é Pop tem {agendados7['pt']} posts agendados nos próximos 7 dias no canal em português "
              f"e {agendados7['es']} no espanhol.")
    resumo += f" Atenção: {len(falhas)} post com falha na agenda." if len(falhas) == 1 else (
        f" Atenção: {len(falhas)} posts com falha na agenda." if falhas else " Nenhuma falha na agenda.")

    total7 = sum(agendados7.values())
    sem_agenda = [k.upper() for k, v in agendados7.items() if not v]
    destaque = {"valor": str(total7), "rotulo": "agendados 7 dias",
                "estado": "atencao" if (falhas or ruins or sem_agenda) else "ok"}
    pontos = []
    if falhas:
        contas_falha = "/".join(sorted({f["conta"].upper() for f in falhas}))
        pontos.append(f"{len(falhas)} falha{'s' if len(falhas) != 1 else ''} na agenda ({contas_falha}).")
    if sem_agenda:
        pontos.append(f"{'/'.join(sem_agenda)} sem post agendado.")
    if ruins:
        pontos.append(f"Coleta com erro em {'/'.join(x.upper() for x in ruins)}.")
    if fb_sem_leitura:
        pontos.append("Facebook sem leitura.")
    frase = corta(" ".join(pontos) if pontos else "Agenda cheia nos dois canais, sem falhas.", 90)

    dados = {"titulo": "Jesus é Pop", "destaque": destaque, "frase": frase, "agenda": agenda,
             "itens": itens, "lista": lista,
             "links": [{"rotulo": "Painel completo", "url": f"{PAINEL}/"},
                       {"rotulo": "Calendário", "url": f"{PAINEL}/calendario"}]}
    return ok(dados, resumo)


if __name__ == "__main__":
    rodar(coletar)
