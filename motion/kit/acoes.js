/* Ações ilustradas (beat "acao"): vinhetas animadas de atores em silhueta de gravura sobre o palco da cena.
   Carregado depois do doc.js quando o cenas.json traz beats "acao". Tudo que depende do tempo é timeline GSAP. */
(() => {
  "use strict";
  const { el, svg, texto, BEATS } = window.__doc;
  const TINTA = "#d9cdb0", PRETO = "#15120f", ACENTO = "var(--k-acento)";
  const VW = 560, VH = 360, CHAO = 300, BX = 900, BY = 578;
  const POS = { esq: 130, centro: 280, dir: 430 };
  const LADO = { esq: { left: "100px" }, centro: { left: "610px" }, dir: { right: "100px" } };
  const DUR = { olha: 3.2, fala: 3.6, telegrama: 3.8, le: 3.2, aponta: 2.8, sobe_a_bordo: 4.0, anda: 3.0 };
  let uid = 0;

  const CSS = `
.a-box{position:absolute;bottom:70px;background:radial-gradient(ellipse at 50% 62%,rgba(11,10,8,.78),rgba(11,10,8,0) 72%)}
.a-box svg{position:absolute;inset:0;overflow:visible}
.a-balao{position:absolute;max-width:46%;padding:10px 18px;background:rgba(21,18,15,.94);box-shadow:inset 0 0 0 1.5px ${TINTA};
  font:italic 400 32px/1.2 var(--k-display-familia);color:#efe6cf;opacity:0}
.a-rot{position:absolute;font:600 22px var(--k-corpo-familia);letter-spacing:.18em;color:var(--k-acento);text-transform:uppercase;
  transform:translateX(-50%);white-space:nowrap;opacity:0}
.a-tira{position:absolute;left:50%;transform:translateX(-50%);padding:8px 18px;background:${TINTA};color:${PRETO};
  font:600 26px var(--k-mono-familia);letter-spacing:.12em;text-transform:uppercase;white-space:nowrap;opacity:0}`;
  document.head.appendChild(Object.assign(document.createElement("style"), { textContent: CSS }));

  const P = (pai, d, o = {}) => {
    const p = svg("path", { d, fill: o.fill || "none", stroke: o.stroke === undefined ? TINTA : o.stroke,
      "stroke-width": o.w || 2.1, "stroke-linecap": "round", "stroke-linejoin": "round" });
    if (o.stroke === null) p.removeAttribute("stroke");
    if (o.op != null) p.setAttribute("opacity", o.op);
    pai.appendChild(p);
    return p;
  };
  const oc = (e) => { e.setAttribute("opacity", 0); return e; };   // nasce oculto: só a timeline revela
  const G = (pai, tr) => { const g = svg("g"); if (tr) g.setAttribute("transform", tr); pai.appendChild(g); return g; };

  // ---------- figuras: silhueta de gravura (contorno creme, fundo quase preto, hachura no lado da sombra)
  const TRAJES = {
    capitao:    { chapeu: "M-10 -25Q0 -35 10 -25L11 -21L-11 -21ZM-12 -21L15 -21", bainha: 34, botoes: true },
    inspetor:   { chapeu: "M-9 -22Q-9 -37 0 -37Q9 -37 9 -22ZM-15 -22L15 -22", bainha: 52 },
    medico:     { chapeu: "M-9 -22Q-9 -36 0 -36Q9 -36 9 -22ZM-14 -22L14 -22", bainha: 34, colete: true },
    secretaria: { chapeu: "M-8 -22Q0 -32 8 -22ZM-18 -22Q0 -28 18 -22", bainha: 62, saia: true },
    menino:     { chapeu: "M-10 -23Q0 -33 10 -23L16 -21L-10 -21Z", bainha: 22, escala: 0.82 },
    marinheiro: { chapeu: "M-10 -22Q0 -30 10 -22ZM-10 -22L10 -22", bainha: 34 },
    civil:      { chapeu: "M-9 -22Q-10 -33 0 -34Q10 -33 9 -22Z", bainha: 34 },
  };

  function figura(pai, traje, hach) {
    const T = TRAJES[traje], f = { traje };
    f.mov = G(pai);
    f.flip = G(f.mov);
    f.bob = G(f.flip);
    const esc = G(f.bob, `scale(${T.escala || 1})`);
    const perna = (x) => {
      const w = G(esc, `translate(${x} -92)`), i = G(w);
      P(i, "M-4 0L-4 86L-5 90L8 90L5 86L4 0Z", { fill: PRETO });
      return i;
    };
    f.pernaE = perna(-6); f.pernaD = perna(6);
    f.tronco = G(G(esc, "translate(0 -92)"));
    const braco = (x) => {
      const o = G(f.tronco, `translate(${x} -52)`), a = G(o), c = G(a, "translate(0 30)");
      P(a, "M-3.5 0L-3 30L3 30L3.5 0Z", { fill: PRETO });
      P(c, "M-3 0L-2.5 28L2.5 28L3 0Z", { fill: PRETO });
      c.appendChild(svg("circle", { cx: 0, cy: 30, r: 3.2, fill: PRETO, stroke: TINTA, "stroke-width": 1.2 }));
      return [a, c];
    };
    f.be = braco(-15);
    const B = T.bainha;
    const corpo = T.saia ? `M-30 ${B}L-14 -50Q-11 -59 0 -59Q11 -59 14 -50L30 ${B}Z` : `M-17 ${B}L-15 -50Q-12 -59 0 -59Q12 -59 15 -50L17 ${B}Z`;
    P(f.tronco, corpo, { fill: PRETO });
    P(f.tronco, T.saia ? `M-30 ${B}L-14 -50Q-11 -59 0 -59L0 ${B}Z` : `M-17 ${B}L-15 -50Q-12 -59 0 -59L0 ${B}Z`,
      { fill: `url(#${hach})`, stroke: null });
    if (T.colete) P(f.tronco, "M-5 -55L0 -22L5 -55Z", { w: 1.1 });
    if (T.botoes) for (const [x, y] of [[-4, -40], [-4, -28], [4, -40], [4, -28]]) f.tronco.appendChild(svg("circle", { cx: x, cy: y, r: 1.3, fill: TINTA }));
    f.bd = braco(15);
    f.cabeca = G(f.tronco, "translate(0 -60)");
    f.cabeca.appendChild(svg("ellipse", { cx: 0, cy: -16, rx: 9, ry: 11, fill: PRETO, stroke: TINTA, "stroke-width": 2.1 }));
    P(f.cabeca, "M0 -27A9 11 0 0 0 0 -5Z", { fill: `url(#${hach})`, stroke: null });
    P(f.cabeca, "M8.6 -17L13 -13.5L8.6 -12", { w: 1.3 });
    P(f.cabeca, T.chapeu, { fill: PRETO });
    for (const e of [f.pernaE, f.pernaD, f.tronco, f.cabeca, ...f.be, ...f.bd]) {
      const bb = e.getBBox();                       // GSAP mede transformOrigin a partir do canto do bbox: converte para a origem local (0,0)
      gsap.set(e, { transformOrigin: `${-bb.x}px ${-bb.y}px` });
    }
    gsap.set(f.bob, { transformOrigin: "0 0" });
    return f;
  }

  const ALVO = (f) => ({ tr: [f.tronco], ca: [f.cabeca], bd: f.bd, be: f.be, pd: [f.pernaD], pe: [f.pernaE] });
  function pose(tl, f, p, t, d = 0.5, ease = "power2.inOut") {
    const A = ALVO(f);
    for (const k in p) [].concat(p[k]).forEach((v, i) => tl.to(A[k][i], { rotation: v, duration: d, ease }, t));
  }
  function respira(tl, figs, t, dur) {
    for (const f of figs) tl.to(f.bob, { y: -0.9, duration: 1.6, yoyo: true, repeat: Math.ceil(dur / 1.6), ease: "sine.inOut" }, t);
  }
  function passos(tl, f, t, dur, n) {
    const d = dur / (n * 2);
    for (let i = 0; i < n * 2; i++) {
      const s = i % 2 ? 1 : -1;
      pose(tl, f, { pd: 22 * s, pe: -22 * s, bd: [-14 * s, 8], be: [14 * s, 8] }, t + i * d, d, "sine.inOut");
      tl.to(f.bob, { y: i % 2 ? 0 : -2.5, duration: d, ease: "sine.inOut" }, t + i * d);
    }
    pose(tl, f, { pd: 0, pe: 0, bd: [0, 0], be: [0, 0] }, t + dur, 0.3);
  }

  // ---------- vinheta: caixa sobre o palco, com véu, chão e filtro de tremor de gravura
  function palco(ctx, b, dur) {
    const n = ++uid, esc = b.escala || 1, { tl } = ctx.c;
    const box = el("div", "a-box");
    Object.assign(box.style, LADO[b.lado || "dir"], { width: `${BX * esc}px`, height: `${BY * esc}px` });
    const g = svg("svg", { viewBox: `0 0 ${VW} ${VH}`, width: "100%", height: "100%" });
    const defs = svg("defs");
    const pat = svg("pattern", { id: `h${n}`, width: 4, height: 4, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" });
    pat.appendChild(svg("line", { x1: 0, y1: 0, x2: 0, y2: 4, stroke: TINTA, "stroke-width": 0.7, opacity: 0.5 }));
    const turb = svg("feTurbulence", { type: "fractalNoise", baseFrequency: 0.03, numOctaves: 1, seed: 1 });
    const filt = svg("filter", { id: `t${n}`, x: "-5%", y: "-5%", width: "110%", height: "110%" });
    filt.append(turb, svg("feDisplacementMap", { in: "SourceGraphic", scale: 1.2 }));
    defs.append(pat, filt);
    g.appendChild(defs);
    const cena = G(g);
    cena.setAttribute("filter", `url(#t${n})`);
    P(cena, `M20 ${CHAO}H540`, { w: 1.2, op: 0.55 });
    P(cena, `M60 ${CHAO + 8}H200M260 ${CHAO + 8}H430`, { w: 0.8, op: 0.3 });
    box.appendChild(g);
    ctx.hud.appendChild(box);
    KIT.pintor((t) => turb.setAttribute("seed", String(Math.floor(t * 12) % 9)));
    tl.fromTo(box, { opacity: 0, y: 20 }, { opacity: 1, y: 0, duration: 0.4, ease: "power3.out", immediateRender: false }, b.at);
    tl.to(box, { opacity: 0, duration: 0.35 }, b.at + dur - 0.35);
    return { box, g: cena, tl, at: b.at, dur, hach: `h${n}`, esc };
  }

  // ator (ou grupo) em x do chão, olhando para a direita (dir = 1) ou esquerda (dir = -1)
  function elenco(S, nome, x, dir) {
    const a = window.__KIT_DADOS.atores[nome], trajes = [].concat(a.traje);
    const figs = trajes.map((tj, i) => {
      const f = figura(S.g, tj, S.hach);
      f.flip.setAttribute("transform", `scale(${dir} 1)`);
      gsap.set(f.mov, { x: x + i * 34 * -dir, y: CHAO });
      return f;
    });
    if (a.nome) {
      const r = texto(el("div", "a-rot", a.nome));
      r.style.left = `${(x / VW) * 100}%`;
      r.style.top = `${((CHAO + 16) / VH) * 100}%`;
      S.box.appendChild(r);
      S.tl.fromTo(r, { opacity: 0 }, { opacity: 1, duration: 0.4, immediateRender: false }, S.at + 0.5);
    }
    respira(S.tl, figs, S.at, S.dur);
    return figs;
  }

  // traço que se desenha entre dois pontos (curva leve)
  function traco(S, x1, y1, x2, y2, t, dur) {
    const p = P(S.g, `M${x1} ${y1}Q${(x1 + x2) / 2} ${Math.min(y1, y2) - 18} ${x2} ${y2}`, { stroke: ACENTO, w: 1.8 });
    const L = p.getTotalLength();
    oc(p);
    S.tl.set(p, { opacity: 1 }, t);
    p.setAttribute("stroke-dasharray", L);
    p.setAttribute("stroke-dashoffset", L);
    S.tl.fromTo(p, { attr: { "stroke-dashoffset": L } }, { attr: { "stroke-dashoffset": 0 }, duration: dur, ease: "power2.inOut", immediateRender: false }, t);
    return p;
  }

  function balao(S, x, txt, t) {
    const b = texto(el("div", "a-balao", txt || "…"));
    b.style.left = `${Math.max(2, (x / VW) * 100 - 8)}%`;
    b.style.top = "4%";
    S.box.appendChild(b);
    S.tl.fromTo(b, { opacity: 0, scale: 0.85 }, { opacity: 1, scale: 1, duration: 0.3, ease: "back.out(2)", immediateRender: false }, t);
    S.tl.to(b, { opacity: 0, duration: 0.3 }, S.at + S.dur - 0.7);
    return b;
  }

  const MODELOS = {
    olha(S, b) {
      const [A] = elenco(S, b.ator, POS.esq, 1), B = elenco(S, b.alvo, POS.dir, -1), t = S.at;
      pose(S.tl, A, { ca: 14 }, t, 0.01);
      pose(S.tl, A, { ca: -8 }, t + 0.7, 0.25, "power3.out");
      pose(S.tl, B[0], { ca: 5 }, t + 0.9, 0.5);
      const y = CHAO - 168;
      traco(S, POS.esq + 14, y, POS.dir - 14, y, t + 0.9, 0.7);
      const ex = svg("text", { x: POS.esq, y: y - 34, "text-anchor": "middle", fill: ACENTO, "font-size": 40, "font-weight": 700,
        "font-family": "var(--k-display-familia)" });
      ex.textContent = "!";
      oc(ex);
      ex.style.transformBox = "fill-box";
      ex.style.transformOrigin = "50% 100%";
      S.g.appendChild(ex);
      S.tl.fromTo(ex, { opacity: 0, scale: 0 }, { opacity: 1, scale: 1, duration: 0.3, ease: "back.out(3)", immediateRender: false }, t + 1.3);
      KIT.cue(t + 1.3, "ping", -10);
    },
    fala(S, b) {
      const [A] = elenco(S, b.ator, POS.esq, 1), B = elenco(S, b.alvo, POS.dir, -1), t = S.at;
      const gesto = (t0) => {
        pose(S.tl, A, { bd: [-55, -35], tr: 3 }, t0, 0.3, "power2.out");
        pose(S.tl, A, { bd: [-18, -10], tr: 0 }, t0 + 0.55, 0.4);
      };
      gesto(t + 0.8); gesto(t + 1.8);
      pose(S.tl, B[0], { ca: 4 }, t + 0.7, 0.5);
      balao(S, POS.esq, b.texto, t + 0.7);
      KIT.cue(t + 0.7, "tique", -10);
    },
    telegrama(S, b) {
      const t = S.at, g = S.g, tl = S.tl;
      P(g, `M120 ${CHAO}V120M105 150H135M110 182H130`, { w: 2.2 });
      g.appendChild(svg("circle", { cx: 120, cy: 117, r: 3.5, fill: PRETO, stroke: TINTA, "stroke-width": 1.6 }));
      [18, 32, 46].forEach((r, i) => {
        const a = P(g, `M${120 + r * 0.7} ${117 - r * 0.7}A${r} ${r} 0 0 1 ${120 + r * 0.7} ${117 + r * 0.7}`, { stroke: ACENTO, w: 2 });
        oc(a);
        tl.fromTo(a, { opacity: 0 }, { opacity: 1, duration: 0.2, yoyo: true, repeat: 5, immediateRender: false }, t + 0.3 + i * 0.18);
        tl.set(a, { opacity: 0 }, t + 2.0);
      });
      // destino: prédio simples com janelas que acendem quando o telegrama chega
      P(g, `M440 ${CHAO}V190H520V${CHAO}M432 190L480 160L528 190`, { fill: PRETO });
      const jan = [0, 1, 2].map((i) => {
        const r = svg("rect", { x: 452 + i * 22, y: 214, width: 12, height: 18, fill: PRETO, stroke: TINTA, "stroke-width": 1.4 });
        g.appendChild(r);
        return r;
      });
      const env = G(g);
      env.appendChild(svg("rect", { x: -11, y: -8, width: 22, height: 16, fill: TINTA, stroke: PRETO, "stroke-width": 1.2 }));
      P(env, "M-11 -8L0 2L11 -8", { stroke: PRETO, w: 1.4 });
      gsap.set(env, { x: 140, y: 205, opacity: 0 });
      tl.set(env, { opacity: 1 }, t + 1.0);
      tl.to(env, { x: 470, duration: 1.4, ease: "power1.inOut" }, t + 1.0);
      tl.to(env, { y: 160, duration: 0.7, ease: "sine.out" }, t + 1.0);
      tl.to(env, { y: 205, duration: 0.7, ease: "sine.in" }, t + 1.7);
      tl.to(env, { opacity: 0, scale: 0.6, duration: 0.2 }, t + 2.4);
      jan.forEach((j, i) => tl.to(j, { fill: "#efe6cf", duration: 0.15 }, t + 2.5 + i * 0.12));
      if (b.texto) {
        const tira = texto(el("div", "a-tira", b.texto));
        tira.style.top = "84%";
        S.box.appendChild(tira);
        tl.fromTo(tira, { opacity: 0, clipPath: "inset(0 100% 0 0)" },
          { opacity: 1, clipPath: "inset(0 0% 0 0)", duration: 0.8, ease: "steps(14)", immediateRender: false }, t + 2.5);
        tl.to(tira, { opacity: 0, duration: 0.3 }, S.at + S.dur - 0.7);
      }
      KIT.cue(t + 0.2, "morse", -10);
      KIT.cue(t + 2.5, "ping", -8);
    },
    le(S, b) {
      const [A] = elenco(S, b.ator, POS.centro, 1), t = S.at, tl = S.tl, x = POS.centro;
      pose(tl, A, { bd: [-72, -85], be: [-58, -95], ca: 14 }, t + 0.4, 0.6);
      const folha = oc(G(S.g, `translate(${x + 30} ${CHAO - 178}) rotate(-8)`));
      P(folha, "M0 0H46V58H0Z", { fill: TINTA, stroke: PRETO, w: 1 });
      const linhas = [10, 22, 34, 46].map((y) => oc(P(folha, `M6 ${y}H${y === 46 ? 28 : 40}`, { stroke: PRETO, w: 1.4 })));
      tl.fromTo(folha, { opacity: 0 }, { opacity: 1, duration: 0.3, immediateRender: false }, t + 0.7);
      linhas.forEach((l, i) => tl.fromTo(l, { opacity: 0 }, { opacity: 1, duration: 0.2, immediateRender: false }, t + 1.2 + i * 0.35));
      if (b.texto) balao(S, x - 40, b.texto, t + 1.6);
      KIT.cue(t + 0.7, "tique", -10);
    },
    aponta(S, b) {
      const [A] = elenco(S, b.ator, POS.esq, 1), B = elenco(S, b.alvo, POS.dir, -1), t = S.at, tl = S.tl;
      pose(tl, A, { bd: [-84, -4], tr: 4, ca: -4 }, t + 0.5, 0.4, "power2.out");
      pose(tl, B[0], { ca: 6 }, t + 0.9, 0.5);
      const anel = svg("ellipse", { cx: POS.dir, cy: CHAO + 2, rx: 30, ry: 6, fill: "none", stroke: ACENTO, "stroke-width": 2 });
      oc(anel);
      anel.style.transformBox = "fill-box";
      anel.style.transformOrigin = "50% 50%";
      S.g.appendChild(anel);
      tl.fromTo(anel, { opacity: 0, scale: 0.5 }, { opacity: 1, scale: 1.4, duration: 0.7, repeat: 2, ease: "power2.out", immediateRender: false }, t + 0.9);
      tl.set(anel, { opacity: 0 }, t + 3.0);
      const seta = P(S.g, `M${POS.dir} ${CHAO - 205}V${CHAO - 186}M${POS.dir - 7} ${CHAO - 194}L${POS.dir} ${CHAO - 186}L${POS.dir + 7} ${CHAO - 194}`,
        { stroke: ACENTO, w: 2.4 });
      oc(seta);
      tl.fromTo(seta, { opacity: 0, y: -8 }, { opacity: 1, y: 0, duration: 0.35, ease: "bounce.out", immediateRender: false }, t + 1.0);
      KIT.cue(t + 0.9, "tique", -10);
    },
    anda(S, b) {
      const de = POS[b.de || "esq"], para = POS[b.para], dir = para >= de ? 1 : -1, t = S.at, tl = S.tl;
      const [A] = elenco(S, b.ator, de, dir);
      const dist = Math.abs(para - de), dur = Math.min(S.dur - 1, Math.max(1.6, dist / 70));
      tl.to(A.mov, { x: para, duration: dur, ease: "none" }, t + 0.5);
      passos(tl, A, t + 0.5, dur, Math.max(2, Math.round(dist / 44)));
    },
    sobe_a_bordo(S, b) {
      const [A] = elenco(S, b.ator, 90, 1), t = S.at, tl = S.tl, g = S.g, topo = CHAO - 70;
      P(g, `M360 ${topo}H545L525 ${CHAO}H378Z`, { fill: PRETO });
      P(g, `M385 ${topo}V${topo - 26}M440 ${topo}V${topo - 26}M495 ${topo}V${topo - 26}M385 ${topo - 26}H525`, { w: 1.4 });
      P(g, `M120 ${CHAO}L360 ${topo}`, { w: 2.6 });
      for (let i = 1; i < 7; i++) P(g, `M${120 + i * 34} ${CHAO - i * 10 - 4}V${CHAO - i * 10 + 4}`, { w: 1.3, op: 0.7 });
      const dur = Math.min(S.dur - 1.6, 2.4);
      tl.to(A.mov, { x: 345, y: topo, duration: dur, ease: "none" }, t + 0.5);
      pose(tl, A, { tr: 6 }, t + 0.5, 0.3);
      passos(tl, A, t + 0.5, dur, 5);
      pose(tl, A, { bd: [-150, -120], tr: 0 }, t + 0.5 + dur + 0.1, 0.35, "power2.out");
      pose(tl, A, { bd: [0, 0] }, t + 0.5 + dur + 0.8, 0.35);
      KIT.cue(t + 0.5 + dur, "tique", -10);
    },
  };

  BEATS.acao = (ctx, b) => {
    const f = MODELOS[b.modelo];
    if (!f) throw new Error(`acao: modelo sem implementação: ${b.modelo}`);
    const dur = b.dur || DUR[b.modelo];
    const S = palco(ctx, b, dur);
    f(S, b);
    (window.__marcas = window.__marcas || []).push({ id: ctx.cena.id, rotulo: `acao ${b.modelo}`, t: b.at + 1.4 });
    return b.at + dur;
  };
})();
