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
  // KIT.custom(fn): contrato = UM por fragmento custom. O _html emite <script>KIT._cena="cNN"</script>
  // antes de cada fragmento; o id vem dali porque document.currentScript era null no render do HyperFrames.
  const customs = {};
  const customsVezes = {};
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

  function contador(tl, alvo, t, o) {
    const fmt = new Intl.NumberFormat(o.formato);
    const ease = gsap.parseEase("power3.out");
    const d = F(45);
    const pinta = (tempo) => {
      const p = Math.min(1, Math.max(0, (tempo - t) / d));
      alvo.textContent = `${o.prefixo}${fmt.format(Math.round(o.de + (o.valor - o.de) * ease(p)))}${o.sufixo}`;
    };
    pintores.push(pinta);
    pinta(t + d);   // texto final no DOM para a medida de layout
    cue(t, "tick");
    return t + d;
  }

  function kenBurns(tl, alvo, t, d) {
    tl.fromTo(alvo, { scale: 1 }, { scale: 1.06, duration: Math.max(d, F(1)), ease: "sine.inOut", immediateRender: false }, t);
    return t;
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

  function numero(c, cena) {
    const n = el("div", `k-linha k-numero k-${cena.estilo} k-cor-${cena.cor}`);
    n.dataset.kTexto = "";
    c.el.appendChild(n);
    fade(c.tl, n, c.t0);
    let fim = contador(c.tl, n, c.t0, cena);
    if (cena.legenda) {
      const l = el("div", `k-linha k-corpo k-legenda k-cor-${cena.cor}`, cena.legenda);
      l.dataset.kTexto = "";
      c.el.appendChild(l);
      fim = fade(c.tl, l, fim - F(20));
    }
    return fim;
  }

  function lista(c, cena) {
    c.el.classList.add("k-lista");
    let t = c.t0;
    if (cena.titulo) {
      const h = el("div", `k-linha k-punch k-lista-titulo k-cor-${cena.cor}`);
      h.dataset.kTexto = "";
      const tx = el("span", "k-txt", cena.titulo);
      h.appendChild(tx);
      c.el.appendChild(h);
      cue(t, "rise");
      t = palavras(c.tl, tx, t) - F(4);
    }
    cena.itens.forEach((item, i) => {
      const row = el("div", `k-item k-corpo k-cor-${cena.cor}`);
      row.dataset.kTexto = "";
      const m = el("span", "k-marcador k-mono");
      if (cena.marcador === "numero") m.textContent = String(i + 1).padStart(2, "0");
      else if (cena.marcador === "check") m.textContent = "✓";
      else m.appendChild(assinaturaEl(c.tema));
      row.append(m, el("span", null, item));
      c.el.appendChild(row);
      c.tl.fromTo(row, { opacity: 0, x: -24 }, { opacity: 1, x: 0, duration: F(14), ease: "power3.out" }, t);
      if (i === 0 && !cena.titulo) cue(t, "rise");
      t += F(10);
    });
    return t + F(4);
  }

  const MOLDURA = { celular: [100, 178, 880, 1564], browser: [60, 560, 960, 600], nenhuma: [0, 0, 1080, 1920] };
  const px = (e, [x, y, w, h]) => Object.assign(e.style, { left: `${x}px`, top: `${y}px`, width: `${w}px`, height: `${h}px` });

  function tela(c, cena) {
    const m = c.layer.querySelector(".k-midia");
    let raio = "0";
    if (cena.moldura === "celular") raio = "36px";
    else if (cena.moldura === "browser") raio = "0 0 24px 24px";
    let alvo = m;   // elemento que entra/sai; o kenburns escala só a imagem dentro da caixa recortada
    if (m.tagName === "IMG") {
      alvo = el("div", "k-midia-caixa");
      Object.assign(alvo.style, { position: "absolute", overflow: "hidden", borderRadius: raio });
      m.replaceWith(alvo);
      alvo.appendChild(m);
      Object.assign(m.style, { left: "0", top: "0", width: "100%", height: "100%" });
      px(alvo, MOLDURA[cena.moldura]);
    } else {
      px(m, MOLDURA[cena.moldura]);
      m.style.borderRadius = raio;
    }
    if (cena.moldura === "browser") m.style.objectPosition = "top";
    const grupo = [alvo];
    if (cena.moldura === "celular") {
      const b = el("div", "k-moldura k-celular");
      px(b, [92, 170, 896, 1580]);
      c.layer.appendChild(b);
      grupo.push(b);
    } else if (cena.moldura === "browser") {
      const j = el("div", "k-moldura k-janela");
      px(j, [60, 504, 960, 656]);
      const barra = el("div", "k-barra-janela");
      for (const cor of ["#A32D14", "#E8CE9A", "#6D8B5C"]) {
        const b = el("i", "k-bolinha");
        b.style.background = cor;
        barra.appendChild(b);
      }
      barra.appendChild(el("span", "k-url-janela", c.tema.url));
      j.appendChild(barra);
      c.layer.insertBefore(j, alvo);
      grupo.push(j);
    }
    c.tl.fromTo(grupo, { opacity: 0, scale: 0.96 }, { opacity: 1, scale: 1, duration: F(18), ease: "power3.out" }, c.t0);
    let fim = c.t0 + F(18);
    // ponytail: vídeo não recebe kenburns (não dá para recortar sem mover o nó <video>)
    if (cena.kenburns && m.tagName === "IMG") kenBurns(c.tl, m, fim, cena.dur - (fim - c.ini));
    if (cena.label) {
      const p = el("div", "k-pill");
      p.append(el("i"), el("span", null, cena.label));
      c.layer.appendChild(p);
      c.tl.fromTo(p, { opacity: 0, scale: 0.6 }, { opacity: 1, scale: 1, duration: F(14), ease: "back.out(2)" }, c.t0 + F(8));
      cue(c.t0 + F(8), "click-pill");
      fim = Math.max(fim, c.t0 + F(22));
    }
    return fim;
  }

  const rgb = (hex) => {
    const n = parseInt(hex.replace("#", "").slice(0, 6), 16);
    return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
  };

  // brilho da íris: anel em WebGL (shader do bloco sdf-iris, só o anel) desenhado em função do tempo
  function brilho(tl, t, d, cor) {
    const cv = document.getElementById("k-brilho");
    if (!cv._k) {
      const gl = cv.getContext("webgl", { preserveDrawingBuffer: true, premultipliedAlpha: true });
      const sh = (src, tipo) => { const s = gl.createShader(tipo); gl.shaderSource(s, src); gl.compileShader(s); return s; };
      const prog = gl.createProgram();
      gl.attachShader(prog, sh("attribute vec2 a;void main(){gl_Position=vec4(a,0.,1.);}", gl.VERTEX_SHADER));
      gl.attachShader(prog, sh(
        "precision highp float;uniform float r;uniform float env;uniform vec3 cor;" +
        "void main(){float d=distance(gl_FragCoord.xy,vec2(540.,960.));" +
        "float a=(exp(-abs(d-r)/14.)+.45*exp(-abs(d-r-28.)/26.))*env*.85;a=clamp(a,0.,1.);" +
        "gl_FragColor=vec4(cor*a,a);}", gl.FRAGMENT_SHADER));
      gl.linkProgram(prog);
      gl.useProgram(prog);
      gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
      const loc = gl.getAttribLocation(prog, "a");
      gl.enableVertexAttribArray(loc);
      gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
      const ease = gsap.parseEase("power2.inOut");
      const uR = gl.getUniformLocation(prog, "r");
      const uE = gl.getUniformLocation(prog, "env");
      const uC = gl.getUniformLocation(prog, "cor");
      const k = { lista: [] };
      cv._k = k;
      pintores.push((tempo) => {
        gl.viewport(0, 0, 1080, 1920);
        gl.clearColor(0, 0, 0, 0);
        gl.clear(gl.COLOR_BUFFER_BIT);
        const b = k.lista.find((x) => tempo > x.t && tempo < x.t + x.d);
        if (!b) return;
        const q = (tempo - b.t) / b.d;
        gl.uniform1f(uR, ease(q) * 1110);
        gl.uniform1f(uE, 4 * q * (1 - q));
        gl.uniform3fv(uC, b.cor);
        gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
      });
    }
    cv._k.lista.push({ t, d, cor: rgb(cor) });
    // canvas WebGL só aparece durante a íris: em backend de software ele pinta um véu branco fora dela
    tl.set(cv, { visibility: "visible" }, t).set(cv, { visibility: "hidden" }, t + d);
  }

  function custom(c, cena) {
    if (customsVezes[cena.id] > 1) throw new Error(`KIT.custom chamado ${customsVezes[cena.id]}x (use uma vez por fragmento)`);
    const fn = customs[cena.id];
    if (!fn) throw new Error("cena custom não chamou KIT.custom(...)");
    const fim = fn(c);
    if (typeof fim !== "number" || !isFinite(fim)) throw new Error("KIT.custom precisa devolver o instante de fim (número)");
    return fim;
  }

  const TIPOS = { frase, endcard, numero, lista, tela };
  const COMP = { palavras, letras, mascara, fade, marcaTexto, risco, assinatura, contador, kenBurns };

  // ---------- transições: entrada da cena nova sobre a anterior
  const TRANS = {
    fade: (tl, cam, t, d) => tl.fromTo(cam, { opacity: 0 }, { opacity: 1, duration: d, ease: "power1.inOut" }, t),
    wipe: (tl, cam, t, d) => tl.fromTo(cam, { clipPath: "inset(0% 100% 0% 0%)" },
      { clipPath: "inset(0% 0% 0% 0%)", duration: d, ease: "power3.inOut" }, t),
    iris: (tl, cam, t, d, tema) => {
      tl.fromTo(cam, { clipPath: "circle(0px at 50% 50%)" },
        { clipPath: "circle(1110px at 50% 50%)", duration: d, ease: "power2.inOut" }, t);
      brilho(tl, t, d, tema.acento);
    },
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
    // relógio: escrita de propriedade roda mesmo com seek({suppressEvents}), ao contrário do onUpdate
    const relogio = { _t: 0, get t() { return this._t; }, set t(v) { this._t = v; for (const p of pintores) p(v); } };
    tl.fromTo(relogio, { t: 0 }, { t: total, duration: total, ease: "none" }, 0);
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
    _cena: null,
    custom: (fn) => {
      const id = window.KIT._cena;
      customs[id] = fn;
      customsVezes[id] = (customsVezes[id] || 0) + 1;
    },
    montar, F, FPS,
  };
})();
