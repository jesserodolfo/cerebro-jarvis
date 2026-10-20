"""Coletor Sites: clientes do estúdio (advogadas, comércio local, Astro) e leads abertos.

Fontes, só leitura:
- ~/Documents/06-Clientes/sites-advogadas: INDEX.md manda; pasta fora do índice usa PROJETO.md
- ~/Documents/03-Marketing/criacao-sites/clientes: projetos Astro
- ~/Documents/02-Comercial/operacao-sites-advogados/leads: dossiês de lead
Sites marcados como no ar recebem um HEAD rápido pra confirmar.
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import datetime
import os
import re
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from _base import DOCS, FUSO, MKT, erro, ok, rodar

ADVOGADAS = DOCS / "06-Clientes/sites-advogadas"
ASTRO = MKT / "criacao-sites/clientes"
LEADS = DOCS / "02-Comercial/operacao-sites-advogados/leads"

IGNORAR_DIRS = {"node_modules", "dist", ".astro", ".git", ".netlify", "__pycache__", ".claude"}
URL_RE = re.compile(r"https?://[^\s)|`_]+")
ESTADO_EMOJI = {"🟢": "ok", "🟡": "atencao", "🔵": "atencao", "⚪": "info"}


def ultima_mod(pasta):
    """Maior mtime da pasta, sem node_modules, build, backups e .DS_Store."""
    maior = 0.0
    for raiz, dirs, arqs in os.walk(pasta):
        dirs[:] = [d for d in dirs if d not in IGNORAR_DIRS]
        for a in arqs:
            if a == ".DS_Store" or ".bak" in a:
                continue
            try:
                maior = max(maior, os.stat(os.path.join(raiz, a)).st_mtime)
            except OSError:
                pass
    return datetime.datetime.fromtimestamp(maior, FUSO) if maior else None


def limpa_status(txt):
    txt = re.sub(r"\s+[\u2014\u2013-]\s+https?://\S+", "", txt)  # tira o link que vem depois do traço no status
    return txt.replace("\u2014", ",").replace("\u2013", ",").strip(" .")


def ler_index():
    """Linhas da tabela do INDEX.md: {pasta: {nome, url, status}}."""
    arq = ADVOGADAS / "INDEX.md"
    clientes = {}
    if not arq.exists():
        return clientes
    for linha in arq.read_text().splitlines():
        cols = [c.strip() for c in linha.strip().strip("|").split("|")]
        if len(cols) < 5 or cols[0] in ("Cliente", "") or set(cols[0]) <= set("-: "):
            continue
        pasta = cols[1].strip("`/ ")
        if not pasta:
            continue
        achou = URL_RE.search(cols[3])
        clientes[pasta] = {"nome": cols[0], "url": achou.group(0) if achou else "",
                           "status": limpa_status(cols[4])}
    return clientes


def status_ficha(pasta):
    ficha = pasta / "PROJETO.md"
    if not ficha.exists():
        return "", ""
    nome = ""
    for linha in ficha.read_text().splitlines()[:15]:
        if linha.startswith("# ") and not nome:
            nome = re.sub(r"^#\s*\S*\s*Projeto\s*[\u2014\u2013-]?\s*", "", linha).strip()
        if linha.startswith("**Status:**"):
            return nome, limpa_status(linha.split("**Status:**", 1)[1])
    return nome, ""


def classe(status):
    emoji = status[:1] if status else ""
    return ESTADO_EMOJI.get(emoji, "info")


def sem_emoji(status):
    return status[1:].strip() if status[:1] in ESTADO_EMOJI else status


def responde(url):
    """(vivo, motivo): vivo se o site responde com status < 400 em até 2,5 s."""
    for metodo in ("HEAD", "GET"):
        try:
            req = urllib.request.Request(url, method=metodo, headers={"User-Agent": "painel-jarvis"})
            with urllib.request.urlopen(req, timeout=2.5) as r:
                return r.status < 400, f"HTTP {r.status}"
        except urllib.error.HTTPError as e:
            if e.code in (405, 501) and metodo == "HEAD":
                continue
            return False, f"HTTP {e.code}"
        except Exception as e:
            return False, type(e).__name__
    return False, "sem resposta"


def coletar():
    if not ADVOGADAS.exists() and not ASTRO.exists():
        return erro("nenhuma pasta de sites encontrada")

    sites = []  # {nome, slug, status, estado, url, mod, origem}
    index = ler_index()

    if ADVOGADAS.exists():
        for pasta in sorted(ADVOGADAS.iterdir()):
            if not pasta.is_dir() or pasta.name.startswith(("_", ".")):
                continue
            linha = index.get(pasta.name)
            if linha:
                nome, status, url = linha["nome"], linha["status"], linha["url"]
            else:
                nome, status = status_ficha(pasta)
                nome, url = nome or pasta.name, ""
                achou = URL_RE.search(status)
                url = achou.group(0) if achou else ""
            sites.append({"nome": nome, "slug": pasta.name, "status": status, "url": url,
                          "mod": ultima_mod(pasta), "origem": "sites-advogadas"})

    if ASTRO.exists():
        for pasta in sorted(ASTRO.iterdir()):
            if not pasta.is_dir() or pasta.name.startswith((".", "_")):
                continue
            sites.append({"nome": pasta.name, "slug": pasta.name,
                          "status": "🟡 Em construção, Astro sem deploy registrado", "url": "",
                          "mod": ultima_mod(pasta), "origem": "criacao-sites"})

    # Confirma no ar quem o índice diz que está no ar.
    no_ar = [s for s in sites if classe(s["status"]) == "ok" and s["url"]]
    with ThreadPoolExecutor(max_workers=8) as ex:
        for s, (vivo, motivo) in zip(no_ar, ex.map(lambda s: responde(s["url"]), no_ar)):
            s["vivo"], s["motivo"] = vivo, motivo

    leads = []
    slugs = {s["slug"] for s in sites}
    if LEADS.exists():
        for arq in sorted(LEADS.glob("*.md")):
            if any(slug in arq.stem for slug in slugs):
                continue  # lead que já virou cliente
            texto = arq.read_text()
            titulo = re.search(r"^#\s*Dossi[êe]:\s*(.+)$", texto, re.M)
            status = re.search(r"Status atual no pipeline:\s*(.+)$", texto, re.M)
            nome = titulo.group(1).strip() if titulo else arq.stem
            leads.append({"nome": nome if nome.lower().startswith("lead") else f"Lead {nome}",
                          "status": re.sub(r"^\W+", "", status.group(1)).strip() if status else "sem status",
                          "mod": datetime.datetime.fromtimestamp(arq.stat().st_mtime, FUSO)})

    publicados = [s for s in sites if classe(s["status"]) == "ok"]
    caidos = [s for s in publicados if s.get("vivo") is False]
    andamento = [s for s in sites if classe(s["status"]) == "atencao"]
    parados = [s for s in sites if classe(s["status"]) == "info"]

    itens = [
        {"rotulo": "Clientes", "valor": len(sites), "estado": "info"},
        {"rotulo": "No ar", "valor": len(publicados) - len(caidos),
         "estado": "erro" if caidos else "ok"},
        {"rotulo": "Em andamento", "valor": len(andamento),
         "estado": "atencao" if andamento else "ok"},
        {"rotulo": "Parados ou arquivados", "valor": len(parados), "estado": "info"},
        {"rotulo": "Leads abertos", "valor": len(leads), "estado": "atencao" if leads else "info"},
    ]
    for s in caidos:
        itens.append({"rotulo": f"{s['nome']} fora do ar", "valor": s["motivo"], "estado": "erro"})

    lista = []
    for s in sites:
        estado = classe(s["status"])
        texto = f"{s['nome']} · {sem_emoji(s['status'])}"
        if s.get("vivo") is False:
            estado = "erro"
            texto = f"{s['nome']} · índice diz no ar, site dá {s['motivo']}"
        item = {"quando": s["mod"].strftime("%d/%m %H:%M") if s["mod"] else "",
                "texto": texto, "estado": estado,
                "_ord": s["mod"].timestamp() if s["mod"] else 0}
        if s["url"] and classe(s["status"]) == "ok":
            item["link"] = s["url"]
        lista.append(item)
    for l in leads:
        lista.append({"quando": l["mod"].strftime("%d/%m %H:%M"),
                      "texto": f"{l['nome']} · {l['status']}", "estado": "atencao",
                      "_ord": l["mod"].timestamp()})
    lista.sort(key=lambda x: x["_ord"], reverse=True)
    for x in lista:
        x.pop("_ord")

    links = [{"rotulo": s["nome"], "url": s["url"]} for s in publicados if s["url"] and s.get("vivo")]

    partes = [f"O senhor tem {len(sites)} sites de clientes, {len(publicados) - len(caidos)} no ar"]
    if andamento:
        partes.append(f"{len(andamento)} em andamento")
    if caidos:
        partes.append(f"{len(caidos)} que o índice diz no ar mas dão erro")
    resumo = ", ".join(partes) + "."
    if leads:
        resumo += f" Há {len(leads)} lead aberto esperando resposta." if len(leads) == 1 else \
                  f" Há {len(leads)} leads abertos esperando resposta."

    return ok({"titulo": "Sites", "itens": itens, "lista": lista[:15], "links": links}, resumo)


if __name__ == "__main__":
    rodar(coletar)
