#!/usr/bin/env python3
"""
Gera o mapa dos votos após as 17 horas (Brasília), por UF a partir do resumo.py.

Entradas (na mesma pasta ou via argumentos):
  resumo_uf.csv, resumo_geral.json   (saidas do resumo.py)
  brasil_ufs.json                    (malha simplificada dos estados, ja incluida)

Saidas:
  web/public/dados.json   dados que o site (Vite, pasta web/) carrega
  docs/mapa.svg           imagem estatica para o README (sem JavaScript)

Uso:
  python gerar_mapa.py
  python gerar_mapa.py --csv resumo_uf.csv --geral resumo_geral.json --saida docs \
      --titulo "Votos após as 17 horas (Brasília) · 2º turno 2026"
"""
import argparse
import csv
import html
import json
import math
from pathlib import Path

AQUI = Path(__file__).resolve().parent
W, H = 760, 760  # area do mapa (viewBox)

METRICAS = [
    # chave (valor numerico), rotulo, rotulo curto, formato, chave do texto exibido (ou None)
    ("votos_apos", "Votos após o fechamento da votação (17 horas de Brasília; no relógio local, 15 horas no Acre e 16 horas em AM, RO, RR, MT e MS)", "Número de votos", "int", None),
    ("pct_votos_apos", "Porcentagem dos votos após o fechamento da votação (17 horas de Brasília; no relógio local de cada estado)", "Porcentagem de votos", "pct3", None),
    # cor = minutos entre o fechamento e o ultimo voto; texto = horario do ultimo voto no RELOGIO LOCAL do estado
    ("ultimo_min_apos", "Horário do último voto no estado, no relógio LOCAL de cada estado (cor: minutos após o fechamento)", "Último voto", "min", "ultimo_voto"),
    ("pct_primeiros_10min", "Porcentagem dos votos após as 17 horas (Brasília) dados nos primeiros 10 minutos", "Porcentagem de votos nos primeiros 10 minutos", "pct1", None),
]
# Fechamento = 17h de Brasilia, no relogio de cada UF: (hora do fechamento, nome do fuso).
# Fuso do Acre = UTC-5; "horario do Amazonas" = UTC-4 (AM, RO, RR, MT, MS); demais = Brasilia.
FUSO_ROTULO = {"AC": ("15h", "Acre"), "AM": ("16h", "Amazonas"), "RO": ("16h", "Amazonas"),
               "RR": ("16h", "Amazonas"), "MT": ("16h", "Amazonas"), "MS": ("16h", "Amazonas")}
ESCALA_CLARA = ("#dbe9f7", "#0b4f9c")   # tema claro: maior = mais escuro
ESCALA_ESCURA = ("#2a4a6e", "#8fd0ff")  # tema escuro: maior = mais claro


# ----------------------------------------------------------------------------
# Geometria
# ----------------------------------------------------------------------------
def projetar(ufs):
    xs = [p[0] for u in ufs for r in u["aneis"] for p in r]
    ys = [p[1] for u in ufs for r in u["aneis"] for p in r]
    lat0 = (min(ys) + max(ys)) / 2
    k = math.cos(math.radians(lat0))
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    esc = min((W - 20) / ((x1 - x0) * k), (H - 20) / (y1 - y0))
    ox = (W - (x1 - x0) * k * esc) / 2
    oy = (H - (y1 - y0) * esc) / 2
    return lambda lon, lat: (ox + (lon - x0) * k * esc, oy + (y1 - lat) * esc)


def centroide(anel):
    a = cx = cy = 0.0
    for i in range(len(anel)):
        x1, y1 = anel[i]
        x2, y2 = anel[(i + 1) % len(anel)]
        c = x1 * y2 - x2 * y1
        a += c
        cx += (x1 + x2) * c
        cy += (y1 + y2) * c
    if abs(a) < 1e-9:
        return anel[0]
    return cx / (3 * a), cy / (3 * a)


def area(anel):
    return abs(sum(anel[i][0] * anel[(i + 1) % len(anel)][1] - anel[(i + 1) % len(anel)][0] * anel[i][1]
                   for i in range(len(anel)))) / 2


def preparar_malha(caminho):
    ufs = json.loads(Path(caminho).read_text(encoding="utf-8"))
    proj = projetar(ufs)
    out = []
    for u in ufs:
        d, maior = [], None
        for r in u["aneis"]:
            pts = [proj(x, y) for x, y in r]
            d.append("M" + "L".join("%.1f,%.1f" % p for p in pts) + "Z")
            if maior is None or area(pts) > area(maior):
                maior = pts
        cx, cy = centroide(maior)
        xs = [p[0] for p in maior]
        out.append({"uf": u["uf"], "nome": u["nome"], "d": "".join(d),
                    "cx": round(cx, 1), "cy": round(cy, 1), "larg": round(max(xs) - min(xs), 1)})
    return out


# ----------------------------------------------------------------------------
# Dados
# ----------------------------------------------------------------------------
def num(v):
    if v in (None, "", "None"):
        return None
    return float(v)


def ler_dados(csv_path, geral_path):
    linhas = {}
    with open(csv_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            linhas[r["uf"].upper()] = {k: num(v) for k, v in r.items() if k != "uf"}
    geral = json.loads(Path(geral_path).read_text(encoding="utf-8")) if Path(geral_path).exists() else {}
    return linhas, geral


def ler_horarios(caminho, dados):
    """Junta horarios_uf.csv (saida do horarios.py) aos dados por UF. Retorna o resumo nacional."""
    p = Path(caminho)
    if not p.exists():
        print("aviso: %s nao encontrado; metricas de horario ficam sem dados" % caminho)
        return {}
    tot10 = totapos = 0
    mais_tardio = None
    with open(p, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            uf = r["uf"].upper()
            d = dados.setdefault(uf, {})
            d["ultimo_voto"] = r["ultimo_voto_max"]
            d["ultimo_voto_p99"] = r["ultimo_voto_p99_secoes"]
            d["ultimo_min_apos"] = num(r["ultimo_min_apos"])
            d["pct_primeiros_10min"] = num(r["pct_nos_primeiros_10min"])
            d["votos_primeiros_10min"] = num(r["votos_primeiros_10min"])
            d["metade_ate"] = r["metade_dos_votos_ate"]
            d["fechamento_h"] = r["corte"]
            tot10 += num(r["votos_primeiros_10min"]) or 0
            totapos += num(r["votos_apos"]) or 0
            if d["ultimo_min_apos"] is not None and (mais_tardio is None or d["ultimo_min_apos"] > mais_tardio[1]):
                mais_tardio = (uf, d["ultimo_min_apos"], d["ultimo_voto"])
    return {
        "pct_primeiros_10min": 100.0 * tot10 / totapos if totapos else None,
        "votos_primeiros_10min": tot10,
        "votos_apos_h": totapos,
        "mais_tardio": {"uf": mais_tardio[0], "min": mais_tardio[1], "hora": mais_tardio[2]} if mais_tardio else None,
    }


def fmt(v, tipo):
    if v is None:
        return "—"
    if tipo == "int":
        return f"{v:,.0f}".replace(",", ".")
    if tipo == "min":
        return "+%d min" % round(v)
    casas = 3 if tipo == "pct3" else 1
    return f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".") + "%"


def hex_rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def mistura(c0, c1, t):
    a, b = hex_rgb(c0), hex_rgb(c1)
    return "#%02x%02x%02x" % tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def cor(v, lo, hi, escala):
    if v is None:
        return "#5b6573"
    t = 0.5 if hi == lo else (v - lo) / (hi - lo)
    return mistura(escala[0], escala[1], max(0, min(1, t)))


# ----------------------------------------------------------------------------
# SVG estatico (README)
# ----------------------------------------------------------------------------
def gerar_svg(malha, dados, geral, titulo, rodape):
    chave, _, _, tipo, _ = METRICAS[0]
    vals = [d.get(chave) for d in dados.values() if d.get(chave) is not None]
    lo, hi = (min(vals), max(vals)) if vals else (0, 1)
    SW, SH = 1200, 640
    esc = 0.72
    ox, oy = 30, 28
    p = []
    p.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SW} {SH}" width="{SW}" height="{SH}" '
             f'role="img" aria-label="{html.escape(titulo)}" font-family="-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif">')
    p.append(f'<rect width="{SW}" height="{SH}" rx="16" fill="#1e3a5f"/>')
    p.append(f'<text x="{SW - 40}" y="56" text-anchor="end" fill="#e9f0f8" font-size="26">{html.escape(titulo)}</text>')
    # cartoes
    cartoes = [
        ("Número de votos", fmt(geral.get("votos_apos"), "int"),
         f'{fmt(geral.get("pct_votos_apos"), "pct3")} dos {fmt(geral.get("votos_total"), "int")} votos analisados'),
        ("Votos nos primeiros 10 minutos", fmt(geral.get("pct_primeiros_10min"), "pct1"),
         f'{fmt(geral.get("votos_primeiros_10min"), "int")} de {fmt(geral.get("votos_apos_h"), "int")} votos'),
        ("Último voto mais tardio", (geral.get("mais_tardio") or {}).get("hora", "—"),
         ("%s · Horário local (%s) · %s após o fechamento" % (geral["mais_tardio"]["uf"], FUSO_ROTULO.get(geral["mais_tardio"]["uf"], ("", "Brasília"))[1], fmt(geral["mais_tardio"]["min"], "min")))
         if geral.get("mais_tardio") else ""),
    ]
    x = 640
    for i, (a, b, c) in enumerate(cartoes):
        y = 84 + i * 112
        p.append(f'<rect x="{x}" y="{y}" width="520" height="100" rx="12" fill="#2f4a6e"/>')
        p.append(f'<text x="{x + 20}" y="{y + 28}" fill="#c9d6e6" font-size="18">{html.escape(a)}</text>')
        p.append(f'<text x="{x + 20}" y="{y + 70}" fill="#fff" font-size="42" font-weight="700">{html.escape(b)}</text>')
        p.append(f'<text x="{x + 20}" y="{y + 90}" fill="#c9d6e6" font-size="15">{html.escape(c)}</text>')
    # top 5
    rank = sorted(((d.get(chave), u) for u, d in dados.items() if d.get(chave) is not None), reverse=True)[:5]
    p.append(f'<text x="640" y="440" fill="#c9d6e6" font-size="16">Estados com mais votos após as 17 horas (Brasília)</text>')
    for i, (v, u) in enumerate(rank):
        y = 470 + i * 28
        p.append(f'<text x="640" y="{y}" fill="#fff" font-size="19">{u}</text>')
        p.append(f'<text x="1160" y="{y}" fill="#fff" font-size="19" text-anchor="end">{fmt(v, tipo)}</text>')
        p.append(f'<line x1="640" x2="1160" y1="{y + 9}" y2="{y + 9}" stroke="#3d5a80"/>')
    # mapa
    p.append(f'<g transform="translate({ox},{oy}) scale({esc})">')
    for m in malha:
        v = dados.get(m["uf"], {}).get(chave)
        p.append(f'<path d="{m["d"]}" fill="{cor(v, lo, hi, ESCALA_ESCURA)}" stroke="#1e3a5f" stroke-width="1.2" stroke-linejoin="round"/>')
    for m in malha:
        if m["larg"] < 26:
            continue
        v = dados.get(m["uf"], {}).get(chave)
        t = 0.5 if (v is None or hi == lo) else (v - lo) / (hi - lo)
        fill = "#0b1f38" if t > 0.45 else "#e9f0f8"
        p.append(f'<text x="{m["cx"]}" y="{m["cy"] + 4}" text-anchor="middle" font-size="12" font-weight="600" fill="{fill}">{m["uf"]}</text>')
    p.append('</g>')
    # legenda
    p.append('<defs><linearGradient id="g"><stop offset="0" stop-color="%s"/><stop offset="1" stop-color="%s"/></linearGradient></defs>' % ESCALA_ESCURA)
    p.append(f'<rect x="40" y="{SH - 62}" width="260" height="12" rx="3" fill="url(#g)"/>')
    p.append(f'<text x="40" y="{SH - 36}" fill="#c9d6e6" font-size="14">{fmt(lo, tipo)}</text>')
    p.append(f'<text x="300" y="{SH - 36}" fill="#c9d6e6" font-size="14" text-anchor="end">{fmt(hi, tipo)}</text>')
    p.append(f'<text x="40" y="{SH - 72}" fill="#c9d6e6" font-size="14">Votos após as 17 horas (Brasília), por UF</text>')
    p.append(f'<text x="{SW - 40}" y="{SH - 20}" fill="#9fb3cb" font-size="14" text-anchor="end">{html.escape(rodape)}</text>')
    p.append('</svg>')
    return "\n".join(p)


# ----------------------------------------------------------------------------
# Dados para o site (web/)
# ----------------------------------------------------------------------------


def gerar_dados(malha, dados, geral, titulo, subtitulo, nota):
    """Monta o JSON lido pelo site em web/ (web/src/main.js)."""
    ufs = []
    for m in malha:
        h, nome = FUSO_ROTULO.get(m["uf"], ("17h", "Brasília"))
        ufs.append({**m, "corte": "%s (%s)" % (h, nome), "rel": nome, "m": dados.get(m["uf"], {})})
    return {
        "meta": {"titulo": titulo, "subtitulo": subtitulo, "nota": nota},
        "geral": geral,
        "metricas": [{"k": k, "rotulo": r, "curto": c, "t": t, "txt": x} for k, r, c, t, x in METRICAS],
        "ufs": ufs,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="resumo_uf.csv")
    ap.add_argument("--geral", default="resumo_geral.json")
    ap.add_argument("--horarios", default="horarios_uf.csv", help="saida do horarios.py")
    ap.add_argument("--malha", default=str(AQUI / "brasil_ufs.json"))
    ap.add_argument("--saida", default="docs", help="pasta do mapa.svg (usado no README)")
    ap.add_argument("--json", default="web/public/dados.json", help="dados lidos pelo site")
    ap.add_argument("--titulo", default="Votos após as 17 horas (Brasília) · 2º turno 2026")
    ap.add_argument("--fonte", default="Fonte: logs de urna do TSE · dados preliminares")
    a = ap.parse_args()

    malha = preparar_malha(a.malha)
    dados, geral = ler_dados(a.csv, a.geral)
    geral.update(ler_horarios(a.horarios, dados))
    desconhecidas = sorted(set(dados) - {m["uf"] for m in malha})
    if desconhecidas:
        print("aviso: UFs do CSV sem desenho no mapa (ignoradas):", desconhecidas)

    sa, sg = geral.get("secoes_analisadas"), geral.get("secoes_total")
    cob = f"{sa:,.0f} de {sg:,.0f} seções analisadas".replace(",", ".") if sa and sg else ""
    sub = "Apenas Brasil, sem exterior" + (" · " + cob if cob else "") + " · dados preliminares · contagem apenas dos votos computados após as 17 horas (Brasília)"
    nota = ("Fonte: arquivos de log de urna publicados pelo TSE (dados preliminares). Corte: 17h de Brasília, que é 15h no Acre e 16h em "
            "AM, RO, RR, MT e MS, no horário local registrado pela própria urna (o oeste do Amazonas e Fernando de Noronha têm o corte ajustado ao fuso do município). Votos depois desse horário são esperados: quem já está na fila "
            "pode votar e, segundo a imprensa, uma decisão do STF em 25/10 permitiu que seções ainda abertas funcionassem até as 19h (Brasília). "
            "O mapa mostra volume e horário, não em quem os votos foram dados, e não indica irregularidade.")

    out = Path(a.saida)
    out.mkdir(parents=True, exist_ok=True)
    (out / "mapa.svg").write_text(gerar_svg(malha, dados, geral, a.titulo, a.fonte), encoding="utf-8")
    dest = Path(a.json)
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = gerar_dados(malha, dados, geral, a.titulo, sub, nota)
    dest.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("gerado:", out / "mapa.svg", "e", dest)


if __name__ == "__main__":
    main()