"""Notícias das últimas 48 h pelo Google News RSS: IA e Claude, Marketing e TikTok Shop."""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import email.utils
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

from _base import FUSO, erro, ok, rodar

RSS = "https://news.google.com/rss/search?q={q}&hl=pt-BR&gl=BR&ceid=BR:pt-419"
TEMAS = {
    "IA e Claude": ['Anthropic OR "Claude AI"', '"inteligência artificial"'],
    "Marketing e TikTok Shop": ['"TikTok Shop"', '"marketing digital"'],
}
IDS_TEMA = {"IA e Claude": "noticias.ia-claude", "Marketing e TikTok Shop": "noticias.marketing-tiktok"}
POR_TEMA = 8
MAX_LISTA = 15


def corta(txt, n):
    """Corta em n caracteres e tira travessão (manchete vem de fora)."""
    txt = " ".join(re.sub(r"\s*[\u2014\u2013]\s*", ", ", txt or "").split())
    return txt if len(txt) <= n else txt[: n - 1].rstrip() + "…"


def buscar(termo):
    url = RSS.format(q=urllib.parse.quote(f"{termo} when:2d"))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 painel-jarvis"})
    with urllib.request.urlopen(req, timeout=4) as r:
        raiz = ET.fromstring(r.read())
    itens = []
    for it in raiz.iter("item"):
        titulo = (it.findtext("title") or "").strip()
        fonte = (it.findtext("source") or "").strip()
        if fonte and titulo.endswith(" - " + fonte):
            titulo = titulo[: -len(" - " + fonte)].strip()
        try:
            quando = email.utils.parsedate_to_datetime(it.findtext("pubDate") or "").astimezone(FUSO)
        except (TypeError, ValueError):
            continue
        if titulo:
            itens.append({"titulo": titulo, "fonte": fonte, "quando": quando,
                          "link": (it.findtext("link") or "").strip()})
    return itens


def coletar():
    pares = [(tema, termo) for tema, termos in TEMAS.items() for termo in termos]
    with ThreadPoolExecutor(max_workers=len(pares)) as ex:
        futuros = [(tema, termo, ex.submit(buscar, termo)) for tema, termo in pares]
    por_tema = {tema: [] for tema in TEMAS}
    falhas = {}
    for tema, termo, f in futuros:
        try:
            por_tema[tema].extend(f.result())
        except Exception as e:
            falhas[termo] = f"{type(e).__name__}: {e}"
    if len(falhas) == len(pares):
        return erro("nenhuma busca respondeu: " + "; ".join(falhas.values()))

    vistos = set()
    for tema, lst in por_tema.items():
        lst.sort(key=lambda n: n["quando"], reverse=True)
        unicos = []
        for n in lst:
            chave = n["titulo"].lower()
            if chave in vistos:
                continue
            vistos.add(chave)
            unicos.append(n)
        por_tema[tema] = unicos[:POR_TEMA]

    itens = []
    for tema, lst in por_tema.items():
        termos_falhos = [t for t in TEMAS[tema] if t in falhas]
        estado = "erro" if len(termos_falhos) == len(TEMAS[tema]) else "atencao" if termos_falhos else "ok"
        itens.append({"id": IDS_TEMA.get(tema, "noticias." + re.sub(r"\W+", "-", tema.lower()).strip("-")),
                      "rotulo": tema, "valor": f"{len(lst)} notícias", "estado": estado})

    todas = sorted(((tema, n) for tema, lst in por_tema.items() for n in lst),
                   key=lambda par: par[1]["quando"], reverse=True)[:MAX_LISTA]
    lista = [{"quando": n["quando"].strftime("%d/%m %H:%M"),
              "texto": f"[{tema}] {n['titulo']}" + (f" · {n['fonte']}" if n["fonte"] else ""),
              "estado": "info", "link": n["link"]} for tema, n in todas]

    frases = []
    for tema, lst in por_tema.items():
        if lst:
            frases.append(f"{tema}: " + "; e ".join(n["titulo"] for n in lst[:2]) + ".")
    resumo = " ".join(frases) if frases else "Não encontrei notícias nas últimas 48 horas."

    # número grande e frase do painel em abas (itens e lista seguem iguais)
    total = sum(len(lst) for lst in por_tema.values())
    destaque = {"valor": str(total), "rotulo": "notícias hoje",
                "estado": "ok" if total and not falhas else "atencao"}
    frase = corta(todas[0][1]["titulo"], 90) if todas else "Sem notícias nas últimas 48 horas."

    return ok({"titulo": "Notícias", "destaque": destaque, "frase": frase, "itens": itens, "lista": lista,
               "links": [{"rotulo": "Google Notícias", "url": "https://news.google.com/?hl=pt-BR&gl=BR&ceid=BR:pt-419"}]},
              resumo)


if __name__ == "__main__":
    rodar(coletar)
