/* Modo documental (vídeo narrado 16:9): palco com câmera (mapa de época ou imagem), beats
   sincronizados à fala, transições ligadas (mergulho/recuo/corte), vinheta e tela final.
   Carregado depois do kit.js quando o cenas.json traz "modo": "doc".
   Tudo que depende do tempo é pintor (KIT.pintor), nunca onUpdate. */
(() => {
  "use strict";
  KIT.tipo("doc", (c) => c.t0 + 0.1);
  KIT.tipo("vinheta", (c) => c.t0 + 0.1);
  KIT.tipo("telafinal", (c) => c.t0 + 0.1);
  for (const n of ["mergulho", "recuo", "corte"])
    KIT.transicao(n, (tl, cam, t, d) => tl.fromTo(cam, { opacity: 0 }, { opacity: 1, duration: d }, t));
})();
