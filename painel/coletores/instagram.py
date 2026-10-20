"""Coletor do Instagram (@jesse.rodolfo): posts da fábrica de conteúdo + agenda do Zernio."""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import datetime
import re
from concurrent.futures import ThreadPoolExecutor

from _base import FUSO, MKT, agora, erro, ok, rodar, zernio_get

POSTS = MKT / "fabrica-conteudo" / "posts"
CONTA = "6aaa8dcc8d284ffb2107d885"  # instagram jesse.rodolfo no Zernio
DIAS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
ID_ZERNIO = re.compile(r"Zernio(?: post)?\s+([0-9a-f]{24})")


def fmt(dt):
    return dt.astimezone(FUSO).strftime("%d/%m %H:%M")


def limpa(txt):
    """Tira travessão de texto que vem de fora (título de post, nome de pasta)."""
    return re.sub(r"\s*[\u2014\u2013]\s*", ", ", txt or "")


def corta(txt, n):
    txt = " ".join(limpa(txt).split())
    return txt if len(txt) <= n else txt[: n - 1].rstrip() + "…"


def dia(d):
    return f"{DIAS[d.weekday()]} {d:%d/%m}"


def quando_zernio(p):
    v = p.get("scheduledFor") or p.get("publishedAt") or p.get("createdAt")
    return datetime.datetime.fromisoformat(v.replace("Z", "+00:00"))


def tipo_zernio(p):
    midias = p.get("mediaItems") or []
    if any(m.get("type") == "video" for m in midias):
        return "reel"
    return "carrossel" if len(midias) > 1 else "imagem"


def do_instagram(p):
    for pl in p.get("platforms") or []:
        conta = pl.get("accountId")
        conta = conta.get("_id") if isinstance(conta, dict) else conta
        if pl.get("platform") == "instagram" and conta == CONTA:
            return pl
    return None


def zernio(status):
    r = zernio_get("posts", status=status, limit=50)
    return [p for p in r.get("posts", []) if do_instagram(p)]


def pastas():
    """Uma entrada por pasta posts/AAAA-MM-DD-slug (menos teste)."""
    saida = []
    if not POSTS.is_dir():
        return saida
    for d in sorted(POSTS.iterdir()):
        m = re.match(r"(\d{4}-\d{2}-\d{2})-(.+)", d.name)
        if not d.is_dir() or not m:
            continue
        data = datetime.date.fromisoformat(m.group(1))
        slug = m.group(2)
        estado = (d / "estado.md").read_text(errors="ignore") if (d / "estado.md").exists() else ""
        reel = slug.startswith("reel-") or ((d / "gravacao.md").exists() and not (d / "slides.json").exists())
        if reel:
            arte = any((d / "saida").glob("*.mp4")) if (d / "saida").is_dir() else False
        else:
            final = d / "saida-final"
            arte = final.is_dir() and any(f.suffix.lower() in (".jpg", ".jpeg", ".png") for f in final.iterdir())
        nome = re.sub(r"^reel-", "", slug).replace("-", " ").strip()
        saida.append({
            "data": data, "pasta": d.name, "tipo": "reel" if reel else "carrossel",
            "titulo": nome[:1].upper() + nome[1:], "arte": arte,
            "descartado": "DESCARTADO" in estado,
            "ids": ID_ZERNIO.findall(estado),
        })
    return saida


def coletar():
    hoje_dt = agora()
    hoje = hoje_dt.date()
    itens, lista = [], []

    with ThreadPoolExecutor(3) as ex:
        futuros = {st: ex.submit(zernio, st) for st in ("scheduled", "published", "failed")}
    z, falha_api = {}, None
    for st, f in futuros.items():
        try:
            z[st] = f.result()
        except Exception as e:
            z[st] = []
            falha_api = f"{type(e).__name__}: {e}"

    locais = pastas()
    ids_zernio = {p["_id"] for st in z for p in z[st]}
    # Pasta sem id no estado.md: casa com post do Zernio do mesmo dia e mesmo tipo
    usados = {i for p in locais for i in p["ids"]}
    for p in locais:
        if p["descartado"] or set(p["ids"]) & ids_zernio:
            continue
        for zp in z["scheduled"] + z["published"]:
            if (zp["_id"] not in usados and quando_zernio(zp).astimezone(FUSO).date() == p["data"]
                    and (tipo_zernio(zp) == "reel") == (p["tipo"] == "reel")):
                p["ids"].append(zp["_id"])
                usados.add(zp["_id"])
                break
    por_id = {i: p for p in locais for i in p["ids"]}

    # Agendados nos próximos 7 dias e publicados nos últimos 7
    limite = hoje_dt + datetime.timedelta(days=7)
    agendados = sorted((p for p in z["scheduled"] if hoje_dt <= quando_zernio(p) <= limite), key=quando_zernio)
    publicados = [p for p in z["published"]
                  if hoje_dt - datetime.timedelta(days=7) <= quando_zernio(p) <= hoje_dt]

    # Semana atual (seg a dom) pela data da pasta
    seg = hoje - datetime.timedelta(days=hoje.weekday())
    criados = [p for p in locais if p["tipo"] == "carrossel" and p["arte"] and not p["descartado"]
               and seg <= p["data"] <= seg + datetime.timedelta(days=6)]

    # Em produção: pasta viva que não virou post no Zernio
    producao = [p for p in locais if not p["descartado"] and not (set(p["ids"]) & ids_zernio)]
    sem_arte = [p for p in producao if not p["arte"]]
    atrasados = [p for p in producao if p["data"] < hoje]

    # Dias sem post nos próximos 7 dias (hoje conta se já publicou ou tem agendado)
    cobertos = {quando_zernio(p).astimezone(FUSO).date() for p in z["scheduled"] + z["published"]}
    vazios = [hoje + datetime.timedelta(days=i) for i in range(7)
              if hoje + datetime.timedelta(days=i) not in cobertos]

    itens.append({"id": "instagram.criados", "rotulo": "Carrosséis criados na semana",
                  "valor": len(criados), "estado": "info"})
    itens.append({"id": "instagram.agendados", "rotulo": "Agendados (próx. 7 dias)", "valor": len(agendados),
                  "estado": "ok" if agendados else "atencao"})
    itens.append({"id": "instagram.publicados", "rotulo": "Publicados (últ. 7 dias)",
                  "valor": len(publicados), "estado": "info"})
    itens.append({"id": "instagram.producao", "rotulo": "Em produção",
                  "valor": f"{len(producao)} ({len(sem_arte)} sem arte final)",
                  "estado": "atencao" if atrasados else "info"})
    itens.append({"id": "instagram.sem-post", "rotulo": "Dias sem post",
                  "valor": ", ".join(dia(d) for d in vazios) or "nenhum",
                  "estado": "atencao" if vazios else "ok"})
    if z["failed"]:
        itens.append({"id": "instagram.falhas", "rotulo": "Falhas no Zernio",
                      "valor": len(z["failed"]), "estado": "erro"})
    if falha_api:
        itens.append({"id": "instagram.zernio", "rotulo": "Zernio", "valor": falha_api[:120], "estado": "erro"})

    for p in agendados:
        local = next((por_id[i] for i in [p["_id"]] if i in por_id), None)
        titulo = local["titulo"] if local else (p.get("content") or "").split("\n")[0][:60]
        lista.append({"_ord": quando_zernio(p), "quando": fmt(quando_zernio(p)),
                      "texto": f"Agendado · {tipo_zernio(p)} · {titulo}", "estado": "ok"})
    for p in producao:
        quando = datetime.datetime.combine(p["data"], datetime.time(10), FUSO)
        falta = "arte pronta, falta agendar" if p["arte"] else "sem arte final"
        lista.append({"_ord": quando, "quando": f"{p['data']:%d/%m}",
                      "texto": f"Em produção · {p['tipo']} · {p['titulo']} ({falta})",
                      "estado": "atencao" if p["data"] <= hoje else "info"})
    lista.sort(key=lambda x: x.pop("_ord"))
    lista = lista[:15]

    frases = [f"No Instagram, {len(agendados)} post{'s' if len(agendados) != 1 else ''} agendado"
              f"{'s' if len(agendados) != 1 else ''} pros próximos 7 dias e {len(publicados)} publicado"
              f"{'s' if len(publicados) != 1 else ''} na última semana."]
    if vazios:
        frases.append(f"{len(vazios)} dia{'s' if len(vazios) != 1 else ''} sem post, a partir de {dia(vazios[0])}.")
    if producao:
        frases.append(f"{len(producao)} em produção.")
    if falha_api:
        frases.append("Não consegui ler o Zernio.")

    # número grande, frase e agenda do painel em abas (a lista e os itens seguem iguais)
    destaque = {"valor": str(len(agendados)), "rotulo": "agendados 7 dias",
                "estado": "atencao" if (vazios or falha_api) else "ok"}
    pontos = []
    if falha_api:
        pontos.append("Zernio sem resposta.")
    if vazios:
        pontos.append(f"{len(vazios)} dia{'s' if len(vazios) != 1 else ''} sem post a partir de {dia(vazios[0])}.")
    else:
        pontos.append("Todos os próximos 7 dias têm post.")
    if z["failed"]:
        pontos.append(f"{len(z['failed'])} falha{'s' if len(z['failed']) != 1 else ''} no Zernio.")
    frase = corta(" ".join(pontos), 90)

    ini_ag = datetime.datetime.combine(hoje, datetime.time(0), FUSO)
    fim_ag = datetime.datetime.combine(hoje + datetime.timedelta(days=6), datetime.time(23, 59, 59), FUSO)
    agenda = []
    for estado_ag, posts in (("info", z["scheduled"]), ("ok", z["published"]), ("erro", z["failed"])):
        for p in posts:
            q = quando_zernio(p).astimezone(FUSO)
            if not (ini_ag <= q <= fim_ag):
                continue
            if estado_ag == "ok" and q.date() != hoje:
                continue  # publicado só entra se foi hoje
            local = por_id.get(p["_id"])
            titulo = local["titulo"] if local else (p.get("content") or "").strip().split("\n")[0]
            ev = {"quando": q.isoformat(timespec="seconds"), "rede": "instagram", "conta": "@jesse.rodolfo",
                  "texto": corta(f"{tipo_zernio(p)} · {titulo}", 70), "estado": estado_ag}
            link = (do_instagram(p) or {}).get("platformPostUrl")
            if link:
                ev["link"] = link
            agenda.append(ev)
    agenda = sorted(agenda, key=lambda e: e["quando"])[:60]

    dados = {
        "titulo": "Instagram",
        "destaque": destaque,
        "frase": frase,
        "agenda": agenda,
        "itens": itens,
        "lista": lista,
        "links": [
            {"rotulo": "Perfil @jesse.rodolfo", "url": "https://www.instagram.com/jesse.rodolfo/"},
            {"rotulo": "Zernio", "url": "https://zernio.com"},
        ],
    }
    if falha_api and not locais:
        return erro(falha_api)
    return ok(dados, " ".join(frases))


if __name__ == "__main__":
    rodar(coletar)
