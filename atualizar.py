#!/usr/bin/env python3
"""Recalcula os resumos e regera o mapa a partir do banco local.

Uso (na raiz do repositorio):  python atualizar.py [--db logs_urna.sqlite]
Depois:  git add dados docs web/public && git commit -m "Atualiza dados" && git push
"""
import argparse
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=str(RAIZ / "logs_urna.sqlite"))
ap.add_argument("--titulo", default="Votos após as 17 horas (Brasília) · 2º turno 2026")
a = ap.parse_args()
db = Path(a.db).resolve()
if not db.exists():
    sys.exit("banco nao encontrado: %s (rode antes o coletor)" % db)


def rodar(args, cwd):
    subprocess.run([sys.executable] + [str(x) for x in args], cwd=cwd, check=True)


dados = RAIZ / "dados"
dados.mkdir(exist_ok=True)
rodar([RAIZ / "src" / "resumo.py", db, "--corte-local"], dados)
rodar([RAIZ / "src" / "horarios.py", db, "--corte-local"], dados)
rodar([RAIZ / "src" / "gerar_mapa.py",
       "--csv", "dados/resumo_uf.csv", "--geral", "dados/resumo_geral.json",
       "--horarios", "dados/horarios_uf.csv", "--saida", "docs", "--titulo", a.titulo], RAIZ)
print("\nPronto. Para conferir o site: cd web && npm run dev")
