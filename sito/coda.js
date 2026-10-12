"use strict";
const codaApi = document.querySelector("script[data-api]")?.dataset.api;
if (codaApi) {
  fetch(codaApi, {credentials: "omit", signal: AbortSignal.timeout(8000)})
    .then(r => { if (!r.ok) throw new Error("Servizio non disponibile"); return r.json(); })
    .then(dati => {
      for (const nodo of document.querySelectorAll("[data-progetto]")) {
        const n = dati.projects?.[nodo.dataset.progetto]?.supporters;
        if (!Number.isSafeInteger(n) || n < 0) continue;
        nodo.textContent = `${n} ${n === 1 ? "persona ha" : "persone hanno"} dedicato il sostegno a questo gioco.`;
        nodo.hidden = false;
      }
    }).catch(() => {}); // La coda e le istruzioni restano consultabili anche senza il servizio.
}
