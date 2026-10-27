import "./style.css";

// Os dados são gerados pelo Python (src/gerar_mapa.py) e ficam em public/dados.json.
let D;
try {
  const r = await fetch(import.meta.env.BASE_URL + "dados.json");
  if (!r.ok) throw new Error("HTTP " + r.status);
  D = await r.json();
} catch (e) {
  document.querySelector("#sub").textContent = "Não foi possível carregar os dados (dados.json).";
  throw e;
}
if (D.meta.titulo) {
  document.title = D.meta.titulo;
  document.querySelector("h1").textContent = D.meta.titulo;
}
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
