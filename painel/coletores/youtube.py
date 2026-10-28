"""Coletor YouTube (Jesus é Pop PT e ES). Lê o jarvis_yt.db e o log da coleta só pra leitura."""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import datetime
import re
import unicodedata

from _base import FUSO, MKT, agora, erro, ok, rodar, sqlite_ro

DB = MKT / "Jesusepop/jarvis_yt.db"
LOGS = MKT / "Jesusepop/metricas/logs"  # coleta_AAAA-MM-DD.log, cada rodada abre com "== dd/mm HH:MM"
CONTAS = ("es", "pt")
NOMES = {"pt": "Jesus é Pop PT", "es": "Jesus é Pop ES"}
IDIOMA = {"pt": "português", "es": "espanhol"}

# Programa de Parcerias do YouTube, regra principal (monetização por anúncio):
# 1.000 inscritos E (4.000 horas públicas de vídeos longos nos últimos 12 meses
# OU 10 milhões de views públicas de Shorts nos últimos 90 dias).
YPP_INSCRITOS = 1_000
YPP_HORAS_LONGO = 4_000
YPP_VIEWS_SHORTS = 10_000_000

# canal com menos views que isso em 7 dias entra como "parado" no resumo e na frase
PARADO_VIEWS7 = 100
# views7 caiu mais que isso (em %) frente a 7 dias antes: estado atencao
QUEDA_ATENCAO = 20
# a API do YouTube arredonda inscritos a partir de 1.000 (3 dígitos significativos)
INSCRITOS_ARREDONDA = 1_000


def num(n):
    return f"{n:,}".replace(",", ".")


def dec(x, casas=1):
    return f"{x:.{casas}f}".replace(".", ",")


def curto(n):
    """Número curto pro destaque, até 8 caracteres: 950, 17,9 mil, 179 mil, 1,2 mi."""
    if n < 1_000:
        return str(n)
    if n < 100_000:
        return f"{dec(n / 1_000)} mil"
    if n < 1_000_000:
        return f"{round(n / 1_000)} mil"
    return f"{dec(n / 1_000_000)} mi"


def pct(x):
    """Porcentagem de progresso: 28%, 0,3%."""
    return f"{dec(x)}%" if x < 10 else f"{x:.0f}%"


def var(p):
    """Variação com sinal: +136%, -12%, +3,5%, 0%."""
    v = abs(p)
    txt = dec(v) if v < 10 else f"{v:.0f}"
    if txt in ("0", "0,0"):
        return "0%"
    return f"{'+' if p > 0 else '-'}{txt}%"


def horas(h):
    return f"{dec(h)} h" if h < 10 else f"{num(round(h))} h"


def dm(data):
    """'2026-10-28' -> '28/10'."""
    return f"{data[8:10]}/{data[5:7]}"


def limpa_titulo(txt):
    """Sem emoji, sem hashtag, sem travessão e sem separador sobrando nas pontas."""
    txt = re.sub(r"#\w+", " ", txt or "")
    fora = {0x200D, 0x20E3, 0xFE0E, 0xFE0F}
    txt = "".join(ch for ch in txt if unicodedata.category(ch) not in ("So", "Cs", "Co")
                  and ord(ch) not in fora and not 0x1F3FB <= ord(ch) <= 0x1F3FF)
    txt = re.sub(r"\s*[\u2014\u2013]\s*", ", ", txt)
    return " ".join(txt.split()).strip(" |·:-,")


def corta(txt, n):
    """Até n caracteres com reticências; corta no fim da palavra quando dá."""
    if len(txt) <= n:
        return txt
    cut = txt[: n - 1]
    if " " in cut[-15:]:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip(" |·:-,") + "…"


def falado(titulo):
    """Título pra voz: só até o '|' e sem caixa alta gritada."""
    t = titulo.split("|")[0].strip(" ,:-")
    letras = [ch for ch in t if ch.isalpha()]
    if letras and sum(ch.isupper() for ch in letras) / len(letras) > 0.6:
        t = t.lower()
        t = t[:1].upper() + t[1:]
    return t


def plural(n, um, varios):
    return f"{n} {um if n == 1 else varios}"


def hora_coleta(data):
    """Hora da última rodada da coleta no log daquele dia, ou '' se não der pra ler."""
    try:
        texto = (LOGS / f"coleta_{data}.log").read_text(errors="replace")
    except OSError:
        return ""
    achados = re.findall(r"^== \d{2}/\d{2} (\d{2}:\d{2})", texto, re.M)
    return achados[-1] if achados else ""


def ler_conta(c, conta):
    """Último dia, dia de base (7 dias antes ou o mais próximo anterior) e publicados 7 dias."""
    ult = c.execute("SELECT * FROM canal_dia WHERE conta=? ORDER BY data DESC LIMIT 1", (conta,)).fetchone()
    if not ult:
        return None
    alvo = str(datetime.date.fromisoformat(ult["data"]) - datetime.timedelta(days=7))
    base = c.execute("SELECT * FROM canal_dia WHERE conta=? AND data<=? ORDER BY data DESC LIMIT 1",
                     (conta, alvo)).fetchone()
    if base is None:  # histórico curto: compara com o primeiro dia que existe
        base = c.execute("SELECT * FROM canal_dia WHERE conta=? AND data<? ORDER BY data LIMIT 1",
                         (conta, ult["data"])).fetchone()
    dias = (datetime.date.fromisoformat(ult["data"]) - datetime.date.fromisoformat(base["data"])).days if base else 0
    # publicados: a agenda do Zernio bate com videos_total; a tabela video só tem o que já entrou no Analytics
    agora_utc = datetime.datetime.now(datetime.timezone.utc)
    fmt = lambda d: d.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    pub = {"short": 0, "longo": 0}
    for r in c.execute("SELECT tipo, count(*) n FROM agenda WHERE conta=? AND status='published' "
                       "AND quando_utc>=? AND quando_utc<=? GROUP BY tipo",
                       (conta, fmt(agora_utc - datetime.timedelta(days=7)), fmt(agora_utc))):
        pub["short" if r["tipo"] == "short" else "longo"] += r["n"]
    return {"ult": ult, "base": base, "dias": dias, "pub": pub}


def itens_conta(conta, x):
    nome, u, b, dias = NOMES[conta], x["ult"], x["base"], x["dias"]
    pref = f"youtube.{conta}"
    periodo = "7 dias" if dias == 7 else f"{dias} dias"
    itens = []

    insc = u["inscritos"] or 0
    arred = insc >= INSCRITOS_ARREDONDA
    if b:
        ganho = insc - (b["inscritos"] or 0)
        valor = f"{num(insc)} ({'+' if ganho >= 0 else ''}{num(ganho)} em {periodo}" + (", número arredondado)" if arred else ")")
    else:
        ganho, valor = 0, f"{num(insc)} (sem dia anterior pra comparar)"
    if arred:  # o saldo do Analytics é exato, o número público não
        saldo = (u["subs_ganhos28"] or 0) - (u["subs_perdidos28"] or 0)
        valor += f" · saldo 28 dias: {'+' if saldo >= 0 else ''}{num(saldo)}"
    itens.append({"id": f"{pref}.inscritos", "rotulo": f"{nome} · inscritos", "valor": valor,
                  "estado": "ok" if ganho > 0 else "info"})

    v7 = u["views7"] or 0
    v7b = (b["views7"] or 0) if b else 0
    if b and v7b:
        p = (v7 - v7b) / v7b * 100
        quando = "a semana anterior" if dias == 7 else f"os 7 dias até {dm(b['data'])}"
        valor, estado = f"{num(v7)} ({var(p)} sobre {quando})", ("ok" if p > 0 else "atencao" if p < -QUEDA_ATENCAO else "info")
    else:
        p, valor, estado = None, f"{num(v7)} (sem base pra comparar)", ("ok" if v7 else "info")
    itens.append({"id": f"{pref}.views7", "rotulo": f"{nome} · views 7 dias", "valor": valor, "estado": estado})

    itens.append({"id": f"{pref}.views28", "rotulo": f"{nome} · views 28 dias",
                  "valor": f"{num(u['views28'] or 0)} views · {horas((u['min28'] or 0) / 60)} assistidas",
                  "estado": "info"})

    pub = x["pub"]
    total_pub = pub["short"] + pub["longo"]
    itens.append({"id": f"{pref}.publicados7", "rotulo": f"{nome} · publicados 7 dias",
                  "valor": f"{total_pub} ({plural(pub['short'], 'short', 'shorts')}, {plural(pub['longo'], 'longo', 'longos')})",
                  "estado": "ok" if total_pub else "info"})

    hl, vs = u["horas_longo365"] or 0, u["views_shorts90"] or 0
    partes = ["inscritos ok" if insc >= YPP_INSCRITOS else
              f"inscritos {num(insc)} de {num(YPP_INSCRITOS)} ({pct(insc / YPP_INSCRITOS * 100)})"]
    partes.append(f"longos {horas(hl)} de {num(YPP_HORAS_LONGO)} em 12 meses ({pct(min(hl / YPP_HORAS_LONGO * 100, 100))})")
    partes.append(f"Shorts {num(vs)} de 10 mi em 90 dias ({pct(min(vs / YPP_VIEWS_SHORTS * 100, 100))})")
    itens.append({"id": f"{pref}.monetizacao", "rotulo": f"{nome} · monetização", "valor": " · ".join(partes),
                  "estado": "info"})
    return itens, p


def top_videos(c, conta):
    d = c.execute("SELECT max(data) d FROM video_dia WHERE conta=?", (conta,)).fetchone()["d"]
    if not d:
        return []
    linhas = c.execute(
        "SELECT d.id, d.views28, d.ctr, d.impressoes, v.titulo, v.tipo, v.publicado, "
        "(SELECT a.quando_utc FROM agenda a WHERE a.conta=d.conta AND a.titulo=v.titulo AND a.status='published' "
        " ORDER BY a.quando_utc LIMIT 1) quando_utc "
        "FROM video_dia d LEFT JOIN video v ON v.conta=d.conta AND v.id=d.id "
        "WHERE d.conta=? AND d.data=? ORDER BY d.views28 DESC, d.impressoes DESC, d.id LIMIT 3", (conta, d)).fetchall()
    saida = []
    for r in linhas:
        if r["quando_utc"]:  # hora de publicação vem da agenda (mesmo título); a tabela video só tem a data
            q = datetime.datetime.fromisoformat(r["quando_utc"].replace("Z", "+00:00")).astimezone(FUSO)
            quando = f"{q:%d/%m %H:%M}"
        else:
            quando = dm(r["publicado"]) if r["publicado"] else ""
        titulo = limpa_titulo(r["titulo"]) or r["id"]
        texto = f"{conta.upper()} · {corta(titulo, 50)} · {num(r['views28'] or 0)} views em 28 dias"
        if r["ctr"] is not None and r["impressoes"]:
            texto += f" · CTR {dec(r['ctr'])}%"
        link = f"https://youtube.com/shorts/{r['id']}" if r["tipo"] == "short" else f"https://youtu.be/{r['id']}"
        saida.append({"quando": quando, "texto": texto, "estado": "info", "link": link,
                      "_views": r["views28"] or 0, "_titulo": titulo})
    return saida


def coletar():
    if not DB.exists():
        return erro(f"banco não encontrado: {DB}")
    c = sqlite_ro(DB)
    c.row_factory = lambda cur, row: {d[0]: v for d, v in zip(cur.description, row)}
    itens, lista, lidos, variacoes = [], [], {}, {}
    try:
        for conta in CONTAS:
            try:
                x = ler_conta(c, conta)
                if x is None:
                    itens.append({"id": f"youtube.{conta}.inscritos", "rotulo": f"{NOMES[conta]} · inscritos",
                                  "valor": "sem coleta", "estado": "atencao"})
                    continue
                lidos[conta] = x
                novos, variacoes[conta] = itens_conta(conta, x)
                itens += novos
            except Exception as e:
                itens.append({"id": f"youtube.{conta}.leitura", "rotulo": f"{NOMES[conta]} · leitura",
                              "valor": f"{type(e).__name__}: {e}"[:120], "estado": "erro"})
        for conta in CONTAS:
            try:
                lista += top_videos(c, conta)
            except Exception as e:
                itens.append({"id": f"youtube.{conta}.videos", "rotulo": f"{NOMES[conta]} · vídeos",
                              "valor": f"{type(e).__name__}: {e}"[:120], "estado": "erro"})
        try:
            ult = max(x["ult"]["data"] for x in lidos.values()) if lidos else None
            falhas = []
            if ult:
                falhas = [r["conta"].split("_")[0].upper() for r in c.execute(
                    "SELECT conta FROM coleta WHERE data=? AND conta LIKE '%\\_canal' ESCAPE '\\' AND ok=0", (ult,))]
        except Exception as e:
            ult, falhas = None, []
            itens.append({"id": "youtube.coleta", "rotulo": "Coleta", "valor": f"{type(e).__name__}: {e}"[:120],
                          "estado": "erro"})
    finally:
        c.close()

    # dados: data do último canal_dia e hora da coleta
    hoje = agora().date()
    if ult:
        hora = hora_coleta(ult)
        valor = f"dados de {dm(ult)}" + (f", coleta das {hora}" if hora else "")
        atrasadas = [f"{k.upper()} parado em {dm(x['ult']['data'])}" for k, x in lidos.items() if x["ult"]["data"] != ult]
        if falhas:
            valor += f" · erro na coleta {'/'.join(falhas)}"
        if atrasadas:
            valor += " · " + ", ".join(atrasadas)
        velho = datetime.date.fromisoformat(ult) < hoje - datetime.timedelta(days=1)
        estado = "atencao" if (velho or falhas or atrasadas) else "info"
    else:
        valor, estado = "sem coleta no banco", "atencao"
    itens.append({"id": "youtube.dados", "rotulo": "Dados do YouTube", "valor": valor, "estado": estado})

    # destaque, frase e resumo
    v7 = {k: x["ult"]["views7"] or 0 for k, x in lidos.items()}
    v7b = {k: (x["base"]["views7"] or 0) if x["base"] else 0 for k, x in lidos.items()}
    total7, total7b = sum(v7.values()), sum(v7b.values())
    p_total = (total7 - total7b) / total7b * 100 if total7b else None
    destaque = {"valor": curto(total7), "rotulo": "views no YouTube em 7 dias",
                "estado": "info" if p_total is None else ("ok" if p_total > 0 else "atencao" if p_total < -QUEDA_ATENCAO else "info")}

    ganho7 = {k: v7[k] - v7b[k] for k in lidos}
    lider = max(lidos, key=lambda k: (ganho7[k], v7[k])) if lidos else None
    parados = [k for k in lidos if v7[k] < PARADO_VIEWS7 and k != lider]

    if lider:
        pl = variacoes.get(lider)
        pontos = [f"{lider.upper()} puxa: {num(v7[lider])} views em 7 dias" + (f" ({var(pl)})" if pl is not None else "")]
        for k in lidos:
            if k == lider:
                continue
            if k in parados:
                pontos.append(f"{k.upper()} parado, {num(v7[k])} views")
            else:
                pk = variacoes.get(k)
                pontos.append(f"{k.upper()} com {num(v7[k])}" + (f" ({var(pk)})" if pk is not None else ""))
        frase = corta(". ".join(pontos) + ".", 90)
    else:
        frase = "Sem dados do YouTube no banco."

    if not lider:
        resumo = "Senhor, não tenho dados do YouTube no banco."
    else:
        idl = IDIOMA[lider]
        if p_total is None:
            mov = ""
        elif round(p_total) == 0:
            mov = ", estável frente à semana anterior"
        else:
            mov = f", {'alta' if p_total > 0 else 'queda'} de {var(abs(p_total)).lstrip('+')}"
        f1 = f"Senhor, o YouTube somou {num(total7)} views em 7 dias{mov}"
        f1 += f", puxado pelo canal em {idl}." if ganho7[lider] > 0 else "."
        u = lidos[lider]
        insc = u["ult"]["inscritos"] or 0
        if insc >= INSCRITOS_ARREDONDA:
            f2 = f"O canal em {idl} tem cerca de {num(insc)} inscritos"
        else:
            g = insc - (u["base"]["inscritos"] or 0) if u["base"] else 0
            f2 = f"O canal em {idl} chegou a {num(insc)} inscritos" + (f", {num(g)} a mais na semana" if g > 0 else "")
        if parados:
            nomes = " e o em ".join(IDIOMA[k] for k in parados)
            f2 += f", e o em {nomes} está parado, com {num(sum(v7[k] for k in parados))} views."
        else:
            f2 += "."
        frases = [f1, f2]
        topo = max(lista, key=lambda r: r["_views"], default=None)
        if topo and topo["_views"]:
            frases.append(f"O vídeo que mais puxa é {falado(topo['_titulo'])}.")
        resumo = " ".join(frases)

    for r in lista:
        r.pop("_views", None)
        r.pop("_titulo", None)

    dados = {"titulo": "YouTube", "destaque": destaque, "frase": frase, "itens": itens,
             "lista_titulo": "VÍDEOS QUE MAIS PUXAM (28 DIAS)", "lista": lista,
             "links": [{"rotulo": "YouTube Studio", "url": "https://studio.youtube.com"}]}
    return ok(dados, resumo)


if __name__ == "__main__":
    rodar(coletar)
