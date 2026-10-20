"""Coletor MelaVitta: agentes de WhatsApp, infraestrutura da VPS de produção e os 2 painéis web.

SÓ LEITURA. Uma única chamada SSH à VPS root@VPS_HOST (variável PAINEL_VPS troca o
destino, só pra teste de falha):

    ssh -o BatchMode=yes -o ConnectTimeout=3 -o StrictHostKeyChecking=yes <VPS> python3 -

O script que roda lá (SCRIPT_REMOTO, constante abaixo) usa somente estes três comandos:

    docker ps -a --format '{{.Names}}'
    docker inspect --type container <nomes da lista fixa>
    pm2 jlist

Nada de docker logs, docker exec, banco, leitura de arquivo ou restart. O script descarta
na própria VPS tudo que não é estado: variáveis de ambiente dos containers (Config.Env) e
saída de healthcheck nunca saem de lá. Volta só nome, status, saúde, falhas seguidas,
início, fim e código de saída (containers) e nome, status, reinícios e uptime (pm2).

Os 2 painéis web saem por HTTP, em paralelo com o SSH. Falha de SSH vira o item vps.ssh
em erro e o card segue com os itens web. Nunca levanta exceção.
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import datetime
import json
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request

from _base import FUSO, agora, ok, rodar

VPS = os.environ.get("PAINEL_VPS", "root@VPS_HOST")
SSH_LIMITE = 3.5  # segundos; o coletor inteiro precisa fechar em menos de 5 s
PRAZO = 3.7       # prazo geral das chamadas em paralelo (SSH e HTTP)

PAINEL_MELAVITTA = "https://painel.senhororcamento.com"
SENHOR_ORC = "https://senhororcamento.com"
CHATWOOT = "https://chat.melavitta.com"
N8N = "https://n8n.melavitta.com"

# Roda na VPS via `python3 -`. Só lê: docker ps, docker inspect e pm2 jlist.
# Descarta Config.Env e Health.Log na origem. Compatível com Python 3.6 ou mais novo.
SCRIPT_REMOTO = r'''
import json, subprocess, time

EXATOS = ("sara-cloud", "bia-baileys", "julia-baileys", "gustavo-baileys",
          "orq-core", "baileys-api", "chatwoot-rails-1", "chatwoot-sidekiq-1", "cliente-app")
PREFIXOS = ("n8n_n8n_editor", "n8n_n8n_webhook", "n8n_n8n_worker")
PM2 = ("gestao", "payt-checkout-api")

def abrir(cmd):
    return subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, universal_newlines=True)

def saida(proc, limite):
    texto, _ = proc.communicate(timeout=limite)
    if proc.returncode != 0:
        raise RuntimeError("codigo %s" % proc.returncode)
    return texto

res = {"containers": [], "pm2": [], "erros": {}}

p_pm2 = None
try:
    p_pm2 = abrir(["pm2", "jlist"])
except Exception as e:
    res["erros"]["pm2"] = type(e).__name__

try:
    nomes = saida(abrir(["docker", "ps", "-a", "--format", "{{.Names}}"]), 3).split()
    alvo = [n for n in nomes if n in EXATOS or n.startswith(PREFIXOS)]
    if alvo:
        for c in json.loads(saida(abrir(["docker", "inspect", "--type", "container"] + alvo), 3)):
            st = c.get("State") or {}
            h = st.get("Health") or {}
            res["containers"].append({
                "nome": (c.get("Name") or "").lstrip("/"),
                "status": st.get("Status"),
                "health": h.get("Status"),
                "falhas": h.get("FailingStreak"),
                "inicio": st.get("StartedAt"),
                "fim": st.get("FinishedAt"),
                "saida": st.get("ExitCode"),
            })
except Exception as e:
    res["erros"]["docker"] = type(e).__name__

if p_pm2 is not None:
    try:
        txt = saida(p_pm2, 3)
        i = txt.find("[{")
        lista = json.JSONDecoder().raw_decode(txt[i:])[0] if i >= 0 else []
        agora_ms = int(time.time() * 1000)
        for p in lista:
            if p.get("name") in PM2:
                e = p.get("pm2_env") or {}
                up = e.get("pm_uptime")
                res["pm2"].append({
                    "nome": p["name"],
                    "status": e.get("status"),
                    "reinicios": e.get("restart_time"),
                    "uptime_ms": agora_ms - up if isinstance(up, (int, float)) else None,
                })
    except Exception as e:
        res["erros"]["pm2"] = type(e).__name__

print(json.dumps(res))
'''

# id, rotulo, nome do container, observação no valor
AGENTES = [
    ("vps.sarah", "Sarah", "sara-cloud", ""),
    ("vps.bia", "BIA", "bia-baileys", ""),
    ("vps.julia", "JulIA", "julia-baileys", ""),
    ("vps.gustavo", "Dr. Gustavo", "gustavo-baileys", ""),
    ("vps.orq", "Orquestrador", "orq-core", "CláudIA e AnalistIA rodam dentro dele"),
    ("vps.chip-legado", "Chip Sarah 04", "baileys-api", ""),
]
# id, rotulo, [(parte, prefixo ou nome)]
INFRA_CONTAINERS = [
    ("vps.n8n", "n8n", [("editor", "n8n_n8n_editor"), ("webhook", "n8n_n8n_webhook"),
                        ("worker", "n8n_n8n_worker")]),
    ("vps.chatwoot", "Chatwoot", [("rails", "chatwoot-rails-1"), ("sidekiq", "chatwoot-sidekiq-1")]),
]
INFRA_PM2 = [("vps.crm", "CRM", "gestao"), ("vps.payt", "Checkout Payt", "payt-checkout-api")]
WEB = [("web.painel-melavitta", "Painel MelaVitta", PAINEL_MELAVITTA),
       ("web.senhororcamento", "Senhor Orçamento", SENHOR_ORC)]

GRAVIDADE = {"ok": 0, "info": 1, "atencao": 2, "erro": 3}


def http(url, timeout):
    """(no ar, motivo). Qualquer resposta HTTP abaixo de 500 conta como no ar (login, redirect)."""
    for metodo in ("HEAD", "GET"):
        try:
            req = urllib.request.Request(url, method=metodo, headers={"User-Agent": "painel-jarvis"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return True, f"HTTP {r.status}"
        except urllib.error.HTTPError as e:
            if e.code in (405, 501) and metodo == "HEAD":
                continue
            return e.code < 500, f"HTTP {e.code}"
        except Exception as e:
            return False, type(e).__name__
    return False, "sem resposta"


def paralelo(funcoes, prazo):
    """Roda cada função numa thread daemon e espera até o prazo. Quem não termina devolve None.
    Thread daemon porque DNS preso não pode segurar a saída do processo (ThreadPoolExecutor seguraria)."""
    resultados = [None] * len(funcoes)

    def alvo(k, f):
        try:
            resultados[k] = f()
        except Exception as e:
            resultados[k] = e

    threads = [threading.Thread(target=alvo, args=(k, f), daemon=True) for k, f in enumerate(funcoes)]
    for t in threads:
        t.start()
    fim = time.monotonic() + prazo
    for t in threads:
        t.join(max(0.0, fim - time.monotonic()))
    return resultados


def ssh_vps():
    """(dados, motivo). dados é o JSON do script remoto; motivo é curto e nunca traz stderr cru."""
    try:
        p = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=3", "-o", "StrictHostKeyChecking=yes",
             VPS, "python3", "-"],
            input=SCRIPT_REMOTO, capture_output=True, text=True, timeout=SSH_LIMITE)
    except subprocess.TimeoutExpired:
        return None, "tempo esgotado"
    except FileNotFoundError:
        return None, "ssh não encontrado"
    except Exception as e:
        return None, type(e).__name__
    if p.returncode != 0:
        err = p.stderr.lower()
        for trecho, motivo in (("timed out", "tempo esgotado"), ("permission denied", "chave recusada"),
                               ("host key verification", "chave do servidor não confere"),
                               ("refused", "conexão recusada"), ("could not resolve", "nome não resolve"),
                               ("no route", "sem rota"), ("unreachable", "rede inalcançável")):
            if trecho in err:
                return None, motivo
        return None, f"ssh código {p.returncode}"
    try:
        dados = json.loads(p.stdout)
        if not isinstance(dados, dict):
            raise ValueError
        return dados, ""
    except ValueError:
        return None, "resposta inválida"


def quando(iso):
    """ISO do docker (com nanossegundos e Z) para datetime em BRT. None se vazio ou ano 1."""
    m = re.match(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:\d{2})?", iso or "")
    if not m:
        return None
    base, fracao, tz = m.groups()
    texto = base + ("." + fracao[:6].ljust(6, "0") if fracao else "") + ("+00:00" if tz in (None, "Z") else tz)
    try:
        dt = datetime.datetime.fromisoformat(texto)
    except ValueError:
        return None
    if dt.year < 2000:
        return None
    return dt.astimezone(FUSO)


def hm(dt):
    return f"{dt:%d/%m %H:%M}" if dt else "hora desconhecida"


def avaliar_container(c):
    """Estado de um container. Devolve dict com estado, tipo, valor, dt (hora do evento) e ev."""
    status = c.get("status")
    saida = c.get("saida")
    if status == "running":
        dt = quando(c.get("inicio"))
        saude = c.get("health")
        if saude == "unhealthy":
            n = c.get("falhas") or 0
            return {"estado": "atencao", "tipo": "saude", "dt": dt, "ev": "subiu",
                    "valor": f"no ar, checagem de saúde falhando ({n} seguidas) desde {hm(dt)}"}
        if saude == "starting":
            return {"estado": "info", "tipo": "iniciando", "dt": dt, "ev": "subiu",
                    "valor": f"no ar, checagem de saúde iniciando desde {hm(dt)}"}
        return {"estado": "ok", "tipo": "ok", "dt": dt, "ev": "subiu", "valor": f"no ar desde {hm(dt)}"}
    if status in ("exited", "dead"):
        dt = quando(c.get("fim"))
        dia = f"{dt:%d/%m}" if dt else "data desconhecida"
        return {"estado": "erro", "tipo": "parado", "dt": dt, "ev": f"parou (saída {saida})",
                "valor": f"parado desde {dia} (saída {saida})"}
    if status == "restarting":
        return {"estado": "atencao", "tipo": "reiniciando", "dt": None, "ev": "",
                "valor": f"reiniciando sem parar (saída {saida})"}
    if status == "paused":
        return {"estado": "atencao", "tipo": "pausado", "dt": quando(c.get("inicio")), "ev": "",
                "valor": "pausado"}
    return {"estado": "erro", "tipo": "parado", "dt": None, "ev": "",
            "valor": f"container em estado {status or 'desconhecido'}"}


def achar_container(containers, nome, prefixo=False):
    """Container pelo nome. Com prefixo (swarm), prefere o que está rodando e o mais recente."""
    candidatos = [c for c in containers
                  if (c.get("nome", "").startswith(nome) if prefixo else c.get("nome") == nome)]
    if not candidatos:
        return None
    candidatos.sort(key=lambda c: (c.get("status") == "running", c.get("inicio") or ""), reverse=True)
    return candidatos[0]


def item_container(id_, rotulo, containers, docker_erro, nome, obs=""):
    if docker_erro:
        r = {"estado": "erro", "tipo": "parado", "dt": None, "ev": "", "valor": "docker não respondeu"}
    else:
        c = achar_container(containers, nome)
        r = (avaliar_container(c) if c else
             {"estado": "erro", "tipo": "parado", "dt": None, "ev": "", "valor": "container não existe"})
    if obs:
        r["valor"] += f" ({obs})"
    return {"id": id_, "rotulo": rotulo, **r}


def item_agregado(id_, rotulo, partes_def, containers, docker_erro):
    """Vários containers num item só: pior estado vence."""
    partes = []
    for nome_parte, prefixo in partes_def:
        if docker_erro:
            r = {"estado": "erro", "tipo": "parado", "dt": None, "ev": "", "valor": "docker não respondeu"}
        else:
            c = achar_container(containers, prefixo, prefixo=True)
            r = (avaliar_container(c) if c else
                 {"estado": "erro", "tipo": "parado", "dt": None, "ev": "", "valor": "container não existe"})
        partes.append((nome_parte, r))
    pior = max((r for _, r in partes), key=lambda r: GRAVIDADE[r["estado"]])
    ruins = [(n, r) for n, r in partes if r["estado"] != "ok"]
    dts = [r["dt"] for _, r in partes if r["dt"] and r["ev"].startswith("subiu")]
    if not ruins:
        nomes = ", ".join(n for n, _ in partes[:-1]) + f" e {partes[-1][0]}"
        ultimo = max(dts) if dts else None
        valor = f"{nomes} no ar (último início {hm(ultimo)})" if ultimo else f"{nomes} no ar"
        tipo, estado, ev, dt = "ok", "ok", "subiu", ultimo
    else:
        valor = "; ".join(f"{n} {r['valor']}" for n, r in ruins)
        if len(ruins) < len(partes):
            valor += "; demais no ar"
        tipo, estado = pior["tipo"], pior["estado"]
        ev, dt = (pior["ev"], pior["dt"])
    return {"id": id_, "rotulo": rotulo, "estado": estado, "tipo": tipo, "valor": valor, "dt": dt, "ev": ev}


def item_pm2(id_, rotulo, nome, pm2, pm2_erro):
    if pm2_erro:
        return {"id": id_, "rotulo": rotulo, "estado": "erro", "tipo": "parado", "dt": None, "ev": "",
                "valor": "pm2 não respondeu"}
    procs = [p for p in pm2 if p.get("nome") == nome]
    if not procs:
        return {"id": id_, "rotulo": rotulo, "estado": "erro", "tipo": "parado", "dt": None, "ev": "",
                "valor": "processo não existe no pm2"}
    p = next((p for p in procs if p.get("status") == "online"), procs[0])
    if p.get("status") == "online":
        n = p.get("reinicios") or 0
        up = p.get("uptime_ms")
        dt = agora() - datetime.timedelta(milliseconds=up) if isinstance(up, (int, float)) else None
        return {"id": id_, "rotulo": rotulo, "estado": "ok", "tipo": "ok", "dt": dt, "ev": "subiu",
                "valor": f"no ar, {n} {'reinício' if n == 1 else 'reinícios'}"}
    return {"id": id_, "rotulo": rotulo, "estado": "erro", "tipo": "parado", "dt": None, "ev": "",
            "valor": f"fora do ar (pm2: {p.get('status')})"}


def juntar(nomes):
    if len(nomes) <= 1:
        return "".join(nomes)
    return ", ".join(nomes[:-1]) + " e " + nomes[-1]


def problemas(itens):
    """Textos de problema agrupados por tipo, na ordem dos itens (sem ponto final)."""
    grupos = {"saude": [], "parado": [], "fora": [], "outro": []}
    for i in itens:
        if i["estado"] in ("ok", "info"):
            continue
        chave = i["tipo"] if i["tipo"] in grupos else "outro"
        grupos[chave].append(i["rotulo"])
    partes = []
    if grupos["saude"]:
        partes.append(f"{juntar(grupos['saude'])} com checagem falhando")
    if grupos["parado"]:
        n = len(grupos["parado"])
        partes.append(f"{juntar(grupos['parado'])} {'parado' if n == 1 else 'parados'}")
    if grupos["fora"]:
        partes.append(f"{juntar(grupos['fora'])} fora do ar")
    if grupos["outro"]:
        partes.append(f"{juntar(grupos['outro'])} pedem atenção")
    return partes, sum(len(v) for v in grupos.values())


def coletar():
    r_ssh, *r_webs = paralelo([ssh_vps] + [(lambda u=url: http(u, 2)) for _, _, url in WEB], PRAZO)
    dados, motivo = r_ssh if isinstance(r_ssh, tuple) else (None, "tempo esgotado")
    webs = [r if isinstance(r, tuple) else (False, "tempo esgotado") for r in r_webs]

    itens_web = []
    for (id_, rotulo, _), (vivo, mot) in zip(WEB, webs):
        itens_web.append({"id": id_, "rotulo": rotulo, "estado": "ok" if vivo else "erro",
                          "tipo": "ok" if vivo else "fora",
                          "valor": "no ar" if vivo else f"fora ({mot})", "dt": None, "ev": ""})

    links = [{"rotulo": "Painel MelaVitta", "url": PAINEL_MELAVITTA},
             {"rotulo": "Senhor Orçamento", "url": SENHOR_ORC},
             {"rotulo": "Chatwoot", "url": CHATWOOT},
             {"rotulo": "n8n", "url": N8N}]

    # SSH falhou: só o item vps.ssh e os 2 painéis web. O card continua ok.
    if dados is None:
        item_ssh = {"id": "vps.ssh", "rotulo": "VPS", "estado": "erro", "tipo": "parado",
                    "valor": f"VPS sem resposta ({motivo})", "dt": None, "ev": ""}
        itens = [item_ssh] + itens_web
        prob_web, _ = problemas(itens_web)
        frase = f"VPS sem resposta ({motivo}); agentes sem leitura."
        if prob_web:
            frase = f"VPS sem resposta; {juntar(prob_web)}."
        resumo = f"Não consegui falar com a VPS da MelaVitta ({motivo}), então não sei o estado dos agentes. "
        resumo += ("Os dois painéis web estão no ar." if not prob_web else f"Atenção: {juntar(prob_web)}.")
        destaque = {"valor": f"?/{len(AGENTES)}", "rotulo": "agentes saudáveis", "estado": "erro"}
        lista = [{"quando": agora().strftime("%d/%m %H:%M"), "texto": f"VPS sem resposta ({motivo})",
                  "estado": "erro"}]
        return montar(itens, destaque, frase[:90], lista, links, resumo)

    containers = dados.get("containers") or []
    pm2 = dados.get("pm2") or []
    erros = dados.get("erros") or {}
    docker_erro, pm2_erro = bool(erros.get("docker")), bool(erros.get("pm2"))

    agentes = [item_container(i, r, containers, docker_erro, n, obs) for i, r, n, obs in AGENTES]
    agentes.append({"id": "vps.maria", "rotulo": "MarIA", "estado": "info", "tipo": "info",
                    "valor": "planejada, chip ainda não comprado", "dt": None, "ev": ""})
    # 20/10 (Jessé): "deixa pra lá o Dr. Felipe, não estou rodando mais esse produto"
    agentes.append({"id": "vps.felipe", "rotulo": "Dr. Felipe", "estado": "info", "tipo": "info",
                    "valor": "desligado, produto encerrado", "dt": None, "ev": ""})
    infra = [item_agregado(i, r, partes, containers, docker_erro) for i, r, partes in INFRA_CONTAINERS]
    infra += [item_pm2(i, r, n, pm2, pm2_erro) for i, r, n in INFRA_PM2]
    pani = item_container("vps.cliente", "Cliente B2B", containers, docker_erro, "cliente-app",
                          "entregue, aguardando cliente fechar")
    infra.append(pani)

    itens = agentes + infra + itens_web

    # destaque: os agentes ativos com container (MarIA e Dr. Felipe ficam fora)
    com_container = agentes[:len(AGENTES)]
    saudaveis = sum(1 for a in com_container if a["estado"] == "ok")
    total = len(com_container)
    piores = [a["estado"] for a in com_container]
    destaque = {"valor": f"{saudaveis}/{total}", "rotulo": "agentes saudáveis",
                "estado": "ok" if saudaveis == total else ("erro" if "erro" in piores else "atencao")}

    partes, n_prob = problemas(itens)
    if not partes:
        frase = "Todos os agentes, a infraestrutura e os painéis estão no ar."
        resumo = (f"Os {total} agentes da MelaVitta estão saudáveis, "
                  "e a infraestrutura e os painéis estão no ar.")
    else:
        frase = "; ".join(partes) + "."
        if len(frase) > 90:
            frase = f"{n_prob} itens pedem atenção, veja a lista."
        resumo = f"{saudaveis} de {total} agentes da MelaVitta estão saudáveis. Atenção em: {'; '.join(partes)}."

    # lista: quando cada item subiu ou parou, mais recentes primeiro
    eventos = [i for i in itens if i["dt"] and i["ev"]]
    eventos.sort(key=lambda i: i["dt"], reverse=True)
    lista = [{"quando": f"{i['dt']:%d/%m %H:%M}", "texto": f"{i['rotulo']} {i['ev']}",
              "estado": i["estado"]} for i in eventos[:15]]

    return montar(itens, destaque, frase, lista, links, resumo)


def montar(itens, destaque, frase, lista, links, resumo):
    limpos = [{"id": i["id"], "rotulo": i["rotulo"], "valor": i["valor"], "estado": i["estado"]}
              for i in itens]
    return ok({"titulo": "MelaVitta", "itens": limpos, "destaque": destaque, "frase": frase,
               "lista": lista, "links": links}, resumo)


if __name__ == "__main__":
    rodar(coletar)
