"""Coletor TikTok: @mirian.dicas1 (afiliada, postagem à mão), @jesse.ia (Zernio) e @vendaepop (loja, Zernio próprio).
Só leitura. Fontes: tiktok-video-ia/saida, banco/clipes.csv, contas/mirian.dicas1/fila-produtos.tsv e GET no Zernio."""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import csv
import datetime
import json
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from _base import FUSO, MKT, ZERNIO, agora, erro, ok, rodar, segredo

PROJ = MKT / "tiktok-video-ia"
SAIDA = PROJ / "saida"
FILA_MIRIAN = PROJ / "contas/mirian.dicas1/fila-produtos.tsv"
CLIPES = PROJ / "banco/clipes.csv"
ENV_PROJ = PROJ / ".env"
CONTA_JESSEIA = "6ad3eb1e97f5a378e29426e1"
DIAS_OLHAR = 14  # janela de dias à frente pra achar buraco na fila da Mirian


def env_proj(nome):
    """Lê uma variável do .env do tiktok-video-ia (a loja tem chave própria do Zernio)."""
    achado = ""
    if ENV_PROJ.exists():
        for linha in ENV_PROJ.read_text().splitlines():
            if linha.startswith(nome + "="):
                achado = linha.split("=", 1)[1].strip().strip('"').strip("'")
    return achado


def zget(chave, caminho, **params):
    """GET no Zernio com a chave dada (a loja usa chave diferente da do _base). Só leitura."""
    if not chave:
        raise RuntimeError("falta chave do Zernio")
    url = f"{ZERNIO}/{caminho.lstrip('/')}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {chave}"})
    with urllib.request.urlopen(req, timeout=4) as r:
        return json.loads(r.read())


def utc_brt(iso):
    if not iso:
        return None
    return datetime.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(FUSO)


def fmt(dt):
    return dt.strftime("%d/%m %H:%M") if isinstance(dt, datetime.datetime) else dt.strftime("%d/%m")


def qtd(n, palavra):
    return f"{n} {palavra}" + ("" if n == 1 else "s")


def ler_json(arq):
    try:
        return json.loads(arq.read_text())
    except Exception:
        return {}


def primeira_linha(texto, n=70):
    t = (texto or "").strip().splitlines()
    t = t[0] if t else ""
    return t if len(t) <= n else t[: n - 1] + "…"


def plataformas(post, conta=None):
    """Entradas tiktok do post, opcionalmente só da conta (accountId)."""
    saida = []
    for p in post.get("platforms", []):
        acc = p.get("accountId") or {}
        acc_id = acc.get("_id") if isinstance(acc, dict) else acc
        if p.get("platform") == "tiktok" and (conta is None or acc_id == conta):
            saida.append(p)
    return saida


# ---------- Mirian ----------
def mirian(hoje):
    itens, lista = [], []
    pastas = sorted(SAIDA.glob(f"{hoje:%Y-%m-%d}-*-mirian")) if SAIDA.exists() else []
    produto = [p for p in pastas if "-chamada-" not in p.name and (p / "video.mp4").exists()]
    chamadas = [p for p in pastas if "-chamada-" in p.name]

    if produto:
        p = produto[-1]
        st = ler_json(p / "decisao.json").get("status", "montado")
        nome = p.name[11:-7]
        estado = "ok" if st == "aprovado" else "atencao"
        itens.append({"rotulo": "Mirian · vídeo de hoje", "valor": f"{nome} ({st})", "estado": estado})
        lista.append({"quando": hoje,
                      "texto": f"@mirian.dicas1 · {nome} · {st} (postagem à mão)", "estado": estado})
    else:
        itens.append({"rotulo": "Mirian · vídeo de hoje", "valor": "não gerado", "estado": "atencao"})
        nome = None

    if chamadas:
        sts = [ler_json(c / "decisao.json").get("status", "montado") for c in chamadas]
        resumo_st = ", ".join(f"{sts.count(s)} {s}" for s in sorted(set(sts)))
        itens.append({"rotulo": "Mirian · chamadas de hoje", "valor": f"{len(chamadas)} ({resumo_st})",
                      "estado": "ok" if all(s == "aprovado" for s in sts) else "atencao"})

    # fila de produtos
    afiliar, proximo, buracos = 0, None, []
    if FILA_MIRIAN.exists():
        with FILA_MIRIAN.open(newline="") as f:
            linhas = list(csv.DictReader(f, delimiter="\t"))
        cobertos = set()
        for l in linhas:
            st = (l.get("status") or "").strip()
            try:
                d = datetime.date.fromisoformat((l.get("data") or "").strip())
            except ValueError:
                d = None
            if st == "afiliar":
                afiliar += 1
                if d and d > hoje and (proximo is None or d < proximo[0]):
                    proximo = (d, l.get("titulo", ""))
            if d and (st == "afiliar" or st.startswith("feito")):
                cobertos.add(d)
        buracos = [hoje + datetime.timedelta(days=i) for i in range(1, DIAS_OLHAR + 1)
                   if hoje + datetime.timedelta(days=i) not in cobertos]
        itens.append({"rotulo": "Mirian · produtos pra afiliar", "valor": str(afiliar),
                      "estado": "atencao" if afiliar < 7 else "ok"})
        itens.append({"rotulo": f"Mirian · dias sem produto ({DIAS_OLHAR} d)",
                      "valor": ", ".join(fmt(d) for d in buracos[:6]) + (" …" if len(buracos) > 6 else "") if buracos else "nenhum",
                      "estado": "atencao" if buracos else "ok"})
        if proximo:
            lista.append({"quando": proximo[0], "texto": f"@mirian.dicas1 · próximo produto: {primeira_linha(proximo[1], 60)}",
                          "estado": "info"})
    else:
        itens.append({"rotulo": "Mirian · fila de produtos", "valor": "fila-produtos.tsv não encontrada", "estado": "erro"})

    return itens, lista, {"video_hoje": nome, "afiliar": afiliar, "buracos": len(buracos)}


# ---------- jessé.ia ----------
def jesseia_local(hoje):
    pastas = [p for p in sorted(SAIDA.glob(f"{hoje:%Y-%m-%d}-*")) if p.is_dir() and not p.name.endswith("-mirian")] \
        if SAIDA.exists() else []
    sts = [ler_json(p / "post.json").get("status", "gerado") for p in pastas if (p / "video.mp4").exists()]
    return sts


def jesseia_zernio(chave):
    agend = zget(chave, "posts", status="scheduled", limit=50).get("posts", [])
    pub = zget(chave, "posts", status="published", limit=30).get("posts", [])
    falhas = zget(chave, "posts", status="failed", limit=20).get("posts", [])
    return agend, pub, falhas


def jesseia(hoje, zernio):
    itens, lista = [], []
    sts = jesseia_local(hoje)
    if sts:
        cont = ", ".join(f"{sts.count(s)} {s}" for s in sorted(set(sts)))
        itens.append({"rotulo": "jessé.ia · vídeos de hoje", "valor": f"{len(sts)} ({cont})", "estado": "ok"})
    else:
        itens.append({"rotulo": "jessé.ia · vídeos de hoje", "valor": "nenhum gerado", "estado": "atencao"})

    agendados = publicados_hoje = 0
    ultimo = None
    if isinstance(zernio, Exception):
        itens.append({"rotulo": "jessé.ia · Zernio", "valor": f"sem resposta ({type(zernio).__name__})", "estado": "erro"})
        return itens, lista, {"agendados": None, "publicados_hoje": None, "videos_hoje": len(sts)}

    agend, pub, falhas = zernio
    for post in agend:
        for p in plataformas(post, CONTA_JESSEIA):
            agendados += 1
            quando = utc_brt(post.get("scheduledFor"))
            lista.append({"quando": quando, "texto": f"@jesse.ia · agendado · {primeira_linha(post.get('content'))}",
                          "estado": "info"})
    for post in pub:
        for p in plataformas(post, CONTA_JESSEIA):
            quando = utc_brt(p.get("publishedAt") or post.get("scheduledFor"))
            if ultimo is None or quando > ultimo[0]:
                ultimo = (quando, p.get("platformPostUrl"))
            if quando and quando.date() == hoje:
                publicados_hoje += 1
                item = {"quando": quando, "texto": f"@jesse.ia · publicado · {primeira_linha(post.get('content'))}",
                        "estado": "ok"}
                if p.get("platformPostUrl"):
                    item["link"] = p["platformPostUrl"]
                lista.append(item)
    falhas_7d = 0
    for post in falhas:
        for p in plataformas(post, CONTA_JESSEIA):
            quando = utc_brt(post.get("scheduledFor"))
            if quando and (agora() - quando).days < 7:
                falhas_7d += 1

    itens.append({"rotulo": "jessé.ia · agendados no Zernio", "valor": str(agendados),
                  "estado": "ok" if agendados else "atencao"})
    itens.append({"rotulo": "jessé.ia · publicados hoje", "valor": str(publicados_hoje), "estado": "info"})
    if ultimo:
        itens.append({"rotulo": "jessé.ia · último publicado", "valor": fmt(ultimo[0]), "estado": "ok"})
    if falhas_7d:
        itens.append({"rotulo": "jessé.ia · falhas em 7 dias", "valor": str(falhas_7d), "estado": "erro"})
    return itens, lista, {"agendados": agendados, "publicados_hoje": publicados_hoje, "videos_hoje": len(sts),
                          "ultimo_url": ultimo[1] if ultimo else None}


# ---------- @vendaepop (loja) ----------
def loja_zernio(chave):
    pub = zget(chave, "posts", status="published", limit=30).get("posts", [])
    agend = zget(chave, "posts", status="scheduled", limit=30).get("posts", [])
    return pub, agend


def loja(hoje, zernio):
    itens, lista = [], []
    # última linha por slug no banco de clipes (o csv acumula linhas repetidas)
    estado_slug = {}
    if CLIPES.exists():
        with CLIPES.open(newline="") as f:
            for l in csv.DictReader(f):
                estado_slug[l.get("slug")] = (l.get("data"), (l.get("vendaepop") or "").strip())
    rascunhos = sorted(s for s, (_, v) in estado_slug.items() if v == "rascunho")
    postados = sum(1 for _, v in estado_slug.values() if v == "postado")
    itens.append({"rotulo": "vendaepop · rascunhos pra postar no app", "valor": str(len(rascunhos)),
                  "estado": "atencao" if rascunhos else "ok"})
    itens.append({"rotulo": "vendaepop · postados (banco)", "valor": str(postados), "estado": "info"})
    for s in rascunhos[:5]:
        d = estado_slug[s][0]
        try:
            dd = datetime.date.fromisoformat(d)
        except (TypeError, ValueError):
            dd = hoje
        lista.append({"quando": dd, "texto": f"@vendaepop · rascunho na caixa do TikTok · {s}", "estado": "atencao"})

    if isinstance(zernio, Exception):
        itens.append({"rotulo": "vendaepop · Zernio", "valor": f"sem resposta ({type(zernio).__name__})", "estado": "erro"})
        return itens, lista, {"rascunhos": len(rascunhos)}
    pub, agend = zernio
    ultimo = None
    for post in pub:
        for p in plataformas(post):
            quando = utc_brt(p.get("publishedAt") or post.get("scheduledFor"))
            if ultimo is None or quando > ultimo:
                ultimo = quando
    n_agend = sum(len(plataformas(p)) for p in agend)
    itens.append({"rotulo": "vendaepop · agendados no Zernio", "valor": str(n_agend), "estado": "info"})
    if ultimo:
        itens.append({"rotulo": "vendaepop · último pelo Zernio", "valor": fmt(ultimo), "estado": "info"})
    return itens, lista, {"rascunhos": len(rascunhos), "agendados": n_agend}


def coletar():
    hoje = agora().date()
    chave_jesse = env_proj("ZERNIO_API_KEY") or segredo("ZERNIO_API_KEY")
    chave_loja = env_proj("ZERNIO_LOJA_API_KEY")

    def seguro(fn, *a):
        try:
            return fn(*a)
        except Exception as e:
            return e

    with ThreadPoolExecutor(max_workers=2) as ex:
        fj = ex.submit(seguro, jesseia_zernio, chave_jesse)
        fl = ex.submit(seguro, loja_zernio, chave_loja)
        zj, zl = fj.result(), fl.result()

    i_m, l_m, r_m = mirian(hoje)
    i_j, l_j, r_j = jesseia(hoje, zj)
    i_l, l_l, r_l = loja(hoje, zl)

    # lista: hoje e futuro, mais próximos primeiro
    def chave_ord(x):
        q = x["quando"]
        if not isinstance(q, datetime.datetime):
            q = datetime.datetime.combine(q, datetime.time(0), FUSO)
        return q
    corte = datetime.datetime.combine(hoje, datetime.time(0), FUSO)
    lista = [x for x in l_j + l_m + l_l if chave_ord(x) >= corte or x["estado"] == "atencao"]
    lista.sort(key=chave_ord)
    for x in lista:
        x["quando"] = fmt(x["quando"])

    # frase falada
    partes = []
    if r_j.get("agendados") is None:
        partes.append(f"o jessé.ia tem {r_j['videos_hoje']} vídeos de hoje e o Zernio não respondeu")
    else:
        partes.append(f"o jessé.ia tem {qtd(r_j['publicados_hoje'], 'publicado')} hoje e "
                      f"{qtd(r_j['agendados'], 'agendado')}")
    if r_m["video_hoje"]:
        st = next((i["valor"] for i in i_m if i["rotulo"] == "Mirian · vídeo de hoje"), "")
        partes.append(f"a Mirian está com o vídeo {st}")
    else:
        partes.append("a Mirian ainda não tem vídeo hoje")
    if r_l["rascunhos"]:
        partes.append(f"a vendaepop tem {qtd(r_l['rascunhos'], 'rascunho')} esperando o senhor postar no app")
    resumo = "No TikTok, " + ", ".join(partes[:-1]) + (" e " if len(partes) > 1 else "") + partes[-1] + "."
    if r_m["afiliar"] < 7:
        resumo += f" Restam só {r_m['afiliar']} produtos pra afiliar na fila da Mirian."

    dados = {
        "titulo": "TikTok",
        "itens": i_j + i_m + i_l,
        "lista": lista[:15],
        "links": [
            {"rotulo": "@jesse.ia", "url": "https://www.tiktok.com/@jesse.ia"},
            {"rotulo": "@mirian.dicas1", "url": "https://www.tiktok.com/@mirian.dicas1"},
            {"rotulo": "@vendaepop", "url": "https://www.tiktok.com/@vendaepop"},
        ],
    }
    return ok(dados, resumo)


if __name__ == "__main__":
    rodar(coletar)
