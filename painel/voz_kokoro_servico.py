"""Serviço de voz do Jarvis (com.jarvis.voz): Kokoro 82M local, em 127.0.0.1:8791.

O que é
    Um servidor HTTP pequeno que carrega o Kokoro UMA vez, aquece com uma frase e fala uma
    frase por vez. Quem chama é o painel (voz_kokoro.py, dentro do servidor.py). O navegador
    nunca fala direto com ele. Roda no painel/.venv (Python 3.14, kokoro-onnx, onnxruntime).
    Modelo e vozes ficam em painel/modelos/ (fora do git).

Rotas
    GET  /saude  -> JSON {"ok", "modelo", "vozes_pt", "carga_ms", "aquecimento_ms", "rss_mb", "pedidos"}
    POST /falar  -> corpo JSON {"texto": str, "voz": str opcional, "velocidade": float opcional}
    POST /aquecer -> 202 {"aquecendo", "ocioso_s"}: se parado há mais de 10 s, sintetiza e joga fora
                     uma frase em segundo plano, pra trazer o modelo de volta à RAM
                    resposta audio/wav (PCM 16 bits, mono, taxa do Kokoro, 24000) com o header
                    X-Sintese-Ms. Erros em JSON {"erro", "codigo"}:
                    400 texto_invalido, 400 voz_invalida, 500 sintese, 503 ocupado.

Regras de segurança
    Só escuta em 127.0.0.1. Recusa Host que não seja 127.0.0.1:<porta> ou localhost:<porta> (403).
    No POST exige Content-Type application/json e recusa Origin de outro site (403).
    O texto falado NUNCA vai para o log. O log fica em painel/logs/voz-servico.log.

Memória (M1 de 8 GB)
    Uma síntese por vez (trava de 5 s, depois 503 ocupado). O modelo carrega uma única vez
    por processo. Nunca suba duas cópias deste serviço.

Configuração (painel/config.json, seção "voz"; chaves que faltarem usam o padrão)
    modelo "int8" (padrão), "fp16" ou "fp32"; voz "pm_alex"; velocidade 1.0; porta 8791;
    max_caracteres_pedido 600.

Como liga
    Pelo launchd, serviço com.jarvis.voz (a sessão principal instala o plist).
    À mão, para teste: painel/.venv/bin/python -I painel/voz_kokoro_servico.py

Como desliga
    launchctl bootout gui/$(id -u)/com.jarvis.voz
    O painel segue de pé e cada frase sai pela voz do navegador.
    À mão: kill <pid> (SIGTERM encerra limpo).
"""
import datetime
import io
import json
import os
import signal
import subprocess
import sys
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PAINEL = Path(__file__).resolve().parent
MODELOS = PAINEL / "modelos"
LOG = PAINEL / "logs" / "voz-servico.log"
CONFIG = PAINEL / "config.json"
FUSO = datetime.timezone(datetime.timedelta(hours=-3))  # BRT

ARQUIVOS_MODELO = {
    "int8": "kokoro-v1.0.int8.onnx",
    "fp16": "kokoro-v1.0.fp16.onnx",
    "fp32": "kokoro-v1.0.onnx",
}
ARQUIVO_VOZES = "voices-v1.0.bin"
PRAZO_TRAVA_S = 5          # espera máxima pela síntese em andamento antes de responder ocupado
FRASE_AQUECIMENTO = "Sistemas online. Estou ouvindo, senhor."
LOG_MAX_BYTES = 1_000_000  # passa disso, o log antigo vira .1 na subida

PADRAO = {"modelo": "int8", "voz": "pm_alex", "velocidade": 1.0, "porta": 8791,
          "max_caracteres_pedido": 600}


def ler_config():
    """Seção voz do config.json com padrões para chave ausente ou de tipo errado."""
    try:
        bruto = json.loads(CONFIG.read_text(encoding="utf-8")).get("voz", {})
    except (OSError, ValueError):
        bruto = {}
    if not isinstance(bruto, dict):
        bruto = {}
    cfg = dict(PADRAO)
    for chave, padrao in PADRAO.items():
        valor = bruto.get(chave)
        if isinstance(valor, bool) or valor is None:
            continue
        if isinstance(padrao, float) and isinstance(valor, (int, float)):
            cfg[chave] = float(valor)
        elif isinstance(padrao, int) and isinstance(valor, int):
            cfg[chave] = valor
        elif isinstance(padrao, str) and isinstance(valor, str) and valor:
            cfg[chave] = valor
    return cfg


CFG = ler_config()
PORTA = CFG["porta"]
HOSTS = {f"127.0.0.1:{PORTA}", f"localhost:{PORTA}"}
ORIGENS = {f"http://127.0.0.1:{PORTA}", f"http://localhost:{PORTA}"}

_trava_log = threading.Lock()
_trava_sintese = threading.Lock()
_kokoro = None  # carregado uma única vez, em carregar()
_estado = {"modelo": CFG["modelo"], "vozes_pt": [], "carga_ms": None, "aquecimento_ms": None,
           "pedidos": 0, "ultima_sintese": 0.0}
# 21/10: com o Mac em swap, o macOS manda o modelo parado pro disco em segundos e a 1ª frase levava
# de 6 a 11 s. POST /aquecer (painel aberto, a cada 60 s, começo de cada pergunta) traz de volta antes.
AQUECER_APOS_S = 10
_cache_rss = {"t": 0.0, "mb": None}


def agora():
    return datetime.datetime.now(FUSO)


def registrar(linha):
    """Uma linha no log com a hora em BRT. Nunca recebe o texto falado."""
    ts = agora().isoformat(timespec="seconds")
    with _trava_log:
        try:
            LOG.parent.mkdir(exist_ok=True)
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(f"{ts} {linha}\n")
        except OSError:
            pass  # sem log não derruba a voz


def girar_log():
    try:
        if LOG.exists() and LOG.stat().st_size > LOG_MAX_BYTES:
            LOG.replace(LOG.with_suffix(".log.1"))
    except OSError:
        pass


def rss_mb():
    """Memória residente atual do processo, em MB (ps, com cache de 5 s)."""
    if time.monotonic() - _cache_rss["t"] < 5 and _cache_rss["mb"] is not None:
        return _cache_rss["mb"]
    mb = None
    try:
        saida = subprocess.run(["/bin/ps", "-o", "rss=", "-p", str(os.getpid())],
                               capture_output=True, text=True, timeout=2).stdout.strip()
        mb = round(int(saida) / 1024, 1)
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    _cache_rss.update(t=time.monotonic(), mb=mb)
    return mb


def carregar():
    """Carrega o Kokoro uma vez e aquece. Chamado só na subida."""
    global _kokoro
    if _kokoro is not None:
        raise RuntimeError("modelo já carregado neste processo")
    nome = ARQUIVOS_MODELO.get(CFG["modelo"])
    if not nome:
        raise SystemExit(f"modelo desconhecido na config: {CFG['modelo']}")
    modelo, vozes = MODELOS / nome, MODELOS / ARQUIVO_VOZES
    for arq in (modelo, vozes):
        if not arq.exists():
            raise SystemExit(f"arquivo do modelo não encontrado: {arq.name}")
    from kokoro_onnx import Kokoro  # import aqui: o log de subida já registra o tempo de carga

    t0 = time.perf_counter()
    _kokoro = Kokoro(str(modelo), str(vozes))
    _estado["carga_ms"] = round((time.perf_counter() - t0) * 1000)
    _estado["vozes_pt"] = sorted(v for v in _kokoro.voices.files if v.startswith(("pm_", "pf_")))
    if CFG["voz"] not in _estado["vozes_pt"]:
        raise SystemExit(f"voz da config não existe no modelo: {CFG['voz']}")
    registrar(f"carga modelo={CFG['modelo']} carga_ms={_estado['carga_ms']}")

    t0 = time.perf_counter()
    _kokoro.create(FRASE_AQUECIMENTO, voice=CFG["voz"], speed=CFG["velocidade"], lang="pt-br")
    _estado["aquecimento_ms"] = round((time.perf_counter() - t0) * 1000)
    _estado["ultima_sintese"] = time.monotonic()
    registrar(f"aquecimento aquecimento_ms={_estado['aquecimento_ms']} rss_mb={rss_mb()}")


def aquecer_em_segundo_plano():
    """Sintetiza a frase de aquecimento e joga fora, só pra trazer o modelo de volta à RAM.
    Não espera a trava: se outra frase está em síntese, o modelo já está quente."""
    if not _trava_sintese.acquire(blocking=False):
        return
    try:
        t0 = time.perf_counter()
        _kokoro.create(FRASE_AQUECIMENTO, voice=CFG["voz"], speed=CFG["velocidade"], lang="pt-br")
        _estado["ultima_sintese"] = time.monotonic()
        registrar(f"aquecer ms={round((time.perf_counter() - t0) * 1000)}")
    except Exception as e:
        registrar(f"aquecer erro tipo={type(e).__name__}")
    finally:
        _trava_sintese.release()


def sintetizar(texto, voz, velocidade):
    """Roda a síntese e devolve (wav_bytes, ms). Quem chama já tem a trava."""
    import numpy as np

    t0 = time.perf_counter()
    audio, taxa = _kokoro.create(texto, voice=voz, speed=velocidade, lang="pt-br")
    pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(taxa))
        w.writeframes(pcm.tobytes())
    return buf.getvalue(), round((time.perf_counter() - t0) * 1000)


class Handler(BaseHTTPRequestHandler):
    server_version = "JarvisVoz/1.0"

    def log_message(self, fmt, *args):
        pass  # o log próprio registra só o que importa, sem texto falado

    def _json(self, obj, status=200):
        corpo = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        try:
            self.end_headers()
            self.wfile.write(corpo)
        except (BrokenPipeError, ConnectionResetError):
            pass  # quem pediu desistiu (prazo do painel): sem rastro de exceção no log

    def _erro(self, status, codigo, msg):
        self._json({"erro": msg, "codigo": codigo}, status)

    def _ok_host(self):
        return self.headers.get("Host") in HOSTS

    def do_GET(self):
        if not self._ok_host():
            return self._json({"erro": "proibido", "codigo": "proibido"}, 403)
        if self.path.partition("?")[0] == "/saude":
            return self._json({"ok": _kokoro is not None, "modelo": _estado["modelo"],
                               "vozes_pt": _estado["vozes_pt"], "carga_ms": _estado["carga_ms"],
                               "aquecimento_ms": _estado["aquecimento_ms"], "rss_mb": rss_mb(),
                               "pedidos": _estado["pedidos"]})
        self._erro(404, "nao_encontrado", "rota inexistente")

    def do_POST(self):
        if not self._ok_host():
            return self._json({"erro": "proibido", "codigo": "proibido"}, 403)
        origem = self.headers.get("Origin")
        if origem is not None and origem not in ORIGENS:
            return self._json({"erro": "proibido", "codigo": "proibido"}, 403)
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return self._json({"erro": "proibido", "codigo": "proibido"}, 403)  # força preflight, nunca respondido
        rota = self.path.partition("?")[0]
        if rota == "/aquecer":
            ocioso = time.monotonic() - _estado["ultima_sintese"]
            vai = _kokoro is not None and ocioso > AQUECER_APOS_S and not _trava_sintese.locked()
            if vai:
                threading.Thread(target=aquecer_em_segundo_plano, daemon=True).start()
            return self._json({"aquecendo": vai, "ocioso_s": round(ocioso)}, 202)
        if rota != "/falar":
            return self._erro(404, "nao_encontrado", "rota inexistente")

        maximo = CFG["max_caracteres_pedido"]
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n < 0 or n > maximo * 8 + 1024:
                raise ValueError("corpo grande demais")
            corpo = json.loads(self.rfile.read(n) or b"{}")
            if not isinstance(corpo, dict):
                raise ValueError("corpo não é objeto")
        except (ValueError, OSError):
            return self._erro(400, "texto_invalido", "pedido ilegível")

        texto = corpo.get("texto")
        texto = texto.strip() if isinstance(texto, str) else ""
        if not texto or len(texto) > maximo:
            registrar(f"pedido chars={len(texto)} ms=- voz=- erro=texto_invalido")
            return self._erro(400, "texto_invalido", f"texto vazio ou acima de {maximo} caracteres")

        voz = corpo.get("voz")
        if voz is None:
            voz = CFG["voz"]
        if not isinstance(voz, str) or voz not in _estado["vozes_pt"]:
            registrar(f"pedido chars={len(texto)} ms=- voz=- erro=voz_invalida")
            return self._erro(400, "voz_invalida", "voz desconhecida")

        velocidade = corpo.get("velocidade")
        if velocidade is None:
            velocidade = CFG["velocidade"]
        if isinstance(velocidade, bool) or not isinstance(velocidade, (int, float)):
            registrar(f"pedido chars={len(texto)} ms=- voz={voz} erro=texto_invalido")
            return self._erro(400, "texto_invalido", "velocidade inválida")
        velocidade = min(2.0, max(0.5, float(velocidade)))

        if not _trava_sintese.acquire(timeout=PRAZO_TRAVA_S):
            registrar(f"pedido chars={len(texto)} ms=- voz={voz} erro=ocupado")
            return self._erro(503, "ocupado", "outra frase está em síntese")
        try:
            _estado["pedidos"] += 1
            wav, ms = sintetizar(texto, voz, velocidade)
            _estado["ultima_sintese"] = time.monotonic()
        except Exception as e:
            registrar(f"pedido chars={len(texto)} ms=- voz={voz} erro=sintese tipo={type(e).__name__}")
            return self._erro(500, "sintese", "a síntese falhou")
        finally:
            _trava_sintese.release()

        registrar(f"pedido chars={len(texto)} ms={ms} voz={voz} ok")
        try:
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(wav)))
            self.send_header("X-Sintese-Ms", str(ms))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(wav)
        except (BrokenPipeError, ConnectionResetError):
            pass  # quem pediu desistiu


def principal():
    girar_log()
    registrar(f"subindo pid={os.getpid()} porta={PORTA} modelo={CFG['modelo']}")
    # Reserva a porta ANTES de carregar o modelo: uma segunda instância falha aqui, sem gastar
    # memória. Sem listen() ainda, quem conectar durante a carga recebe "recusado" (voz fora).
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", PORTA), Handler, bind_and_activate=False)
        srv.server_bind()
    except OSError as e:
        registrar(f"falha porta={PORTA} tipo={type(e).__name__}")
        raise SystemExit(f"porta {PORTA} indisponível: {e}")
    srv.daemon_threads = True
    carregar()
    srv.server_activate()

    def encerrar(*_):
        registrar("desligando")
        threading.Thread(target=srv.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, encerrar)
    registrar(f"no ar porta={PORTA} rss_mb={rss_mb()}")
    print(f"Voz do Jarvis no ar em http://127.0.0.1:{PORTA}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    principal()
