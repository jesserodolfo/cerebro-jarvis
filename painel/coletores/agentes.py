"""Coletor Agentes: quem está no ar entre os agentes, rotinas e painéis do Jessé.

Só leitura. `launchctl list` (uma chamada, com timeout), HTTP com timeout curto
e o scheduled-tasks.json do app Claude (só lê lastRunAt).
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import datetime
import json
import subprocess
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from _base import FUSO, agora, ok, rodar

LAUNCH_AGENTS = Path.home() / "Library/LaunchAgents"
TAREFAS_APP = Path.home() / "Library/Application Support/Claude/claude-code-sessions"
TAREFAS_DIR = Path.home() / ".claude/scheduled-tasks"
JARVIS = "ai.hermes.gateway-jarvis"
PAINEL_JEP = "http://127.0.0.1:8787/"
MELAVITTA = "https://painel.senhororcamento.com"
SENHOR_ORC = "https://senhororcamento.com"


def launchctl():
    """{label: (pid ou None, último status)} de tudo que está carregado no launchd do usuário."""
    saida = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=3).stdout
    carregados = {}
    for linha in saida.splitlines()[1:]:
        partes = linha.split("\t")
        if len(partes) != 3:
            continue
        pid, status, label = partes
        carregados[label] = (int(pid) if pid.strip().isdigit() else None,
                             int(status) if status.strip().lstrip("-").isdigit() else None)
    return carregados


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


def tarefas_agendadas():
    """Tarefas do app Claude: lê o scheduled-tasks.json mais recente. Nunca altera."""
    arquivos = sorted(TAREFAS_APP.glob("*/*/scheduled-tasks.json"),
                      key=lambda p: p.stat().st_mtime, reverse=True) if TAREFAS_APP.exists() else []
    for arq in arquivos:
        try:
            return json.loads(arq.read_text()).get("scheduledTasks", [])
        except (OSError, ValueError):
            continue
    return []


def quando(iso):
    if not iso:
        return None
    return datetime.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(FUSO)


def coletar():
    itens, lista = [], []

    with ThreadPoolExecutor(max_workers=4) as ex:
        f_jep = ex.submit(http, PAINEL_JEP, 2)
        f_mela = ex.submit(http, MELAVITTA, 3)
        f_orc = ex.submit(http, SENHOR_ORC, 3)
        try:
            carregados = launchctl()
            erro_launchctl = ""
        except Exception as e:
            carregados, erro_launchctl = {}, type(e).__name__

    # Jarvis Telegram
    if erro_launchctl:
        itens.append({"rotulo": "Jarvis Telegram", "valor": f"launchctl falhou ({erro_launchctl})", "estado": "erro"})
    elif JARVIS in carregados and carregados[JARVIS][0]:
        itens.append({"rotulo": "Jarvis Telegram", "valor": f"no ar, PID {carregados[JARVIS][0]}", "estado": "ok"})
    elif JARVIS in carregados:
        itens.append({"rotulo": "Jarvis Telegram", "valor": f"parado, última saída {carregados[JARVIS][1]}", "estado": "erro"})
    else:
        itens.append({"rotulo": "Jarvis Telegram", "valor": "não carregado no launchd", "estado": "erro"})

    # Painel Jesus é Pop (8787)
    vivo, motivo = f_jep.result()
    itens.append({"rotulo": "Painel Jesus é Pop", "valor": "no ar" if vivo else f"fora ({motivo})",
                  "estado": "ok" if vivo else "erro"})

    # Rotinas launchd do Jesus é Pop
    plists = sorted(p.stem for p in LAUNCH_AGENTS.glob("com.jesusepop.*.plist"))
    labels = sorted(set(plists) | {l for l in carregados if l.startswith("com.jesusepop.")})
    falhas = 0
    for label in labels:
        nome = label.removeprefix("com.jesusepop.")
        if label not in carregados:
            estado, texto = "erro", "não carregada"
        else:
            pid, status = carregados[label]
            if pid:
                estado, texto = "ok", f"rodando, PID {pid}"
            elif status == 0:
                estado, texto = "ok", "carregada, última saída 0"
            else:
                estado, texto = "atencao", f"carregada, última saída {status}"
        falhas += estado != "ok"
        lista.append({"quando": "", "texto": f"Rotina {nome} · {texto}", "estado": estado})
    if not erro_launchctl:
        itens.append({"rotulo": "Rotinas Jesus é Pop",
                      "valor": f"{len(labels) - falhas} de {len(labels)} ok",
                      "estado": "ok" if not falhas else "atencao"})

    # Tarefas agendadas do app Claude (rotina das 8h do TikTok e as recorrentes)
    tarefas = tarefas_agendadas()
    tiktok = next((t for t in tarefas if t.get("id") == "jesse-ia-rotina-diaria"), None)
    if tiktok:
        ultima = quando(tiktok.get("lastRunAt"))
        horas = (agora() - ultima).total_seconds() / 3600 if ultima else None
        if not tiktok.get("enabled"):
            estado, valor = "atencao", "desligada"
        elif horas is None:
            estado, valor = "atencao", "ligada, nunca rodou"
        else:
            estado = "ok" if horas <= 26 else "atencao"
            valor = f"rodou {ultima:%d/%m %H:%M}"
        itens.append({"rotulo": "Rotina TikTok 8h", "valor": valor, "estado": estado})
    elif (TAREFAS_DIR / "jesse-ia-rotina-diaria").exists():
        itens.append({"rotulo": "Rotina TikTok 8h", "valor": "existe, sem registro de execução", "estado": "atencao"})
    else:
        itens.append({"rotulo": "Rotina TikTok 8h", "valor": "não encontrada", "estado": "erro"})

    recorrentes = []
    for t in tarefas:
        if not t.get("enabled") or not t.get("cronExpression"):
            continue
        ultima = quando(t.get("lastRunAt"))
        recorrentes.append((ultima.timestamp() if ultima else 0, {
            "quando": f"{ultima:%d/%m %H:%M}" if ultima else "",
            "texto": f"Tarefa {t.get('displayName') or t.get('id')} · cron {t['cronExpression']}",
            "estado": "ok" if ultima else "atencao"}))
    lista = [x for _, x in sorted(recorrentes, key=lambda r: r[0], reverse=True)] + lista

    # Painéis na web
    for rotulo, fut in (("Painel MelaVitta", f_mela), ("Senhor Orçamento", f_orc)):
        vivo, motivo = fut.result()
        itens.append({"rotulo": rotulo, "valor": "no ar" if vivo else f"fora ({motivo})",
                      "estado": "ok" if vivo else "erro"})

    itens.append({"rotulo": "Cliente B2B", "valor": "entregue, aguardando cliente fechar", "estado": "info"})

    links = [{"rotulo": "Painel Jesus é Pop", "url": PAINEL_JEP},
             {"rotulo": "Painel MelaVitta", "url": MELAVITTA},
             {"rotulo": "Senhor Orçamento", "url": SENHOR_ORC}]

    vigiados = [i for i in itens if i["estado"] != "info"]
    problemas = [i["rotulo"] for i in vigiados if i["estado"] != "ok"]
    if not problemas:
        resumo = f"Todos os {len(vigiados)} agentes e painéis estão no ar."
    else:
        resumo = (f"{len(vigiados) - len(problemas)} de {len(vigiados)} agentes e painéis estão no ar. "
                  f"Atenção em: {', '.join(problemas)}.")

    return ok({"titulo": "Agentes", "itens": itens, "lista": lista[:15], "links": links}, resumo)


if __name__ == "__main__":
    rodar(coletar)
