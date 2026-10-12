/* Modo documental (vídeo narrado 16:9): palco com câmera (mapa de época ou imagem), beats
   sincronizados à fala, transições ligadas (mergulho/recuo/corte), vinheta e tela final.
   Carregado depois do kit.js quando o cenas.json traz "modo": "doc".
   Tudo que depende do tempo é pintor (KIT.pintor), nunca onUpdate. */
(() => {
  "use strict";
  const V = document.documentElement.dataset.aspecto === "9:16";   // __KIT_DADOS ainda não existe aqui (carrega depois)
  const W = V ? 1080 : 1920, H = V ? 1920 : 1080, DERIVA = 0.006, SAIDA = 0.35;
  const easeIO = gsap.parseEase("power2.inOut");
  const easeOut = gsap.parseEase("power3.out");
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
  const fmt = new Intl.NumberFormat("pt-BR");
  const el = (tag, cls, txt) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (txt != null) e.textContent = txt;
    return e;
  };
  const svg = (tag, attrs) => {
    const e = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  };
  const texto = (e) => { e.dataset.kTexto = ""; return e; };
  // imagem do palco/inserto; ajuste "contain" (retrato, jornal, panorama): inteira sobre cópia desfocada dela mesma
  const foto = (cls, arq, ajuste) => {
    const m = el("div", cls);
    if (ajuste !== "contain") { m.style.backgroundImage = `url("${arq}")`; return m; }
    for (const [tam, filtro] of [["cover", "blur(40px) brightness(.45)"], ["contain", "none"]]) {
      const f = el("div", "d-foto");
      Object.assign(f.style, { backgroundImage: `url("${arq}")`, backgroundSize: tam, filter: filtro,
                               transform: tam === "cover" ? "scale(1.1)" : "none" });
      m.appendChild(f);
    }
    return m;
  };

  const CSS = `
.d-palco{position:absolute;inset:0;overflow:hidden;transform-origin:50% 50%}
.d-cam{position:absolute;left:0;top:0;transform-origin:0 0}
.d-img{position:absolute;inset:0;background-size:cover;background-position:center;filter:sepia(.35) contrast(1.1) brightness(.8)}
.d-foto{position:absolute;inset:0;background-position:center;background-repeat:no-repeat}
.d-mapa{position:absolute;inset:0;background-size:100% 100%;filter:sepia(.45) saturate(.55) contrast(1.05) brightness(.62)}
.d-cam svg{position:absolute;left:0;top:0;overflow:visible}
.d-rota{fill:none;stroke:var(--k-acento);stroke-width:6;stroke-linecap:round}
.d-ping{fill:none;stroke:#C0392B;stroke-width:5}
.d-ponto{fill:#C0392B}
.d-hud{position:absolute;inset:0;pointer-events:none}
.d-hud>*{opacity:0}
.t{color:var(--k-sobre);text-shadow:0 2px 18px rgba(0,0,0,.9),0 0 4px rgba(0,0,0,.8)}
.d-chip{position:absolute;padding:10px 20px;background:rgba(11,10,8,.85);border-left:4px solid #C0392B;font:600 26px var(--k-corpo-familia);letter-spacing:.08em;white-space:nowrap;text-transform:uppercase}
.d-data{position:absolute;left:120px;top:90px}
.d-data .m{font:600 32px var(--k-corpo-familia);letter-spacing:.4em;color:var(--k-acento);text-transform:uppercase}
.d-data .m,.d-data .a{opacity:0}
.d-data .a{font:600 140px/1 var(--k-display-familia)}
.d-painel{position:absolute;right:120px;top:200px;width:560px;padding:32px 36px;background:rgba(11,10,8,.88);border-top:4px solid var(--k-acento)}
.d-painel .v{font:500 140px/1 var(--k-mono-familia)}
.d-painel .l{font:italic 400 38px var(--k-display-familia);color:#cdbf9f;margin:6px 0 20px}
.d-pontos{display:grid;grid-template-columns:repeat(25,16px);gap:5px}
.d-pontos i{width:16px;height:16px;border-radius:50%;background:var(--k-acento);opacity:.12}
.d-rotulo{position:absolute;left:120px;bottom:120px;padding-left:22px;border-left:4px solid var(--k-acento)}
.d-rotulo .n{font:600 56px var(--k-display-familia)}
.d-rotulo .p{font:600 24px var(--k-corpo-familia);letter-spacing:.2em;color:var(--k-acento);text-transform:uppercase;margin-top:6px}
.d-palavras{position:absolute;left:120px;right:120px;top:430px;text-align:center;font:800 110px var(--k-corpo-familia);text-transform:uppercase}
.d-palavras.c{right:700px}  /* cena com contador: fica à esquerda do painel (x>=1240) */
.d-palavras span{display:inline-block;margin:0 20px;position:relative;opacity:0}
.d-palavras.f{left:200px;right:200px;top:50%;transform:translateY(-55%);line-height:1.12}
.d-palavras.f.c{right:700px}
.d-palavras.f.a{top:22%;transform:none}  /* cena com ação: a vinheta ocupa o terço de baixo */
.d-palavras.f span{margin:0 12px}
.d-palavras.f span.hl{color:var(--k-acento)}
.d-risco{position:absolute;left:0;right:0;top:52%;height:12px;background:#C0392B;transform:scaleX(0);transform-origin:left}
.d-veu{position:absolute;inset:0;background:rgba(0,0,0,.55)}
.d-citacao{position:absolute;left:240px;right:240px;top:300px;text-align:center}
.d-citacao .q{font:italic 400 66px/1.25 var(--k-display-familia)}
.d-citacao .a{font:600 26px var(--k-corpo-familia);letter-spacing:.2em;color:var(--k-acento);text-transform:uppercase;margin-top:28px}
.d-lista{position:absolute;left:160px;top:220px;width:1100px}
.d-lista .i{font:500 48px var(--k-corpo-familia);padding:14px 0 14px 24px;box-shadow:inset 3px 0 0 var(--k-acento);margin-bottom:14px;background:rgba(11,10,8,.6);opacity:0}
.d-linha{position:absolute;left:160px;right:160px;top:640px;height:3px;background:var(--k-acento)}
.d-marco{position:absolute;top:-14px;width:30px;height:30px;margin-left:-15px;border-radius:50%;border:3px solid var(--k-acento);background:#0b0a08;opacity:0}
.d-marco .d{position:absolute;top:-76px;left:50%;transform:translateX(-50%);font:500 40px var(--k-mono-familia);white-space:nowrap}
.d-marco .x{position:absolute;top:44px;left:50%;transform:translateX(-50%);font:italic 400 30px var(--k-display-familia);color:#cdbf9f;white-space:nowrap}
.d-cursor{position:absolute;top:-10px;left:0;width:22px;height:22px;margin-left:-11px;border-radius:50%;background:#C0392B}
.d-inserto{position:absolute;inset:0;background-size:cover;background-position:center;filter:sepia(.3) contrast(1.1) brightness(.78);opacity:0}
.d-selo{position:absolute}
.d-fx{position:absolute;inset:0;pointer-events:none}
.d-vin{position:absolute;inset:0;background:radial-gradient(ellipse at center,rgba(0,0,0,0) 50%,rgba(0,0,0,.8) 100%)}
.d-flick{position:absolute;inset:0;background:#000;opacity:0}
.d-flash{position:absolute;inset:0;background:#fff6e0;opacity:0}
.d-papel{position:absolute;inset:0;background:radial-gradient(ellipse at 50% 45%,#3a3125 0%,#1d1912 60%,#0e0d0b 100%)}
.d-marca{position:absolute;left:200px;right:200px;top:690px;text-align:center;font:500 44px var(--k-mono-familia);letter-spacing:.5em;clip-path:inset(0 100% 0 0)}
.d-titulo{position:absolute;left:200px;right:200px;top:770px;text-align:center;font:italic 400 64px var(--k-display-familia);opacity:0}
.d-guia{position:absolute;border:2px solid rgba(184,134,43,.45);opacity:0}
.d-guia .g{position:absolute;left:0;right:0;bottom:-52px;text-align:center;font:600 22px var(--k-corpo-familia);letter-spacing:.2em;color:rgba(237,230,214,.6);text-transform:uppercase}
.d-prox{position:absolute;left:200px;right:200px;top:130px;text-align:center;font:italic 600 76px var(--k-display-familia);opacity:0}
.d-tag{position:absolute;left:200px;right:200px;bottom:110px;text-align:center;font:500 30px var(--k-corpo-familia);letter-spacing:.15em;color:#cdbf9f;opacity:0}
html[data-aspecto="9:16"] .d-data{left:80px;top:200px}
html[data-aspecto="9:16"] .d-data .a{font-size:130px}
html[data-aspecto="9:16"] .d-painel{left:80px;right:auto;top:470px;width:920px;padding:28px 32px}
html[data-aspecto="9:16"] .d-painel .v{font-size:120px}
html[data-aspecto="9:16"] .d-pontos{grid-template-columns:repeat(40,16px)}
html[data-aspecto="9:16"] .d-rotulo{left:80px;right:80px;bottom:300px}
html[data-aspecto="9:16"] .d-rotulo .n{font-size:50px;line-height:1.1;white-space:normal}
html[data-aspecto="9:16"] .d-rotulo .p{white-space:normal}
html[data-aspecto="9:16"] .d-palavras{left:80px;right:80px;top:760px;font-size:96px}
html[data-aspecto="9:16"] .d-palavras.c{right:80px;top:780px}
html[data-aspecto="9:16"] .d-palavras.f{left:80px;right:80px;top:50%}
html[data-aspecto="9:16"] .d-palavras.f.c{right:80px}
html[data-aspecto="9:16"] .d-palavras span{margin:0 14px}
html[data-aspecto="9:16"] .d-citacao{left:80px;right:80px;top:520px}
html[data-aspecto="9:16"] .d-citacao .q{font-size:54px}
html[data-aspecto="9:16"] .d-lista{left:80px;width:920px;top:470px}
html[data-aspecto="9:16"] .d-lista .i{font-size:44px}
html[data-aspecto="9:16"] .d-linha{left:120px;right:120px;top:900px}
html[data-aspecto="9:16"] .d-marco .d{font-size:34px}
html[data-aspecto="9:16"] .d-marco .x{font-size:26px}
html[data-aspecto="9:16"] .d-prox{left:80px;right:80px;top:860px;font-size:64px}
html[data-aspecto="9:16"] .d-cta{position:absolute;left:80px;right:80px;top:1060px;text-align:center;font:700 44px var(--k-punch-familia);letter-spacing:.12em;color:var(--k-acento);text-transform:uppercase;opacity:0}
html[data-aspecto="9:16"] .d-tag{left:80px;right:80px;bottom:300px}
.d-legenda{display:none}
html[data-aspecto="9:16"] .d-legenda{display:block;position:absolute;left:80px;right:80px;top:1250px;height:220px;text-align:center}
html[data-aspecto="9:16"] .d-legenda span{position:absolute;left:0;right:0;top:0;font:800 72px/1.1 var(--k-corpo-familia);text-transform:uppercase;opacity:0;overflow-wrap:anywhere}`;
  document.head.appendChild(el("style", null, CSS));

  // ---------- camada de clima (uma vez, dentro de #k-fixos, abaixo do grão do kit)
  let fx = null;
  function iniciarFx() {
    if (fx) return fx;
    const host = document.getElementById("k-fixos");
    const raiz = el("div", "d-fx"), flick = el("div", "d-flick"), flash = el("div", "d-flash");
    raiz.append(el("div", "d-vin"), flick, flash);
    host.prepend(raiz);
    KIT.pintor((t) => {
      const r = Math.sin(Math.floor(t * 12) * 12.9898) * 43758.5453;
      flick.style.opacity = ((r - Math.floor(r)) * 0.07).toFixed(3);
    });
    fx = { raiz, flash };
    return fx;
  }

  // ---------- câmera: movimentos (t, d, x, y, s) a partir de um estado inicial + deriva lenta
  function camAt(cam, t) {
    let cur = cam.ini, t0 = 0;
    for (const m of cam.ms) {
      if (t < m.t) break;
      const e = easeIO(Math.min(1, (t - m.t) / m.d));
      cur = { x: m.de.x + (m.x - m.de.x) * e, y: m.de.y + (m.y - m.de.y) * e, s: m.de.s + (m.s - m.de.s) * e };
      t0 = m.t + m.d;
    }
    return { x: cur.x, y: cur.y, s: cur.s * (1 + DERIVA * Math.max(0, t - Math.max(t0, cam.t0))) };
  }
  function construirCam(ini, moves, t0) {
    const cam = { ini, ms: [], t0 };
    for (const m of moves.slice().sort((a, b) => a.t - b.t)) cam.ms.push({ ...m, de: camAt(cam, m.t) });
    return cam;
  }

  // ---------- beats: (ctx, b, i) -> instante em que a entrada termina
  const SLOT = { data: "canto", contador: "painel", rotulo: "rotulo", palavras: "centro", citacao: "centro",
                 lista: "centro", linha_tempo: "centro", selo: "centro", legenda: "legenda" };
  const fora = (ctx, b) => {   // sai quando o próximo beat do mesmo slot entra, ou no fim da cena
    const prox = ctx.beats.filter((o) => o.at > b.at + 0.01 && SLOT[o.faz] && SLOT[o.faz] === SLOT[b.faz])
      .sort((x, y) => x.at - y.at)[0];
    return Math.min(prox ? prox.at - 0.1 : ctx.fim, ctx.fim) - SAIDA;
  };
  const sai = (ctx, e, b, minimo) => ctx.c.tl.to(e, { opacity: 0, duration: SAIDA }, Math.max(fora(ctx, b), minimo));
  const IN = (tl, e, t, de = { y: 20 }) =>
    tl.fromTo(e, { opacity: 0, ...de }, { opacity: 1, x: 0, y: 0, duration: 0.45, ease: "power3.out", immediateRender: false }, t);
  const mostra = (tl, e, t) => tl.fromTo(e, { opacity: 0 }, { opacity: 1, duration: 0.01, immediateRender: false }, t);

  function caminho(P) {
    if (P.length === 2) {
      const [[x1, y1], [x2, y2]] = P, mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
      return `M${x1} ${y1} Q${mx - (y2 - y1) * 0.2} ${my + (x2 - x1) * 0.2} ${x2} ${y2}`;
    }
    let d = `M${P[0][0]} ${P[0][1]}`;
    for (let i = 0; i < P.length - 1; i++) {
      const p0 = P[Math.max(0, i - 1)], p1 = P[i], p2 = P[i + 1], p3 = P[Math.min(P.length - 1, i + 2)];
      d += ` C${p1[0] + (p2[0] - p0[0]) / 6} ${p1[1] + (p2[1] - p0[1]) / 6}` +
           ` ${p2[0] - (p3[0] - p1[0]) / 6} ${p2[1] - (p3[1] - p1[1]) / 6} ${p2[0]} ${p2[1]}`;
    }
    return d;
  }

  function seloSvg(tam) {
    const s = svg("svg", { viewBox: "0 0 240 240", width: tam, height: tam });
    const a1 = svg("circle", { cx: 120, cy: 120, r: 112, fill: "none", stroke: "#8C2F1B", "stroke-width": 10 });
    const a2 = svg("circle", { cx: 120, cy: 120, r: 96, fill: "none", stroke: "#8C2F1B", "stroke-width": 3 });
    const k = svg("text", { x: 120, y: 162, "text-anchor": "middle", "font-family": "K Fraunces", "font-style": "italic",
                            "font-weight": 600, "font-size": 132, fill: "#cdbf9f" });
    k.textContent = "K";
    s.append(a1, a2, k);
    return { s, aneis: [a1, a2] };
  }

  const BEATS = {
    camera: (ctx, b) => b.at,

    ponto(ctx, b) {
      const [x, y] = ctx.pts[b.ponto], { tl } = ctx.c, r = 13 / ctx.base;
      const dot = svg("circle", { cx: x, cy: y, r, class: "d-ponto", opacity: 0 });
      const ping = svg("circle", { cx: x, cy: y, r, class: "d-ping", opacity: 0, "vector-effect": "non-scaling-stroke" });
      ctx.g.append(ping, dot);
      tl.fromTo(dot, { attr: { opacity: 0 } }, { attr: { opacity: 1 }, duration: 0.1, immediateRender: false }, b.at);
      for (const k of [0, 0.7])
        tl.fromTo(ping, { attr: { r, opacity: 1 } }, { attr: { r: r * 6, opacity: 0 }, duration: 0.9, ease: "power2.out",
                  immediateRender: false }, b.at + k);
      if (b.rotulo) {
        const chip = el("div", "d-chip t", b.rotulo);
        ctx.hud.appendChild(chip);
        ctx.ancoras.push([chip, x, y, -40, -70]);
        IN(tl, chip, b.at + 0.1, { x: -16 });
      }
      KIT.cue(b.at, "ping");
      return b.at + 0.6;
    },

    rota(ctx, b) {
      const P = [b.de, ...(b.via || []), b.para].map((n) => ctx.pts[n]);
      const path = svg("path", { d: caminho(P), class: "d-rota", "vector-effect": "non-scaling-stroke" });
      ctx.g.insertBefore(path, ctx.g.firstChild);
      const L = path.getTotalLength(), dur = b.dur || 2.0, t0 = b.at;
      path.setAttribute("stroke-dasharray", `0 ${L}`);
      const nav = b.navio ? svg("path", { d: "M-26 6 L26 6 L18 18 L-18 18 Z M-2 6 L-2 -30 L22 2 Z M-6 6 L-6 -22 L-24 2 Z",
                                          fill: "#EDE6D6", opacity: 0 }) : null;
      if (nav) ctx.g.appendChild(nav);
      let km = null;
      if (b.km) {
        km = el("div", "d-chip t");
        km.style.borderLeftColor = "var(--k-acento)";
        ctx.hud.appendChild(km);
        const meio = path.getPointAtLength(L / 2);
        ctx.ancoras.push([km, meio.x, meio.y, 30, -24]);
        IN(ctx.c.tl, km, t0, { x: 0 });
      }
      KIT.pintor((t) => {
        const p = easeIO(clamp((t - t0) / dur, 0, 1));
        path.setAttribute("stroke-dasharray", `${(p * L).toFixed(1)} ${L}`);
        path.setAttribute("opacity", t >= t0 ? 1 : 0);
        if (nav) {
          const q = path.getPointAtLength(p * L);
          nav.setAttribute("transform", `translate(${q.x},${q.y}) scale(${(1.4 / ctx.base).toFixed(3)})`);
          nav.setAttribute("opacity", t >= t0 && p < 1 ? 1 : 0);
        }
        if (km) km.textContent = `${fmt.format(Math.round(p * b.km))} km`;
      });
      KIT.cue(t0, "whoosh", -10);
      return t0 + 0.5;
    },

    contador(ctx, b) {
      const { tl } = ctx.c, pn = el("div", "d-painel t"), dur = 0.9;
      const v = texto(el("div", "v")), l = texto(el("div", "l", b.legenda || ""));
      pn.append(v, l);
      const dots = [];
      if (b.pontos) {
        const gr = el("div", "d-pontos");
        for (let i = 0; i < b.valor; i++) dots.push(gr.appendChild(el("i")));
        pn.appendChild(gr);
      }
      ctx.hud.appendChild(pn);
      // painel vai para a esquerda quando o ponto em foco cairia debaixo dele
      const ref = ctx.beats.filter((o) => o.at <= b.at && [o.ponto, o.para, o.de].some((n) => n && ctx.pts[n])).pop();
      const nome = ref && [ref.ponto, ref.para, ref.de].find((n) => n && ctx.pts[n]);
      const esq = nome && ctx.tela(...ctx.pts[nome], b.at + 0.5)[0] > W / 2;
      if (esq) Object.assign(pn.style, { left: "120px", right: "auto", top: "300px" });
      IN(tl, pn, b.at - 0.12, { x: esq ? -60 : 60 });
      sai(ctx, pn, b, b.at + dur);
      const pre = b.prefixo || "", suf = b.sufixo || "";
      KIT.pintor((t) => {
        const p = easeOut(clamp((t - b.at) / dur, 0, 1)), n = Math.round(dots.length * p);
        v.textContent = `${pre}${fmt.format(Math.round(b.valor * p))}${suf}`;
        dots.forEach((d, i) => { d.style.opacity = i < n ? "1" : ".12"; });
      });
      v.textContent = `${pre}${fmt.format(b.valor)}${suf}`;
      KIT.cue(b.at, "tique");
      return b.at + dur;
    },

    data(ctx, b) {
      const pal = String(b.t).trim().split(/\s+/), ano = pal.pop(), { tl } = ctx.c;
      const box = el("div", "d-data t"), m = texto(el("div", "m", pal.join(" "))), a = texto(el("div", "a", ano));
      box.append(m, a);
      ctx.hud.appendChild(box);
      mostra(tl, box, b.at);
      tl.fromTo(m, { opacity: 0, x: -30 }, { opacity: 1, x: 0, duration: 0.35, ease: "power3.out", immediateRender: false }, b.at);
      tl.fromTo(a, { opacity: 0, scale: 1.35, transformOrigin: "left center" },
                { opacity: 1, scale: 1, duration: 0.35, ease: "back.out(2)", immediateRender: false }, b.at + 0.3);
      sai(ctx, box, b, b.at + 0.65);
      KIT.cue(b.at + 0.3, "carimbo");
      return b.at + 0.65;
    },

    rotulo(ctx, b) {
      const box = el("div", "d-rotulo t");
      box.appendChild(texto(el("div", "n", b.nome)));
      if (b.papel) box.appendChild(texto(el("div", "p", b.papel)));
      ctx.hud.appendChild(box);
      IN(ctx.c.tl, box, b.at, { x: -30 });
      sai(ctx, box, b, b.at + 0.45);
      KIT.cue(b.at, "whoosh", -12);
      return b.at + 0.45;
    },

    palavras(ctx, b) {
      const frase = typeof b.frase === "string";
      const box = el("div", "d-palavras t" + (frase ? " f" : "") + (ctx.beats.some((o) => o.faz === "contador") ? " c" : "") +
        (ctx.beats.some((o) => o.faz === "acao") ? " a" : "")), { tl } = ctx.c;
      if (frase) box.style.fontSize = `${b.palavras.length <= 4 ? 120 : b.palavras.length <= 7 ? 100 : 84}px`;
      const ats = b.ats.length ? b.ats : b.palavras.map((_, i) => b.at + i * 0.3);
      const limpa = (w) => String(w).replace(/#\d+$/, "").replace(/[^\p{L}\p{N}']/gu, "").toLowerCase();
      const marca = new Set([b.risco, ...(b.destaque || [])].filter(Boolean).map(limpa));
      mostra(tl, box, b.at);
      b.palavras.forEach((w, i) => {
        const s = texto(el("span", null, String(w).replace(/#\d+$/, "")));
        if (frase && marca.has(limpa(w))) s.classList.add("hl");
        box.appendChild(s);
        tl.fromTo(s, { opacity: 0, y: 40 }, { opacity: 1, y: 0, duration: 0.22, ease: "back.out(2.5)", immediateRender: false }, ats[i]);
        KIT.cue(ats[i], "tique", -12);
        if (b.risco && limpa(b.risco) === limpa(w)) {
          const r = el("b", "d-risco");
          s.appendChild(r);
          const tr = ats[ats.length - 1] + 0.3;
          tl.fromTo(r, { scaleX: 0 }, { scaleX: 1, duration: 0.25, ease: "power2.out", immediateRender: false }, tr);
          KIT.cue(tr, "impacto", -8);
        }
      });
      ctx.hud.appendChild(box);
      const fimP = ats[ats.length - 1] + (b.risco ? 0.55 : 0.25);
      sai(ctx, box, b, fimP);
      return ats[ats.length - 1] + 0.25;
    },

    citacao(ctx, b) {
      const veu = el("div", "d-veu"), box = el("div", "d-citacao t"), { tl } = ctx.c;
      box.append(texto(el("div", "q", `“${b.t}”`)), texto(el("div", "a", b.autor)));
      ctx.hud.append(veu, box);
      tl.fromTo(veu, { opacity: 0 }, { opacity: 1, duration: 0.4, immediateRender: false }, b.at);
      IN(tl, box, b.at + 0.1);
      sai(ctx, veu, b, b.at + 0.55);
      sai(ctx, box, b, b.at + 0.55);
      KIT.cue(b.at, "whoosh", -10);
      return b.at + 0.55;
    },

    lista(ctx, b) {
      const box = el("div", "d-lista t"), { tl } = ctx.c;
      mostra(tl, box, b.at);
      let fim = b.at;
      b.itens.forEach((it, i) => {
        const r = texto(el("div", "i", it.t));
        box.appendChild(r);
        const t = it.at != null ? it.at : b.at + i * 0.5;
        tl.fromTo(r, { opacity: 0, x: -24 }, { opacity: 1, x: 0, duration: 0.35, ease: "power3.out", immediateRender: false }, t);
        KIT.cue(t, "tique", -10);
        fim = Math.max(fim, t + 0.35);
      });
      ctx.hud.appendChild(box);
      sai(ctx, box, b, fim);
      return fim;
    },

    linha_tempo(ctx, b) {
      const ln = el("div", "d-linha t"), cur = el("div", "d-cursor"), { tl } = ctx.c, n = b.marcos.length;
      ln.appendChild(cur);
      tl.fromTo(ln, { opacity: 0, scaleX: 0, transformOrigin: "left center" },
                { opacity: 1, scaleX: 1, duration: 0.6, ease: "power3.inOut", immediateRender: false }, b.at);
      let fim = b.at + 0.6;
      b.marcos.forEach((m, i) => {
        const x = n === 1 ? 50 : 8 + (i / (n - 1)) * 84;   // 8–92%: rótulos das pontas dentro da safe area
        const mk = el("div", "d-marco");
        mk.style.left = `${x}%`;
        mk.append(texto(el("div", "d", m.data)), texto(el("div", "x", m.t || "")));
        ln.appendChild(mk);
        const t = m.at != null ? m.at : b.at + 0.6 + i * 0.8;
        tl.fromTo(mk, { opacity: 0, y: 12 }, { opacity: 1, y: 0, duration: 0.3, immediateRender: false }, t);
        tl.to(cur, { left: `${x}%`, duration: 0.4, ease: "power2.inOut" }, t - 0.1);
        KIT.cue(t, "tique", -10);
        fim = Math.max(fim, t + 0.3);
      });
      ctx.hud.appendChild(ln);
      sai(ctx, ln, b, fim);
      return fim;
    },

    inserto(ctx, b) {
      const im = foto("d-inserto", b.arquivo, b.ajuste), { tl } = ctx.c;
      ctx.palco.appendChild(im);
      tl.fromTo(im, { opacity: 0, scale: 1.12 }, { opacity: 1, scale: 1.04, duration: 0.6, ease: "power2.out", immediateRender: false }, b.at);
      tl.to(im, { scale: 1.0, duration: Math.max(0.1, ctx.fim - b.at - 0.6), ease: "none" }, b.at + 0.6);
      KIT.cue(b.at, "whoosh", -10);
      return b.at + 0.6;
    },

    legenda(ctx, b) {
      const box = el("div", "d-legenda t"), { tl } = ctx.c;
      ctx.hud.appendChild(box);
      mostra(tl, box, b.at);
      b.grupos.forEach((g) => {
        const s = texto(el("span", null, g.t)), a = ctx.c.fala + g.s, f = ctx.c.fala + g.f;
        box.appendChild(s);
        tl.fromTo(s, { opacity: 0 }, { opacity: 1, duration: 0.01, immediateRender: false }, a);
        tl.to(s, { opacity: 0, duration: 0.01 }, Math.max(a + 0.02, f - 0.01));
      });
      return b.at;
    },

    selo(ctx, b) {
      const box = el("div", "d-selo"), { tl } = ctx.c;
      Object.assign(box.style, { left: `${W / 2 - 130}px`, top: V ? "520px" : "300px", width: "260px", height: "260px" });
      box.appendChild(seloSvg(260).s);
      ctx.hud.appendChild(box);
      tl.fromTo(box, { opacity: 0, scale: 1.8 }, { opacity: 1, scale: 1, duration: 0.35, ease: "power4.in", immediateRender: false }, b.at);
      tl.to(box, { scale: 1.08, duration: 0.25, yoyo: true, repeat: 3, ease: "sine.inOut" }, b.at + 0.5);
      sai(ctx, box, b, b.at + 1.5);
      KIT.cue(b.at + 0.35, "carimbo");
      return b.at + 0.6;
    },
  };

  KIT.tipo("doc", (c, cena) => {
    iniciarFx();
    const D = window.__KIT_DADOS, mapa = D.mapa, p = cena.palco || { tipo: "escuro" };
    const palco = el("div", "d-palco"), cam = el("div", "d-cam"), hud = el("div", "d-hud");
    palco.appendChild(cam);
    c.layer.append(palco, hud);
    let dims, pts = {};
    if (p.tipo === "mapa") {
      dims = { mw: mapa.w, mh: mapa.h, base: Math.max(W / mapa.w, H / mapa.h) };
      const m = el("div", "d-mapa");
      m.style.backgroundImage = `url("${mapa.arquivo}")`;
      cam.appendChild(m);
      pts = mapa.pontos;
    } else {
      dims = { mw: W, mh: H, base: 1 };
      if (p.tipo === "imagem") {
        cam.appendChild(foto("d-img", p.arquivo, p.ajuste));
      }
    }
    Object.assign(cam.style, { width: `${dims.mw}px`, height: `${dims.mh}px` });
    const g = svg("svg", { width: dims.mw, height: dims.mh, viewBox: `0 0 ${dims.mw} ${dims.mh}` });
    cam.appendChild(g);
    const fim = c.ini + cena.dur - (cena.saida ? cena.saida.dur : 0);
    const abs = (s) => (s == null ? null : c.fala + s);
    const beats = (cena.beats || []).map((b) => ({
      ...b, at: abs(b.s), ats: (b.ts || []).map(abs),
      itens: (b.itens || []).map((x) => ({ ...x, at: abs(x.s) })),
      marcos: (b.marcos || []).map((x) => ({ ...x, at: abs(x.s) })),
    }));
    // câmera
    const nomeDe = (b) => [b.para, b.ponto, b.de].find((n) => n && pts[n]);
    const primeiro = beats.map(nomeDe).find(Boolean);
    let ini;
    if (p.tipo === "mapa") {
      const [x0, y0] = primeiro ? pts[primeiro] : [dims.mw / 2, dims.mh / 2];
      ini = c.entra === "recuo" ? { x: x0, y: y0, s: 3.2 } : (window.__docCamMapa || { x: x0, y: y0, s: 1.2 });
    } else ini = { x: W / 2, y: H / 2, s: 1.08 };
    const moves = [];
    if (p.tipo === "mapa" && c.entra === "recuo") moves.push({ t: c.ini, d: 1.0, x: ini.x, y: ini.y, s: 1.15 });
    let alvo = null;
    for (const b of beats) {
      if (b.faz === "camera" && p.tipo === "mapa" && pts[b.para]) {
        moves.push({ t: b.at, d: b.dur || 1.6, x: pts[b.para][0], y: pts[b.para][1], s: b.zoom || 1.6 });
      } else if (b.faz === "camera" && b.area) {
        const [ax, ay, aw, ah] = b.area;
        moves.push({ t: b.at, d: b.dur || 1.6, x: (ax + aw / 2) * W, y: (ay + ah / 2) * H, s: clamp(1 / Math.max(aw, ah), 1, 3) });
        alvo = [(ax + aw / 2) * W, (ay + ah / 2) * H];
      } else if (b.faz === "rota" && p.tipo === "mapa" &&
                 !beats.some((o) => o.faz === "camera" && Math.abs(o.at - b.at) < 0.05)) {
        moves.push({ t: b.at, d: b.dur || 2.0, x: pts[b.para][0], y: pts[b.para][1], s: b.zoom || 1.35 });
      }
      if (nomeDe(b)) alvo = pts[nomeDe(b)];
    }
    const camera = construirCam(ini, moves, c.ini);
    const ancoras = [];   // [elemento, x, y, dx, dy]: overlay preso a um ponto do palco
    const pose = (t) => {   // posição do palco na tela no instante t (pintor e ctx.tela usam a mesma conta)
      const st = camAt(camera, t), sc = dims.base * st.s;
      return { sc, tx: clamp(W / 2 - st.x * sc, W - dims.mw * sc, 0), ty: clamp(H / 2 - st.y * sc, H - dims.mh * sc, 0) };
    };
    const tela = (x, y, t) => { const q = pose(t); return [q.tx + x * q.sc, q.ty + y * q.sc]; };
    KIT.pintor((t) => {
      if (t < c.ini - 0.05 || t > c.ini + cena.dur + 0.05) return;
      const { tx, ty, sc } = pose(t);
      cam.style.transform = `translate(${tx.toFixed(2)}px,${ty.toFixed(2)}px) scale(${sc.toFixed(5)})`;
      for (const [e, x, y, dx, dy] of ancoras) {
        const w = e.offsetWidth, h = e.offsetHeight, l = tx + x * sc + dx, tp = ty + y * sc + dy;
        e.style.left = `${(V ? clamp(l, 80, 1000 - w) : l).toFixed(1)}px`;
        e.style.top = `${(V ? clamp(tp, 180, 1660 - h) : tp).toFixed(1)}px`;
      }
    });
    if (p.tipo === "mapa") window.__docCamMapa = camAt(camera, fim);
    c.layer._doc = {
      mergulho: (t, d) => {
        const de = camAt(camera, t), [x, y] = alvo || [de.x, de.y];
        camera.ms.push({ t, d, x, y, s: de.s * 4, de });
      },
    };
    const ctx = { c, cena, hud, g, pts, base: dims.base, beats, fim, ancoras, palco, cam, tela };
    let ultimo = c.t0;
    beats.forEach((b, i) => {
      const f = BEATS[b.faz];
      if (!f) throw new Error(`beat desconhecido: ${b.faz}`);
      ultimo = Math.max(ultimo, f(ctx, b, i));
    });
    return ultimo;
  });

  // ---------- abertura: selo K carimba no papel, anéis se desenham, marca datilografada, título
  KIT.tipo("vinheta", (c, cena) => {
    iniciarFx();
    const { tl } = c, t0 = c.ini + 0.1, saidaDur = cena.saida ? cena.saida.dur : 0, sai = c.ini + cena.dur - saidaDur - 0.01;   // zoom de saída só depois do ponto de medição do layout (fim - 0.02)
    const palco = el("div", "d-palco");
    palco.appendChild(el("div", "d-papel"));
    c.layer.appendChild(palco);
    const box = el("div", "d-selo");
    Object.assign(box.style, { left: `${W / 2 - 160}px`, top: "300px", width: "320px", height: "320px", opacity: "0" });
    const { s, aneis } = seloSvg(320);
    box.appendChild(s);
    const marca = texto(el("div", "d-marca t", "KRYVANTIS")), tit = texto(el("div", "d-titulo t", cena.titulo || ""));
    palco.append(box, marca, tit);
    tl.fromTo(box, { opacity: 0, scale: 2.4 }, { opacity: 1, scale: 1, duration: 0.35, ease: "power4.in", immediateRender: false }, t0);
    tl.fromTo(palco, { x: -8 }, { x: 0, duration: 0.25, ease: "elastic.out(1,0.3)", immediateRender: false }, t0 + 0.35);
    for (let i = 0; i < 18; i++) {   // poeira do impacto
      const d = el("i"), a = (i / 18) * Math.PI * 2, r = 180 + (i % 3) * 60;
      Object.assign(d.style, { position: "absolute", left: `${W / 2}px`, top: "460px", width: "6px", height: "6px",
                               borderRadius: "50%", background: "#cdbf9f", opacity: "0" });
      palco.appendChild(d);
      tl.fromTo(d, { opacity: 0.8, x: 0, y: 0 }, { opacity: 0, x: Math.cos(a) * r, y: Math.sin(a) * r * 0.6, duration: 0.9,
                ease: "power2.out", immediateRender: false }, t0 + 0.35);
    }
    for (const a of aneis) {
      const L = 2 * Math.PI * Number(a.getAttribute("r"));
      a.setAttribute("stroke-dasharray", L);
      a.setAttribute("stroke-dashoffset", L);
      tl.fromTo(a, { attr: { "stroke-dashoffset": L } }, { attr: { "stroke-dashoffset": 0 }, duration: 0.6, ease: "power2.inOut",
                immediateRender: false }, t0 + 0.4);
    }
    tl.fromTo(marca, { clipPath: "inset(0 100% 0 0)" }, { clipPath: "inset(0 0% 0 0)", duration: 0.7, ease: "steps(9)",
              immediateRender: false }, t0 + 0.9);
    tl.fromTo(tit, { opacity: 0, y: 20 }, { opacity: 1, y: 0, duration: 0.5, ease: "power3.out", immediateRender: false }, t0 + 1.6);
    tl.to(palco, { scale: 5, opacity: 0, duration: Math.min(0.5, Math.max(0.1, saidaDur)), ease: "power3.in", transformOrigin: "50% 42%" }, sai);
    KIT.cue(t0 + 0.35, "carimbo");
    KIT.cue(t0 + 0.9, "maquina");
    KIT.cue(sai, "whoosh");
    return t0 + 2.1;
  });

  // ---------- tela final (20 s): quadros-guia nas posições dos elementos finais do YouTube
  KIT.tipo("telafinal", (c, cena) => {
    iniciarFx();
    const { tl } = c, t0 = c.ini + 0.2, D = window.__KIT_DADOS, tx = cena.textos || {};
    const palco = el("div", "d-palco");
    c.layer.appendChild(palco);
    if (D.mapa) {
      const m = el("div", "d-img");
      Object.assign(m.style, { backgroundImage: `url("${D.mapa.arquivo}")`, filter: "blur(16px) sepia(.5) brightness(.32)",
                               transform: "scale(1.1)" });
      palco.appendChild(m);
    }
    const prox = texto(el("div", "d-prox t", tx.prox || ""));
    const ins = el("div", "d-guia");
    Object.assign(ins.style, { left: "330px", top: "330px", width: "340px", height: "340px", borderRadius: "50%" });
    ins.appendChild(el("div", "g", tx.inscreva || ""));
    const vid = el("div", "d-guia");
    Object.assign(vid.style, { left: "870px", top: "320px", width: "720px", height: "405px" });
    vid.appendChild(el("div", "g", tx.video || ""));
    const tag = texto(el("div", "d-tag t", c.tema.tagline || ""));
    const cta = texto(el("div", "d-cta t", tx.inscreva || ""));
    let itens = [prox, ins, vid, tag];
    if (V) {                       // Short: sem quadros-guia (elementos finais não existem em Shorts)
      const selo = el("div", "d-selo"), { s } = seloSvg(240);
      Object.assign(selo.style, { left: `${W / 2 - 120}px`, top: "560px", width: "240px", height: "240px" });
      selo.appendChild(s);
      palco.append(selo, prox, cta, tag);
      itens = [selo, prox, cta, tag];
    } else palco.append(prox, ins, vid, tag);
    itens.forEach((e, i) =>
      tl.fromTo(e, { opacity: 0, y: 16 }, { opacity: 1, y: 0, duration: 0.6, ease: "power3.out", immediateRender: false }, t0 + i * 0.2));
    KIT.cue(t0, "whoosh", -10);
    return t0 + 1.4;
  });
  // ---------- transições ligadas (entrada da cena nova; `ant` = camada da cena anterior)
  KIT.transicao("mergulho", (tl, cam, t, d, tema, ant) => {
    const meio = t + d * 0.45, flash = iniciarFx().flash;
    if (ant && ant._doc) ant._doc.mergulho(t - 0.1, d * 0.55 + 0.1);
    tl.fromTo(cam, { opacity: 0 }, { opacity: 1, duration: d * 0.4 }, meio);
    tl.fromTo(flash, { opacity: 0 }, { opacity: 0.85, duration: 0.1, immediateRender: false }, meio - 0.05)
      .to(flash, { opacity: 0, duration: 0.45 }, meio + 0.05);
    const palco = cam.querySelector(".d-palco");
    if (palco) tl.fromTo(palco, { scale: 1.7 }, { scale: 1, duration: 1.1, ease: "power3.out", immediateRender: false }, meio);
    KIT.cue(meio, "clarao", -8);
  });
  KIT.transicao("recuo", (tl, cam, t, d, tema, ant) => {
    const pp = ant && ant.querySelector(".d-palco");
    if (pp) tl.to(pp, { scale: 0.8, opacity: 0, duration: d, ease: "power2.in" }, t);
    tl.fromTo(cam, { opacity: 0 }, { opacity: 1, duration: d * 0.6 }, t + d * 0.4);
    KIT.cue(t, "whoosh", -8);
  });
  KIT.transicao("corte", (tl, cam, t, d) => {
    tl.fromTo(cam, { opacity: 0 }, { opacity: 1, duration: 0.01 }, t + d * 0.5);
    KIT.cue(t, "whoosh", -10);
  });

  window.__doc = { W, H, el, svg, texto, clamp, easeIO, easeOut, fmt, iniciarFx, camAt, BEATS, SAIDA };
})();
