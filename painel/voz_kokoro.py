"""Provedor de voz Kokoro: o servidor.py importa este módulo e fala com o serviço local.

Só biblioteca padrão (o servidor.py não tem pip). O motor roda à parte, em
voz_kokoro_servico.py (launchd com.jarvis.voz, 127.0.0.1:8791). Aqui só há o cliente.

Interface usada pelo servidor:
    TIPO      -> "audio/wav"
    ErroVoz   -> .codigo (fora, lento, texto_invalido, voz_invalida, ocupado, api) e .msg
                 em pt-BR falável, sem travessão
    abrir(t)  -> iterador de pedaços de 16 KB; erros viram ErroVoz ANTES do primeiro pedaço
    status()  -> {"provedor", "disponivel", "voz", "modelo", "motivo", "hoje_frases", "rss_mb"?}

Uso registrado em logs/uso-voz.jsonl: {ts, caracteres, ms_primeiro_byte, ok, codigo?, provedor}.
O texto falado nunca é gravado. ms_primeiro_byte conta de abrir() até chegar o status 200 do
serviço (o serviço só responde com a síntese pronta, então o áudio já está a caminho).

Teste: a variável de ambiente PAINEL_VOZ_PRAZO_MS troca o prazo (só para testar o erro lento).
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "coletores"))

import http.client
import json
import os
import socket
import threading
import time

import _base

TIPO = "audio/wav"
HOST = "127.0.0.1"
LOG = _base.PAINEL / "logs" / "uso-voz.jsonl"
CONFIG = _base.PAINEL / "config.json"
PEDACO = 16 * 1024
PRAZO_STATUS_S = 0.5
LEITURA_MAX_LOG = 5_000_000  # bytes lidos do fim do uso-voz.jsonl ao contar o dia

_trava_log = threading.Lock()

MENSAGENS = {
    "fora": "Senhor, a voz local está desligada. Sigo com a voz reserva.",
    "lento": "Senhor, a voz local demorou demais. Sigo com a voz reserva.",
    "texto_invalido": "Senhor, não consigo falar esse texto. Sigo com a voz reserva.",
    "voz_invalida": "Senhor, a voz escolhida não existe no serviço local. Sigo com a voz reserva.",
    "ocupado": "Senhor, a voz local está ocupada com outra frase. Sigo com a voz reserva.",
    "api": "Senhor, a voz local falhou. Sigo com a voz reserva.",
}


class ErroVoz(Exception):
    """codigo: fora, lento, texto_invalido, voz_invalida, ocupado, api. msg: pt-BR falável."""

    def __init__(self, codigo, msg):
        super().__init__(f"{codigo}: {msg}")
        self.codigo = codigo
        self.msg = msg


def _erro(codigo, msg=None):
    return ErroVoz(codigo, msg or MENSAGENS[codigo])


def _cfg():
    """Seção voz do config.json com padrões para chave ausente."""
    try:
        bruto = json.loads(CONFIG.read_text(encoding="utf-8")).get("voz", {})
    except (OSError, ValueError):
        bruto = {}
    if not isinstance(bruto, dict):
        bruto = {}

    def num(chave, padrao, tipo):
        v = bruto.get(chave)
        return tipo(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 else padrao

    prazo_ms = num("prazo_ms", 3000, int)
    teste = os.environ.get("PAINEL_VOZ_PRAZO_MS", "").strip()
    if teste.isdigit() and int(teste) > 0:
        prazo_ms = int(teste)
    voz = bruto.get("voz")
    voz = voz if isinstance(voz, str) and voz else "pm_alex"
    opcoes = [v for v in bruto.get("opcoes") or [] if isinstance(v, str) and v]
    return {"porta": num("porta", 8791, int), "prazo_ms": prazo_ms,
            "velocidade": num("velocidade", 1.0, float),
            "max_caracteres": num("max_caracteres_pedido", 600, int),
            "voz": voz, "opcoes": opcoes or [voz],
            "modelo": bruto.get("modelo") if isinstance(bruto.get("modelo"), str) else "int8"}


def _registrar(caracteres, ms_primeiro_byte, ok, codigo=None):
    linha = {"ts": _base.agora().isoformat(timespec="seconds"), "caracteres": caracteres,
             "ms_primeiro_byte": ms_primeiro_byte, "ok": ok, "provedor": "kokoro"}
    if codigo:
        linha["codigo"] = codigo
    with _trava_log:
        try:
            LOG.parent.mkdir(exist_ok=True)
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(linha, ensure_ascii=False) + "\n")
        except OSError:
            pass  # sem registro não derruba a voz


class _Fluxo:
    """Iterador de pedaços do WAV. Registra o uso uma vez, no fim ou no close()."""

    def __init__(self, conn, resp, caracteres, ms_primeiro_byte, total):
        self._conn, self._resp = conn, resp
        self._caracteres, self._ms, self._total = caracteres, ms_primeiro_byte, total
        self._lidos = 0
        self._fechado = False

    def __iter__(self):
        return self

    def __next__(self):
        if self._fechado:
            raise StopIteration
        try:
            pedaco = self._resp.read(PEDACO)
        except (OSError, http.client.HTTPException):
            self._fechar(False, "api")
            raise _erro("api")
        if not pedaco:
            completo = self._total is None or self._lidos == self._total
            self._fechar(completo, None if completo else "api")
            if not completo:
                raise _erro("api")
            raise StopIteration
        self._lidos += len(pedaco)
        return pedaco

    def close(self):
        # fechar sem ter lido tudo (navegador cancelou) conta como falha parcial
        completo = self._total is not None and self._lidos == self._total
        self._fechar(completo, None if completo else "cancelado")

    def _fechar(self, ok, codigo):
        if self._fechado:
            return
        self._fechado = True
        try:
            self._conn.close()
        except OSError:
            pass
        _registrar(self._caracteres, self._ms, ok, codigo)


def abrir(texto, voz=None):
    """Valida, pede ao serviço dentro do prazo e só devolve o iterador depois do status 200.
    voz: a escolhida no seletor do painel; fora de config.json/voz.opcoes vale a padrão."""
    inicio = time.monotonic()
    cfg = _cfg()
    voz = voz if voz in cfg["opcoes"] else cfg["voz"]
    texto = texto.strip() if isinstance(texto, str) else ""
    if not texto:
        _registrar(0, None, False, "texto_invalido")
        raise _erro("texto_invalido", "Senhor, a frase veio vazia. Nada a falar.")
    if len(texto) > cfg["max_caracteres"]:
        _registrar(len(texto), None, False, "texto_invalido")
        raise _erro("texto_invalido", "Senhor, a frase é longa demais para a voz local. Sigo com a voz reserva.")

    prazo_s = cfg["prazo_ms"] / 1000
    corpo = json.dumps({"texto": texto, "voz": voz, "velocidade": cfg["velocidade"]},
                       ensure_ascii=False).encode()
    conn = http.client.HTTPConnection(HOST, cfg["porta"], timeout=prazo_s)

    def falhar(codigo, msg=None):
        try:
            conn.close()
        except OSError:
            pass
        _registrar(len(texto), None, False, codigo)
        return _erro(codigo, msg)

    try:
        conn.connect()
        conn.sock.settimeout(max(0.05, prazo_s - (time.monotonic() - inicio)))  # prazo total, não por operação
        conn.request("POST", "/falar", body=corpo,
                     headers={"Content-Type": "application/json", "Content-Length": str(len(corpo))})
        resp = conn.getresponse()
    except (socket.timeout, TimeoutError):
        raise falhar("lento")
    except (ConnectionRefusedError, FileNotFoundError):
        raise falhar("fora")
    except (OSError, http.client.HTTPException):
        raise falhar("api")

    if resp.status != 200:
        try:
            codigo = json.loads(resp.read(4096) or b"{}").get("codigo")
        except (OSError, ValueError, AttributeError, http.client.HTTPException):
            codigo = None
        if resp.status == 400 and codigo in ("texto_invalido", "voz_invalida"):
            raise falhar(codigo)
        if resp.status == 503 and codigo == "ocupado":
            raise falhar("ocupado")
        raise falhar("api")

    ms = round((time.monotonic() - inicio) * 1000)
    tamanho = resp.getheader("Content-Length")
    total = int(tamanho) if tamanho and tamanho.isdigit() else None
    return _Fluxo(conn, resp, len(texto), ms, total)


def _hoje_frases():
    """Linhas ok de hoje (BRT) deste provedor no uso-voz.jsonl."""
    hoje, n = _base.agora().date().isoformat(), 0
    try:
        with open(LOG, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - LEITURA_MAX_LOG))
            linhas = f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return 0
    for linha in linhas:
        try:
            r = json.loads(linha)
        except ValueError:
            continue
        if (isinstance(r, dict) and r.get("ok") is True and r.get("provedor") == "kokoro"
                and str(r.get("ts", "")).startswith(hoje)):
            n += 1
    return n


def aquecer():
    """Pede ao serviço pra trazer o modelo de volta à memória. Não espera a síntese; nunca levanta exceção."""
    conn = http.client.HTTPConnection(HOST, _cfg()["porta"], timeout=PRAZO_STATUS_S)
    try:
        conn.request("POST", "/aquecer", body=b"{}", headers={"Content-Type": "application/json"})
        return json.loads(conn.getresponse().read(1024) or b"{}")
    except Exception:
        return None
    finally:
        try:
            conn.close()
        except OSError:
            pass


def status():
    """GET /saude com prazo de 0,5 s. Nunca levanta exceção."""
    cfg = _cfg()
    saida = {"provedor": "kokoro", "disponivel": False, "voz": cfg["voz"], "opcoes": cfg["opcoes"],
             "modelo": cfg["modelo"], "motivo": "", "hoje_frases": 0}
    try:
        saida["hoje_frases"] = _hoje_frases()
    except Exception:
        pass
    conn = http.client.HTTPConnection(HOST, cfg["porta"], timeout=PRAZO_STATUS_S)
    try:
        conn.request("GET", "/saude")
        resp = conn.getresponse()
        dados = json.loads(resp.read(8192) or b"{}")
        if resp.status != 200 or not isinstance(dados, dict):
            saida["motivo"] = "O serviço de voz respondeu com erro."
        elif dados.get("ok") is not True:
            saida["motivo"] = "O serviço de voz ainda está carregando o modelo."
        else:
            saida["disponivel"] = True
            if isinstance(dados.get("modelo"), str):
                saida["modelo"] = dados["modelo"]
            if isinstance(dados.get("rss_mb"), (int, float)):
                saida["rss_mb"] = dados["rss_mb"]
    except (socket.timeout, TimeoutError):
        saida["motivo"] = "O serviço de voz não respondeu a tempo."
    except (ConnectionRefusedError, FileNotFoundError):
        saida["motivo"] = "O serviço de voz está desligado."
    except (OSError, ValueError, http.client.HTTPException):
        saida["motivo"] = "O serviço de voz respondeu de forma inesperada."
    finally:
        try:
            conn.close()
        except OSError:
            pass
    return saida
