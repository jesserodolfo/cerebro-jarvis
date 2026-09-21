#!/usr/bin/env python3
"""Puxa as métricas do Instagram pelo Zernio e grava uma tabela enxuta.

Só faz GET. Nunca imprime a chave.
Uso:
  python3 scripts/puxar-metricas.py              # últimos 90 dias
  python3 scripts/puxar-metricas.py --dias 364   # primeira rodada, histórico (a API aceita até 1 ano)
  python3 scripts/puxar-metricas.py --from-json arquivo.json   # teste sem API

A chave vem de ZERNIO_API_KEY no ambiente ou no .env do perfil jarvis.
"""
import argparse
import datetime as dt
import json
import os
import statistics
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://zernio.com/api/v1/analytics"
RAIZ = Path(__file__).resolve().parent.parent
ENV_PERFIL = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes/profiles/jarvis")) / ".env"


def ler_chave():
    chave = os.environ.get("ZERNIO_API_KEY", "").strip()
    if not chave and ENV_PERFIL.exists():
        for linha in ENV_PERFIL.read_text(encoding="utf-8").splitlines():
            if linha.startswith("ZERNIO_API_KEY="):
                chave = linha.split("=", 1)[1].strip().strip('"').strip("'")
    if not chave:
        sys.exit("Falta ZERNIO_API_KEY. Peça ao Jessé para gravar a chave somente leitura "
                 f"em {ENV_PERFIL}. Não peça a chave na conversa.")
    return chave


def puxar(chave, dias, conta):
    hoje = dt.date.today()
    base = {"fromDate": (hoje - dt.timedelta(days=dias)).isoformat(),
            "toDate": hoje.isoformat(), "platform": "instagram", "limit": 50}
    if conta:
        base["accountId"] = conta
    posts, contas, pagina = [], [], 1
    while True:
        url = API + "?" + urllib.parse.urlencode({**base, "page": pagina})
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {chave}"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                dados = json.load(r)
        except urllib.error.HTTPError as e:
            motivo = e.read().decode("utf-8", "replace")[:300].replace(chave, "[CHAVE]")
            sys.exit(f"Zernio respondeu HTTP {e.code} na página {pagina}: {motivo}")
        posts += dados.get("posts", [])
        contas = dados.get("accounts", contas)
        if pagina >= dados.get("pagination", {}).get("pages", 1):
            return posts, contas
        pagina += 1


def enxugar(p):
    a = p.get("analytics") or {}
    n = lambda k: a.get(k) or 0
    alcance = n("reach")
    legenda = " ".join((p.get("content") or "").split()).replace("|", "/")
    return {
        "data": (p.get("publishedAt") or "")[:10],
        "tipo": (p.get("mediaProductType") or p.get("mediaType") or "?").lower(),
        "dur": a.get("videoDurationSeconds") or 0,
        "alcance": alcance, "views": n("views"), "curt": n("likes"), "com": n("comments"),
        "comp": n("shares"), "salv": n("saves"),
        # 0 nesses dois campos significa que o Instagram não mediu, não que foi zero
        "assist": round(n("igReelsAvgWatchTime") / 1000, 1) or None,
        "pulo": a.get("reelsSkipRate") or None,
        "eng": a.get("engagementRate") or 0,
        "valor": round((n("shares") + n("saves")) / alcance * 1000, 1) if alcance else 0,
        "legenda": legenda[:90],
        "url": p.get("platformPostUrl") or "",
    }


def mediana(linhas, campo):
    # post sem alcance ainda não sincronizou métrica: fica fora da conta
    v = [l[campo] for l in linhas if l[campo] is not None and l["alcance"]]
    return round(statistics.median(v), 1) if v else "-"


def media(linhas, campo):
    # valor é esparso (muito post com 0): mediana esconde o sinal, média mostra
    v = [l[campo] for l in linhas if l[campo] is not None and l["alcance"]]
    return round(statistics.mean(v), 1) if v else "-"


def faixa(d):
    if not d:
        return "sem duração"
    return "até 30s" if d <= 30 else "31 a 60s" if d <= 60 else "61 a 90s" if d <= 90 else "mais de 90s"


def tabela(linhas):
    cab = "| data | tipo | dur s | alcance | views | curt | com | comp | salv | assist s | pulo % | eng % | valor | legenda | url |"
    out = [cab, "|" + "---|" * 15]
    for l in linhas:
        out.append("| {data} | {tipo} | {dur} | {alcance} | {views} | {curt} | {com} | {comp} | {salv} | "
                   "{assist} | {pulo} | {eng} | {valor} | {legenda} | {url} |".format(
                       **{**l, "pulo": "-" if l["pulo"] is None else l["pulo"],
                          "assist": "-" if l["assist"] is None else l["assist"]}))
    return out


def grupos(linhas, chave, titulo):
    out = [f"### {titulo}", "| grupo | posts | alcance med | eng % med | valor médio | pulo % med | assist s med |",
           "|---|---|---|---|---|---|---|"]
    nomes = sorted({chave(l) for l in linhas})
    for g in nomes:
        sub = [l for l in linhas if chave(l) == g]
        aviso = "" if len(sub) >= 4 else " (amostra insuficiente)"
        out.append(f"| {g}{aviso} | {len(sub)} | {mediana(sub,'alcance')} | {mediana(sub,'eng')} | "
                   f"{media(sub,'valor')} | {mediana(sub,'pulo')} | {mediana(sub,'assist')} |")
    return out + [""]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dias", type=int, default=90)
    ap.add_argument("--conta", default="")
    ap.add_argument("--from-json", default="")
    ap.add_argument("--saida", default="")
    args = ap.parse_args()

    if args.from_json:
        dados = json.loads(Path(args.from_json).read_text(encoding="utf-8"))
        posts, contas = dados.get("posts", []), dados.get("accounts", [])
    else:
        posts, contas = puxar(ler_chave(), min(args.dias, 364), args.conta)

    linhas = sorted((enxugar(p) for p in posts), key=lambda l: l["data"], reverse=True)
    if not linhas:
        sys.exit("Nenhum post no período.")
    reels = [l for l in linhas if l["tipo"] == "reels"]
    hoje = dt.date.today().isoformat()
    seg = ", ".join(f"@{c.get('username')}: {c.get('followersCount')} seguidores" for c in contas) or "-"

    doc = [f"# Métricas do Instagram, extração de {hoje}",
           "Gerado por scripts/puxar-metricas.py. Não edite à mão: a próxima rodada sobrescreve.",
           "", f"- Base: {len(linhas)} posts, de {linhas[-1]['data']} a {linhas[0]['data']}",
           f"- Conta: {seg}",
           "- valor = (compartilhamentos + salvamentos) por 1.000 de alcance. É o sinal mais forte de "
           "conteúdo útil para quem decide.",
           "- Grupo com menos de 4 posts não sustenta conclusão.",
           "- Traço em pulo ou assist: o Instagram não mediu esse post. Fica fora da mediana.", "",
           "## Medianas por grupo", ""]
    doc += grupos(linhas, lambda l: l["tipo"], "Por tipo")
    if reels:
        doc += grupos(reels, lambda l: faixa(l["dur"]), "Reels por duração")
    doc += grupos(linhas, lambda l: l["data"][:7], "Por mês")
    # alcance baixo infla o valor: 1 salvamento em 14 de alcance não é sinal
    base_valor = [l for l in linhas if l["alcance"] >= 100]
    doc += ["## 10 maiores em valor (alcance de 100 ou mais)", ""] + tabela(sorted(base_valor, key=lambda l: l["valor"], reverse=True)[:10]) + [""]
    doc += ["## 10 maiores em alcance", ""] + tabela(sorted(linhas, key=lambda l: l["alcance"], reverse=True)[:10]) + [""]
    if reels:
        com_pulo = [l for l in reels if l["pulo"] is not None]
        doc += ["## 10 Reels com mais pulo", ""] + tabela(sorted(com_pulo, key=lambda l: l["pulo"], reverse=True)[:10]) + [""]
    doc += ["## Todos os posts", ""] + tabela(linhas) + [""]

    saida = Path(args.saida) if args.saida else RAIZ / "saidas/metricas" / f"{hoje}-posts.md"
    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.write_text("\n".join(doc), encoding="utf-8")
    print(f"{len(linhas)} posts gravados em {saida}")


if __name__ == "__main__":
    main()
