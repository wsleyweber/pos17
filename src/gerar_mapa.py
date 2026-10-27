#!/usr/bin/env python3
"""
Gera o mapa dos votos após as 17 horas (Brasília), por UF a partir do resumo.py.

Entradas (na mesma pasta ou via argumentos):
  resumo_uf.csv, resumo_geral.json   (saidas do resumo.py)
  brasil_ufs.json                    (malha simplificada dos estados, ja incluida)

Saidas (pasta docs/, a que o GitHub Pages publica):
  docs/index.html   mapa interativo, arquivo unico, sem dependencias externas
  docs/mapa.svg     imagem estatica para o README (sem JavaScript)

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
# HTML interativo
# ----------------------------------------------------------------------------
HTML = r"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITULO__</title>
<meta name="description" content="Mapa interativo dos votos computados após as 17 horas (Brasília) por UF, a partir dos logs de urna do TSE.">
<style>
:root{
  --bg:#f4f6f9; --card:#fff; --ink:#16212e; --mut:#5a6878; --line:#dde3ea; --sem:#b9c1cc;
  --c0:__C0L__; --c1:__C1L__; --stroke:#fff; --acc:#0b4f9c; --focus:#0b4f9c;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#0f1b2d; --card:#1a2c46; --ink:#e9f0f8; --mut:#a5b6cb; --line:#2c4263; --sem:#4a5668;
    --c0:__C0D__; --c1:__C1D__; --stroke:#0f1b2d; --acc:#8fd0ff; --focus:#8fd0ff;
  }
}
:root[data-theme="dark"]{
  --bg:#0f1b2d; --card:#1a2c46; --ink:#e9f0f8; --mut:#a5b6cb; --line:#2c4263; --sem:#4a5668;
  --c0:__C0D__; --c1:__C1D__; --stroke:#0f1b2d; --acc:#8fd0ff; --focus:#8fd0ff;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.45 -apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:20px 16px 40px}
h1{font-size:1.35rem;margin:0 0 4px}
.sub{color:var(--mut);margin:0 0 16px;font-size:.92rem}
.tiles{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:16px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.tile .k{color:var(--mut);font-size:.85rem}
.tile .v{font-size:2rem;font-weight:700;line-height:1.15;margin:2px 0}
.tile .d{color:var(--mut);font-size:.82rem}
.seg{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:12px}
.seg button{font:inherit;font-size:.88rem;padding:7px 12px;border-radius:999px;border:1px solid var(--line);background:var(--card);color:var(--ink);cursor:pointer}
.seg button[aria-pressed="true"]{background:var(--acc);border-color:var(--acc);color:var(--bg);font-weight:600}
.seg button:focus-visible,.row:focus-visible,path:focus-visible{outline:3px solid var(--focus);outline-offset:2px}
.grid{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(0,1fr);gap:16px;align-items:start}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px}
svg.mapa{width:100%;height:auto;display:block}
svg.mapa path{stroke:var(--stroke);stroke-width:1.2;stroke-linejoin:round;cursor:pointer;transition:opacity .12s}
svg.mapa.dim path{opacity:.45}
svg.mapa.dim path.on{opacity:1;stroke:var(--ink);stroke-width:2.2}
svg.mapa text{font-size:12px;font-weight:600;pointer-events:none}
.legenda{display:flex;align-items:center;gap:10px;margin:8px 4px 2px;font-size:.82rem;color:var(--mut)}
.legenda .bar{flex:1;max-width:260px;height:12px;border-radius:3px;background:linear-gradient(90deg,var(--c0),var(--c1))}
.legenda .sem{display:inline-flex;align-items:center;gap:6px;margin-left:auto}
.legenda .sem i{width:12px;height:12px;border-radius:3px;background:var(--sem);display:inline-block}
.det{min-height:150px;margin-bottom:12px}
.det h2{font-size:1.05rem;margin:0 0 8px}
.det dl{display:grid;grid-template-columns:1fr auto;gap:4px 12px;margin:0;font-size:.92rem}
.det dt{color:var(--mut)} .det dd{margin:0;text-align:right;font-variant-numeric:tabular-nums;font-weight:600}
.det .vazio{color:var(--mut);font-size:.92rem}
.lista{max-height:430px;overflow:auto}
.row{display:grid;grid-template-columns:26px 34px 1fr auto;gap:8px;align-items:center;padding:6px 8px;border-radius:8px;cursor:pointer;font-size:.92rem}
.row:hover,.row.on{background:color-mix(in srgb,var(--acc) 14%,transparent)}
.row .n{color:var(--mut);font-size:.8rem;text-align:right}
.row .b{height:8px;border-radius:4px;background:var(--line);position:relative;overflow:hidden}
.row .b i{position:absolute;left:0;top:0;bottom:0;background:var(--acc);border-radius:4px}
.row .vv{font-variant-numeric:tabular-nums;font-weight:600;min-width:72px;text-align:right}
.nota{color:var(--mut);font-size:.8rem;margin-top:16px}
.aviso{background:color-mix(in srgb,var(--acc) 14%,transparent);border-left:4px solid var(--acc);border-radius:8px;padding:9px 12px;margin:0 0 12px;font-size:.88rem}
@media (max-width:860px){.grid{grid-template-columns:1fr}.tiles{grid-template-columns:1fr}.tile .v{font-size:1.7rem}}
</style>
</head>
<body>
<div class="wrap">
  <h1>__TITULO__</h1>
  <p class="sub" id="sub"></p>
  <div class="tiles" id="tiles"></div>
  <div class="seg" id="seg" role="group" aria-label="Métrica exibida no mapa"></div>
  <p class="aviso" id="aviso" hidden></p>
  <div class="grid">
    <div class="card">
      <svg class="mapa" id="mapa" viewBox="0 0 __W__ __H__" role="img" aria-label="Mapa do Brasil por UF"></svg>
      <div class="legenda"><span id="lo"></span><div class="bar"></div><span id="hi"></span><span class="sem"><i></i>sem dados / sem voto após</span></div>
    </div>
    <div>
      <div class="card det" id="det" aria-live="polite"></div>
      <div class="card lista" id="lista"></div>
    </div>
  </div>
  <p class="nota" id="nota"></p>
</div>
<script>
const D = __DATA__;
const $ = s => document.querySelector(s);
const NS = "http://www.w3.org/2000/svg";
const fmt = (v, t) => v == null ? "—" :
  t === "int" ? Math.round(v).toLocaleString("pt-BR") :
  t === "min" ? "+" + Math.round(v) + " min" :
  v.toLocaleString("pt-BR", {minimumFractionDigits: t === "pct3" ? 3 : 1, maximumFractionDigits: t === "pct3" ? 3 : 1}) + "%";
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const rgb = h => [1,3,5].map(i => parseInt(h.slice(i, i+2), 16));
const mix = (a, b, t) => { const A = rgb(a), B = rgb(b); return "rgb(" + A.map((x, i) => Math.round(x + (B[i]-x)*t)).join(",") + ")"; };

const txt = (u, v) => (metrica.txt && u.m[metrica.txt]) ? u.m[metrica.txt] + " " + u.rel : fmt(v, metrica.t);
const AVISO_LOCAL = "Horários no relógio local de cada estado. A ordem e a cor mostram os minutos após o fechamento, que são comparáveis entre estados.";
let metrica = D.metricas[0], ativo = null, fixo = null;
const porUF = Object.fromEntries(D.ufs.map(u => [u.uf, u]));

function dominio() {
  const v = D.ufs.map(u => u.m[metrica.k]).filter(x => x != null);
  return v.length ? [Math.min(...v), Math.max(...v)] : [0, 1];
}
function corDe(v, lo, hi) {
  if (v == null) return css("--sem");
  const t = hi === lo ? .5 : (v - lo) / (hi - lo);
  return mix(css("--c0"), css("--c1"), Math.max(0, Math.min(1, t)));
}

function montar() {
  $("#sub").textContent = D.meta.subtitulo;
  const g = D.geral;
  const tiles = [
    ["Número de votos", fmt(g.votos_apos, "int"), fmt(g.pct_votos_apos, "pct3") + " dos " + fmt(g.votos_total, "int") + " votos analisados"],
    ["Votos nos primeiros 10 minutos ", fmt(g.pct_primeiros_10min, "pct1"), g.votos_primeiros_10min == null ? "" : fmt(g.votos_primeiros_10min, "int") + " de " + fmt(g.votos_apos_h, "int") + " votos"],
    ["Último voto mais tardio", g.mais_tardio ? g.mais_tardio.hora : "—", g.mais_tardio ? g.mais_tardio.uf + " · Horário local (" + porUF[g.mais_tardio.uf].rel + ") · " + fmt(g.mais_tardio.min, "min") + " após o fechamento" : ""]
  ];
  $("#tiles").innerHTML = tiles.map(t => '<div class="tile"><div class="k">' + t[0] + '</div><div class="v">' + t[1] + '</div><div class="d">' + t[2] + '</div></div>').join("");
  $("#seg").innerHTML = "";
  D.metricas.forEach(m => {
    const b = document.createElement("button");
    b.textContent = m.curto; b.title = m.rotulo;
    b.setAttribute("aria-pressed", m === metrica);
    b.onclick = () => { metrica = m; pintar(); };
    $("#seg").appendChild(b);
  });
  const svg = $("#mapa");
  svg.innerHTML = "";
  D.ufs.forEach(u => {
    const p = document.createElementNS(NS, "path");
    p.setAttribute("d", u.d); p.dataset.uf = u.uf;
    p.setAttribute("tabindex", "0"); p.setAttribute("role", "button");
    p.addEventListener("mouseenter", () => { ativo = u.uf; detalhe(); });
    p.addEventListener("mouseleave", () => { ativo = null; detalhe(); });
    p.addEventListener("focus", () => { ativo = u.uf; detalhe(); });
    p.addEventListener("blur", () => { ativo = null; detalhe(); });
    p.addEventListener("click", () => { fixo = fixo === u.uf ? null : u.uf; detalhe(); });
    p.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); p.click(); } });
    svg.appendChild(p);
  });
  D.ufs.forEach(u => {
    if (u.larg < 26) return;
    const t = document.createElementNS(NS, "text");
    t.setAttribute("x", u.cx); t.setAttribute("y", u.cy + 4); t.setAttribute("text-anchor", "middle");
    t.textContent = u.uf; t.dataset.uf = u.uf; svg.appendChild(t);
  });
  $("#nota").textContent = D.meta.nota;
  pintar();
}

function pintar() {
  const [lo, hi] = dominio();
  [...$("#seg").children].forEach((b, i) => b.setAttribute("aria-pressed", D.metricas[i] === metrica));
  const av = $("#aviso"); av.hidden = metrica.k !== "ultimo_min_apos"; av.textContent = AVISO_LOCAL;
  document.querySelectorAll("#mapa path").forEach(p => {
    const v = porUF[p.dataset.uf].m[metrica.k];
    p.setAttribute("fill", corDe(v, lo, hi));
    p.setAttribute("aria-label", porUF[p.dataset.uf].nome + ": " + txt(porUF[p.dataset.uf], v));
  });
  document.querySelectorAll("#mapa text").forEach(t => {
    const v = porUF[t.dataset.uf].m[metrica.k];
    t.setAttribute("fill", luminancia(corDe(v, lo, hi)) > .45 ? "#0b1f38" : "#f1f6fb");
  });
  $("#lo").textContent = fmt(lo, metrica.t); $("#hi").textContent = fmt(hi, metrica.t);
  lista(); detalhe();
}
function luminancia(c) {
  const m = c.match(/\d+/g); if (!m) return .5;
  const [r, g, b] = m.map(Number); return (0.299*r + 0.587*g + 0.114*b) / 255;
}

function lista() {
  const [lo, hi] = dominio();
  const ord = [...D.ufs].sort((a, b) => (b.m[metrica.k] ?? -Infinity) - (a.m[metrica.k] ?? -Infinity));
  $("#lista").innerHTML = "";
  ord.forEach((u, i) => {
    const v = u.m[metrica.k];
    const r = document.createElement("div");
    r.className = "row"; r.dataset.uf = u.uf; r.tabIndex = 0;
    const w = v == null ? 0 : (hi === lo ? 100 : 8 + 92 * (v - lo) / (hi - lo));
    r.innerHTML = '<span class="n">' + (i + 1) + '</span><strong>' + u.uf + '</strong><span class="b"><i style="width:' + w + '%"></i></span><span class="vv">' + txt(u, v) + '</span>';
    r.onmouseenter = () => { ativo = u.uf; detalhe(); };
    r.onmouseleave = () => { ativo = null; detalhe(); };
    r.onfocus = r.onmouseenter; r.onblur = r.onmouseleave;
    r.onclick = () => { fixo = fixo === u.uf ? null : u.uf; detalhe(); };
    r.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); r.click(); } };
    $("#lista").appendChild(r);
  });
}

function detalhe() {
  const uf = ativo || fixo;
  document.querySelectorAll("#mapa path, .row").forEach(el => el.classList.toggle("on", el.dataset.uf === uf));
  $("#mapa").classList.toggle("dim", !!uf);
  const el = $("#det");
  if (!uf) { el.innerHTML = '<div class="vazio">Passe o mouse (ou toque) em um estado para ver os detalhes.</div>'; return; }
  const u = porUF[uf], m = u.m;
  const cob = m.secoes_total ? " (" + fmt(100 * m.secoes_analisadas / m.secoes_total, "pct1") + ")" : "";
  const ap = "após as " + u.corte;
  el.innerHTML = '<h2>' + u.nome + ' (' + u.uf + ')</h2><dl>' +
    '<dt>Votos ' + ap + '</dt><dd>' + fmt(m.votos_apos, "int") + '</dd>' +
    '<dt>Porcentagem dos votos ' + ap + '</dt><dd>' + fmt(m.pct_votos_apos, "pct3") + '</dd>' +
    '<dt>Nos primeiros 10 minutos ' + ap + '</dt><dd>' + fmt(m.pct_primeiros_10min, "pct1") + (m.votos_primeiros_10min != null ? " (" + fmt(m.votos_primeiros_10min, "int") + ")" : "") + '</dd>' +
    '<dt>Último voto no estado (no horário local)</dt><dd>' + (m.ultimo_voto ? m.ultimo_voto + " (" + fmt(m.ultimo_min_apos, "min") + ")" : "—") + '</dd>' +
    '<dt> </dt> <dd> </dd>' +
    '<dt> </dt> <dd> </dd>' +
    '<dt> </dt> <dd> </dd>' +
    '<dt>Votos totais analisados</dt><dd>' + fmt(m.votos, "int") + '</dd>' +
    '<dt>Seções analisadas</dt><dd>' + fmt(m.secoes_analisadas, "int") + (m.secoes_total ? " de " + fmt(m.secoes_total, "int") : "") + cob + '</dd>' +
    '<dt>Seções com voto ' + ap + '</dt><dd>' + fmt(m.secoes_com_voto_apos, "int") + '</dd></dl>';
}

montar();
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", pintar);
</script>
</body>
</html>
"""


def gerar_html(malha, dados, geral, titulo, subtitulo, nota):
    ufs = []
    for m in malha:
        h, nome = FUSO_ROTULO.get(m["uf"], ("17h", "Brasília"))
        ufs.append({**m, "corte": "%s (%s)" % (h, nome), "rel": nome, "m": dados.get(m["uf"], {})})
    payload = {
        "meta": {"subtitulo": subtitulo, "nota": nota},
        "geral": geral,
        "metricas": [{"k": k, "rotulo": r, "curto": c, "t": t, "txt": x} for k, r, c, t, x in METRICAS],
        "ufs": ufs,
    }
    s = HTML
    for a, b in {"__TITULO__": html.escape(titulo), "__W__": str(W), "__H__": str(H),
                 "__C0L__": ESCALA_CLARA[0], "__C1L__": ESCALA_CLARA[1],
                 "__C0D__": ESCALA_ESCURA[0], "__C1D__": ESCALA_ESCURA[1]}.items():
        s = s.replace(a, b)
    # "</" dentro de <script> poderia encerrar o bloco antes da hora
    dados_js = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return s.replace("__DATA__", dados_js)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="resumo_uf.csv")
    ap.add_argument("--geral", default="resumo_geral.json")
    ap.add_argument("--horarios", default="horarios_uf.csv", help="saida do horarios.py")
    ap.add_argument("--malha", default=str(AQUI / "brasil_ufs.json"))
    ap.add_argument("--saida", default="docs")
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
    sub = "Apenas Brasil, sem exterior" + (" · " + cob if cob else "") + " · dados preliminares · os dados trabalhadores são referentes apenas aos votos computados após as 17 horas no horário de Brasília"
    nota = ("Fonte: arquivos de log de urna publicados pelo TSE (dados preliminares). Corte: 17h de Brasília, que é 15h no Acre e 16h em "
            "AM, RO, RR, MT e MS, no horário local registrado pela própria urna (o oeste do Amazonas e Fernando de Noronha têm o corte ajustado ao fuso do município). Votos depois desse horário são esperados: quem já está na fila "
            "pode votar e, segundo a imprensa, uma decisão do STF em 25/10 permitiu que seções ainda abertas funcionassem até as 19h (Brasília). "
            "O mapa mostra volume e horário, não em quem os votos foram dados, e não indica irregularidade.")

    out = Path(a.saida)
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(gerar_html(malha, dados, geral, a.titulo, sub, nota), encoding="utf-8")
    (out / "mapa.svg").write_text(gerar_svg(malha, dados, geral, a.titulo, a.fonte), encoding="utf-8")
    print("gerado:", out / "index.html", "e", out / "mapa.svg")


if __name__ == "__main__":
    main()