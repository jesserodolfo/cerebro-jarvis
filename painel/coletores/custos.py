"""Coletor de custos: consumo do Claude Code na semana do plano, em equivalente de API.

Lê ~/.claude/projects/<pasta>/**/*.jsonl só pra leitura. Cache próprio em
painel/logs/custos-cache.json: cada arquivo guarda até onde foi lido (offset) e o
que somou, então a 2ª rodada só lê o trecho novo.
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import datetime
import hashlib
import json
import os

from _base import FUSO, PAINEL, agora, erro, ok, rodar

PROJETOS = pathlib.Path.home() / ".claude/projects"
CONFIG = PAINEL / "config.json"
CACHE = PAINEL / "logs/custos-cache.json"
USO_API = PAINEL / "logs/uso-api.jsonl"
DIAS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
NOMES_MODELO = {"opus-5-5": "Opus 5.5", "opus-5": "Opus 5", "sonnet-5-5": "Sonnet 5.5", "sonnet-5": "Sonnet 5",
                "haiku-5-5": "Haiku 5.5", "fable-5-1": "Fable 5.1", "fable-5": "Fable 5", "opus-4-8": "Opus 4.8"}


def inicio_semana(agora_brt):
    """Último domingo 09:00 BRT."""
    dias = (agora_brt.weekday() + 1) % 7  # domingo = 0
    ini = (agora_brt - datetime.timedelta(days=dias)).replace(hour=9, minute=0, second=0, microsecond=0)
    if ini > agora_brt:
        ini -= datetime.timedelta(days=7)
    return ini


def casar_preco(modelo, precos):
    for k in sorted(precos, key=len, reverse=True):
        if k in modelo:
            return k, precos[k]
    return None, None


def usd(v):
    return f"US$ {v:.0f}" if v >= 10 else f"US$ {v:.2f}".replace(".", ",")


def pct(v):
    return f"{v:.0f}%"


def ler_cache(semana, assinatura):
    try:
        c = json.loads(CACHE.read_text())
        if c.get("semana") == semana and c.get("precos") == assinatura:
            return c
    except Exception:
        pass
    return {"semana": semana, "precos": assinatura, "arquivos": {}}


def gravar_cache(c):
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE.with_suffix(".tmp")
    tmp.write_text(json.dumps(c, ensure_ascii=False))
    os.replace(tmp, CACHE)


def novo_registro(pasta):
    return {"pasta": pasta, "mtime": 0, "tamanho": 0, "offset": 0, "ids": [],
            "total": 0.0, "tipo": [0.0, 0.0, 0.0, 0.0], "modelo": {}, "dia": {}, "sem_preco": 0}


def ler_trecho(caminho, reg, vistos, corte_utc, precos):
    """Lê do offset até a última linha completa e soma no registro do arquivo."""
    with open(caminho, "rb") as f:
        f.seek(reg["offset"])
        bruto = f.read()
    fim = bruto.rfind(b"\n")
    if fim < 0:
        return
    reg["offset"] += fim + 1
    for linha in bruto[:fim].split(b"\n"):
        if b'"usage"' not in linha:
            continue
        try:
            d = json.loads(linha.decode("utf-8", "ignore"))
        except Exception:
            continue
        msg = d.get("message") or {}
        u = msg.get("usage") if isinstance(msg, dict) else None
        ts = d.get("timestamp")
        if not u or not ts:
            continue
        try:
            t = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            continue
        if t < corte_utc:
            continue
        chave = msg.get("id") or d.get("uuid")
        if chave in vistos:
            continue
        vistos.add(chave)
        reg["ids"].append(chave)
        m, p = casar_preco(msg.get("model", "?"), precos)
        if not p:
            reg["sem_preco"] += 1
            continue
        v = [u.get("input_tokens", 0) * p[0] / 1e6, u.get("output_tokens", 0) * p[1] / 1e6,
             u.get("cache_read_input_tokens", 0) * p[2] / 1e6, u.get("cache_creation_input_tokens", 0) * p[3] / 1e6]
        s = sum(v)
        for i in range(4):
            reg["tipo"][i] += v[i]
        reg["total"] += s
        reg["modelo"][m] = reg["modelo"].get(m, 0.0) + s
        dia = t.astimezone(FUSO).strftime("%Y-%m-%d")
        reg["dia"][dia] = reg["dia"].get(dia, 0.0) + s


def atualizar(cache, ini_brt, precos):
    corte_utc = ini_brt.astimezone(datetime.timezone.utc)
    corte_ts = corte_utc.timestamp()
    arquivos = cache["arquivos"]
    atuais = {}
    if PROJETOS.exists():
        for f in PROJETOS.rglob("*.jsonl"):
            try:
                st = f.stat()
            except OSError:
                continue
            if st.st_mtime >= corte_ts:
                atuais[str(f)] = (f, st)
    # arquivo apagado ou encolhido: tira a contribuição dele
    for caminho in list(arquivos):
        reg = arquivos[caminho]
        st = atuais.get(caminho, (None, None))[1]
        if st is None or st.st_size < reg["offset"]:
            del arquivos[caminho]
    vistos = set()
    for reg in arquivos.values():
        vistos.update(reg["ids"])
    for caminho, (f, st) in atuais.items():
        reg = arquivos.get(caminho)
        if reg is None:
            pasta = f.relative_to(PROJETOS).parts[0]
            reg = arquivos[caminho] = novo_registro(pasta)
        elif reg["mtime"] == st.st_mtime and reg["tamanho"] == st.st_size:
            continue
        ler_trecho(f, reg, vistos, corte_utc, precos)
        reg["mtime"], reg["tamanho"] = st.st_mtime, st.st_size


def fatia_de(pasta, fatias):
    for fa in fatias:
        if any(p in pasta for p in fa.get("pastas", [])):
            return fa["id"]
    return "outros"


def uso_api_semana(corte_utc):
    total = 0.0
    if not USO_API.exists():
        return total
    for linha in USO_API.read_text(errors="ignore").splitlines():
        try:
            d = json.loads(linha)
            t = datetime.datetime.fromisoformat(d["ts"].replace("Z", "+00:00"))
            if t.tzinfo is None:
                t = t.replace(tzinfo=FUSO)
            if t >= corte_utc:
                total += float(d.get("custo_usd", 0))
        except Exception:
            continue
    return total


def coletar():
    cfg = json.loads(CONFIG.read_text())
    precos = cfg["precos_por_milhao"]
    cap = float(cfg["semana"]["capacidade_usd"])
    fatias = cfg["fatias"]
    agora_brt = agora()
    ini = inicio_semana(agora_brt)
    assinatura = hashlib.sha1(json.dumps(precos, sort_keys=True).encode()).hexdigest()[:12]

    cache = ler_cache(ini.isoformat(), assinatura)
    atualizar(cache, ini, precos)
    try:
        gravar_cache(cache)
    except OSError:
        pass  # sem cache a conta continua certa, só fica mais lenta

    total, por_fatia, por_modelo, por_dia, sem_preco = 0.0, {}, {}, {}, 0
    for reg in cache["arquivos"].values():
        total += reg["total"]
        sem_preco += reg["sem_preco"]
        fid = fatia_de(reg["pasta"], fatias)
        por_fatia[fid] = por_fatia.get(fid, 0.0) + reg["total"]
        for m, v in reg["modelo"].items():
            por_modelo[m] = por_modelo.get(m, 0.0) + v
        for d, v in reg["dia"].items():
            por_dia[d] = por_dia.get(d, 0.0) + v

    horas = max((agora_brt - ini).total_seconds() / 3600, 1.0)
    fator = 168 / horas  # projeta o gasto atual pra semana inteira
    uso_pct = total / cap * 100
    ritmo_pct = uso_pct * fator
    calibrado = cfg["semana"].get("calibrado_em", "")

    estado_semana = "erro" if uso_pct >= 100 else "atencao" if uso_pct > 70 else "ok"
    itens = [
        {"id": "custos.semana", "rotulo": "Semana do plano",
         "valor": f"{pct(uso_pct)} estimado ({usd(total)} de ~{usd(cap)})", "estado": estado_semana},
        {"id": "custos.previsao", "rotulo": "Previsão até domingo", "valor": f"{pct(ritmo_pct)} do limite no ritmo atual",
         "estado": "ok" if ritmo_pct <= 85 else "atencao" if ritmo_pct <= 100 else "erro"},
    ]
    acima, fatias_out = [], []
    for fa in fatias:
        gasto = por_fatia.get(fa["id"], 0.0)
        g_pct = gasto / cap * 100
        r_pct = g_pct * fator
        alvo = float(fa["pct"])
        estado = "ok" if r_pct <= alvo else "atencao" if r_pct <= 1.2 * alvo else "erro"
        if estado == "erro":
            acima.append(fa["rotulo"])
        itens.append({"id": f"custos.fatia.{fa['id']}", "rotulo": fa["rotulo"],
                      "valor": f"{usd(gasto)} · {pct(g_pct)} (fatia {pct(alvo)}) · ritmo {pct(r_pct)}",
                      "estado": estado})
        fatias_out.append({"id": f"custos.fatia.{fa['id']}", "rotulo": fa["rotulo"],
                           "gasto_usd": round(gasto, 2), "fatia_usd": round(cap * alvo / 100, 2),
                           "pct_usado": round(g_pct, 1), "pct_fatia": round(alvo, 1), "estado": estado})

    fable = sum(v for m, v in por_modelo.items() if "fable" in m)
    itens.append({"id": "custos.fable", "rotulo": "Fable 5.1", "valor": f"{usd(fable)} na semana ({pct(fable / total * 100 if total else 0)} do gasto)",
                  "estado": "info"})

    nuvem = cfg.get("nuvem", {})
    aviso_nuvem = ""
    if nuvem:
        expira = datetime.datetime.fromisoformat(nuvem["expira"])
        faltam = (expira - agora_brt).total_seconds() / 86400
        if faltam <= 0:
            valor, estado = f"crédito venceu em {expira:%d/%m}", "erro"
        else:
            valor = f"{usd(float(nuvem['saldo_usd']))} de {usd(float(nuvem['total_usd']))}, vence {expira:%d/%m} (lido {nuvem.get('lido_em', '?')})"
            estado = "atencao" if faltam < 5 else "info"
            if faltam < 5:
                aviso_nuvem = f" O crédito da nuvem vence em {int(faltam) or 1} dia{'s' if int(faltam) > 1 else ''}."
        itens.append({"id": "custos.nuvem", "rotulo": "Nuvem", "valor": valor, "estado": estado})

    api = uso_api_semana(ini.astimezone(datetime.timezone.utc))
    itens.append({"id": "custos.api", "rotulo": "API do painel", "valor": f"{usd(api)} na semana", "estado": "info"})
    itens.append({"id": "custos.estimativa", "rotulo": "Estimativa", "valor": f"calibrada em {calibrado}", "estado": "info"})
    if sem_preco:
        itens.append({"id": "custos.sem-preco", "rotulo": "Sem preço", "valor": f"{sem_preco} respostas de modelo fora da tabela", "estado": "info"})

    lista = []
    for m, v in sorted(por_modelo.items(), key=lambda x: -x[1])[:5]:
        lista.append({"quando": "semana", "texto": f"{NOMES_MODELO.get(m, m)} · {usd(v)} ({pct(v / total * 100 if total else 0)})",
                      "estado": "info"})
    for d in sorted(por_dia, reverse=True)[:7]:
        dt = datetime.date.fromisoformat(d)
        lista.append({"quando": f"{DIAS[dt.weekday()]} {dt:%d/%m}", "texto": usd(por_dia[d]), "estado": "info"})

    resumo = f"Semana em {pct(uso_pct)} do limite, no ritmo de {pct(ritmo_pct)} até domingo."
    if len(acima) == 1:
        resumo += f" {acima[0]} está acima da fatia."
    elif acima:
        resumo += f" {', '.join(acima[:-1])} e {acima[-1]} estão acima da fatia."
    else:
        resumo += " Todos os projetos estão dentro da fatia."
    resumo += aviso_nuvem

    # número grande e frase do painel em abas (itens e lista seguem iguais)
    destaque = {"valor": pct(uso_pct), "rotulo": "da semana do plano", "estado": estado_semana}
    frase = f"Ritmo de {pct(ritmo_pct)} até domingo; "
    if len(acima) == 1:
        frase += f"{acima[0]} acima da fatia."
    elif acima:
        frase += f"{', '.join(acima[:-1])} e {acima[-1]} acima da fatia."
    else:
        frase += "todos dentro da fatia."
    if len(frase) > 90:
        frase = frase[:89].rstrip() + "…"

    dados = {"titulo": "Custos", "destaque": destaque, "frase": frase, "fatias": fatias_out,
             "itens": itens, "lista": lista[:15], "links": [],
             "semana_inicio": ini.strftime("%d/%m %H:%M"), "total_usd": round(total, 2)}
    return ok(dados, resumo)


if __name__ == "__main__":
    rodar(coletar)
