"""Voz do Jarvis: ElevenLabs Flash v2.5 em streaming, chamada SÓ pelo servidor.

Só biblioteca padrão. A chave (ELEVENLABS_API_KEY) e o id da voz (ELEVENLABS_VOICE_ID)
vêm de painel/.env pela _base.segredo e nunca saem daqui: não vão para log, erro,
retorno nem navegador. O texto falado também nunca vai para o log (privacidade).

Interface usada pelo servidor:
    abrir(texto)  -> iterador de pedaços mp3 (erros viram ErroVoz ANTES do 1o pedaço)
    status()      -> {"tem_chave", "tem_voz", "hoje_creditos", "teto", "modelo"}
    saldo()       -> números e datas (BRT) da assinatura

Linha de comando (teste e amostras):
    python -I voz.py saldo
    python -I voz.py falar "texto" saida.mp3
    python -I voz.py amostras <pasta>
    python -I voz.py salvar <id_gerado> [nome]

Fontes da API (documentação oficial, lida em 2026-10-20):
    elevenlabs.io/docs/api-reference/text-to-speech/stream
    elevenlabs.io/docs/api-reference/user/subscription/get
    elevenlabs.io/docs/api-reference/text-to-voice/design
    elevenlabs.io/docs/api-reference/text-to-voice/create
    elevenlabs.io/docs/api-reference/introduction  (header character-cost)
    elevenlabs.io/docs/eleven-api/resources/errors
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "coletores"))

import base64
import datetime
import http.client
import json
import re
import socket
import ssl
import threading
import time
import urllib.error
import urllib.request

import _base

API = "https://api.elevenlabs.io"
LOG = _base.PAINEL / "logs" / "uso-voz.jsonl"
CONFIG = _base.PAINEL / "config.json"
USER_AGENT = "JarvisPainel/1.0"

TIMEOUT_S = 5          # conexão e leitura do streaming
TIMEOUT_DESIGN_S = 90  # Voice Design gera 3 amostras e demora alguns segundos
PEDACO = 4096          # leitura em pedaços de 4 KB

# Créditos por caractere, por modelo. Fonte: página de preços da ElevenLabs (Creator inclui
# 275k créditos no modelo v4 e 550k no Flash/Turbo) e o FAQ de preços ("Flash v2.5 custa 50%
# menos por caractere nas gerações por API"). A doc de modelos não traz o número exato, então
# a estimativa é a base do teto e o header character-cost (quando vier) vale mais.
# Confira com a variação do saldo no primeiro `falar` real (a CLI imprime os dois).
FATOR_CREDITO = {
    "eleven_flash_v2_5": 0.5,
    "eleven_turbo_v2_5": 0.5,
    "eleven_multilingual_v2": 1.0,
}
FATOR_PADRAO = 1.0     # modelo desconhecido: assume o caro, protege o teto

# Padrões da doc (stream). Pode ser sobrescrito em config.json > voz > voice_settings.
VOICE_SETTINGS = {"stability": 0.5, "similarity_boost": 0.75, "style": 0.0,
                  "use_speaker_boost": True, "speed": 1.0}

# Voice Design: o modelo da doc (eleven_multilingual_ttv_v2 cobre português; o
# eleven_ttv_v3 também). Sem nome de ator, personagem ou dublador real.
MODELO_DESIGN = "eleven_multilingual_ttv_v2"
DESCRICAO_VOZ = (
    "Voz masculina grave, calma e elegante, de mordomo refinado e discreto. "
    "Fala português do Brasil com sotaque neutro, ritmo pausado, dicção impecável, "
    "timbre quente e firme, sem exagero de emoção, como quem atende com serenidade."
)
TEXTO_AMOSTRA = (
    "Boa noite, senhor. O painel está atualizado. Três pontos pedem atenção "
    "e a semana está em trinta e três por cento do limite."
)

_trava = threading.Lock()
_em_voo = 0.0          # créditos estimados de pedidos abertos e ainda não registrados
ultimo_uso = {}        # última linha registrada (a CLI lê daqui)


class ErroVoz(Exception):
    """codigo: sem_chave, sem_voz, teto, chave_recusada, sem_credito, rede, api, texto_invalido.
    msg: pt-BR, falável, sem travessão. detalhe: técnico e curto, nunca com a chave."""

    def __init__(self, codigo, msg, detalhe=""):
        super().__init__(f"{codigo}: {msg}")
        self.codigo = codigo
        self.msg = msg
        self.detalhe = detalhe


_MSG = {
    "sem_chave": "Senhor, a chave da voz ainda não está configurada. Sigo com a voz reserva.",
    "sem_voz": "Senhor, a voz do Jarvis ainda não foi escolhida. Sigo com a voz reserva.",
    "teto": "Senhor, atingi o limite de voz de hoje. Sigo com a voz reserva.",
    "chave_recusada": "Senhor, o serviço de voz recusou a chave de acesso. Sigo com a voz reserva.",
    "sem_credito": "Senhor, acabaram os créditos de voz da conta. Sigo com a voz reserva.",
    "rede": "Senhor, não consegui falar com o serviço de voz. Sigo com a voz reserva.",
    "api": "Senhor, o serviço de voz devolveu um erro. Sigo com a voz reserva.",
}


def _erro(codigo, detalhe=""):
    return ErroVoz(codigo, _MSG[codigo], detalhe)


# ---------------------------------------------------------------- configuração e log

def _cfg():
    try:
        voz = json.loads(CONFIG.read_text()).get("voz", {})
    except (OSError, ValueError):
        voz = {}
    return {
        "modelo": voz.get("modelo") or "eleven_flash_v2_5",
        "formato": voz.get("formato") or "mp3_44100_128",
        "teto": int(voz.get("teto_creditos_dia") or 2000),
        "max_chars": int(voz.get("max_caracteres_pedido") or 600),
        "settings": voz.get("voice_settings") or VOICE_SETTINGS,
    }


def _linhas_log():
    try:
        with open(LOG, encoding="utf-8") as f:
            for linha in f:
                try:
                    yield json.loads(linha)
                except ValueError:
                    continue
    except OSError:
        return


def _dia_brt(ts):
    try:
        return datetime.datetime.fromisoformat(ts).astimezone(_base.FUSO).date()
    except (TypeError, ValueError):
        return None


def hoje_creditos():
    """Soma dos créditos de hoje (BRT) no log."""
    hoje = _base.agora().date()
    total = 0.0
    for r in _linhas_log():
        if _dia_brt(r.get("ts")) == hoje:
            try:
                total += float(r.get("creditos") or 0)
            except (TypeError, ValueError):
                pass
    return total


def _registrar(caracteres, creditos, real, ms, ok, codigo=None, tipo=None):
    """Uma linha por uso. Sem o texto falado."""
    linha = {"ts": _base.agora().isoformat(timespec="seconds"), "caracteres": caracteres,
             "creditos": round(float(creditos), 2), "real": bool(real),
             "ms_primeiro_byte": ms, "ok": bool(ok)}
    if codigo:
        linha["codigo"] = codigo
    if tipo:
        linha["tipo"] = tipo
    ultimo_uso.clear()
    ultimo_uso.update(linha)
    try:
        with _trava:
            LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(linha, ensure_ascii=False) + "\n")
    except OSError:
        pass  # o log nunca derruba o áudio


# ---------------------------------------------------------------- texto

def _limpar(texto):
    """Tira markdown simples e símbolos que o TTS leria em voz alta."""
    t = str(texto or "")
    t = re.sub(r"```.*?```", " ", t, flags=re.S)
    t = re.sub(r"`([^`]*)`", r"\1", t)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", t)
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"https?://\S+", " ", t)
    t = re.sub(r"^\s*[-=_*]{3,}\s*$", " ", t, flags=re.M)
    t = re.sub(r"^\s{0,3}#{1,6}\s*", "", t, flags=re.M)
    t = re.sub(r"^\s*>\s?", "", t, flags=re.M)
    t = re.sub(r"^\s*(?:[-*+•]|\d+[.)])\s+", "", t, flags=re.M)
    t = re.sub(r"(\*\*|__)(.+?)\1", r"\2", t, flags=re.S)
    t = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\1", t, flags=re.S)
    t = re.sub(r"(?<!\w)_(?!\s)(.+?)(?<!\s)_(?!\w)", r"\1", t, flags=re.S)
    t = t.replace("*", "").replace("#", " ")
    t = re.sub(r"\s*[\u2014\u2013]\s*", ", ", t)   # travessões viram pausa
    t = re.sub(r"\s*\|\s*", ", ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


# ---------------------------------------------------------------- HTTP

_urlopen = urllib.request.urlopen   # os testes trocam esta função por uma falsa


def _chave():
    chave = _base.segredo("ELEVENLABS_API_KEY")
    if not chave:
        raise _erro("sem_chave", "ELEVENLABS_API_KEY ausente")
    return chave


def _voz_id():
    voz = _base.segredo("ELEVENLABS_VOICE_ID")
    if not voz:
        raise _erro("sem_voz", "ELEVENLABS_VOICE_ID ausente")
    return voz


def _erro_http(e):
    """HTTPError da API -> ErroVoz. Lê no máximo 2 KB do corpo e nunca o repassa inteiro."""
    try:
        bruto = e.read(2048).decode("utf-8", "replace")
    except Exception:
        bruto = ""
    codigo_api = msg_api = ""
    try:
        d = json.loads(bruto).get("detail", "")
        if isinstance(d, dict):
            codigo_api = " ".join(str(d.get(k, "")) for k in ("code", "status", "type"))
            msg_api = str(d.get("message", ""))
        else:
            msg_api = str(d)
    except (ValueError, AttributeError):
        pass
    pista = (codigo_api + " " + msg_api).lower()
    curto = re.sub(r"[^a-z0-9_ ]", "", codigo_api.lower()).strip()[:60]
    detalhe = f"HTTP {e.code} {curto}".strip()
    if e.code == 402 or "quota" in pista or "insufficient_credits" in pista:
        return _erro("sem_credito", detalhe)
    if "permission" in pista or e.code == 403:
        return ErroVoz("api", "Senhor, a chave não tem permissão para esta operação do serviço de voz. "
                              "Sigo com a voz reserva.", detalhe)
    if e.code == 401:
        return _erro("chave_recusada", detalhe)
    if e.code == 404 and "voice" in pista:
        return _erro("sem_voz", detalhe)
    return _erro("api", detalhe)


def _requisitar(metodo, caminho, corpo=None, timeout=TIMEOUT_S, chave=None):
    """Abre a conexão e devolve a resposta aberta. Traduz falhas para ErroVoz."""
    chave = chave or _chave()
    dados = json.dumps(corpo, ensure_ascii=False).encode("utf-8") if corpo is not None else None
    req = urllib.request.Request(API + caminho, data=dados, method=metodo, headers={
        "xi-api-key": chave, "Content-Type": "application/json",
        "Accept": "application/json, audio/mpeg", "User-Agent": USER_AGENT})
    try:
        return _urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        try:
            raise _erro_http(e) from None
        finally:
            e.close()
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError,
            http.client.HTTPException, ssl.SSLError, OSError) as e:
        motivo = getattr(e, "reason", e)
        raise _erro("rede", type(motivo).__name__) from None


def _json(metodo, caminho, corpo=None, timeout=TIMEOUT_S):
    resp = _requisitar(metodo, caminho, corpo, timeout)
    try:
        return json.loads(resp.read())
    except ValueError:
        raise _erro("api", "resposta que não é JSON") from None
    except (socket.timeout, TimeoutError, ConnectionError, http.client.HTTPException, OSError):
        raise _erro("rede", "leitura interrompida") from None
    finally:
        try:
            resp.close()
        except Exception:
            pass


# ---------------------------------------------------------------- fala (streaming)

class _Fluxo:
    """Iterador de pedaços mp3. Registra o uso uma vez só: no fim, na falha ou no close()."""

    def __init__(self, resp, primeiro, meta):
        self._resp = resp
        self._primeiro = primeiro
        self._meta = meta
        self._fim = False

    def __iter__(self):
        return self

    def __next__(self):
        if self._primeiro is not None:
            pedaco, self._primeiro = self._primeiro, None
            return pedaco
        if self._fim:
            raise StopIteration
        try:
            pedaco = self._resp.read1(PEDACO)
        except (socket.timeout, TimeoutError, ConnectionError, http.client.HTTPException, OSError):
            self._encerrar(False, "rede")
            raise _erro("rede", "stream interrompido") from None
        if not pedaco:
            self._encerrar(True)
            raise StopIteration
        return pedaco

    def close(self):
        self._encerrar(False, "interrompido")

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def _encerrar(self, ok, codigo=None):
        global _em_voo
        if self._fim:
            return
        self._fim = True
        m = self._meta
        with _trava:
            _em_voo = max(0.0, _em_voo - m["estimativa"])
        try:
            self._resp.close()
        except Exception:
            pass
        _registrar(m["caracteres"], m["creditos"], m["real"], m["ms"], ok, codigo)


def _custo_header(resp):
    """Custo real do pedido, se a ElevenLabs mandar o header (character-cost, na doc)."""
    for nome in ("character-cost", "x-character-count"):
        try:
            valor = resp.headers.get(nome)
            if valor is not None:
                return float(str(valor).strip())
        except (TypeError, ValueError, AttributeError):
            continue
    return None


def abrir(texto):
    """Valida, confere o teto, abre a conexão e só então devolve o iterador de pedaços mp3.
    Tudo que pode falhar antes do áudio levanta ErroVoz aqui, antes do 1o pedaço."""
    global _em_voo
    cfg = _cfg()
    limpo = _limpar(texto)
    if not limpo:
        raise ErroVoz("texto_invalido", "Senhor, não recebi texto para falar.")
    if len(limpo) > cfg["max_chars"]:
        raise ErroVoz("texto_invalido", f"Senhor, o texto passa de {cfg['max_chars']} caracteres "
                                        "e é longo demais para a voz.")
    chave = _chave()
    voz = _voz_id()

    fator = FATOR_CREDITO.get(cfg["modelo"], FATOR_PADRAO)
    estimativa = len(limpo) * fator
    with _trava:  # reserva atômica: dois pedidos juntos não furam o teto
        if hoje_creditos() + _em_voo + estimativa > cfg["teto"]:
            raise _erro("teto", f"hoje {hoje_creditos():.0f} de {cfg['teto']}")
        _em_voo += estimativa

    def liberar():
        global _em_voo
        with _trava:
            _em_voo = max(0.0, _em_voo - estimativa)

    corpo = {"text": limpo, "model_id": cfg["modelo"], "language_code": "pt",
             "voice_settings": cfg["settings"]}
    caminho = f"/v1/text-to-speech/{voz}/stream?output_format={cfg['formato']}"
    t0 = time.monotonic()
    resp = None
    try:
        resp = _requisitar("POST", caminho, corpo, TIMEOUT_S, chave)
        primeiro = resp.read1(PEDACO)
        if not primeiro:
            raise _erro("api", "stream vazio")
    except ErroVoz as e:
        liberar()
        if resp is not None:
            resp.close()
        if e.codigo in ("chave_recusada", "sem_credito", "sem_voz", "rede", "api"):
            _registrar(len(limpo), 0, False, None, False, e.codigo)
        raise
    except (socket.timeout, TimeoutError, ConnectionError, http.client.HTTPException, OSError):
        liberar()
        if resp is not None:
            resp.close()
        _registrar(len(limpo), 0, False, None, False, "rede")
        raise _erro("rede", "primeiro pedaço") from None
    ms = int((time.monotonic() - t0) * 1000)
    real = _custo_header(resp)
    meta = {"caracteres": len(limpo), "estimativa": estimativa, "ms": ms,
            "creditos": estimativa if real is None else real, "real": real is not None}
    return _Fluxo(resp, primeiro, meta)


# ---------------------------------------------------------------- status e saldo

def status():
    try:
        cfg = _cfg()
        return {"tem_chave": bool(_base.segredo("ELEVENLABS_API_KEY")),
                "tem_voz": bool(_base.segredo("ELEVENLABS_VOICE_ID")),
                "hoje_creditos": round(hoje_creditos(), 1), "teto": cfg["teto"],
                "modelo": cfg["modelo"]}
    except Exception:
        return {"tem_chave": False, "tem_voz": False, "hoje_creditos": 0.0,
                "teto": 2000, "modelo": "eleven_flash_v2_5"}


def saldo():
    """GET /v1/user/subscription. Só números e datas em BRT, nunca a chave."""
    d = _json("GET", "/v1/user/subscription")
    usado = d.get("character_count")
    limite = d.get("character_limit")
    reset = d.get("next_character_count_reset_unix")
    saida = {
        "plano": d.get("tier"), "status": d.get("status"),
        "creditos_usados": usado, "creditos_limite": limite,
        "creditos_restantes": (limite - usado) if isinstance(usado, int) and isinstance(limite, int) else None,
        "proximo_reset": (datetime.datetime.fromtimestamp(reset, _base.FUSO)
                          .isoformat(timespec="minutes") if isinstance(reset, int) else None),
        "vozes_usadas": d.get("voice_slots_used"), "vozes_limite": d.get("voice_limit"),
        "painel_hoje": round(hoje_creditos(), 1),
    }
    return saida


# ---------------------------------------------------------------- Voice Design (CLI)

def gerar_amostras(pasta, modelo=MODELO_DESIGN):
    """POST /v1/text-to-voice/design -> grava amostra-N.mp3 e amostras.json. Cobra pelos
    caracteres do TEXTO_AMOSTRA, uma vez por geração (3 vozes)."""
    destino = pathlib.Path(pasta)
    destino.mkdir(parents=True, exist_ok=True)
    corpo = {"voice_description": DESCRICAO_VOZ, "text": TEXTO_AMOSTRA, "model_id": modelo}
    caminho = f"/v1/text-to-voice/design?output_format={_cfg()['formato']}"
    t0 = time.monotonic()
    try:
        d = _json("POST", caminho, corpo, TIMEOUT_DESIGN_S)
    except ErroVoz as e:
        if "409" not in e.detalhe:
            raise
        time.sleep(2)  # a doc manda repetir quando já há geração em andamento
        d = _json("POST", caminho, corpo, TIMEOUT_DESIGN_S)
    ms = int((time.monotonic() - t0) * 1000)
    previas = d.get("previews") or []
    if not previas:
        raise _erro("api", "Voice Design sem amostras")
    itens = []
    for i, p in enumerate(previas, 1):
        arq = destino / f"amostra-{i}.mp3"
        arq.write_bytes(base64.b64decode(p.get("audio_base_64", "")))
        itens.append({"n": i, "arquivo": arq.name, "generated_voice_id": p.get("generated_voice_id"),
                      "duracao_s": p.get("duration_secs"), "tipo": p.get("media_type")})
    (destino / "amostras.json").write_text(json.dumps(
        {"modelo": modelo, "descricao": DESCRICAO_VOZ, "texto": d.get("text") or TEXTO_AMOSTRA,
         "amostras": itens}, ensure_ascii=False, indent=2) + "\n")
    # Gasto: caracteres do texto, 1 geração. Fator 1.0 por cautela (a doc não dá o número).
    _registrar(len(TEXTO_AMOSTRA), len(TEXTO_AMOSTRA), False, ms, True, tipo="design")
    return itens


def salvar_voz(generated_voice_id, nome="Jarvis Mordomo"):
    """POST /v1/text-to-voice -> voice_id definitivo. Não grava no .env."""
    d = _json("POST", "/v1/text-to-voice", {
        "voice_name": nome, "voice_description": DESCRICAO_VOZ,
        "generated_voice_id": generated_voice_id}, TIMEOUT_DESIGN_S)
    voz_id = d.get("voice_id")
    if not voz_id:
        raise _erro("api", "resposta sem voice_id")
    return voz_id


# ---------------------------------------------------------------- linha de comando

def _usado_conta():
    try:
        return saldo().get("creditos_usados")
    except ErroVoz:
        return None


def _cli(argv):
    if len(argv) < 2:
        print(__doc__.split("Linha de comando")[1].split("Fontes")[0].strip(), file=sys.stderr)
        return 2
    cmd = argv[1]
    if cmd == "saldo":
        print(json.dumps(saldo(), ensure_ascii=False, indent=2))
    elif cmd == "falar" and len(argv) == 4:
        antes = _usado_conta()
        total = 0
        fluxo = abrir(argv[2])
        with open(argv[3], "wb") as f:
            for pedaco in fluxo:
                f.write(pedaco)
                total += len(pedaco)
        u = ultimo_uso
        print(f"bytes: {total}")
        print(f"ms ate o primeiro byte: {u.get('ms_primeiro_byte')}")
        print(f"creditos: {u.get('creditos')} ({'real, do header' if u.get('real') else 'estimado'})")
        depois = _usado_conta()
        if antes is not None and depois is not None:
            print(f"variacao no saldo da conta: {depois - antes} (pode atrasar um pouco)")
    elif cmd == "amostras" and len(argv) in (3, 4):
        itens = gerar_amostras(argv[2], *(argv[3:4]))
        for it in itens:
            print(f"amostra-{it['n']}.mp3  id={it['generated_voice_id']}  {it['duracao_s']}s")
        print(f"texto: {len(TEXTO_AMOSTRA)} caracteres, 1 geracao")
    elif cmd == "salvar" and len(argv) in (3, 4):
        print(salvar_voz(argv[2], *(argv[3:4])))
    else:
        print("uso: voz.py saldo | falar \"texto\" saida.mp3 | amostras <pasta> | salvar <id> [nome]",
              file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(_cli(sys.argv))
    except ErroVoz as e:
        print(f"[{e.codigo}] {e.msg}" + (f" ({e.detalhe})" if e.detalhe else ""), file=sys.stderr)
        sys.exit(1)
