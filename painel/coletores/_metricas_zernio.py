"""Peças comuns dos coletores de métricas (metricas_tiktok e metricas_instagram). Não é coletor.

Fonte: API REST do Zernio, só GET por _base.zernio_get. Nomes reais dos filtros (camelCase; nome
desconhecido a API ignora sem avisar, por isso o código confere a conta de cada post):
  GET analytics               accountId, fromDate, toDate (AAAA-MM-DD, dia UTC), sortBy (date, views...),
                              order (asc, desc), limit (até 100; 200 dá HTTP 400), page
  GET accounts/follower-stats accountIds (vírgula), fromDate, toDate, granularity (daily, weekly, monthly)
  GET accounts                lista as contas da chave (platform, username, isActive)
As contas saem do GET accounts de cada chave, filtradas por plataforma e isActive. Nenhum id fixo."""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import datetime
import re
import threading
import time
import urllib.error
import urllib.parse

from _base import FUSO, MKT, ok, segredo, zernio_get

ENV_PROJ = MKT / "tiktok-video-ia" / ".env"
LIMITE_RODADA1 = 3.5  # s para contas e seguidores
LIMITE_TOTAL = 6.5    # s para a coleta inteira (o servidor corta cada coletor em 8 s)
LISTA_TITULO = "POSTS QUE MAIS PUXAM (28 DIAS)"
TOP_POR_CONTA = 3
REDE = {"tiktok": "TikTok", "instagram": "Instagram"}
PERFIL = {"tiktok": "https://www.tiktok.com/@{}", "instagram": "https://www.instagram.com/{}/"}
UTC = datetime.timezone.utc


# ---------- chaves (nunca saem daqui: nem print, nem dados, nem mensagem de erro) ----------

def env_proj(nome):
    """Lê uma variável do .env do tiktok-video-ia (a loja tem chave própria do Zernio)."""
    achado = ""
    if ENV_PROJ.exists():
        for linha in ENV_PROJ.read_text().splitlines():
            if linha.startswith(nome + "="):
                achado = linha.split("=", 1)[1].strip().strip('"').strip("'")
    return achado


def chave_de(nome):
    if nome == "jesse":
        return segredo("ZERNIO_API_KEY") or env_proj("ZERNIO_API_KEY")
    if nome == "loja":
        return env_proj("ZERNIO_LOJA_API_KEY")
    return ""


# ---------- chamadas em paralelo com prazo ----------

def motivo(e):
    """Texto curto da falha, sem URL, cabeçalho ou chave."""
    if isinstance(e, urllib.error.HTTPError):
        return f"Zernio respondeu HTTP {e.code}"
    if isinstance(e, TimeoutError) or isinstance(getattr(e, "reason", None), TimeoutError):
        return "Zernio demorou demais"
    if isinstance(e, urllib.error.URLError):
        return "sem conexão com o Zernio"
    if isinstance(e, RuntimeError) and "falta chave" in str(e):
        return "falta chave do Zernio"
    return f"falha na leitura ({type(e).__name__})"


def em_paralelo(tarefas, ate):
    """tarefas: {nome: função sem argumento}. Threads daemon; espera até o instante `ate`
    (time.monotonic). Devolve {nome: (True, valor) ou (False, motivo)}. Nunca levanta."""
    saida, trava = {}, threading.Lock()

    def roda(nome, f):
        try:
            res = (True, f())
        except Exception as e:  # falha de uma chamada vira motivo, não exceção
            res = (False, motivo(e))
        with trava:
            saida[nome] = res

    fios = [threading.Thread(target=roda, args=(n, f), daemon=True) for n, f in tarefas.items()]
    for t in fios:
        t.start()
    for t in fios:
        t.join(max(0.0, ate - time.monotonic()))
    with trava:
        return {n: saida.get(n, (False, "Zernio demorou demais")) for n in tarefas}


def get(caminho, chave, ate, **params):
    """zernio_get com 1 nova tentativa em HTTP 429 (limite por segundo do analytics), se der tempo."""
    try:
        return zernio_get(caminho, chave=chave, **params)
    except urllib.error.HTTPError as e:
        if e.code != 429 or ate - time.monotonic() < 2:
            raise
    time.sleep(1)
    return zernio_get(caminho, chave=chave, **params)


# ---------- formatação ----------

def mil(n):
    return f"{int(n):,}".replace(",", ".")


def curto(n):
    """Até 8 caracteres: 4.120, 17,9 mil, 123 mil, 1,2 mi."""
    n = int(n)
    if n < 10_000:
        return mil(n)
    if n < 100_000:
        return f"{n // 100 / 10:.1f}".replace(".", ",") + " mil"
    if n < 1_000_000:
        return f"{n // 1000} mil"
    if n < 10_000_000:
        return f"{n // 100_000 / 10:.1f}".replace(".", ",") + " mi"
    return f"{n // 1_000_000} mi"


def plural(n, um, varios):
    return f"{mil(n)} {um if n == 1 else varios}"


def trecho(txt, n=50):
    """Início do texto do post, sem hashtag e sem travessão, até n caracteres."""
    txt = re.sub(r"#\S+", " ", txt or "")
    txt = re.sub(r"\s*[\u2014\u2013]\s*", ", ", txt)
    txt = " ".join(txt.split()).strip(" ,.;:-|")
    if not txt:
        return "(sem legenda)"
    return txt if len(txt) <= n else txt[: n - 1].rstrip(" ,.;:-") + "…"


def sem_query(url):
    if not url:
        return ""
    p = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((p.scheme, p.netloc, p.path, "", ""))


def slug(user):
    return re.sub(r"[^a-z0-9.-]+", "-", (user or "").lower()).strip(".-") or "conta"


def quando(p):
    v = p.get("publishedAt") or p.get("scheduledFor") or ""
    try:
        return datetime.datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None


# ---------- leitura de posts ----------

def entrada_da_conta(p, conta_id, plataforma):
    """Entrada de platforms[] do post que é desta conta. None se o post é de outra conta."""
    pls = p.get("platforms") or []
    for pl in pls:
        aid = pl.get("accountId")
        aid = aid.get("_id") if isinstance(aid, dict) else aid
        if aid == conta_id:
            return pl
    if not pls and p.get("platform") == plataforma:
        return {}
    return None


def metricas(p, conta_id, plataforma):
    """(views, curtidas, comentários, compartilhamentos) do post nesta conta, ou None se não é dela."""
    pl = entrada_da_conta(p, conta_id, plataforma)
    if pl is None:
        return None
    a = pl.get("analytics") or p.get("analytics") or {}
    return tuple(int(a.get(k) or 0) for k in ("views", "likes", "comments", "shares"))


def posts_desde(conta, desde, ate, **extra):
    """Posts da conta publicados de `desde` (UTC) até agora. Pagina de 100 em 100, até 5 páginas."""
    posts, pagina = [], 1
    while True:
        r = get("analytics", conta["chave"], ate, accountId=conta["id"],
                fromDate=desde.date().isoformat(), limit=100, page=pagina, **extra)
        posts += r.get("posts") or []
        paginas = (r.get("pagination") or {}).get("pages") or 1
        if pagina >= min(paginas, 5):
            return posts
        pagina += 1


def top_posts(conta, desde, ate):
    r = get("analytics", conta["chave"], ate, accountId=conta["id"], fromDate=desde.date().isoformat(),
            sortBy="views", order="desc", limit=10)
    return r.get("posts") or []


# ---------- seguidores ----------

def ganho_7d(serie, atual):
    """Seguidores ganhos em 7 dias pela série diária do follower-stats. None sem dados."""
    pts = []
    for s in serie or []:
        try:
            pts.append((datetime.date.fromisoformat(str(s.get("date"))[:10]), int(s["followers"])))
        except (KeyError, TypeError, ValueError):
            continue
    pts.sort()
    if not pts:
        return None
    alvo = pts[-1][0] - datetime.timedelta(days=7)
    antes = [f for d, f in pts if d <= alvo]
    base = antes[-1] if antes else pts[0][1]
    return (atual if atual is not None else pts[-1][1]) - base


# ---------- o bloco ----------

def coletar_rede(bloco, titulo, plataforma, nomes_chaves):
    inicio = time.monotonic()
    agora_utc = datetime.datetime.now(UTC)
    hoje = agora_utc.date()
    desde7 = agora_utc - datetime.timedelta(days=7)
    desde28 = agora_utc - datetime.timedelta(days=28)
    rede = REDE.get(plataforma, plataforma)
    itens, lista, links, falas = [], [], [], []

    # rodada 1: contas e seguidores de cada chave, em paralelo
    chaves = {n: chave_de(n) for n in nomes_chaves}
    tarefas = {}
    for n, k in chaves.items():
        if k:
            fim1 = inicio + LIMITE_RODADA1
            tarefas[("contas", n)] = lambda k=k, fim1=fim1: get("accounts", k, fim1)
            tarefas[("seguidores", n)] = lambda k=k, fim1=fim1: get(
                "accounts/follower-stats", k, fim1,
                fromDate=(hoje - datetime.timedelta(days=8)).isoformat(), granularity="daily")
    r1 = em_paralelo(tarefas, inicio + LIMITE_RODADA1)

    contas, vistos = [], set()
    for n in nomes_chaves:
        if not chaves[n]:
            falha = "falta chave do Zernio"
        else:
            ok_c, val_c = r1[("contas", n)]
            ok_s, val_s = r1[("seguidores", n)]
            fonte = val_c if ok_c else (val_s if ok_s else None)  # follower-stats também lista as contas
            falha = None if fonte is not None else val_c
        if falha:
            itens.append({"id": f"{bloco}.{n}.contas", "rotulo": f"Contas do Zernio (chave {n})",
                          "valor": falha, "estado": "erro"})
            falas.append((f"não consegui ler as contas da chave {n}", None))
            continue
        seg = {}
        if ok_s:
            for a in val_s.get("accounts") or []:
                seg[a.get("_id")] = (a.get("currentFollowers"), (val_s.get("stats") or {}).get(a.get("_id")))
        for a in fonte.get("accounts") or []:
            if a.get("platform") != plataforma or not a.get("isActive") or a.get("_id") in vistos:
                continue
            vistos.add(a["_id"])
            contas.append({"id": a["_id"], "user": a.get("username") or a["_id"], "chave": chaves[n],
                           "seg": seg.get(a["_id"]), "seg_falha": None if ok_s else val_s})

    # rodada 2: posts de 7 dias e top de 28 dias de cada conta, filtrados por accountId, em paralelo
    tarefas = {}
    fim = inicio + LIMITE_TOTAL
    for c in contas:
        tarefas[(c["id"], 7)] = lambda c=c: posts_desde(c, desde7, fim)
        tarefas[(c["id"], 28)] = lambda c=c: top_posts(c, desde28, fim)
    r2 = em_paralelo(tarefas, fim)

    total_views, algum_ok, resumo_contas, ganhos, melhores = 0, False, [], [], []
    for c in contas:
        user, base_id = c["user"], f"{bloco}.{slug(c['user'])}"
        links.append({"rotulo": f"@{user} no {rede}", "url": PERFIL[plataforma].format(user)})
        try:
            # seguidores
            seguidores, ganho = None, None
            if c["seg"]:
                seguidores = c["seg"][0]
                ganho = ganho_7d(c["seg"][1], seguidores)
            if seguidores is None:
                itens.append({"id": f"{base_id}.seguidores", "rotulo": f"@{user} seguidores",
                              "valor": c["seg_falha"] or "sem dados de seguidores", "estado": "erro"})
            else:
                g = "" if ganho is None else f" ({'+' if ganho > 0 else ''}{mil(ganho)} em 7 dias)"
                itens.append({"id": f"{base_id}.seguidores", "rotulo": f"@{user} seguidores",
                              "valor": mil(seguidores) + g, "estado": "ok" if (ganho or 0) > 0 else "info"})
                if ganho is not None:
                    ganhos.append((ganho, user))

            # semana
            ok7, val7 = r2[(c["id"], 7)]
            n_posts = views = None
            if ok7:
                n_posts = views = curt = coment = compart = 0
                for p in val7:
                    m = metricas(p, c["id"], plataforma)
                    dt = quando(p)
                    if m is None or dt is None or dt < desde7 or p.get("status", "published") != "published":
                        continue
                    n_posts += 1
                    views += m[0]
                    curt, coment, compart = curt + m[1], coment + m[2], compart + m[3]
                total_views += views
                algum_ok = True
                itens.append({"id": f"{base_id}.posts7", "rotulo": f"@{user} posts em 7 dias",
                              "valor": mil(n_posts), "estado": "info"})
                itens.append({"id": f"{base_id}.views7", "rotulo": f"@{user} views em 7 dias",
                              "valor": mil(views), "estado": "info"})
                itens.append({"id": f"{base_id}.engajamento7", "rotulo": f"@{user} engajamento em 7 dias",
                              "valor": f"{mil(curt + coment + compart)} ({mil(curt)} curtidas, "
                                       f"{mil(coment)} coment., {mil(compart)} compart.)",
                              "estado": "info"})
            else:  # um alerta só por conta: o motivo fica em posts7
                itens.append({"id": f"{base_id}.posts7", "rotulo": f"@{user} posts em 7 dias",
                              "valor": val7, "estado": "erro"})
                for campo, rot in (("views7", "views em 7 dias"), ("engajamento7", "engajamento em 7 dias")):
                    itens.append({"id": f"{base_id}.{campo}", "rotulo": f"@{user} {rot}",
                                  "valor": "sem dados", "estado": "info"})

            # top 28 dias
            ok28, val28 = r2[(c["id"], 28)]
            if ok28:
                tops = []
                for p in val28:
                    m, dt = metricas(p, c["id"], plataforma), quando(p)
                    if m is not None and dt is not None and dt >= desde28:
                        tops.append((m[0], dt, p))
                tops.sort(key=lambda t: t[0], reverse=True)
                for v, dt, p in tops[:TOP_POR_CONTA]:
                    item = {"quando": dt.astimezone(FUSO).strftime("%d/%m %H:%M"),
                            "texto": f"@{user} · {trecho(p.get('content'))} · {mil(v)} views", "estado": "info"}
                    if sem_query(p.get("platformPostUrl")):
                        item["link"] = sem_query(p.get("platformPostUrl"))
                    lista.append(item)
                if tops:
                    melhores.append((tops[0][0], user))
            else:
                lista.append({"quando": datetime.datetime.now(FUSO).strftime("%d/%m %H:%M"),
                              "texto": f"@{user} · não consegui ler os posts de 28 dias ({val28})",
                              "estado": "erro"})

            resumo_contas.append(frase_conta(user, seguidores, ganho, n_posts, views))
        except Exception as e:  # dado inesperado de uma conta não derruba o bloco
            itens.append({"id": f"{base_id}.leitura", "rotulo": f"@{user} leitura",
                          "valor": f"falha ao montar ({type(e).__name__})", "estado": "erro"})
            resumo_contas.append((f"não consegui ler {user} agora", None))

    if not contas and not itens:
        itens.append({"id": f"{bloco}.contas", "rotulo": f"Contas do {rede} no Zernio",
                      "valor": "nenhuma conta ativa", "estado": "atencao"})

    dados = {
        "titulo": titulo,
        "itens": itens,
        "lista": lista[:15],
        "lista_titulo": LISTA_TITULO,
        "links": links,
        "destaque": ({"valor": curto(total_views), "rotulo": "views em 7 dias", "estado": "info"} if algum_ok
                     else {"valor": "?", "rotulo": "views em 7 dias", "estado": "erro"}),
        "frase": frase_bloco(ganhos, melhores, len(contas)),
    }
    return ok(dados, resumo(rede, resumo_contas + falas))


def frase_conta(user, seguidores, ganho, n_posts, views):
    """(seguidores e ganho, posts e views) de uma conta, em pedaços de frase."""
    if seguidores is not None:
        a = f"{user} tem {plural(seguidores, 'seguidor', 'seguidores')}"
        if ganho is not None:
            a += (f", mais {mil(ganho)} na semana" if ganho > 0 else
                  f", menos {mil(-ganho)} na semana" if ganho < 0 else ", igual à semana passada")
    else:
        a = f"{user} ficou sem a contagem de seguidores"
    if n_posts is not None:
        b = f"fez {plural(n_posts, 'post', 'posts')} com {plural(views, 'view', 'views')} em 7 dias"
    else:
        b = "os posts da semana não vieram agora"
    return (a, b)


def resumo(rede, partes):
    """2 ou 3 frases curtas que o Jarvis fala, começando por "Senhor,". Sem travessão, emoji ou markdown.
    partes: [(pedaço a, pedaço b ou None)]. Uma conta vira 2 frases; várias, 1 frase por conta (até 3)."""
    def cap(s):
        return s[0].upper() + s[1:]

    if not partes:
        return f"Senhor, não achei conta ativa do {rede} no Zernio."
    if len(partes) == 1:
        a, b = partes[0]
        frases = [f"Senhor, no {rede}, {a}."] + ([f"{cap(b)}."] if b else [])
    else:
        frases = []
        for i, (a, b) in enumerate(partes[:3]):
            txt = f"{a} e {b}" if b else a
            if i == 0:
                frases.append(f"Senhor, no {rede}, {txt}.")
            else:
                frases.append(f"{cap(txt)}." if txt.startswith("não ") else f"A conta {txt}.")
    return " ".join(frases).replace("\u2014", ",").replace("\u2013", ",")


def frase_bloco(ganhos, melhores, n_contas):
    """Até 90 caracteres: quem mais ganhou seguidores e o post que mais puxou em 28 dias."""
    partes = []
    if ganhos:
        g, user = max(ganhos)
        if g > 0:
            partes.append(f"@{user} ganhou {plural(g, 'seguidor', 'seguidores')} em 7 dias")
        elif g < 0:
            partes.append(f"@{user} perdeu {plural(-g, 'seguidor', 'seguidores')} em 7 dias")
        else:
            partes.append("Seguidores estáveis em 7 dias")
    if melhores:
        v, user = max(melhores)
        partes.append(f"top 28 dias: @{user} com {mil(v)} views" if n_contas > 1
                      else f"melhor post de 28 dias com {mil(v)} views")
    if not partes:
        return "Sem métricas do Zernio agora"
    frase = "; ".join(partes)
    if len(frase) > 90:
        frase = partes[0]
    frase = frase[0].upper() + frase[1:] if not frase.startswith("@") else frase
    return frase if len(frase) <= 90 else frase[:89].rstrip() + "…"
