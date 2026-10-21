"""Servidor do painel Jarvis. Só biblioteca padrão, só em 127.0.0.1:8790.

Rotas:
  GET  /               index.html
  GET  /api/estado     junta os coletores (cache por coletor; ?forcar=1 refaz)
  GET  /api/briefing   resumo falado montado dos coletores, sem chamar a API
  GET  /api/notas      Second Brain (notas.json)
  POST /api/notas      grava o Second Brain inteiro
  POST /api/chat       pergunta ao Claude, resposta em streaming (linhas "data: {...}")
  POST /api/voz        uma frase em áudio pelo provedor do config.json (voz_<provedor>.py), ou JSON de erro pra voz reserva
  GET  /api/uso        gasto da API (sessão e hoje) e situação da voz
"""
import concurrent.futures
import datetime
import importlib
import json
import os
import re
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PAINEL = Path(__file__).resolve().parent
sys.path.insert(0, str(PAINEL / "coletores"))
sys.path.insert(1, str(PAINEL))  # voz_<provedor>.py
import _base  # noqa: E402

PORTA = 8790
HOSTS = {f"127.0.0.1:{PORTA}", f"localhost:{PORTA}"}
ORIGENS = {f"http://{h}" for h in HOSTS}
NOTAS = PAINEL / "notas.json"
LOGS = PAINEL / "logs"
USO_LOG = LOGS / "uso-api.jsonl"
CONFIG = json.loads((PAINEL / "config.json").read_text())

COLETORES = ["tiktok", "instagram", "jesusepop", "custos", "sites", "agentes", "melavitta", "noticias"]
VALIDADE = {"noticias": 900, "custos": 120, "melavitta": 300}  # segundos; o resto vale 60
BRIEFING_MAX = 400  # caracteres: o resumo falado cabe no teto de voz
TEMPO_COLETOR = 8

API = "https://api.anthropic.com/v1/messages"
MODOS = {
    "rapido": {"model": "claude-haiku-5-5", "max_tokens": 700, "thinking": {"type": "disabled"}},
    "profundo": {"model": "claude-opus-5-5", "max_tokens": 4000, "output_config": {"effort": "medium"},
                 "fallbacks": "default"},
}
AREAS = {
    "metas": "Metas", "trabalho": "Carreira", "projetos": "Projetos", "financas": "Finanças",
    "aprendizado": "Aprendizado", "saude": "Saúde", "relacoes": "Relações", "meta": "Você",
}
SAVE = re.compile(r"\[\[SAVE:([a-z_]+)\|([^|\]]+)\|([\s\S]+?)\]\]")

trava_notas = threading.Lock()
trava_estado = threading.Lock()
cache = {}  # nome -> (instante, resultado)
uso_sessao = {"chamadas": 0, "custo_usd": 0.0, "entrada": 0, "saida": 0, "cache_lido": 0}


# ---------- estado dos projetos ----------

def rodar_coletor(nome):
    try:
        modulo = importlib.import_module(nome)
        return modulo.coletar()
    except Exception as e:
        return _base.erro(f"{type(e).__name__}: {e}")


def estado(forcar=False):
    agora = time.time()
    with trava_estado:
        vencidos = [n for n in COLETORES
                    if forcar or n not in cache or agora - cache[n][0] > VALIDADE.get(n, 60)]
        if vencidos:
            with concurrent.futures.ThreadPoolExecutor(len(vencidos)) as ex:
                futuros = {n: ex.submit(rodar_coletor, n) for n in vencidos}
                for n, f in futuros.items():
                    try:
                        cache[n] = (agora, f.result(timeout=TEMPO_COLETOR))
                    except concurrent.futures.TimeoutError:
                        antigo = cache.get(n)
                        cache[n] = (agora, antigo[1] if antigo else _base.erro("demorou demais"))
        blocos = {n: cache[n][1] for n in COLETORES}
    alertas = []
    for n, b in blocos.items():
        if not b.get("ok"):
            alertas.append({"bloco": n, "estado": "erro", "titulo": n, "rotulo": "sem dados",
                            "texto": f"{n}: {b.get('erro', 'sem dados')}"})
            continue
        dados = b.get("dados", {})
        for it in dados.get("itens", []):
            if it.get("estado") in ("erro", "atencao"):
                alertas.append({"bloco": n, "estado": it["estado"], "titulo": dados.get("titulo", n),
                                "rotulo": it.get("rotulo"),
                                "texto": f"{dados.get('titulo', n)}: {it.get('rotulo')} {it.get('valor')}"})
    alertas.sort(key=lambda a: a["estado"] != "erro")
    return {"gerado": _base.agora().isoformat(timespec="seconds"), "blocos": blocos, "alertas": alertas}


def estado_rapido():
    """Pro chat: nunca espera coletor. Usa o cache e, se vencido, atualiza em segundo plano."""
    agora = time.time()
    if all(n in cache for n in COLETORES):
        if any(agora - cache[n][0] > VALIDADE.get(n, 60) for n in COLETORES) and not trava_estado.locked():
            threading.Thread(target=estado, daemon=True).start()
        blocos = {n: cache[n][1] for n in COLETORES}
        return {"blocos": blocos}
    return estado()


def briefing(bloco=None):
    e = estado()
    if bloco in e["blocos"]:
        b = e["blocos"][bloco]
        return {"texto": b.get("resumo") or "Senhor, não tenho esses dados agora.", "alertas": 0}
    # curto de propósito (até BRIEFING_MAX): só os críticos e os números da visão geral
    criticos = [a for a in e["alertas"] if a["estado"] == "erro"]
    n_erro, n_aten = len(criticos), len(e["alertas"]) - len(criticos)
    if criticos:
        nomes = [f"{a.get('titulo')}, {str(a.get('rotulo') or '').lower()}" for a in criticos[:3]]
        frases = [f"Senhor, {n_erro} {'alerta crítico' if n_erro == 1 else 'alertas críticos'}: {'; '.join(nomes)}."]
    else:
        frases = ["Senhor, nenhum alerta crítico."]
    custos = e["blocos"].get("custos", {})
    destaque = custos.get("dados", {}).get("destaque") if custos.get("ok") else None
    if destaque:
        frases.append(f"A semana do plano está em {destaque.get('valor')}.")
    posts = posts_hoje(e["blocos"])
    if posts:
        frases.append(f"Hoje são {posts} posts na agenda.")
    if n_aten:
        frases.append(f"E {n_aten} pontos de atenção na aba Projetos.")
    texto = ""
    for f in frases:
        if len(texto) + len(f) + 1 > BRIEFING_MAX:
            break
        texto = f"{texto} {f}".strip()
    return {"texto": texto, "alertas": len(e["alertas"]), "criticos": n_erro, "atencao": n_aten}


def posts_hoje(blocos):
    """Posts das redes com horário hoje, somando a agenda de todos os coletores (rotinas fora)."""
    hoje, total = _base.agora().date(), 0
    for b in blocos.values():
        if not b.get("ok"):
            continue
        for a in b.get("dados", {}).get("agenda") or []:
            if a.get("rede") == "rotina":
                continue
            try:
                total += datetime.datetime.fromisoformat(a["quando"]).astimezone(_base.FUSO).date() == hoje
            except (KeyError, TypeError, ValueError):
                continue
    return total


def estado_para_prompt(e):
    """Texto estável (sem horário de coleta) pra caber no cache do prompt."""
    partes = []
    for n, b in e["blocos"].items():
        if not b.get("ok"):
            partes.append(f"## {n}\nsem dados agora ({b.get('erro', '')})")
            continue
        d = b.get("dados", {})
        linhas = [f"## {d.get('titulo', n)}", b.get("resumo", "")]
        if isinstance(d.get("destaque"), dict):
            linhas.append(f"- destaque: {d['destaque'].get('valor')} {d['destaque'].get('rotulo')}")
        linhas += [f"- {i.get('rotulo')}: {i.get('valor')} [{i.get('estado')}]" for i in d.get("itens", [])]
        linhas += [f"  · {x.get('quando', '')} {x.get('texto', '')}" for x in d.get("lista", [])[:8]]
        partes.append("\n".join(linhas))
    return "\n\n".join(partes)


# ---------- Second Brain ----------

def ler_notas():
    with trava_notas:
        return json.loads(NOTAS.read_text())


def gravar_notas(dados):
    if not isinstance(dados.get("notas"), list) or not isinstance(dados.get("rel"), list):
        raise ValueError("formato inválido")
    ids = set()
    for n in dados["notas"]:
        if not all(isinstance(n.get(k), str) and n.get(k).strip() for k in ("id", "area", "title")):
            raise ValueError("nota sem id, área ou título")
        if n["area"] not in AREAS:
            raise ValueError(f"área desconhecida: {n['area']}")
        n.setdefault("body", "")
        ids.add(n["id"])
    dados["rel"] = [r for r in dados["rel"] if isinstance(r, list) and len(r) == 2 and r[0] in ids and r[1] in ids]
    with trava_notas:
        if NOTAS.exists():
            NOTAS.with_suffix(".json.bak").write_text(NOTAS.read_text())
        tmp = NOTAS.with_suffix(".tmp")
        tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=1))
        os.replace(tmp, NOTAS)
    return dados


def normal(s):
    s = unicodedata.normalize("NFD", s.lower().strip())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def aplicar_saves(texto):
    """Cria ou atualiza notas pelas linhas [[SAVE:...]] e devolve (texto limpo, notas salvas)."""
    achados = SAVE.findall(texto)
    limpo = SAVE.sub("", texto).strip()
    if not achados:
        return limpo, []
    dados = ler_notas()
    salvas = []
    for area, titulo, corpo in achados:
        area, titulo, corpo = area.strip(), titulo.strip(), corpo.strip()
        if area not in AREAS:
            area = "meta"
        nota = next((n for n in dados["notas"] if normal(n["title"]) == normal(titulo)), None)
        if nota:
            nota.update(area=area, body=corpo)
        else:
            base = re.sub(r"[^a-z0-9]+", "-", normal(titulo)).strip("-") or "nota"
            nid, i = base, 2
            while any(n["id"] == nid for n in dados["notas"]):
                nid, i = f"{base}-{i}", i + 1
            nota = {"id": nid, "area": area, "title": titulo, "body": corpo}
            dados["notas"].append(nota)
            dados["rel"].append(["jesse", nid])
        salvas.append(nota["id"])
    gravar_notas(dados)
    return limpo, salvas


# ---------- cérebro ----------

def system_prompt(notas, e):
    por_area = {}
    for n in notas["notas"]:
        por_area.setdefault(n["area"], []).append(f"- {n['title']}: {n['body']}")
    brain = "\n\n".join(f"### {AREAS[a]}\n" + "\n".join(v) for a, v in por_area.items())
    fixo = f"""Você é o Jarvis, assistente pessoal de voz do Jessé Machado. Personalidade de mordomo britânico formal: educado, preciso, sereno, com humor seco e discreto. Fale sempre em português do Brasil e trate o Jessé por "senhor".

Regras de resposta:
- A resposta será falada em voz alta. De 2 a 4 frases curtas. Sem markdown, sem lista, sem emoji, sem travessão.
- Escreva números como se fala ("cento e vinte e nove dólares" pode ser "129 dólares"); datas no formato "21 de outubro".
- Use só o que está no Second Brain e no estado dos projetos abaixo. Nunca invente número, data, preço ou fato. Se não souber, diga que não tem esse dado.
- Este painel só lê. Se o senhor pedir para postar, publicar, apagar ou editar algo, diga que isso é feito na sessão do projeto e sugira qual.
- Seja direto: comece pela resposta, depois o detalhe.

# PROTOCOLO DE MEMÓRIA VIVA
Se o senhor revelar algo novo e duradouro (meta, projeto, decisão, pessoa, hábito), TERMINE a resposta com uma linha no formato EXATO [[SAVE:area|titulo|texto]], com area em: metas, trabalho, projetos, financas, aprendizado, saude, relacoes, meta. Se já existir nota com esse título, ela é atualizada (escreva o texto completo da nota); senão nasce uma nova. Inclua só quando houver algo realmente novo. Escolha a área pelo assunto (podcast, livro e curso vão em aprendizado; família em relações). Nunca leia essa linha em voz alta. Se o senhor pediu para anotar, confirme com "Anotado, senhor." e nada mais sobre a anotação; se não pediu, não comente que salvou.

# SECOND BRAIN (contexto da vida do senhor)
{brain}"""
    # 3 blocos: o fixo quase nunca muda; o estado muda quando um coletor muda; a hora muda sempre
    projetos = "# ESTADO DOS PROJETOS (lido dos arquivos, do banco e do Zernio)\n" + estado_para_prompt(e)
    agora = _base.agora()
    dias = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
    hora = f"Agora: {dias[agora.weekday()]}, {agora:%d/%m/%Y %H:%M} (horário de Brasília)."
    return [{"type": "text", "text": fixo, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": projetos, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": hora}]


def chave_api():
    return _base.segredo("ANTHROPIC_API_KEY")


def custo(modelo, u):
    for k in sorted(CONFIG["precos_por_milhao"], key=len, reverse=True):
        if k in modelo:
            p = CONFIG["precos_por_milhao"][k]
            return (u.get("input_tokens", 0) * p[0] + u.get("output_tokens", 0) * p[1]
                    + u.get("cache_read_input_tokens", 0) * p[2] + u.get("cache_creation_input_tokens", 0) * p[3]) / 1e6
    return 0.0


def registrar_uso(modelo, u):
    c = custo(modelo, u)
    uso_sessao["chamadas"] += 1
    uso_sessao["custo_usd"] += c
    uso_sessao["entrada"] += u.get("input_tokens", 0)
    uso_sessao["saida"] += u.get("output_tokens", 0)
    uso_sessao["cache_lido"] += u.get("cache_read_input_tokens", 0)
    LOGS.mkdir(exist_ok=True)
    with USO_LOG.open("a") as f:
        f.write(json.dumps({"ts": _base.agora().isoformat(timespec="seconds"), "modelo": modelo,
                            "custo_usd": round(c, 6), "uso": u}) + "\n")
    return c


def gasto_hoje():
    """US$ da API do painel hoje (BRT), somando logs/uso-api.jsonl."""
    hoje, total = _base.agora().date().isoformat(), 0.0
    if USO_LOG.exists():
        for linha in USO_LOG.read_text().splitlines():
            try:
                r = json.loads(linha)
            except ValueError:
                continue
            if str(r.get("ts", "")).startswith(hoje):
                total += r.get("custo_usd", 0) or 0
    return round(total, 6)


def provedor_voz():
    """Módulo voz_<provedor>.py escolhido em config.json/voz.provedor; None quando é "nenhum"."""
    nome = str(CONFIG.get("voz", {}).get("provedor") or "nenhum")
    if nome == "nenhum" or not re.fullmatch(r"[a-z0-9_]+", nome):
        return None
    return importlib.import_module("voz_" + nome)


def situacao_voz():
    nome = CONFIG.get("voz", {}).get("provedor") or "nenhum"
    try:
        modulo = provedor_voz()
        if modulo is None:
            return {"provedor": "nenhum", "disponivel": False, "motivo": "voz principal desligada no config.json"}
        st = modulo.status()
        st.setdefault("provedor", nome)
        st.setdefault("disponivel", bool(st.get("tem_chave") and st.get("tem_voz")))  # provedor antigo
        return st
    except Exception as e:
        return {"provedor": nome, "disponivel": False, "motivo": f"provedor não carregou ({type(e).__name__})"}


def limpar_historico(msgs):
    """Últimas 20 falas, alternando user/assistant, começando por user."""
    saida = []
    for m in msgs[-20:]:
        if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str) and m["content"].strip():
            if saida and saida[-1]["role"] == m["role"]:
                saida[-1]["content"] += "\n" + m["content"][:4000]
            else:
                saida.append({"role": m["role"], "content": m["content"][:4000]})
    while saida and saida[0]["role"] != "user":
        saida.pop(0)
    return saida


def conversar(corpo, enviar):
    """Chama a API em streaming e manda eventos pro navegador por enviar(dict)."""
    chave = chave_api()
    if not chave:
        return enviar({"t": "erro", "codigo": "sem_chave",
                       "msg": "Senhor, falta a chave da API. Cole a chave no arquivo painel ponto env."})
    modo = MODOS.get(corpo.get("modo"), MODOS["rapido"])
    msgs = limpar_historico(corpo.get("mensagens", []))
    if not msgs or msgs[-1]["role"] != "user":
        return enviar({"t": "erro", "codigo": "vazio", "msg": "Não entendi a pergunta, senhor."})
    pedido = {k: v for k, v in modo.items()}
    pedido.update(stream=True, system=system_prompt(ler_notas(), estado_rapido()), messages=msgs)
    cab = {"x-api-key": chave, "anthropic-version": "2023-06-01", "content-type": "application/json"}
    if "fallbacks" in pedido:
        cab["anthropic-beta"] = "server-side-fallback-2026-07-01"
    req = urllib.request.Request(API, data=json.dumps(pedido).encode(), headers=cab, method="POST")
    texto, mandado, uso, parada, modelo = "", 0, {}, None, pedido["model"]
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            for linha in r:
                linha = linha.decode("utf-8", "ignore").strip()
                if not linha.startswith("data:"):
                    continue
                ev = json.loads(linha[5:])
                tipo = ev.get("type")
                if tipo == "message_start":
                    modelo = ev["message"].get("model", modelo)
                    uso.update(ev["message"].get("usage", {}))
                elif tipo == "content_block_delta" and ev["delta"].get("type") == "text_delta":
                    texto += ev["delta"]["text"]
                    # nunca manda pro navegador o que vier a partir de "[[" (linha de SAVE)
                    i = texto.find("[[")
                    seguro = texto[:i] if i >= 0 else (texto[:-1] if texto.endswith("[") else texto)
                    if len(seguro) > mandado:
                        enviar({"t": "texto", "v": seguro[mandado:]})
                        mandado = len(seguro)
                elif tipo == "message_delta":
                    uso.update({k: v for k, v in ev.get("usage", {}).items() if v is not None})
                    parada = ev.get("delta", {}).get("stop_reason") or parada
                elif tipo == "error":
                    return enviar({"t": "erro", "codigo": "api",
                                   "msg": "Senhor, a API devolveu um erro no meio da resposta. Tente de novo."})
    except urllib.error.HTTPError as e:
        motivo = {401: "a chave da API foi recusada. Confira a chave no painel ponto env",
                  403: "a chave não tem permissão para esse modelo",
                  429: "a API pediu uma pausa por excesso de uso. Tente em instantes",
                  529: "a API está sobrecarregada. Tente em instantes"}.get(e.code, f"a API respondeu com erro {e.code}")
        return enviar({"t": "erro", "codigo": "http", "status": e.code, "msg": f"Senhor, {motivo}."})
    except (urllib.error.URLError, TimeoutError, OSError):
        return enviar({"t": "erro", "codigo": "rede", "msg": "Senhor, não consegui conectar à API. Verifique a internet."})
    if parada == "refusal":
        texto = "Lamento, senhor, mas não posso ajudar com isso."
    limpo, salvas = aplicar_saves(texto)
    c = registrar_uso(modelo, uso)
    enviar({"t": "fim", "texto": limpo, "salvas": salvas, "modelo": modelo, "parada": parada,
            "custo_usd": round(c, 6), "sessao_usd": round(uso_sessao["custo_usd"], 6),
            "cache_lido": uso.get("cache_read_input_tokens", 0)})


# ---------- HTTP ----------

class Handler(BaseHTTPRequestHandler):
    server_version = "JarvisPainel/1.0"

    def _ok_origem(self, post=False):
        if self.headers.get("Host") not in HOSTS:
            return False  # bloqueia DNS rebinding
        if post:
            origem = self.headers.get("Origin")
            if origem is not None and origem not in ORIGENS:
                return False
            if not (self.headers.get("Content-Type") or "").startswith("application/json"):
                return False  # força preflight de CORS, que este servidor nunca responde
        return True

    def _json(self, obj, status=200):
        corpo = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def _ler_corpo(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 2_000_000:
            raise ValueError("corpo grande demais")
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        if not self._ok_origem():
            return self._json({"erro": "proibido"}, 403)
        rota, _, query = self.path.partition("?")
        if rota == "/":
            corpo = (PAINEL / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return self.wfile.write(corpo)
        if rota == "/api/estado":
            return self._json(estado(forcar="forcar=1" in query))
        if rota == "/api/briefing":
            bloco = query.partition("bloco=")[2].split("&")[0] or None
            return self._json(briefing(bloco))
        if rota == "/api/notas":
            return self._json(ler_notas())
        if rota == "/api/uso":
            return self._json({**uso_sessao, "tem_chave": bool(chave_api()), "hoje_usd": gasto_hoje(),
                               "voz": situacao_voz()})
        if rota == "/favicon.ico":
            self.send_response(204)
            return self.end_headers()
        self._json({"erro": "não encontrado"}, 404)

    def do_HEAD(self):
        if not self._ok_origem():
            self.send_response(403)
        else:
            self.send_response(200 if self.path.partition("?")[0] in ("/", "/api/uso") else 404)
        self.end_headers()

    def do_POST(self):
        if not self._ok_origem(post=True):
            return self._json({"erro": "proibido"}, 403)
        try:
            corpo = self._ler_corpo()
        except ValueError as e:
            return self._json({"erro": str(e)}, 400)
        if self.path == "/api/notas":
            try:
                return self._json(gravar_notas(corpo))
            except ValueError as e:
                return self._json({"erro": str(e)}, 400)
        if self.path == "/api/chat":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()

            def enviar(ev):
                try:
                    self.wfile.write(f"data: {json.dumps(ev, ensure_ascii=False)}\n\n".encode())
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass  # navegador cancelou (botão parar)
            return conversar(corpo, enviar)
        if self.path == "/api/voz":
            return self._voz(corpo.get("texto") if isinstance(corpo.get("texto"), str) else "",
                             corpo.get("voz") if isinstance(corpo.get("voz"), str) else None)
        self._json({"erro": "não encontrado"}, 404)

    def _voz(self, texto, voz=None):
        """Uma frase em áudio. Qualquer falha antes do primeiro pedaço volta como JSON e o navegador usa a voz reserva.
        voz: a do seletor do painel; o provedor só aceita as de config.json/voz.opcoes."""
        try:
            modulo = provedor_voz()
            if modulo is None:
                return self._json({"erro": "", "codigo": "desligada"}, 503)
            fluxo = modulo.abrir(texto, voz) if voz else modulo.abrir(texto)
        except Exception as e:
            codigo = getattr(e, "codigo", "api")
            msg = getattr(e, "msg", "Senhor, a voz principal falhou. Sigo com a voz reserva.")
            return self._json({"erro": msg, "codigo": codigo}, 429 if codigo == "teto" else 503)
        self.send_response(200)
        self.send_header("Content-Type", getattr(modulo, "TIPO", "audio/mpeg"))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            for pedaco in fluxo:
                self.wfile.write(pedaco)
        except (BrokenPipeError, ConnectionResetError):
            pass  # navegador cancelou (botão parar)
        except Exception as e:
            sys.stderr.write(f"voz: falhou no meio do áudio ({type(e).__name__})\n")
        finally:
            fechar = getattr(fluxo, "close", None)
            if fechar:
                fechar()

    def log_message(self, fmt, *args):
        if not self.path.startswith("/api/estado"):
            sys.stderr.write(f"{datetime.datetime.now():%H:%M:%S} {fmt % args}\n")


def principal():
    LOGS.mkdir(exist_ok=True)
    threading.Thread(target=estado, daemon=True).start()  # aquece o cache dos coletores
    srv = ThreadingHTTPServer(("127.0.0.1", PORTA), Handler)
    srv.daemon_threads = True
    print(f"Jarvis no ar em http://127.0.0.1:{PORTA}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    principal()
