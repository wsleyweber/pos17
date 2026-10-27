#!/usr/bin/env python3
"""
Coletor de logs de urna do TSE (2o turno) -> SQLite com um resumo por secao.

Uso:
  python coletor_tse.py --ufs ac rr        # apenas estas UFs
  python coletor_tse.py --todas            # todas as UFs (sem exterior)
  python coletor_tse.py --calibrar caminho/log.jez    # mostra os tipos de linha do log

Retoma de onde parou (secoes ja gravadas com status ok/sem_log sao puladas).
"""
import argparse
import asyncio
import collections
import io
import json
import re
import sqlite3
import sys
import time
import zipfile
from pathlib import Path

# ----------------------------------------------------------------------------
# CONFIGURACAO (confira com URLs reais; foram montadas a partir da descricao)
# ----------------------------------------------------------------------------
PLEITO = "p003221"
URL_CS = "{base}/config/{uf}/{uf}-{pleito}-cs.json"
URL_AUX = "{base}/dados/{uf}/{mun}/{zona}/{secao}/{pleito}-{uf}-m{mun}-z{zona}-s{secao}-aux.json"
URL_LOG = "{base}/dados/{uf}/{mun}/{zona}/{secao}/{hash}/{arquivo}"

UFS = ["ac", "al", "am", "ap", "ba", "ce", "df", "es", "go", "ma", "mg", "ms",
       "mt", "pa", "pb", "pe", "pi", "pr", "rj", "rn", "ro", "rr", "rs", "sc",
       "se", "sp", "to"]  # sem "zz" (exterior)

# Padroes das linhas do logd.dat (conferidos com um log real do 2o turno via --calibrar).
RE_TS = re.compile(r"^(\d{2}/\d{2}/\d{4})\s+(\d{2}):(\d{2}):(\d{2})")
RE_TIPO = re.compile(r"Tipo de habilita\w+ do eleitor \[([^\]]+)\]", re.I)  # ex.: [biométrica]
RE_VOTO = re.compile(r"O voto do eleitor foi computado", re.I)  # voto concluido

# Fuso dos logs: o horario gravado na urna e LOCAL. Diferenca (em horas) para Brasilia.
# O corte (--corte, em horario de Brasilia) e convertido para o horario local da UF.
# Obs.: AM tem municipios no fuso -2 (oeste) e PA/PE/MG etc. seguem Brasilia; Fernando de
# Noronha (PE) e +1 -- casos pontuais nao tratados aqui.
OFFSET_UF = {"ac": -2, "am": -1, "mt": -1, "ms": -1, "ro": -1, "rr": -1}

# Para nao inflar o banco, so guardamos o histograma a partir deste horario LOCAL
# (cobre cortes de 15:00 a 18:00 locais, ou seja, fusos de -2 a +1 em relacao a Brasilia).
# O corte final por municipio e calculado em resumo.py a partir disso.
HIST_DESDE = "1400"

BUCKET_MIN = 10  # histograma em baldes de 10 min (17:00 cai na borda de um balde)


# ----------------------------------------------------------------------------
# Parser do log
# ----------------------------------------------------------------------------
def eh_biometrica(tipo: str) -> bool:
    return tipo.strip().lower().startswith("biom")


def parse_log(texto: str, dia: str, corte_min: int) -> dict:
    """dia no formato DD/MM/AAAA; corte_min = minutos desde 00:00 (17h = 1020).
    O tipo de habilitacao e lido da linha 'Tipo de habilitação do eleitor [..]' que
    antecede 'O voto do eleitor foi computado'."""
    tipo = None
    tipo_ausente = 0
    votos = []  # (minuto_do_dia, sem_bio)
    for linha in texto.splitlines():
        m = RE_TS.match(linha)
        if not m:
            continue
        data, h, mi = m.group(1), int(m.group(2)), int(m.group(3))
        msg = linha[m.end():]
        mt = RE_TIPO.search(msg)
        if mt:
            tipo = mt.group(1)
        elif RE_VOTO.search(msg):
            if data == dia:
                if tipo is None:
                    tipo_ausente += 1
                votos.append((h * 60 + mi, tipo is None or not eh_biometrica(tipo)))
            tipo = None

    antes = [v for v in votos if v[0] < corte_min]
    apos = [v for v in votos if v[0] >= corte_min]
    hist = collections.defaultdict(lambda: [0, 0])
    for minuto, sem_bio in votos:
        b = minuto // BUCKET_MIN * BUCKET_MIN
        k = "%02d%02d" % (b // 60, b % 60)
        if k < HIST_DESDE:
            continue
        hist[k][0] += 1
        hist[k][1] += int(sem_bio)
    return {
        "votos": len(votos),
        "votos_antes": len(antes),
        "votos_apos": len(apos),
        "sem_bio": sum(v[1] for v in votos),
        "sem_bio_antes": sum(v[1] for v in antes),
        "sem_bio_apos": sum(v[1] for v in apos),
        "tipo_ausente": tipo_ausente,
        "primeiro": min((v[0] for v in votos), default=None),
        "ultimo": max((v[0] for v in votos), default=None),
        "hist": json.dumps(hist, separators=(",", ":")),
    }


def extrair_logd(conteudo_jez: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(conteudo_jez)) as z:
        nome = next(n for n in z.namelist() if n.lower().endswith("logd.dat"))
        return z.read(nome).decode("latin-1")


def calibrar(caminho: str):
    p = Path(caminho)
    texto = extrair_logd(p.read_bytes()) if p.suffix.lower() in (".jez", ".zip") \
        else p.read_text(encoding="latin-1")
    cont = collections.Counter()
    for linha in texto.splitlines():
        m = RE_TS.match(linha)
        if not m:
            continue
        msg = re.sub(r"\b[0-9A-Fa-f]{16,}\b", "<hash>", linha[m.end():].strip())
        cont[re.sub(r"\d+", "#", msg)[:140]] += 1
    print("Tipos de linha mais frequentes (digitos -> #):")
    for msg, n in cont.most_common(60):
        print("%7d  %s" % (n, msg))
    print("\nProcure as linhas de: biometria reconhecida, eleitor habilitado,")
    print("habilitacao manual e voto computado, e ajuste os RE_* no topo do script.")


# ----------------------------------------------------------------------------
# Leitura dos JSON do TSE
# ----------------------------------------------------------------------------
def listar_secoes(cs: dict, uf: str):
    """Estrutura esperada: abr[].mu[].zon[].sec[] com 'cd'/'ns'. Confira com um cs.json real."""
    out = []
    try:
        for abr in cs["abr"]:
            for mu in abr["mu"]:
                for zon in mu["zon"]:
                    for sec in zon["sec"]:
                        out.append((uf, str(mu["cd"]).zfill(5),
                                    str(zon["cd"]).zfill(4), str(sec["ns"]).zfill(4)))
    except (KeyError, TypeError) as e:
        raise SystemExit("Estrutura inesperada no cs.json de %s (%r). "
                         "Abra o arquivo e ajuste listar_secoes()." % (uf, e))
    return out


def achar_log(aux):
    """Retorna (hash, nome_do_log). Formato real: hashes[].arq[] = {"nm":..., "tp":"log"}.
    Se houver mais de um hash (reenvio/substituicao), usa o mais recente da lista."""
    achados = []
    for h in aux.get("hashes", []):
        for a in h.get("arq", []):
            if isinstance(a, dict):
                nm, tp = a.get("nm", ""), a.get("tp")
            else:
                nm, tp = str(a), None
            if tp == "log" or nm.endswith("-log.jez"):
                achados.append((h.get("hash"), nm))
    return achados[-1] if achados else (None, None)


# ----------------------------------------------------------------------------
# Banco
# ----------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS secoes(
  uf TEXT, mun TEXT, zona TEXT, secao TEXT,
  status TEXT, hash TEXT,
  votos INT, votos_antes INT, votos_apos INT,
  sem_bio INT, sem_bio_antes INT, sem_bio_apos INT,
  primeiro INT, ultimo INT, tipo_ausente INT, hist TEXT, erro TEXT,
  PRIMARY KEY(uf, mun, zona, secao));
CREATE TABLE IF NOT EXISTS meta(uf TEXT PRIMARY KEY, total_secoes INT);
"""
COLS = ["uf", "mun", "zona", "secao", "status", "hash", "votos", "votos_antes",
        "votos_apos", "sem_bio", "sem_bio_antes", "sem_bio_apos", "primeiro",
        "ultimo", "tipo_ausente", "hist", "erro"]


def gravar(db, linhas):
    db.executemany("INSERT OR REPLACE INTO secoes(%s) VALUES(%s)" %
                   (",".join(COLS), ",".join("?" * len(COLS))),
                   [[l.get(c) for c in COLS] for l in linhas])
    db.commit()


# ----------------------------------------------------------------------------
# Download
# ----------------------------------------------------------------------------
async def baixar(client, url, tentativas=5):
    ultimo = None
    for i in range(tentativas):
        try:
            r = await client.get(url, timeout=40)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.content
        except Exception as e:  # noqa: BLE001
            ultimo = e
            await asyncio.sleep(2 ** i)
    raise ultimo


async def processar_secao(client, args, chave, raw_dir):
    uf, mun, zona, secao = chave
    base = dict(base=args.base, uf=uf, mun=mun, zona=zona, secao=secao, pleito=PLEITO)
    res = dict(uf=uf, mun=mun, zona=zona, secao=secao)
    try:
        aux_b = await baixar(client, URL_AUX.format(**base))
        if aux_b is None:
            return {**res, "status": "sem_log", "erro": "aux 404"}
        h, arq = achar_log(json.loads(aux_b))
        if not h:
            return {**res, "status": "sem_log", "erro": "aux sem hash/log"}
        jez = await baixar(client, URL_LOG.format(hash=h, arquivo=arq, **base))
        if jez is None:
            return {**res, "status": "sem_log", "hash": h, "erro": "log 404"}
        if raw_dir:
            (raw_dir / arq).write_bytes(jez)
        texto = await asyncio.to_thread(extrair_logd, jez)
        corte_local = args.corte_min + 60 * OFFSET_UF.get(uf, 0)
        dados = await asyncio.to_thread(parse_log, texto, args.data, corte_local)
        return {**res, "status": "ok", "hash": h, **dados}
    except Exception as e:  # noqa: BLE001
        return {**res, "status": "erro", "erro": repr(e)[:300]}


async def main_async(args):
    import httpx
    db = sqlite3.connect(args.db)
    db.executescript(SCHEMA)
    raw_dir = Path(args.guardar_jez) if args.guardar_jez else None
    if raw_dir:
        raw_dir.mkdir(parents=True, exist_ok=True)

    ufs = UFS if args.todas else [u.lower() for u in args.ufs]
    limites = httpx.Limits(max_connections=args.conc, max_keepalive_connections=args.conc)
    async with httpx.AsyncClient(limits=limites, headers={"User-Agent": "analise-logs-urna/1.0"}) as client:
        for uf in ufs:
            cs_b = await baixar(client, URL_CS.format(base=args.base, uf=uf, pleito=PLEITO))
            if cs_b is None:
                print("[%s] cs.json nao encontrado, pulando" % uf)
                continue
            secoes = listar_secoes(json.loads(cs_b), uf)
            db.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (uf, len(secoes)))
            db.commit()
            ok_status = ("ok",) if args.refazer_sem_log else ("ok", "sem_log")
            feitas = {tuple(r) for r in db.execute(
                "SELECT uf,mun,zona,secao FROM secoes WHERE uf=? AND status IN(%s)" %
                ",".join("?" * len(ok_status)), (uf,) + ok_status)}
            pendentes = [s for s in secoes if s not in feitas]
            print("[%s] %d secoes, %d pendentes" % (uf, len(secoes), len(pendentes)))

            fila = asyncio.Queue()
            for s in pendentes:
                fila.put_nowait(s)
            buf, t0, n = [], time.time(), 0

            async def worker():
                nonlocal n
                while True:
                    try:
                        s = fila.get_nowait()
                    except asyncio.QueueEmpty:
                        return
                    buf.append(await processar_secao(client, args, s, raw_dir))
                    n += 1
                    if args.pausa:
                        await asyncio.sleep(args.pausa)

            async def descarregar():
                while any(not t.done() for t in tarefas):
                    await asyncio.sleep(5)
                    if buf:
                        lote = buf[:]
                        del buf[:len(lote)]
                        gravar(db, lote)
                    print("  [%s] %d/%d  %.1f secoes/s" % (uf, n, len(pendentes),
                                                          n / max(time.time() - t0, 1)))

            tarefas = [asyncio.create_task(worker()) for _ in range(args.conc)]
            await asyncio.gather(descarregar(), *tarefas)
            if buf:
                gravar(db, buf)
    db.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="https://resultados.tse.jus.br/oficial/ele2026/arquivo-urna/3221",
                    help="prefixo ate a pasta 3221, sem barra final")
    ap.add_argument("--ufs", nargs="*", default=[])
    ap.add_argument("--todas", action="store_true")
    ap.add_argument("--db", default="logs_urna.sqlite")
    ap.add_argument("--data", default="25/10/2026", help="dia da votacao DD/MM/AAAA")
    ap.add_argument("--corte", default="17:00", help="horario de corte HH:MM")
    ap.add_argument("--conc", type=int, default=20, help="downloads simultaneos")
    ap.add_argument("--pausa", type=float, default=0.0, help="espera (s) entre secoes por worker")
    ap.add_argument("--refazer-sem-log", action="store_true",
                    help="tenta de novo as secoes marcadas sem_log (aux/log 404 em coleta anterior)")
    ap.add_argument("--guardar-jez", help="(opcional, desligado por padrao) pasta para guardar os .jez originais")
    ap.add_argument("--calibrar", help="arquivo .jez ou logd.dat para inspecionar os tipos de linha")
    args = ap.parse_args()

    if args.calibrar:
        return calibrar(args.calibrar)
    if not (args.ufs or args.todas):
        ap.error("informe --base e --ufs/--todas (ou use --calibrar)")
    h, m = args.corte.split(":")
    args.corte_min = int(h) * 60 + int(m)
    asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())