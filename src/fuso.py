"""Fuso horario por municipio, deduzido dos proprios logs.

O horario gravado no log e o relogio LOCAL da urna. A votacao abre as 08:00 de Brasilia, entao a
mediana do primeiro voto das secoes de um municipio mostra o fuso dele (07:0x => -1, 06:0x => -2,
09:0x => +1). Isso pega o oeste do AM (-2) e Fernando de Noronha (+1) sem lista manual.
Municipios com menos de MIN_SECOES secoes (com log) usam o fuso padrao da UF.
"""
import statistics
from collections import defaultdict

# Fuso padrao por UF (horas em relacao a Brasilia). UFs ausentes = 0.
FUSO_UF = {"ac": -2, "am": -1, "mt": -1, "ms": -1, "ro": -1, "rr": -1}
ABERTURA_MIN = 8 * 60
MIN_SECOES = 3


def fusos_municipios(db, min_secoes=MIN_SECOES):
    """Retorna ({(uf, mun): fuso}, divergentes, n_municipios_sem_base).
    divergentes = municipios cujo fuso deduzido difere do padrao da UF."""
    primeiros = defaultdict(list)
    for uf, mun, p in db.execute(
            "SELECT uf, mun, primeiro FROM secoes WHERE status='ok' AND primeiro IS NOT NULL"):
        primeiros[(uf, mun)].append(p)
    fusos, divergentes, sem_base = {}, [], 0
    for (uf, mun), lst in primeiros.items():
        padrao = FUSO_UF.get(uf, 0)
        fusos[(uf, mun)] = padrao
        if len(lst) < min_secoes:
            sem_base += 1
            continue
        med = statistics.median(lst)
        inf = round((med - ABERTURA_MIN) / 60)
        if -3 <= inf <= 1:
            fusos[(uf, mun)] = inf
            if inf != padrao:
                divergentes.append((uf.upper(), mun, len(lst), med, padrao, inf))
    return fusos, sorted(divergentes), sem_base


def fuso_de(fusos, uf, mun):
    return fusos.get((uf, mun), FUSO_UF.get(uf, 0))
