/* Ações ilustradas (beat "acao"): vinhetas animadas de atores em silhueta de gravura sobre o palco da cena.
   Carregado depois do doc.js quando o cenas.json traz beats "acao". Tudo que depende do tempo é timeline GSAP. */
(() => {
  "use strict";
  const { BEATS } = window.__doc;
  BEATS.acao = () => { throw new Error("acao: modelos ainda não implementados"); };
})();
