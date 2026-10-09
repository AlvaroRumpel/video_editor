/* Modo documental (vídeo narrado 16:9): palco com câmera (mapa de época ou imagem), beats
   sincronizados à fala, transições ligadas (mergulho/recuo/corte), vinheta e tela final.
   Carregado depois do kit.js quando o cenas.json traz "modo": "doc".
   Tudo que depende do tempo é pintor (KIT.pintor), nunca onUpdate. */
(() => {
  "use strict";
  const W = 1920, H = 1080, DERIVA = 0.006, SAIDA = 0.35;
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

  const CSS = `
.d-palco{position:absolute;inset:0;overflow:hidden;transform-origin:50% 50%}
.d-cam{position:absolute;left:0;top:0;transform-origin:0 0}
.d-img{position:absolute;inset:0;background-size:cover;background-position:center;filter:sepia(.35) contrast(1.1) brightness(.8)}
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
.d-data .a{font:600 140px/1 var(--k-display-familia)}
.d-painel{position:absolute;right:120px;top:200px;width:560px;padding:32px 36px;background:rgba(11,10,8,.88);border-top:4px solid var(--k-acento)}
.d-painel .v{font:500 140px/1 var(--k-mono-familia)}
.d-painel .l{font:italic 400 38px var(--k-display-familia);color:#cdbf9f;margin:6px 0 20px}
.d-pontos{display:grid;grid-template-columns:repeat(25,16px);gap:5px}
.d-pontos i{width:16px;height:16px;border-radius:50%;background:var(--k-acento);opacity:.12}
.d-rotulo{position:absolute;left:120px;bottom:120px;padding-left:22px;border-left:4px solid var(--k-acento)}
.d-rotulo .n{font:600 56px var(--k-display-familia)}
.d-rotulo .p{font:600 24px var(--k-corpo-familia);letter-spacing:.2em;color:var(--k-acento);text-transform:uppercase;margin-top:6px}
.d-palavras{position:absolute;left:120px;right:120px;bottom:130px;text-align:center;font:800 110px var(--k-corpo-familia);text-transform:uppercase}
.d-palavras span{display:inline-block;margin:0 20px;position:relative;opacity:0}
.d-risco{position:absolute;left:-10px;right:-10px;top:52%;height:12px;background:#C0392B;transform:scaleX(0);transform-origin:left}
.d-veu{position:absolute;inset:0;background:rgba(0,0,0,.55)}
.d-citacao{position:absolute;left:240px;right:240px;top:300px;text-align:center}
.d-citacao .q{font:italic 400 66px/1.25 var(--k-display-familia)}
.d-citacao .a{font:600 26px var(--k-corpo-familia);letter-spacing:.2em;color:var(--k-acento);text-transform:uppercase;margin-top:28px}
.d-lista{position:absolute;left:160px;top:220px;width:1100px}
.d-lista .i{font:500 48px var(--k-corpo-familia);padding:14px 0 14px 24px;border-left:3px solid var(--k-acento);margin-bottom:14px;background:rgba(11,10,8,.6);opacity:0}
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
.d-marca{position:absolute;left:0;right:0;top:690px;text-align:center;font:500 44px var(--k-mono-familia);letter-spacing:.5em;clip-path:inset(0 100% 0 0)}
.d-titulo{position:absolute;left:200px;right:200px;top:770px;text-align:center;font:italic 400 64px var(--k-display-familia);opacity:0}
.d-guia{position:absolute;border:2px solid rgba(184,134,43,.45);opacity:0}
.d-guia .g{position:absolute;left:0;right:0;bottom:-52px;text-align:center;font:600 22px var(--k-corpo-familia);letter-spacing:.2em;color:rgba(237,230,214,.6);text-transform:uppercase}
.d-prox{position:absolute;left:0;right:0;top:130px;text-align:center;font:italic 600 76px var(--k-display-familia);opacity:0}
.d-tag{position:absolute;left:0;right:0;bottom:110px;text-align:center;font:500 30px var(--k-corpo-familia);letter-spacing:.15em;color:#cdbf9f;opacity:0}`;
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

  const BEATS = { camera: (ctx, b) => b.at };

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
        const m = el("div", "d-img");
        m.style.backgroundImage = `url("${p.arquivo}")`;
        cam.appendChild(m);
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
    KIT.pintor((t) => {
      if (t < c.ini - 0.05 || t > c.ini + cena.dur + 0.05) return;
      const st = camAt(camera, t), sc = dims.base * st.s;
      const tx = clamp(W / 2 - st.x * sc, W - dims.mw * sc, 0), ty = clamp(H / 2 - st.y * sc, H - dims.mh * sc, 0);
      cam.style.transform = `translate(${tx.toFixed(2)}px,${ty.toFixed(2)}px) scale(${sc.toFixed(5)})`;
      for (const [e, x, y, dx, dy] of ancoras) {
        e.style.left = `${(tx + x * sc + dx).toFixed(1)}px`;
        e.style.top = `${(ty + y * sc + dy).toFixed(1)}px`;
      }
    });
    if (p.tipo === "mapa") window.__docCamMapa = camAt(camera, fim);
    c.layer._doc = {
      mergulho: (t, d) => {
        const de = camAt(camera, t), [x, y] = alvo || [de.x, de.y];
        camera.ms.push({ t, d, x, y, s: de.s * 4, de });
      },
    };
    const ctx = { c, cena, hud, g, pts, base: dims.base, beats, fim, ancoras, palco, cam };
    let ultimo = c.t0;
    beats.forEach((b, i) => {
      const f = BEATS[b.faz];
      if (!f) throw new Error(`beat desconhecido: ${b.faz}`);
      ultimo = Math.max(ultimo, f(ctx, b, i));
    });
    return ultimo;
  });

  KIT.tipo("vinheta", (c) => c.t0 + 0.1);
  KIT.tipo("telafinal", (c) => c.t0 + 0.1);
  for (const n of ["mergulho", "recuo", "corte"])
    KIT.transicao(n, (tl, cam, t, d) => tl.fromTo(cam, { opacity: 0 }, { opacity: 1, duration: d }, t));

  window.__doc = { W, H, el, svg, texto, clamp, easeIO, easeOut, fmt, iniciarFx, camAt, BEATS, SAIDA };
})();
