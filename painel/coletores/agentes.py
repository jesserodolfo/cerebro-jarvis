"""Coletor Agentes: agentes e rotinas do Mac do Jessé, cada um com status, última
atividade e último erro. Os agentes da VPS ficam no coletor melavitta.py.

Só leitura: `launchctl list` (uma chamada, com timeout), plists do LaunchAgents,
logs de rotina (só hora e presença de erro, nunca o conteúdo), HTTP local com timeout
curto, o state.db do Hermes em mode=ro (só a hora da última mensagem do usuário, nunca
texto) e o scheduled-tasks.json do app Claude.
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import json
import plistlib
import re
import subprocess
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

from _base import FUSO, MKT, agora, ok, rodar, sqlite_ro

LAUNCH_AGENTS = Path.home() / "Library/LaunchAgents"
TAREFAS_APP = Path.home() / "Library/Application Support/Claude/claude-code-sessions"
TAREFAS_DIR = Path.home() / ".claude/scheduled-tasks"
HERMES = Path.home() / ".hermes/profiles/jarvis"
LOGS = MKT / "Jesusepop/metricas/logs"
POSTS = MKT / "fabrica-conteudo/posts"
JARVIS = "ai.hermes.gateway-jarvis"
PAINEL_JEP = "http://127.0.0.1:8787/"

TOLERANCIA = timedelta(minutes=5)   # execução um pouco antes do horário ainda conta
FOLGA = timedelta(hours=2)          # passou disso sem rodar = atrasada
CONVERSA_ANTIGA = timedelta(days=7)
DIAS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
PESO = {"ok": 0, "info": 1, "atencao": 2, "erro": 3}

# (id launchd, nome curto, texto da agenda, tipo de log)
ROTINAS = [
    ("limpacache", "Limpa cache", "Limpeza de cache do Mac", "limpeza"),
    ("coleta", "Coleta", "Coleta Jesus é Pop", "coleta"),
    ("oracao", "Oração", "Oração Jesus é Pop", "oracao"),
    ("verificar", "Verificação", "Verificação de publicação", "verificar"),
    ("semanal", "Semanal", "Semanal Jesus é Pop", "semanal"),
]

RE_CABECALHO = re.compile(r"^== (\d\d)/(\d\d) (\d\d):(\d\d)", re.M)
RE_ERRO_LOG = re.compile(r"Traceback|Error|ERRO|falhou|⚠")
RE_LIMPEZA = re.compile(r"^(\d\d)/(\d\d) (\d\d):(\d\d) livre ([\d.]+) GB -> ([\d.]+) GB", re.M)
RE_ERRO_HERMES = re.compile(
    r"^(\d{4})-(\d\d)-(\d\d) (\d\d):(\d\d):(\d\d),\d+ (?:ERROR|CRITICAL) (\S+)(.*)$", re.M)
RE_CRON = re.compile(r"^(\d{1,2}) (\d{1,2}) \* \* \*$")


def pior(a, b):
    return a if PESO[a] >= PESO[b] else b


def cortar(texto, limite):
    return texto if len(texto) <= limite else texto[:limite - 1].rstrip() + "."


def hm(dt):
    return f"{dt:%d/%m %H:%M}"


# ---------------------------------------------------------------- fontes basicas

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
    """(no ar, motivo). Qualquer resposta HTTP abaixo de 500 conta como no ar (login, redirect).
    Só HEAD: 405/501 também prova que o servidor respondeu. O dashboard.py da 8787 não tem HEAD e,
    sob carga, o GET dele passava do prazo e pintava o painel de vermelho sem estar fora."""
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "painel-jarvis"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return True, f"HTTP {r.status}"
    except urllib.error.HTTPError as e:
        return e.code < 500 or e.code in (501,), f"HTTP {e.code}"
    except Exception as e:
        return False, type(e).__name__


def ler_final(caminho, limite=262144):
    """Últimos `limite` bytes do arquivo como texto. Nunca lê o arquivo inteiro."""
    with open(caminho, "rb") as f:
        f.seek(0, 2)
        tamanho = f.tell()
        f.seek(max(0, tamanho - limite))
        return f.read().decode("utf-8", "replace")


def data_do_log(dia, mes, hora, minuto, ref):
    """Cabeçalho do log não traz o ano: usa o corrente e recua um ano se cair no futuro."""
    dt = datetime(ref.year, int(mes), int(dia), int(hora), int(minuto), tzinfo=FUSO)
    return dt.replace(year=dt.year - 1) if dt > ref + timedelta(days=1) else dt


# ---------------------------------------------------------------- agendamento (plist)

def ler_regras(label):
    """StartCalendarInterval do plist como lista de dicts. None se o plist não abre."""
    try:
        with open(LAUNCH_AGENTS / f"{label}.plist", "rb") as f:
            dados = plistlib.load(f)
    except Exception:
        return None
    regras = dados.get("StartCalendarInterval") or []
    if isinstance(regras, dict):
        regras = [regras]
    return [r for r in regras if isinstance(r, dict)]


def ocorrencias(regras, dia):
    """Horários em que as regras disparam no `dia` (date). Weekday do launchd: 0 e 7 = domingo."""
    saida = []
    for r in regras:
        if "Month" in r and int(r["Month"]) != dia.month:
            continue
        if "Day" in r and int(r["Day"]) != dia.day:
            continue
        if "Weekday" in r and (int(r["Weekday"]) + 6) % 7 != dia.weekday():
            continue
        saida.append(datetime(dia.year, dia.month, dia.day, int(r.get("Hour", 0)),
                              int(r.get("Minute", 0)), tzinfo=FUSO))
    return sorted(saida)


def ultima_prevista(regras, ref):
    for i in range(400):
        passadas = [o for o in ocorrencias(regras, (ref - timedelta(days=i)).date()) if o <= ref]
        if passadas:
            return passadas[-1]
    return None


def proxima(regras, ref):
    for i in range(400):
        futuras = [o for o in ocorrencias(regras, (ref + timedelta(days=i)).date()) if o > ref]
        if futuras:
            return futuras[0]
    return None


def rotulo_horario(nome, regras):
    if not regras:
        return nome
    r = regras[0]
    if "Month" in r and "Day" in r:
        return f"{nome} {int(r['Day']):02d}/{int(r['Month']):02d}"
    hora = f"{int(r.get('Hour', 0)):02d}:{int(r.get('Minute', 0)):02d}"
    if "Weekday" in r:
        return f"{nome} {DIAS[(int(r['Weekday']) + 6) % 7]} {hora}"
    return f"{nome} {hora}"


def estado_agenda(sched, ultima, ref, carregada, erro_ultima, rodando):
    """Estado do evento de hoje: ok rodou, info vai rodar, atencao atrasado ou com erro, erro sem job."""
    if not carregada:
        return "erro"
    rodou = bool(ultima) and ultima.date() == sched.date() and ultima >= sched - TOLERANCIA
    if rodou:
        return "atencao" if erro_ultima else "ok"
    if not rodando and ref > sched + FOLGA:
        return "atencao"
    return "info"


# ---------------------------------------------------------------- logs das rotinas

def ler_log(tipo, ref):
    """{'ultima': datetime|None, 'erro': bool, 'extra': str, 'falha': str}. Nunca levanta e nunca devolve conteúdo."""
    vazio = {"ultima": None, "erro": False, "extra": "", "falha": ""}
    try:
        if tipo == "limpeza":
            arq = LOGS / "limpeza_cache.log"
            if not arq.exists():
                return vazio
            achados = RE_LIMPEZA.findall(ler_final(arq, 65536))
            if not achados:
                return vazio
            dia, mes, hora, minuto, _antes, depois = achados[-1]
            return {**vazio, "ultima": data_do_log(dia, mes, hora, minuto, ref), "extra": f"livre {depois} GB"}

        if tipo in ("coleta", "semanal"):
            arqs = sorted(LOGS.glob(f"{tipo}_[0-9]*.log"))
            arq = arqs[-1] if arqs else None
        else:
            arq = LOGS / ("oracao.log" if tipo == "oracao" else "verificar_publicacao.log")
        if arq is None or not arq.exists():
            return vazio
        texto = ler_final(arq)
        cabecalhos = list(RE_CABECALHO.finditer(texto))
        if cabecalhos:
            ultimo = cabecalhos[-1]
            ultima = data_do_log(ultimo.group(1), ultimo.group(2), ultimo.group(3), ultimo.group(4), ref)
            bloco = texto[ultimo.start():]
        else:  # sem cabeçalho (semanal): vale a hora de modificação do arquivo
            ultima = datetime.fromtimestamp(arq.stat().st_mtime, FUSO)
            bloco = texto
        return {**vazio, "ultima": ultima, "erro": bool(RE_ERRO_LOG.search(bloco))}
    except Exception as e:
        return {**vazio, "falha": type(e).__name__}


# ---------------------------------------------------------------- Jarvis Telegram (Hermes)

def categoria_erro(modulo, resto):
    baixo = f"{modulo} {resto}".lower()
    if "telegram" in baixo and "network" in baixo:
        return "rede do Telegram"
    if "telegram" in baixo:
        return "Telegram"
    return re.sub(r"[^A-Za-z0-9_.]", "", modulo)[:30] or "sem categoria"


def ultimo_erro_hermes(ref):
    """(datetime, categoria) do último ERROR do errors.log, lendo só os últimos 64 KB. None se não há."""
    arq = HERMES / "logs/errors.log"
    if not arq.exists():
        return None
    ultimo = None
    for m in RE_ERRO_HERMES.finditer(ler_final(arq, 65536)):
        ultimo = m
    if not ultimo:
        return None
    a, mes, d, h, mi, s = (int(ultimo.group(i)) for i in range(1, 7))
    return datetime(a, mes, d, h, mi, s, tzinfo=FUSO), categoria_erro(ultimo.group(7), ultimo.group(8))


def ultima_conversa_hermes():
    """Hora da última mensagem do usuário. A consulta nunca toca coluna de texto."""
    with closing(sqlite_ro(HERMES / "state.db")) as con:
        ts = con.execute("SELECT max(timestamp) FROM messages WHERE role='user'").fetchone()[0]
    return datetime.fromtimestamp(float(ts), FUSO) if ts else None


def avaliar_hermes(carregados, falha_lc, ref):
    """Devolve (item, eventos da lista, motivo do problema ou '', conversa)."""
    partes, estado, motivo, eventos = [], "ok", [], []

    if falha_lc:
        partes.append(f"launchctl falhou ({falha_lc})")
        estado = "erro"
        motivo.append("sem leitura do launchd")
    elif JARVIS not in carregados:
        partes.append("não carregado no launchd")
        estado = "erro"
        motivo.append("não carregado")
    elif carregados[JARVIS][0]:
        partes.append("no ar")
    else:
        partes.append(f"parado, última saída {carregados[JARVIS][1]}")
        estado = "erro"
        motivo.append("parado")

    conversa = None
    try:
        conversa = ultima_conversa_hermes()
        if conversa:
            partes.append(f"última conversa {hm(conversa)}")
            eventos.append((conversa, {"quando": hm(conversa), "texto": "Jarvis Telegram: última conversa",
                                       "estado": "info"}))
        else:
            partes.append("sem conversa registrada")
    except Exception as e:
        partes.append(f"conversa ilegível ({type(e).__name__})")
        estado = pior(estado, "atencao")
        motivo.append("conversa ilegível")

    try:
        erro_log = ultimo_erro_hermes(ref)
        if erro_log:
            quando, cat = erro_log
            partes.append(f"erro {cat} {hm(quando)}")
            recente = ref - quando <= timedelta(hours=24)
            if recente:
                estado = pior(estado, "atencao")
                motivo.append(f"erro recente na {cat}" if cat.startswith("rede") else f"erro recente ({cat})")
            eventos.append((quando, {"quando": hm(quando), "texto": f"Jarvis Telegram: erro {cat}",
                                     "estado": "atencao" if recente else "info"}))
        else:
            partes.append("sem erro recente no log")
    except Exception as e:
        partes.append(f"log de erro ilegível ({type(e).__name__})")
        estado = pior(estado, "atencao")
        motivo.append("log de erro ilegível")

    item = {"id": "hermes.telegram", "rotulo": "Jarvis Telegram", "valor": " · ".join(partes), "estado": estado}
    return item, eventos, ", ".join(motivo), conversa


# ---------------------------------------------------------------- rotinas Jesus é Pop

def avaliar_rotina(rid, nome, texto_agenda, tipo, carregados, falha_lc, ref):
    """Devolve (item, evento da lista ou None, entradas da agenda de hoje, motivo do problema)."""
    label = f"com.jesusepop.{rid}"
    regras = ler_regras(label)
    rotulo = rotulo_horario(nome, regras or [])
    item = {"id": f"jesusepop.{rid}", "rotulo": rotulo, "valor": "", "estado": "ok"}
    evento, agenda, motivo = None, [], ""

    if falha_lc:
        item.update(valor=f"launchctl falhou ({falha_lc})", estado="erro")
        return item, evento, agenda, "sem leitura do launchd"
    carregada = label in carregados
    pid, status = carregados.get(label, (None, None))
    if not carregada:
        item.update(valor="não carregada no launchd", estado="erro")
        return item, evento, agenda, "não carregada"
    if not regras:
        item.update(valor="agendamento ilegível no plist", estado="atencao")
        return item, evento, agenda, "agendamento ilegível"

    log = ler_log(tipo, ref)
    ultima, erro_ultima = log["ultima"], log["erro"]
    prev, prox = ultima_prevista(regras, ref), proxima(regras, ref)
    atrasada = bool(prev and not pid and ref > prev + FOLGA and (ultima is None or ultima < prev - TOLERANCIA))
    saida_ruim = status not in (0, None) and not pid

    problemas = []
    if erro_ultima:
        problemas.append(f"erro na última execução ({hm(ultima)})")
        motivo = "erro na última execução"
    if atrasada:
        problemas.append(f"atrasada, esperada {hm(prev)}")
        motivo = motivo or "atrasada"
    if saida_ruim:
        problemas.append(f"launchd saída {status}")
        motivo = motivo or f"saída {status} no launchd"
    if log["falha"]:
        problemas.append(f"log ilegível ({log['falha']})")
        motivo = motivo or "log ilegível"

    partes = problemas or ["ok"]
    if pid:
        partes.append("rodando agora")
    if ultima and not erro_ultima:
        partes.append(f"rodou {hm(ultima)}")
    elif not ultima:
        partes.append("sem registro de execução")
    if log["extra"]:
        partes.append(log["extra"])
    if prox:
        partes.append(f"próxima {hm(prox)}")
    item.update(valor=" · ".join(partes), estado="atencao" if problemas else "ok")

    if ultima:
        evento = (ultima, {"quando": hm(ultima), "texto": f"{nome} rodou" + (" com erro" if erro_ultima else ""),
                           "estado": "atencao" if erro_ultima else "ok"})
    for sched in ocorrencias(regras, ref.date()):
        agenda.append((sched, {"rede": "rotina", "conta": rotulo, "texto": texto_agenda,
                               "estado": estado_agenda(sched, ultima, ref, True, erro_ultima, bool(pid))}))
    return item, evento, agenda, motivo


def avaliar_conferir05(carregados, falha_lc, ref):
    """Tarefa pontual (Month/Day no plist): só diz quando está agendada. Não tem log."""
    label = "com.jesusepop.conferir05"
    regras = ler_regras(label)
    item = {"id": "jesusepop.conferir05", "rotulo": rotulo_horario("Conferir", regras or []), "valor": "", "estado": "info"}
    agenda = []
    if falha_lc:
        item.update(valor=f"launchctl falhou ({falha_lc})", estado="erro")
        return item, agenda, "sem leitura do launchd"
    if label not in carregados:
        item.update(valor="não carregada no launchd", estado="erro")
        return item, agenda, "não carregada"
    if not regras:
        item.update(valor="agendamento ilegível no plist", estado="atencao")
        return item, agenda, "agendamento ilegível"
    r = regras[0]
    alvo = datetime(ref.year, int(r.get("Month", ref.month)), int(r.get("Day", ref.day)),
                    int(r.get("Hour", 0)), int(r.get("Minute", 0)), tzinfo=FUSO)
    item["valor"] = f"agendada {hm(alvo)}" + (", já passou" if alvo <= ref else "")
    if alvo.date() == ref.date():
        agenda.append((alvo, {"rede": "rotina", "conta": item["rotulo"], "texto": "Conferência pontual Jesus é Pop",
                              "estado": "info"}))
    return item, agenda, ""


def avaliar_painel(carregados, falha_lc, f_http):
    vivo, motivo = f_http.result()
    pid = carregados.get("com.jesusepop.painel", (None, None))[0]
    item = {"id": "jesusepop.painel", "rotulo": "Painel Jesus é Pop", "valor": "", "estado": "ok"}
    if falha_lc:
        item.update(valor=("no ar, porta 8787" if vivo else f"fora ({motivo}), launchctl falhou ({falha_lc})"),
                    estado="ok" if vivo else "erro")
    elif "com.jesusepop.painel" not in carregados:
        item.update(valor="não carregado no launchd" + (", mas a porta 8787 responde" if vivo else ""), estado="erro")
    elif not pid:
        item.update(valor="parado" + (", mas a porta 8787 responde" if vivo else ""), estado="erro")
    elif vivo:
        item["valor"] = "no ar · porta 8787 respondendo"
    else:
        item.update(valor=f"processo vivo, porta 8787 sem resposta ({motivo})", estado="erro")
    problema = "" if item["estado"] == "ok" else "fora do ar"
    return item, problema


# ---------------------------------------------------------------- rotina TikTok 8h (app Claude)

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


def quando_iso(iso):
    if not iso:
        return None
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(FUSO)


def avaliar_tiktok(ref):
    """O app não grava sucesso nem erro: só hora da última execução e próximo horário."""
    item = {"id": "tiktok.rotina8h", "rotulo": "Rotina TikTok 8h", "valor": "", "estado": "ok"}
    evento, agenda = None, []
    tarefas = tarefas_agendadas()
    t = next((x for x in tarefas if x.get("id") == "jesse-ia-rotina-diaria"), None)
    if not t:
        if (TAREFAS_DIR / "jesse-ia-rotina-diaria").exists():
            item.update(valor="existe, sem registro de execução", estado="atencao")
            return item, evento, agenda, "sem registro de execução"
        item.update(valor="não encontrada", estado="erro")
        return item, evento, agenda, "não encontrada"

    ultima = quando_iso(t.get("lastRunAt"))
    ligada = bool(t.get("enabled"))
    m = RE_CRON.match(t.get("cronExpression") or "")
    alvo = datetime(ref.year, ref.month, ref.day, int(m.group(2)), int(m.group(1)), tzinfo=FUSO) if m else None
    prox = (alvo if alvo > ref else alvo + timedelta(days=1)) if alvo else None

    motivo = ""
    if not ligada:
        partes, estado, motivo = ["desligada"], "atencao", "desligada"
        if ultima:
            partes.append(f"última {hm(ultima)}")
    elif ultima is None:
        partes, estado, motivo = ["ligada, nunca rodou"], "atencao", "nunca rodou"
    elif (ref - ultima).total_seconds() / 3600 > 26:
        partes, estado, motivo = [f"ligada, sem rodar desde {hm(ultima)}"], "atencao", "mais de 26h sem rodar"
    else:
        partes, estado = ["ligada", f"rodou {hm(ultima)}"], "ok"
    if ligada and prox:
        partes.append(f"próxima {hm(prox)}")
    item.update(valor=" · ".join(partes), estado=estado)

    if ultima:
        evento = (ultima, {"quando": hm(ultima), "texto": "Rotina TikTok 8h rodou",
                           "estado": "atencao" if estado == "atencao" else "ok"})
    if ligada and alvo:
        agenda.append((alvo, {"rede": "rotina", "conta": "Rotina TikTok 8h",
                              "texto": "Clipes do dia jessé.ia + Mirian",
                              "estado": estado_agenda(alvo, ultima, ref, True, False, False)}))
    return item, evento, agenda, motivo


# ---------------------------------------------------------------- FabIA

def avaliar_fabia():
    """Fábrica de carrosséis, sem rotina agendada: última atividade = subpasta de post mexida por último."""
    item = {"id": "fabia", "rotulo": "FabIA", "valor": "", "estado": "info"}
    try:
        pastas = [(p.stat().st_mtime, p.name) for p in POSTS.iterdir() if p.is_dir() and not p.name.startswith(".")]
    except OSError as e:
        item.update(valor=f"pasta de posts ilegível ({type(e).__name__})", estado="erro")
        return item, None, "pasta de posts ilegível"
    if not pastas:
        item["valor"] = "nenhum post ainda"
        return item, None, ""
    mtime, nome = max(pastas)
    quando = datetime.fromtimestamp(mtime, FUSO)
    nome = nome[:40]
    item["valor"] = f"último post {nome}, mexido {hm(quando)}"
    return item, (quando, {"quando": hm(quando), "texto": f"FabIA: mexeu em {nome}", "estado": "info"}), ""


# ---------------------------------------------------------------- montagem

def coletar():
    ref = agora()
    itens, eventos, agenda, problemas = [], [], [], []

    with ThreadPoolExecutor(max_workers=2) as ex:
        f_http = ex.submit(http, PAINEL_JEP, 3.5)
        f_lc = ex.submit(launchctl)
        try:
            carregados, falha_lc = f_lc.result(), ""
        except Exception as e:
            carregados, falha_lc = {}, type(e).__name__

    def registrar(item, motivo):
        itens.append(item)
        if item["estado"] in ("atencao", "erro"):
            problemas.append((item["rotulo"], motivo or "pede atenção"))

    item, evs, motivo, conversa = avaliar_hermes(carregados, falha_lc, ref)
    registrar(item, motivo)
    eventos += evs

    item, motivo = avaliar_painel(carregados, falha_lc, f_http)
    registrar(item, motivo)

    for rid, nome, texto_agenda, tipo in ROTINAS:
        item, ev, ag, motivo = avaliar_rotina(rid, nome, texto_agenda, tipo, carregados, falha_lc, ref)
        registrar(item, motivo)
        if ev:
            eventos.append(ev)
        agenda += ag

    item, ag, motivo = avaliar_conferir05(carregados, falha_lc, ref)
    registrar(item, motivo)
    agenda += ag

    item, ev, ag, motivo = avaliar_tiktok(ref)
    registrar(item, motivo)
    if ev:
        eventos.append(ev)
    agenda += ag

    item, ev, motivo = avaliar_fabia()
    registrar(item, motivo)
    if ev:
        eventos.append(ev)

    # destaque: só conta o que é vigiado (info fica de fora)
    vigiados = [i for i in itens if i["estado"] != "info"]
    n_ok = sum(i["estado"] == "ok" for i in vigiados)
    estado_geral = "ok"
    for i in vigiados:
        estado_geral = pior(estado_geral, i["estado"])
    destaque = {"valor": f"{n_ok}/{len(vigiados)}", "rotulo": "agentes do Mac ok", "estado": estado_geral}

    # frase curta do bloco
    conversa_antiga = bool(conversa) and ref - conversa > CONVERSA_ANTIGA
    if problemas:
        nomes = ", ".join(r for r, _ in problemas)
        frase = f"Atenção em {nomes}."
        if conversa_antiga:
            frase += (" Sem conversa desde " if "Jarvis Telegram" in nomes
                      else " Jarvis Telegram sem conversa desde ") + f"{conversa:%d/%m}."
    elif conversa_antiga:
        frase = f"Tudo rodando; Jarvis Telegram sem conversa desde {conversa:%d/%m}."
    else:
        frase = "Tudo rodando."
    frase = cortar(frase, 90)

    # resumo falado
    if n_ok == len(vigiados):
        resumo = f"Todos os {len(vigiados)} agentes do Mac estão ok."
    else:
        resumo = f"{n_ok} de {len(vigiados)} agentes do Mac estão ok."
    if problemas:
        detalhes = []
        for rotulo, motivo in problemas:
            if rotulo == "Jarvis Telegram" and conversa_antiga:
                motivo = f"{motivo}, sem conversa desde {conversa:%d/%m}"
            detalhes.append(f"{rotulo} ({motivo})")
        resumo += " Pede atenção: " + "; ".join(detalhes) + "."
    elif conversa_antiga:
        resumo += f" Jarvis Telegram está sem conversa desde {conversa:%d/%m}."
    else:
        resumo += " Nada pede atenção."

    # lista: mais recentes primeiro, no máximo 15
    lista = [e for _, e in sorted(eventos, key=lambda x: x[0], reverse=True)][:15]

    # agenda: só hoje, em ordem crescente
    agenda_ord = []
    for sched, dados in sorted(agenda, key=lambda x: x[0]):
        agenda_ord.append({"quando": sched.isoformat(timespec="seconds"), "rede": dados["rede"],
                           "conta": dados["conta"][:24], "texto": dados["texto"][:70], "estado": dados["estado"]})

    dados = {"titulo": "Agentes", "itens": itens, "lista": lista,
             "links": [{"rotulo": "Painel Jesus é Pop", "url": PAINEL_JEP}],
             "destaque": destaque, "frase": frase, "agenda": agenda_ord[:60]}
    return ok(dados, resumo)


if __name__ == "__main__":
    rodar(coletar)
