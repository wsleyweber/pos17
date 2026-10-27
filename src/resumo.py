#!/usr/bin/env python3
"""Agrega logs_urna.sqlite nas metricas do painel: geral + tabela por UF.

Saidas: resumo_geral.json e resumo_uf.csv (valores numericos; formate depois na imagem).

Uso:
  python resumo.py [logs_urna.sqlite]                 # corte unico de 17:00 em todas as UFs
  python resumo.py [logs_urna.sqlite] --corte-local   # fechamento local (17h de Brasilia) POR MUNICIPIO:
                                                      # fuso deduzido dos logs (ver fuso.py); AC 15h; AM/RO/RR/MT/MS 16h
                                                      # (oeste do AM 15h); Noronha 18h; demais 17h

Totais (votos, sem biometria) vem das colunas votos/sem_bio da secao, que sao completas. O hist
so guarda as faixas a partir das 14:00 locais e serve apenas para somar o que veio apos o corte.

Use --corte-local se o relogio gravado nos logs for o horario LOCAL da urna (confira com
as consultas do final deste arquivo). O recalculo usa o histograma por faixas de 10 min
gravado pelo coletor, entao NAO precisa baixar os logs de novo.
"""
import csv
import json
import sqlite3
import sys
from collections import defaultdict

from fuso import FUSO_UF, fuso_de, fusos_municipios

CORTE_PADRAO = 17 * 60

args = [a for a in sys.argv[1:] if not a.startswith("--")]
local = "--corte-local" in sys.argv
db = sqlite3.connect(args[0] if args else "logs_urna.sqlite")


fusos, divergentes, sem_base = fusos_municipios(db) if local else ({}, [], 0)


def corte_da(uf, mun):
    """Minutos (relogio local do municipio) em que fecha a votacao = 17h de Brasilia."""
    return CORTE_PADRAO + 60 * fuso_de(fusos, uf, mun) if local else CORTE_PADRAO


def pct(a, b):
    return (100.0 * a / b) if b else None


acc = defaultdict(lambda: defaultdict(int))
for uf, mun, votos_s, sb_s, hist in db.execute(
        "SELECT uf, mun, votos, sem_bio, hist FROM secoes WHERE status='ok'"):
    c = corte_da(uf, mun)
    a = acc[uf]
    a["secoes_analisadas"] += 1
    va = sa = 0
    for faixa, (n, sb) in json.loads(hist).items():
        if int(faixa[:2]) * 60 + int(faixa[2:]) >= c:
            va += n
            sa += sb
    a["votos"] += votos_s or 0
    a["sem_bio"] += sb_s or 0
    a["votos_apos"] += va
    a["sem_bio_apos"] += sa
    a["votos_antes"] += (votos_s or 0) - va
    a["sem_bio_antes"] += (sb_s or 0) - sa
    a["secoes_com_voto_apos"] += 1 if va else 0

totais = dict(db.execute("SELECT uf, total_secoes FROM meta"))
por_uf = []
for uf, a in acc.items():
    por_uf.append({
        "uf": uf.upper(),
        "pct_votos_apos": pct(a["votos_apos"], a["votos"]),
        "votos_apos": a["votos_apos"],
        "pct_sem_bio_apos": pct(a["sem_bio_apos"], a["votos_apos"]),
        "pct_sem_bio_antes": pct(a["sem_bio_antes"], a["votos_antes"]),
        "votos": a["votos"],
        "secoes_analisadas": a["secoes_analisadas"],
        "secoes_total": totais.get(uf),
        "secoes_com_voto_apos": a["secoes_com_voto_apos"],
    })
por_uf.sort(key=lambda x: -(x["pct_votos_apos"] or 0))


def soma(k):
    return sum(a[k] for a in acc.values())


votos, votos_antes, votos_apos = soma("votos"), soma("votos_antes"), soma("votos_apos")
sb_antes, sb_apos = soma("sem_bio_antes"), soma("sem_bio_apos")
analisadas = soma("secoes_analisadas")
total = sum(totais.get(uf) or 0 for uf in acc)

geral = {
    "criterio_corte": "fechamento local por UF" if local else "17:00 do relogio do log, todas as UFs",
    "votos_total": votos,
    "votos_apos": votos_apos,
    "pct_votos_apos": pct(votos_apos, votos),
    "sem_bio_apos": sb_apos,
    "pct_sem_bio_apos": pct(sb_apos, votos_apos),
    "sem_bio_antes": sb_antes,
    "votos_antes": votos_antes,
    "pct_sem_bio_antes": pct(sb_antes, votos_antes),
    "secoes_analisadas": analisadas,
    "secoes_total": total,
    "pct_secoes_analisadas": pct(analisadas, total),
    "secoes_com_voto_apos": soma("secoes_com_voto_apos"),
    "secoes_sem_log_ou_erro": db.execute(
        "SELECT COUNT(*) FROM secoes WHERE status != 'ok'").fetchone()[0],
}

with open("resumo_geral.json", "w", encoding="utf-8") as f:
    json.dump(geral, f, ensure_ascii=False, indent=2)
if por_uf:
    with open("resumo_uf.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(por_uf[0].keys()))
        w.writeheader()
        w.writerows(por_uf)
if local:
    with open("fusos_inferidos.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["uf", "mun", "secoes", "mediana_primeiro_voto_min", "fuso_padrao_uf", "fuso_deduzido"])
        w.writerows(divergentes)
    print("fuso por municipio: %d divergem do padrao da UF (ver fusos_inferidos.csv); "
          "%d municipios com menos de 3 secoes usaram o padrao da UF" % (len(divergentes), sem_base))
print(json.dumps(geral, ensure_ascii=False, indent=2))

# ----------------------------------------------------------------------------
# COMO SABER SE O RELOGIO DO LOG E LOCAL OU DE BRASILIA
# A votacao abre as 8h de Brasilia. Se o relogio for LOCAL, o primeiro voto mais comum
# sera ~6h no AC e ~7h em AM/RO/RR/MT/MS; se for de Brasilia, ~8h em todos. Rode:
#
#   sqlite3 logs_urna.sqlite "SELECT uf, primeiro/60 AS hora, COUNT(*) AS secoes
#     FROM secoes WHERE status='ok' AND primeiro IS NOT NULL
#     AND uf IN ('ac','am','rr','sp') GROUP BY uf, hora ORDER BY uf, secoes DESC;"
#
# Veja tambem, no AC, a hora mais comum do ultimo voto (deve ser ~15h se local, ~17h se Brasilia).
# ----------------------------------------------------------------------------
