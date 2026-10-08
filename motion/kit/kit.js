/* Kit de motion do video_editor: monta reels a partir de window.__KIT_DADOS
   (gerado por ui/motion.py) numa timeline GSAP que o HyperFrames renderiza.
   Trechos adaptados dos blocos grain-overlay, bottom-up-letters, inline-highlight
   e sdf-iris do catálogo HyperFrames (Apache License 2.0, © HeyGen). */
(() => {
  "use strict";
  const FPS = 30;
  const F = (n) => n / FPS;
  const quadro = (s) => Math.ceil(s * FPS - 1e-6) / FPS;
  const r3 = (s) => Math.round(s * 1000) / 1000;
  const customs = {};
  const cues = [];
  const pintores = [];   // (tempo) => void, chamados a cada seek: estado em função do tempo, nunca acumulado

  const el = (tag, cls, txt) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (txt != null) e.textContent = txt;
    return e;
  };
  const cue = (t, som, ganho_db = -6) => cues.push({ t: r3(t), som, ganho_db });

  // ---------- entradas de texto: (tl, alvo, t) -> instante em que terminam
  function palavras(tl, alvo, t) {
    const ws = alvo.textContent.split(/\s+/).filter(Boolean);
    alvo.textContent = "";
    const spans = ws.map((w, i) => {
      const m = el("span", "k-mascara");
      const s = el("span", null, w);
      m.appendChild(s);
      alvo.appendChild(m);
      if (i < ws.length - 1) alvo.appendChild(document.createTextNode(" "));
      return s;
    });
    tl.fromTo(spans, { yPercent: 110 }, { yPercent: 0, duration: F(14), ease: "expo.out", stagger: F(6) }, t);
    return t + F(14) + F(6) * (spans.length - 1);
  }

  function letras(tl, alvo, t) {
    const chars = Array.from(alvo.textContent);
    alvo.textContent = "";
    const spans = chars.map((ch) => {
      const s = el("span", "k-letra", ch === " " ? " " : ch);
      alvo.appendChild(s);
      return s;
    });
    tl.fromTo(spans, { opacity: 0, y: 90, scale: 0.6 },
      { opacity: 1, y: 0, scale: 1, duration: F(14), ease: "back.out(1.7)", stagger: F(2) }, t);
    return t + F(14) + F(2) * (spans.length - 1);
  }

  function mascara(tl, alvo, t) {
    tl.fromTo(alvo, { clipPath: "inset(-20% 100% -20% -10%)" },
      { clipPath: "inset(-20% -10% -20% -10%)", duration: F(18), ease: "power3.out" }, t);
    return t + F(18);
  }

  function fade(tl, alvo, t) {
    tl.fromTo(alvo, { opacity: 0, y: 24 }, { opacity: 1, y: 0, duration: F(18), ease: "power3.out" }, t);
    return t + F(18);
  }

  // ---------- destaques: (tl, bloco, t, tema) -> instante em que terminam
  function marcaTexto(tl, bloco, t) {
    bloco.classList.add("k-com-marca");
    tl.fromTo(bloco, { "--k-marca": 0 }, { "--k-marca": 1, duration: F(14), ease: "power3.out" }, t);
    return t + F(14);
  }

  function risco(tl, bloco, t) {
    const r = el("i", "k-risco");
    bloco.appendChild(r);
    tl.fromTo(r, { scaleX: 0 }, { scaleX: 1, duration: F(8), ease: "power3.out" }, t);
    return t + F(8);
  }

  function assinaturaEl(tema) {
    if (tema.assinatura.tipo === "icone") {
      const i = el("img", "k-icone");
      i.src = tema.assinatura.src;
      return i;
    }
    return el("span", "k-ponto");
  }

  function assinatura(tl, bloco, t, tema) {
    const s = assinaturaEl(tema);
    bloco.appendChild(s);
    tl.fromTo(s, { opacity: 0 }, { opacity: 1, duration: F(1) }, t);
    tl.fromTo(s, { y: -900 }, { y: 0, duration: F(8), ease: "power2.in" }, t)
      .to(s, { y: -110, duration: F(4), ease: "power2.out" }, t + F(8))
      .to(s, { y: 0, duration: F(3), ease: "power2.in" }, t + F(12))
      .to(s, { y: -35, duration: F(1.5), ease: "power2.out" }, t + F(15))
      .to(s, { y: 0, duration: F(1.5), ease: "power2.in" }, t + F(16.5));
    cue(t + F(8), "pop-dourado");
    return t + F(18);
  }

  const ANIM = { palavras, letras, mascara, fade };
  const DESTAQUE = { "marca-texto": marcaTexto, risco, assinatura };

  // ---------- tipos de cena: (c, cena) -> instante em que a última entrada termina
  function linhas(c, lista, t) {
    let cur = t;
    lista.forEach((ln, i) => {
      const div = el("div", `k-linha k-${ln.estilo} k-cor-${ln.cor}`);
      div.dataset.kTexto = "";
      const bloco = el("span", "k-bloco");
      const txt = el("span", "k-txt", ln.t);
      bloco.appendChild(txt);
      div.appendChild(bloco);
      c.el.appendChild(div);
      const ini = ln.em != null ? Math.max(cur, c.t0 + ln.em) : cur;
      if (ln.anim === "palavras" && i === 0) cue(ini, "rise");
      if (ln.anim === "letras" || ln.anim === "mascara") cue(ini, "whoosh-reveal");
      let fim = ANIM[ln.anim](c.tl, txt, ini);
      for (const d of ln.destaque) fim = DESTAQUE[d](c.tl, bloco, fim - F(2), c.tema);
      cur = fim - F(4);
    });
    return cur + F(4);
  }

  const frase = (c, cena) => linhas(c, cena.linhas, c.t0);

  function endcard(c, cena) {
    let t = c.t0;
    cue(t, "sting-endcard");
    const marca = el("div", `k-linha k-display k-endcard-marca k-cor-${cena.cor}`);
    marca.dataset.kTexto = "";
    const bloco = el("span", "k-bloco");
    const txt = el("span", "k-txt", c.tema.endcard_marca);
    bloco.appendChild(txt);
    marca.appendChild(bloco);
    c.el.appendChild(marca);
    t = mascara(c.tl, txt, t);
    t = assinatura(c.tl, bloco, t - F(4), c.tema);
    const tag = el("div", `k-linha k-corpo k-tagline k-cor-${cena.cor}`, cena.tagline);
    tag.dataset.kTexto = "";
    c.el.appendChild(tag);
    t = fade(c.tl, tag, t - F(6));
    const cta = el("div", "k-linha k-cta", cena.cta);
    cta.dataset.kTexto = "";
    c.el.appendChild(cta);
    c.tl.fromTo(cta, { opacity: 0, scale: 0.6 }, { opacity: 1, scale: 1, duration: F(14), ease: "back.out(2)" }, t);
    cue(t, "click-pill");
    t += F(14);
    const url = el("div", `k-linha k-url k-cor-${cena.cor}`, cena.url);
    url.dataset.kTexto = "";
    c.el.appendChild(url);
    return fade(c.tl, url, t - F(4));
  }

  function custom(c, cena) {
    const fn = customs[cena.id];
    if (!fn) throw new Error("cena custom não chamou KIT.custom(...)");
    const fim = fn(c);
    if (typeof fim !== "number" || !isFinite(fim)) throw new Error("KIT.custom precisa devolver o instante de fim (número)");
    return fim;
  }

  const TIPOS = { frase, endcard };
  const COMP = { palavras, letras, mascara, fade, marcaTexto, risco, assinatura };

  // ---------- transições: entrada da cena nova sobre a anterior
  const TRANS = {
    fade: (tl, cam, t, d) => tl.fromTo(cam, { opacity: 0 }, { opacity: 1, duration: d, ease: "power1.inOut" }, t),
  };

  // ---------- fundo, manchas, grão
  function fundo(c, cena) {
    const f = el("div", "k-fundo");
    f.style.background = `var(--k-fundo-${cena.fundo})`;
    c.layer.prepend(f);
    if (cena.fundo !== "claro") return;
    const a = el("div", "k-mancha");
    const b = el("div", "k-mancha");
    Object.assign(a.style, { left: "-260px", top: "240px" });
    Object.assign(b.style, { left: "480px", top: "1120px" });
    f.append(a, b);
    c.tl.fromTo(a, { x: 0, y: 0 }, { x: 140, y: 90, duration: 6, ease: "sine.inOut" }, c.ini);
    c.tl.fromTo(b, { x: 0, y: 0 }, { x: -160, y: -120, duration: 6, ease: "sine.inOut" }, c.ini);
  }

  function grao(tema) {
    const g = document.getElementById("k-grao");
    g.style.opacity = String(tema.grao);
    if (!tema.grao) return;
    pintores.push((tempo) => {
      const n = Math.floor((tempo * FPS) / 2);
      const r = (k) => { const x = Math.sin(n * 12.9898 + k * 78.233) * 43758.5453; return x - Math.floor(x); };
      g.style.transform = `translate(${((r(1) - 0.5) * 20).toFixed(2)}%, ${((r(2) - 0.5) * 20).toFixed(2)}%)`;
    });
  }

  // ---------- montagem
  function montar() {
    const D = window.__KIT_DADOS;
    const tema = D.tema;
    const tl = gsap.timeline({ paused: true });
    const erros = [];
    const cenas = [];
    const wmClaro = document.getElementById("k-wm-claro");
    const wmEscuro = document.getElementById("k-wm-escuro");
    const barra = document.getElementById("k-barra");
    for (const w of [wmClaro, wmEscuro]) {
      w.textContent = tema.wordmark;
      w.classList.add(`k-${tema.wordmark_fonte}`);
      w.style.fontSize = "52px";
    }
    grao(tema);
    let ini = 0;
    D.cenas.forEach((cena, i) => {
      const layer = document.getElementById(cena.id);
      const entra = i > 0 ? D.cenas[i - 1].saida : null;
      const c = { tl, layer, el: layer.querySelector(".k-conteudo"), tema, ini,
        t0: ini + (entra ? entra.dur : 0) + F(4), F, cue, C: COMP };
      fundo(c, cena);
      let fim;
      try {
        fim = cena.tipo === "custom" ? custom(c, cena) : TIPOS[cena.tipo](c, cena);
      } catch (e) {
        erros.push({ id: cena.id, motivo: String((e && e.message) || e) });
        fim = c.t0;
      }
      const saida = cena.saida ? cena.saida.dur : 0;
      const min = quadro(fim - ini + (cena.tipo === "endcard" ? 1.2 : 0.8) + saida);
      let dur = min;
      if (cena.dur != null) {
        dur = quadro(cena.dur);
        if (dur + 1e-6 < min) erros.push({ id: cena.id, motivo: `dur ${cena.dur}s abaixo do mínimo ${min.toFixed(2)}s` });
      }
      tl.set(layer, { visibility: "visible" }, ini).set(layer, { visibility: "hidden" }, ini + dur);
      if (entra) TRANS[entra.transicao](tl, layer, ini, entra.dur, tema);
      const claro = cena.fundo === "claro";
      tl.set(wmClaro, { autoAlpha: cena.fixos && claro ? 0.55 : 0 }, ini);
      tl.set(wmEscuro, { autoAlpha: cena.fixos && !claro ? 0.55 : 0 }, ini);
      if (tema.barra) tl.set(barra, { autoAlpha: cena.fixos ? 1 : 0 }, ini);
      cenas.push({ id: cena.id, ini: r3(ini), dur: r3(dur), min: r3(min), saida });
      ini += dur - saida;
    });
    const total = quadro(ini);
    if (tema.barra) tl.fromTo(barra, { scaleX: 0 }, { scaleX: 1, duration: total, ease: "none" }, 0);
    tl.to({}, { duration: 0 }, total);
    const pintar = () => { const t = tl.time(); for (const p of pintores) p(t); };
    tl.eventCallback("onUpdate", pintar);
    window.__timelines = window.__timelines || {};
    window.__timelines.main = tl;
    window.__kit = {
      duracao: r3(total), cenas, erros,
      cues: cues.slice().sort((a, b) => a.t - b.t),
      ir: (t) => { tl.seek(t, false); pintar(); },
    };
    tl.seek(0, false);
    pintar();
  }

  window.KIT = {
    custom: (fn) => { customs[document.currentScript.closest(".cena").id] = fn; },
    montar, F, FPS,
  };
})();
