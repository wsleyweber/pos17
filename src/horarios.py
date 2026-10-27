#!/usr/bin/env python3
"""Horario do ultimo voto e distribuicao dos votos apos o corte, por UF.

Usa apenas o que o coletor ja gravou (colunas ultimo e hist). Nao baixa nada.
Saidas: horarios_uf.csv e impressao na tela.
Uso: python horarios.py [logs_urna.sqlite] [--corte 17:00] [--corte-local]
"""
import csv
import json
import sqlite3
import sys
from collections import defaultdict

from fuso import FUSO_UF, fuso_de, fusos_municipios

args = [a for a in sys.argv[1:] if not a.startswith("--")]
corte = "17:00"
if "--corte" in sys.argv:
    corte = sys.argv[sys.argv.index("--corte") + 1]
h, m = corte.split(":")
corte_padrao = int(h) * 60 + int(m)
if corte_padrao % 10:
    sys.exit("o corte precisa ser multiplo de 10 minutos (o hist usa faixas de 10 min)")
# --corte-local: fechamento local (17h de Brasilia): AC 15h; AM/RO/RR/MT/MS 16h; demais 17h.
# Os horarios saem no relogio padrao da UF; secoes de municipios com outro fuso (oeste do AM,
# Noronha) tem os horarios deslocados para esse relogio (ver fuso.py).
CORTE_LOCAL = {"ac": 15 * 60, "am": 16 * 60, "ro": 16 * 60, "rr": 16 * 60, "mt": 16 * 60, "ms": 16 * 60}
local = "--corte-local" in sys.argv

db = sqlite3.connect(args[0] if args else "logs_urna.sqlite")
fusos = fusos_municipios(db)[0] if local else {}
hhmm = lambda mi: "%02d:%02d" % (mi // 60, mi % 60)


def pctl(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * len(xs)))] if xs else None


por_uf = defaultdict(lambda: {"faixas": defaultdict(int), "ultimos": [], "total": 0, "secoes": 0})
for uf, mun, ultimo, hist in db.execute("SELECT uf, mun, ultimo, hist FROM secoes WHERE status='ok'"):
    corte_min = CORTE_LOCAL.get(uf, corte_padrao) if local else corte_padrao
    # desloca o relogio da secao para o relogio padrao da UF
    desloc = 60 * (FUSO_UF.get(uf, 0) - fuso_de(fusos, uf, mun)) if local else 0
    ultimo = ultimo + desloc if ultimo is not None else ultimo
    d = por_uf[uf]
    d["corte"] = corte_min
    apos = {}
    for faixa, (n, _) in json.loads(hist).items():
        ini = int(faixa[:2]) * 60 + int(faixa[2:]) + desloc
        if ini >= corte_min:
            apos[ini] = n
    if not apos:
        continue
    d["secoes"] += 1
    d["total"] += sum(apos.values())
    d["ultimos"].append(ultimo)
    for ini, n in apos.items():
        d["faixas"][ini] += n

linhas = []
for uf, d in sorted(por_uf.items()):
    t = d["total"]
    corte_min = d["corte"]
    if not t:
        continue
    acum, mediana_min = 0, None
    for ini in sorted(d["faixas"]):
        acum += d["faixas"][ini]
        if mediana_min is None and acum >= t / 2:
            mediana_min = ini + 10   # fim da faixa em que se atinge 50%
    prim = d["faixas"].get(corte_min, 0)
    linhas.append({
        "uf": uf.upper(),
        "corte": hhmm(corte_min),
        "votos_apos": t,
        "secoes_com_voto_apos": d["secoes"],
        "ultimo_voto_max": hhmm(max(d["ultimos"])),
        "ultimo_voto_p99_secoes": hhmm(pctl(d["ultimos"], 0.99)),
        "ultimo_voto_mediana_secoes": hhmm(pctl(d["ultimos"], 0.5)),
        "pct_nos_primeiros_10min": round(100 * prim / t, 1) if t else None,
        "pct_nos_primeiros_30min": round(100 * sum(d["faixas"].get(corte_min + k, 0) for k in (0, 10, 20)) / t, 1) if t else None,
        "metade_dos_votos_ate": hhmm(mediana_min) if mediana_min else None,
        "ultimo_min_apos": max(d["ultimos"]) - corte_min,
        "votos_primeiros_10min": prim,
        "votos_primeiros_30min": sum(d["faixas"].get(corte_min + k, 0) for k in (0, 10, 20)),
    })

if not linhas:
    sys.exit("nenhuma secao com voto apos o corte no banco")
with open("horarios_uf.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(linhas[0]))
    w.writeheader()
    w.writerows(linhas)
cols = list(linhas[0])
print("  ".join(c[:14].ljust(14) for c in cols))
for r in linhas:
    print("  ".join(str(r[c]).ljust(14) for c in cols))
