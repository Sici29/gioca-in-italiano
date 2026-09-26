/* Gioca in Italiano - logica dell'interfaccia.
 *
 * Python fa il lavoro pesante e manda eventi con window.hubEvent(); qui si
 * disegna soltanto. Ogni chiamata verso Python passa da pywebview.api.
 */
'use strict';

const S = {
  projects: [],
  summary: {},
  library: {},
  boot: {},
  filter: 'tutte',
  query: '',
  sort: 'perte',
  installing: {},
  // Operazioni dell'installer in corso (controllo, ripristino...), il loro
  // esito e le righe che l'installer ha scritto: una voce per traduzione.
  operazioni: {},
  esiti: {},
  registri: {},
  proposals: [],
  voted: {},
  auth: {},
  oauth: {},
  setupSbloccato: false,
  loginUrl: '',
  rate: null,
  checkedAt: null,
  source: '',
  hubUpdate: null,
  drawerRepo: '',
  lastFocus: null,
};

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

/* Aggancia un gestore solo se l'elemento c'e' davvero. Serve a non far
 * cadere tutto lo script quando si rimuove un pulsante dall'HTML: senza
 * questo, un singolo selettore a vuoto interrompe l'esecuzione e tutto cio'
 * che viene dopo, avvio compreso, non viene mai registrato. */
function on(sel, event, handler) {
  const el = $(sel);
  if (el) el.addEventListener(event, handler);
  else console.warn('elemento assente, gestore ignorato:', sel);
}

/* ------------------------------------------------------------- utilita' - */

function esc(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/* useGrouping: 'always' e' necessario, non pignoleria: in italiano il
 * raggruppamento predefinito salta i numeri di quattro cifre, e 1284 sarebbe
 * uscito senza punto. */
const nf = new Intl.NumberFormat('it-IT', { useGrouping: 'always' });
const nf1 = new Intl.NumberFormat('it-IT', {
  useGrouping: 'always',
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});
const fmtNum = (n) => nf.format(Number(n) || 0);

function fmtDate(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleDateString('it-IT', { day: 'numeric', month: 'short', year: 'numeric' });
}

function relTime(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const secs = (Date.now() - d.getTime()) / 1000;
  const rtf = new Intl.RelativeTimeFormat('it', { numeric: 'auto' });
  const steps = [
    [60, 'second', 1],
    [3600, 'minute', 60],
    [86400, 'hour', 3600],
    [604800, 'day', 86400],
    [2629800, 'week', 604800],
    [31557600, 'month', 2629800],
  ];
  for (const [limit, unit, div] of steps) {
    if (secs < limit) return rtf.format(-Math.round(secs / div), unit);
  }
  return rtf.format(-Math.round(secs / 31557600), 'year');
}

function fmtSpeed(bytesAlSecondo) {
  const n = Number(bytesAlSecondo) || 0;
  if (n <= 0) return '';
  if (n < 1024 * 1024) return `${fmtNum(Math.round(n / 1024))} KB/s`;
  return `${nf1.format(n / 1048576)} MB/s`;
}

function fmtEta(secondi) {
  const s = Math.round(Number(secondi) || 0);
  if (s <= 0) return '';
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60);
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60} min`;
}

function fmtSize(bytes) {
  const n = Number(bytes) || 0;
  if (!n) return '—';
  // toFixed userebbe il punto: in italiano il separatore decimale e' la virgola.
  if (n < 1024 * 1024) return `${fmtNum(Math.round(n / 1024))} KB`;
  return `${nf1.format(n / 1048576)} MB`;
}

/* Markdown ridotto all'essenziale: le note di rilascio usano poco piu' di
 * titoli, elenchi, grassetto e codice. */
function md(text) {
  const out = [];
  let inList = false;
  for (const raw of String(text || '').split(/\r?\n/)) {
    let line = esc(raw.trim());
    if (!line) {
      if (inList) { out.push('</ul>'); inList = false; }
      continue;
    }
    line = line
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\[(.+?)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" data-external>$1</a>');

    const heading = line.match(/^#{1,6}\s+(.*)$/);
    const item = line.match(/^[-*]\s+(.*)$/);
    if (heading) {
      if (inList) { out.push('</ul>'); inList = false; }
      out.push(`<h4>${heading[1]}</h4>`);
    } else if (item) {
      if (!inList) { out.push('<ul>'); inList = true; }
      out.push(`<li>${item[1]}</li>`);
    } else {
      if (inList) { out.push('</ul>'); inList = false; }
      out.push(`<p>${line}</p>`);
    }
  }
  if (inList) out.push('</ul>');
  return out.join('');
}

async function api(method, ...args) {
  if (!window.pywebview || !window.pywebview.api || !window.pywebview.api[method]) return null;
  try {
    return await window.pywebview.api[method](...args);
  } catch (err) {
    console.error(method, err);
    return null;
  }
}

/* ---------------------------------------------------------------- toast - */

let toastTimer = null;
function toast(text, kind = 'info') {
  const el = $('#toast');
  el.textContent = text;
  el.className = `toast is-${kind}`;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, kind === 'error' ? 7000 : 4000);
}

/* -------------------------------------------------------------- render - */

/* Ricerca indifferente ad accenti e maiuscole: "pokemon" deve trovare
 * "Pokémon", e nessuno scrive gli accenti in un campo di ricerca. */
function piatto(testo) {
  return String(testo || '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase();
}

/*
 * L'ordine "Per te". Il criterio non e' la data ma quanto ti riguarda: prima
 * i giochi che hai davvero e che aspettano un aggiornamento, poi quelli che
 * hai e che potresti tradurre, e via cosi'. Chi apre l'hub di solito vuole
 * sapere "c'e' qualcosa da fare per me?", non "cos'e' uscito per ultimo".
 */
function urgenza(p) {
  if (p.installed_game && p.status === 'aggiornamento') return 0;
  if (p.installed_game && !p.installed_tag) return 1;
  if (p.installed_game) return 2;
  if (p.status === 'aggiornamento') return 3;
  if (p.installed_tag) return 4;
  return 5;
}

/*
 * Una riga sola dalle note di rilascio: sulla card risponde alla domanda che
 * uno si fa davanti al pulsante "Aggiorna", cioe' "aggiorna cosa?".
 *
 * Non e' semplicemente la prima riga. Le note cominciano quasi sempre con un
 * titolo che ripete il nome del gioco e la versione - roba che sulla card c'e'
 * gia' due volte - quindi i titoli si saltano e si preferisce il primo punto
 * elenco, che e' dove sta il cambiamento vero.
 */
function ripulisci(riga) {
  return riga
    .replace(/^[\s>#*\-+]+/, '')
    .replace(/^\d+[.)]\s*/, '')
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, '$1')  // link e immagini: resta il testo
    .replace(/[*_`~]/g, '')
    .replace(/:$/, '')
    .trim();
}

function primaRiga(testo) {
  const righe = String(testo || '').split(/\r?\n/);
  let ripiego = '';

  for (const riga of righe) {
    const grezza = riga.trim();
    if (!grezza) continue;

    const pulita = ripulisci(grezza);
    if (pulita.length <= 3) continue;

    if (/^[-*+]\s/.test(grezza) || /^\d+[.)]\s/.test(grezza)) return pulita;
    // Un titolo non e' un cambiamento: al massimo e' meglio di niente.
    if (!ripiego && !grezza.startsWith('#')) ripiego = pulita;
  }
  return ripiego;
}

/*
 * Compatibilita' fra la traduzione e il gioco installato.
 *
 * Le parole sono la parte delicata. "Incompatibile" sarebbe falso: una patch
 * puo' non toccare una riga di testo, e allora la traduzione funziona lo
 * stesso. Si riferisce quello che si sa - il gioco e' stato aggiornato dopo -
 * e la conclusione la trae chi legge. Quando non si sa niente, non compare
 * niente: una rassicurazione inventata e' peggio del silenzio.
 */
const COMPAT = {
  allineata: {
    cls: 'ok',
    breve: '',
    lungo: 'In pari con la versione del gioco che hai',
  },
  gioco_avanti: {
    cls: 'warn',
    breve: 'Gioco più nuovo',
    lungo: 'Il gioco ha ricevuto un aggiornamento dopo questa traduzione: qualche testo potrebbe restare in inglese',
  },
  traduzione_avanti: {
    cls: 'info',
    breve: 'Aggiorna il gioco',
    lungo: 'Questa traduzione è fatta per una versione del gioco più recente della tua: aggiorna il gioco',
  },
};

/*
 * Quando la compatibilita' merita di essere mostrata.
 *
 * Le date di Steam dicono un fatto solo in una direzione. "Il gioco e' stato
 * aggiornato dopo la traduzione" e' vero e basta. "Non e' stato aggiornato
 * dopo", invece, non prova che la traduzione sia fatta per quella build:
 * mostrarlo con un pallino verde e la parola "allineata" era una promessa
 * che l'hub non poteva mantenere. Quindi il verde compare solo quando c'e'
 * una build o una serie dichiarata a confermarlo, e sulla card l'avviso
 * compare solo quando e' certo: un falso allarme ripetuto rende invisibile
 * anche quello vero.
 */
function compatDaMostrare(c, dove) {
  const voce = COMPAT[(c || {}).stato];
  if (!voce) return null;
  const certa = c.certezza === 'esatta' || c.certezza === 'serie';
  if (c.stato === 'allineata' && !certa) return null;
  if (dove === 'card' && (!certa || !voce.breve)) return null;
  return voce;
}

/*
 * Il pulsante principale fa la cosa piu' utile in quel momento. Quando la
 * traduzione e' installata e in pari, reinstallarla non serve quasi mai:
 * serve giocare. "Reinstalla" resta nel menu Altro dei dettagli.
 */
function azionePrincipale(p) {
  const repo = esc(p.repo);
  const scaricabile = !!((p.latest || {}).download);
  if (p.status === 'aggiornato' && p.avvio) {
    return { label: 'Gioca', attr: `data-gioca="${repo}"`, gioca: true };
  }
  const label = p.status === 'aggiornamento' ? 'Aggiorna'
    : p.status === 'aggiornato' ? 'Reinstalla' : 'Installa';
  return { label, attr: `data-install="${repo}" ${scaricabile ? '' : 'disabled'}` };
}

const ICONA_GIOCA = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M5 3.2v9.6L12.6 8z" fill="currentColor"/></svg>';

function statusOf(p) {
  if (p.status === 'aggiornamento') return { label: 'Aggiorna', cls: 'badge-update', text: 'AGGIORNAMENTO' };
  if (p.status === 'aggiornato') return { label: 'Reinstalla', cls: 'badge-installed', text: 'INSTALLATA' };
  return { label: 'Installa', cls: '', text: '' };
}

function cardHtml(p) {
  const latest = p.latest || {};
  const azione = azionePrincipale(p);
  // Un badge solo per lo stato. Prima ne comparivano due insieme,
  // "Aggiornata" e "Da aggiornare", e in italiano il primo si legge "e' gia'
  // a posto": l'opposto di quello che voleva dire. Qui vince il piu' utile.
  const badges = [];
  if (p.status === 'aggiornamento') {
    badges.push('<span class="badge badge-update">Da aggiornare</span>');
  } else if (p.novita === 'nuova') {
    badges.push('<span class="badge badge-new">Nuova</span>');
  } else if (p.novita === 'aggiornamento') {
    badges.push('<span class="badge badge-update">Nuova versione</span>');
  } else if (p.status === 'aggiornato') {
    badges.push('<span class="badge badge-installed">Installata</span>');
  }

  const avviso = compatDaMostrare(p.compat, 'card');
  if (avviso) {
    badges.push(
      `<span class="badge badge-${avviso.cls}" title="${esc(avviso.lungo)}">${avviso.breve}</span>`
    );
  }

  const owned = p.installed_game
    ? `<span class="card-owned" title="Rilevato su questo PC tramite ${esc(p.game_source)}">
         <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8.5l3.2 3.2L13 5" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>
         Ce l'hai
       </span>`
    : '';

  const stellata = ((S.auth || {}).starred || []).includes(p.repo);
  const stella = `
    <button class="card-star${stellata ? ' is-starred' : ''}" data-star="${esc(p.repo)}"
            title="${stellata ? 'Togli la stella' : 'Metti una stella su GitHub'}">
      <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1.6 9.9 5.7l4.5.5-3.4 3 1 4.4L8 11.3 4 13.6l1-4.4-3.4-3 4.5-.5z"
        fill="${stellata ? 'currentColor' : 'none'}" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/></svg>
      <span>${fmtNum(p.stars)}</span>
    </button>`;

  // Cosa porta l'aggiornamento, in una riga. Solo quando serve davvero:
  // su una traduzione gia' allineata sarebbe rumore.
  const cambia = p.status === 'aggiornamento' ? primaRiga(latest.body) : '';
  const nota = cambia
    ? `<p class="card-cambia" title="${esc(cambia)}">${esc(cambia)}</p>`
    : '';

  const progress = S.installing[p.repo];
  const cover = p.cover
    ? `<img src="${p.cover}" alt="" draggable="false">`
    : '<div style="width:100%;height:100%;background:var(--surface-2)"></div>';

  return `
  <article class="card${p.installed_game && p.status === 'aggiornamento' ? ' card-urgente' : ''}"
           data-repo="${esc(p.repo)}" style="--tinta:${esc(p.tinta || 'var(--accent)')}">
    <div class="card-art" data-open="${esc(p.repo)}">
      ${cover}
      <div class="card-badges">${badges.join('')}</div>
      ${stella}
      ${owned}
    </div>
    <div class="card-progress${progress && progress.fase === 'run' ? ' is-indeterminate' : ''}"><div style="width:${progress ? progress.percent : 0}%"></div></div>
    <div class="card-body">
      <h3 class="card-title">${esc(p.title)}</h3>
      <div class="card-meta">
        <span class="card-version">${esc(latest.tag || 'nessuna release')}</span>
        <span class="card-dot">·</span>
        <span>${esc(relTime(latest.date))}</span>
        <span class="card-dot">·</span>
        <span>${fmtNum(p.total_downloads)} download</span>
      </div>
      ${nota}
    </div>
    <div class="card-actions">
      ${progress && progress.fase === 'run'
        // Durante l'installazione vera niente "Annulla": fermare l'installer
        // mentre copia i file lascerebbe il gioco a meta'. Si annulla solo
        // lo scaricamento.
        ? `<button class="btn btn-primary" disabled>Installo…</button>
           <button class="btn btn-ghost" data-open="${esc(p.repo)}">Dettagli</button>`
        : progress
          ? `<button class="btn btn-primary" disabled>${Math.round(progress.percent || 0)}%</button>
             <button class="btn btn-ghost" data-cancel="${esc(p.repo)}">Annulla</button>`
          : `<button class="btn btn-primary${azione.gioca ? ' btn-gioca' : ''}" ${azione.attr}>
               ${azione.gioca ? ICONA_GIOCA : ''}${azione.label}
             </button>
             <button class="btn btn-ghost" data-open="${esc(p.repo)}">Dettagli</button>`}
    </div>
    <div class="card-download" ${progress && progress.testo ? '' : 'hidden'}>${esc(progress ? progress.testo || '' : '')}</div>
  </article>`;
}

function visibleProjects() {
  let list = S.projects.slice();

  if (S.filter === 'mie') list = list.filter((p) => p.installed_game);
  else if (S.filter === 'aggiornare') list = list.filter((p) => p.status === 'aggiornamento');
  else if (S.filter === 'installate') list = list.filter((p) => p.installed_tag);

  const q = piatto(S.query.trim());
  if (q) {
    list = list.filter((p) => piatto(`${p.title} ${p.repo} ${p.description}`).includes(q));
  }

  const perData = (a, b) => {
    const da = (a.latest && a.latest.date) || '';
    const db = (b.latest && b.latest.date) || '';
    return db.localeCompare(da);
  };

  if (S.sort === 'nome') list.sort((a, b) => a.title.localeCompare(b.title, 'it'));
  else if (S.sort === 'download') list.sort((a, b) => b.total_downloads - a.total_downloads);
  else if (S.sort === 'perte') {
    list.sort((a, b) => urgenza(a) - urgenza(b) || perData(a, b));
  } else list.sort(perData);
  return list;
}

function renderGrid() {
  const list = visibleProjects();
  const grid = $('#grid');
  const empty = $('#empty');

  const conteggio = $('#result-count');
  if (conteggio) {
    const totale = S.projects.length;
    conteggio.textContent = list.length === totale
      ? `${fmtNum(totale)} ${totale === 1 ? 'traduzione' : 'traduzioni'}`
      : `${fmtNum(list.length)} di ${fmtNum(totale)}`;
    conteggio.hidden = !totale;
  }

  const cercato = S.query.trim();
  const proponi = $('#empty-propose');

  if (!list.length) {
    grid.innerHTML = '';
    empty.hidden = false;
    if (S.filter === 'mie') {
      $('#empty-title').textContent = 'Nessuno di questi giochi risulta installato';
      $('#empty-body').textContent =
        'L’hub cerca in Steam, Epic, GOG e nei programmi installati. Se il gioco c’è ma non viene visto, aprilo almeno una volta dal suo launcher.';
    } else if (cercato) {
      $('#empty-title').textContent = `Nessuna traduzione per «${cercato}»`;
      $('#empty-body').textContent =
        'Non esiste ancora. Se la vuoi, proponila: le più votate sono quelle a cui do la precedenza.';
    } else {
      $('#empty-title').textContent = 'Nessun risultato';
      $('#empty-body').textContent = 'Prova a cambiare filtro o testo di ricerca.';
    }
    // Una ricerca a vuoto e' il momento esatto in cui sai cosa vorresti:
    // chiederlo qui costa un clic, tornarci dopo non capita quasi mai.
    if (proponi) {
      proponi.hidden = !cercato || S.filter === 'mie';
      proponi.textContent = `Proponi «${cercato}»`;
    }
    return;
  }
  if (proponi) proponi.hidden = true;
  empty.hidden = true;
  grid.innerHTML = list.map(cardHtml).join('');
}

/*
 * I numeri in cima salgono fino al loro valore invece di comparire. Dura un
 * terzo di secondo: non e' un effetto, e' il modo di far capire che quel
 * numero e' stato appena ricalcolato. Parte solo quando cambia davvero,
 * altrimenti ogni ridisegno della pagina farebbe ripartire il conto.
 */
function conta(el, valore) {
  if (!el) return;
  const arrivo = Number(valore) || 0;
  const partenza = Number(el.dataset.valore);

  if (partenza === arrivo) return;
  el.dataset.valore = String(arrivo);

  const fermo = matchMedia('(prefers-reduced-motion: reduce)').matches;
  // Da zero, o per uno scarto di uno, l'animazione non aggiunge niente.
  if (fermo || !Number.isFinite(partenza) || Math.abs(arrivo - partenza) < 2) {
    el.textContent = fmtNum(arrivo);
    return;
  }

  const durata = 340;
  const avvio = performance.now();
  const passo = (ora) => {
    const t = Math.min(1, (ora - avvio) / durata);
    const morbido = 1 - Math.pow(1 - t, 3);
    el.textContent = fmtNum(Math.round(partenza + (arrivo - partenza) * morbido));
    if (t < 1) requestAnimationFrame(passo);
  };
  requestAnimationFrame(passo);
}

function renderStats() {
  const s = S.summary;
  if (s.count === undefined) $('#stat-count').textContent = '—';
  else conta($('#stat-count'), s.count);
  $('#stat-count-note').textContent = s.count === 1 ? 'in catalogo' : 'in catalogo';

  conta($('#stat-updates'), s.updates || 0);
  $('#stat-updates-box').classList.toggle('is-alert', (s.updates || 0) > 0);
  $('#stat-updates-note').textContent = s.updates
    ? 'da scaricare'
    : (s.installed ? 'tutto a posto' : 'nessuna installata');

  conta($('#stat-downloads'), s.downloads);
  $('#stat-releases-note').textContent = `${fmtNum(s.releases)} release pubblicate`;

  conta($('#stat-owned'), s.owned || 0);
  const lib = S.library || {};
  $('#stat-library-note').textContent = lib.count
    ? `su ${fmtNum(lib.count)} programmi trovati`
    : 'nessuna libreria rilevata';

  // Contatori sui filtri: aiutano a capire cosa c'e' dietro ogni chip.
  const counts = {
    tutte: S.projects.length,
    mie: S.projects.filter((p) => p.installed_game).length,
    aggiornare: S.projects.filter((p) => p.status === 'aggiornamento').length,
    installate: S.projects.filter((p) => p.installed_tag).length,
  };
  $$('.chip').forEach((chip) => {
    chip.dataset.count = fmtNum(counts[chip.dataset.filter] || 0);
  });
}

function renderBanner() {
  const novita = S.projects.filter((p) => p.novita);
  const banner = $('#banner');
  if (!novita.length) { banner.hidden = true; return; }

  const nuove = novita.filter((p) => p.novita === 'nuova');
  const agg = novita.filter((p) => p.novita === 'aggiornamento');
  const parti = [];
  if (nuove.length) parti.push(`${nuove.length} ${nuove.length === 1 ? 'nuova traduzione' : 'nuove traduzioni'}`);
  if (agg.length) parti.push(`${agg.length} ${agg.length === 1 ? 'aggiornata' : 'aggiornate'}`);

  $('#banner-title').textContent = 'Novità dall’ultima volta';
  $('#banner-body').textContent = `${parti.join(' e ')}: ${novita.map((p) => p.title).join(', ')}.`;
  banner.hidden = false;
}

function renderBoard() {
  const list = $('#board-list');
  const empty = $('#board-empty');
  const items = S.proposals || [];

  if (!items.length) {
    list.innerHTML = '';
    empty.hidden = false;
    return;
  }
  empty.hidden = true;

  list.innerHTML = items.map((p) => {
    const voted = S.voted[String(p.number)] ? ' is-voted' : '';
    const titolo = String(p.title || '').replace(/^\[Proposta\]\s*/i, '');
    const meta = [];
    if (p.comments) meta.push(`${fmtNum(p.comments)} ${p.comments === 1 ? 'commento' : 'commenti'}`);
    meta.push(`aperta ${relTime(p.created)}`);
    return `
    <li class="proposal">
      <button class="vote${voted}" data-vote="${p.number}" title="Vota questa proposta">
        <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 3.2 13.2 10H2.8z" fill="currentColor"/></svg>
        <strong>${fmtNum(p.votes)}</strong>
      </button>
      <div class="proposal-text">
        <strong>${esc(titolo)}</strong>
        <span>${esc(meta.join(' · '))}</span>
      </div>
      ${p.in_lavorazione ? '<span class="proposal-state">In lavorazione</span>' : ''}
    </li>`;
  }).join('');
}

/* L'avviso spiega cosa e' successo e, quando ha senso, offre di riprovare
 * subito invece di lasciare la persona a chiedersi cosa fare. */
function mostraAvviso(errore) {
  const box = $('#notice');
  const testo = $('#notice-text');
  const riprova = $('#notice-retry');

  if (!errore) {
    box.hidden = true;
    return;
  }
  // Qui arrivano solo codici, mai il testo di un'eccezione: le parole le
  // sceglie la finestra. Prima compariva "401 Client Error: Unauthorized for
  // url: https://api.github.com/..." a chi voleva solo vedere le traduzioni.
  if (errore === 'rate_limit') {
    testo.textContent =
      'GitHub chiede una pausa: ti mostro le traduzioni dell’ultimo controllo e riprovo da solo più tardi.';
    box.className = 'notice is-warn';
    riprova.hidden = true;
  } else {
    testo.textContent =
      'GitHub non risponde: ti mostro le traduzioni dell’ultimo controllo e riprovo da solo fra poco.';
    box.className = 'notice is-warn';
    riprova.hidden = false;
  }
  box.hidden = false;
}

function renderHubUpdate() {
  const box = $('#hub-update');
  const u = S.hubUpdate;
  if (!u || !u.available || S.updateDismissed) {
    box.hidden = true;
    return;
  }
  const pezzi = [`Sei alla ${u.current}, l'ultima è la ${u.version}`];
  if (u.asset && u.asset.size) pezzi.push(fmtSize(u.asset.size));
  $('#hub-update-body').textContent = pezzi.join(' · ') + '.';
  box.hidden = false;
}

function renderFollow() {
  const btn = $('#btn-follow');
  if (!btn) return;
  const a = S.auth || {};
  btn.classList.toggle('is-following', !!a.following);
  $('#follow-label').textContent = a.following
    ? `Segui ${S.boot.user || ''}`.trim()
    : 'Segui su GitHub';
  btn.title = a.following ? 'Smetti di seguire' : 'Segui su GitHub';
}

function renderAccount() {
  const btn = $('#btn-account');
  const a = S.auth || {};

  // Il pulsante resta sempre visibile. Nasconderlo quando manca il Client ID
  // faceva sembrare l'accesso rotto invece che da configurare: meglio un
  // pulsante che spiega cosa manca di un pulsante che non c'e'.
  btn.hidden = false;
  btn.classList.toggle('is-disabled', !a.configured);
  $('#account-label').textContent = a.logged_in ? a.login : 'Accedi';
  btn.title = !a.configured
    ? 'Accesso in-app non attivo: si attiva dalle impostazioni'
    : a.logged_in
      ? 'Esci da GitHub'
      : 'Facoltativo: collegati per stellare, votare e proporre senza aprire il browser';
}

/* Un aggiornamento automatico arriva mentre la persona sta guardando la
 * pagina: ridisegnare e basta la riporterebbe in cima e le chiuderebbe il
 * pannello sotto il naso. Qui si rimette tutto dov'era. */
function render() {
  const scorrimento = window.scrollY;
  const pannelloAperto = S.drawerRepo && !$('#drawer').hidden;

  renderStats();
  renderBanner();
  renderHubUpdate();
  renderGrid();
  renderBoard();

  if (scorrimento) window.scrollTo({ top: scorrimento });
  if (pannelloAperto) openDrawer(S.drawerRepo, { silenzioso: true });
}

function renderSkeleton() {
  $('#grid').innerHTML = Array.from({ length: 4 })
    .map(() => `<article class="card skeleton"><div class="sk sk-art"></div><div class="sk sk-line"></div><div class="sk sk-line short"></div><div style="height:15px"></div></article>`)
    .join('');
}

/* ------------------------------------------------------ fuoco da tastiera - */
/*
 * Quando si apre un pannello o una finestra, il fuoco deve entrarci dentro e
 * restarci: altrimenti chi naviga con il tabulatore si ritrova a percorrere
 * la pagina sottostante senza vedere dove sta andando. Alla chiusura torna
 * dove era prima.
 */

const SELETTORE_FUOCO =
  'button:not([disabled]), [href], input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])';

function attivabili(contenitore) {
  return Array.from(contenitore.querySelectorAll(SELETTORE_FUOCO)).filter(
    (el) => el.offsetParent !== null || el === document.activeElement
  );
}

function apriConFuoco(contenitore) {
  S.lastFocus = document.activeElement;
  const elementi = attivabili(contenitore);
  if (elementi.length) elementi[0].focus();
}

function restituisciFuoco() {
  if (S.lastFocus && document.contains(S.lastFocus)) {
    try { S.lastFocus.focus(); } catch (e) { /* elemento sparito */ }
  }
  S.lastFocus = null;
}

function contenitoreAperto() {
  for (const sel of ['#modal-propose', '#modal-login', '#modal-oauth', '#modal-tasti', '#drawer', '#settings']) {
    const el = $(sel);
    if (el && !el.hidden) return el;
  }
  return null;
}

document.addEventListener('keydown', (ev) => {
  if (ev.key !== 'Tab') return;
  const contenitore = contenitoreAperto();
  if (!contenitore) return;

  const elementi = attivabili(contenitore);
  if (!elementi.length) return;
  const primo = elementi[0];
  const ultimo = elementi[elementi.length - 1];

  if (ev.shiftKey && document.activeElement === primo) {
    ev.preventDefault();
    ultimo.focus();
  } else if (!ev.shiftKey && document.activeElement === ultimo) {
    ev.preventDefault();
    primo.focus();
  }
});

/* -------------------------------------------------------------- drawer - */

/* --------------------------------------- l'installer, dentro i dettagli - */

/* Il pulsante principale dei dettagli: lo stesso della card, ma mentre
 * l'installer lavora dice che sta lavorando invece di offrirsi di nuovo. */
function pulsantePrincipale(p) {
  const inCorso = S.installing[p.repo];
  if (inCorso) {
    const testo = inCorso.fase === 'run' ? 'Installo…' : `${Math.round(inCorso.percent || 0)}%`;
    return `<button class="btn btn-primary" disabled>${testo}</button>`;
  }
  const azione = azionePrincipale(p);
  const occupato = S.operazioni[p.repo] ? 'disabled' : '';
  return `<button class="btn btn-primary${azione.gioca ? ' btn-gioca' : ''}" ${azione.attr} ${occupato}>
      ${azione.gioca ? ICONA_GIOCA : ''}${azione.label}
    </button>`;
}

/*
 * Il menu dell'installer, riportato nell'hub. Delle sue voci originali qui
 * mancano solo quelle che l'hub fa gia' per conto suo: "controlla se esiste
 * una nuova versione" (e' il suo mestiere) e "crediti e sostieni il progetto"
 * (sta in fondo alla pagina). Per tutto il resto c'e' "Apri l'installer
 * completo", che lo apre com'era, col suo menu.
 */
function menuAltro(p) {
  const repo = esc(p.repo);
  const profilo = p.installer || {};
  const occupato = S.operazioni[p.repo] || S.installing[p.repo] ? 'disabled' : '';
  const voce = (attributi, testo, extra = '') =>
    `<button class="menu-voce${extra}" type="button" role="menuitem" ${attributi}>${testo}</button>`;

  const voci = ['<p class="menu-titolo">Traduzione</p>'];
  if (profilo.check && p.installed_game) {
    voci.push(voce(`data-azione="check" data-repo="${repo}" ${occupato}`, 'Controlla la traduzione'));
  }
  if (p.status === 'aggiornato') {
    voci.push(voce(`data-install="${repo}" ${occupato}`, 'Reinstalla'));
  }
  if (profilo.restore && p.installed_game) {
    // Toglie la traduzione dal gioco: chiede conferma con un secondo clic,
    // senza aprire finestre.
    voci.push(voce(`data-conferma="restore" data-repo="${repo}" ${occupato}`,
      'Ripristina i file originali', ' menu-pericolo'));
  }
  if (profilo.backup) {
    voci.push(voce(`data-azione="backup" data-repo="${repo}"`, 'Apri la cartella dei backup'));
  }
  voci.push(voce(`data-azione="completo" data-repo="${repo}" ${occupato}`, 'Apri l’installer completo'));

  voci.push('<p class="menu-titolo">Gioco</p>');
  if (p.installed_game) {
    voci.push(voce(`data-folder="${repo}"`, 'Apri la cartella del gioco'));
  }
  if (p.cartella_scelta) {
    voci.push(voce(`data-scegli-cartella="${repo}" title="${esc(p.cartella_scelta)}"`,
      'Cambia la cartella del gioco…'));
    voci.push(voce(`data-dimentica-cartella="${repo}"`, 'Torna a cercarla da solo'));
  } else {
    voci.push(voce(`data-scegli-cartella="${repo}"`, 'Indica la cartella del gioco…'));
  }

  voci.push('<p class="menu-titolo">Aiuto</p>');
  voci.push(voce(`data-url="${esc(p.bug_url)}"`, 'Segnala un problema'));
  voci.push(voce(`data-url="${esc(p.releases_url)}"`, 'Apri su GitHub'));
  return voci.join('');
}

const NOMI_OPERAZIONE = {
  install: 'Installazione',
  check: 'Controllo',
  restore: 'Ripristino',
  backup: 'Apertura della cartella dei backup',
  completo: 'Installer aperto',
};

/* Cosa sta facendo l'installer, o com'e' andata l'ultima volta. */
function pannelloOperazione(p) {
  const repo = p.repo;
  const righe = S.registri[repo] || [];
  const inCorso = S.operazioni[repo]
    || (S.installing[repo] && S.installing[repo].fase === 'run' ? 'install' : '');

  if (inCorso) {
    const nota = inCorso === 'completo'
      ? 'L’installer è aperto nella sua finestra: quando lo chiudi, torni qui.'
      : 'Non chiudere l’hub finché non ha finito.';
    return `
      <div class="operazione in-corso">
        <div class="operazione-testa">
          <span class="operazione-rotella" aria-hidden="true"></span>
          <strong>${esc(NOMI_OPERAZIONE[inCorso] || 'Operazione')} in corso…</strong>
        </div>
        <p class="operazione-nota">${nota}</p>
        <pre class="registro registro-vivo" ${righe.length ? '' : 'hidden'}>${esc(righe.slice(-8).join('\n'))}</pre>
      </div>`;
  }

  const e = S.esiti[repo];
  if (!e) return '';
  const tipo = !e.ok ? 'errore' : e.parziale ? 'avviso' : 'ok';
  const tutte = (e.righe || []).join('\n');
  // Per un controllo le righe SONO la risposta, e si mostrano aperte; per
  // un'installazione sono il retroscena, e stanno chiuse.
  const dettagli = !tutte ? '' : e.azione === 'check'
    ? `<pre class="registro">${esc(tutte)}</pre>`
    : `<details class="operazione-dettagli"><summary>Tutto quello che ha scritto l’installer</summary><pre class="registro">${esc(tutte)}</pre></details>`;

  return `
    <div class="operazione ${tipo}">
      <div class="operazione-testa">
        <span class="operazione-punto" aria-hidden="true"></span>
        <strong>${esc(e.messaggio || (e.ok ? 'Fatto.' : 'Non riuscito.'))}</strong>
        <button class="operazione-chiudi" type="button" data-chiudi-esito="${esc(repo)}" aria-label="Chiudi">×</button>
      </div>
      ${e.consiglio ? `<p class="operazione-consiglio">${esc(e.consiglio)}</p>` : ''}
      ${dettagli}
    </div>`;
}

/* Il riquadro della compatibilita' nel pannello dei dettagli. Qui, a
 * differenza della card, si mostra anche il caso tranquillo: chi ha aperto i
 * dettagli vuole sapere, e "e' a posto" e' una risposta. */
function rigaCompat(p) {
  const voce = compatDaMostrare(p.compat, 'dettagli');
  if (!voce) return '';
  return `
    <div class="compat compat-${voce.cls}">
      <span class="compat-punto" aria-hidden="true"></span>
      <strong>${esc(voce.lungo)}</strong>
    </div>`;
}

function openDrawer(repo, opzioni = {}) {
  const p = S.projects.find((x) => x.repo === repo);
  if (!p) return;
  const latest = p.latest || {};
  S.drawerRepo = repo;

  // Le release sono in ordine dal piu' recente: tutte quelle che precedono
  // quella installata sono cambiamenti che non hai ancora.
  const elenco = (p.releases || []).slice(0, 12);
  const indiceInstallata = p.installed_tag
    ? elenco.findIndex((r) => r.tag === p.installed_tag)
    : -1;

  const releases = elenco.map((r, i) => {
    const daPrendere = indiceInstallata > 0 && i < indiceInstallata;
    const installata = p.installed_tag && r.tag === p.installed_tag;
    return `
    <div class="release${daPrendere ? ' release-nuova' : ''}">
      <div class="release-head">
        <span class="release-tag">${esc(r.tag)}</span>
        ${installata ? '<span class="release-pill">installata</span>' : ''}
        ${daPrendere ? '<span class="release-pill release-pill-nuova">non ancora installata</span>' : ''}
        <span class="release-date">${esc(fmtDate(r.date))}</span>
      </div>
      ${r.body ? `<div class="release-body">${md(r.body)}</div>` : ''}
    </div>`;
  }).join('');

  // Nel pannello resta solo quello che serve per decidere se installare:
  // che versione e', quando e' uscita, quale hai, quanto pesa. Build del
  // gioco, fonte della copertina, numero di rilasci e di download, avvisi
  // sul hub.json: diagnostica, utile a chi pubblica e rumore per chi
  // installa. Chi pubblica la trova nel registro dell'hub.
  $('#drawer-body').innerHTML = `
    <div class="drawer-hero" style="--tinta:${esc(p.tinta || 'var(--accent)')}">
      ${p.cover ? `<img src="${p.cover}" alt="" draggable="false">` : ''}
      <button class="hero-cambia" data-cover="${esc(p.repo)}" type="button"
              title="Usa un’immagine tua come copertina">Cambia immagine</button>
      <div class="drawer-hero-text">
        <h2>${esc(p.title)}</h2>
        <p>${esc(p.description || '')}</p>
      </div>
    </div>
    <div class="drawer-pad">
      ${rigaCompat(p)}

      <div class="drawer-actions">
        ${pulsantePrincipale(p)}
        ${p.avvio && !azionePrincipale(p).gioca
          ? `<button class="btn btn-ghost" data-gioca="${esc(p.repo)}">${ICONA_GIOCA}Gioca</button>`
          : ''}
        <div class="menu-contenitore">
          <button class="btn btn-ghost" data-menu-altro type="button" aria-haspopup="true" aria-expanded="false">
            Altro
            <svg class="menu-freccia" viewBox="0 0 16 16" aria-hidden="true"><path d="M4 6l4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>
          </button>
          <div class="menu" role="menu" hidden>${menuAltro(p)}</div>
        </div>
      </div>

      <div id="drawer-operazione">${pannelloOperazione(p)}</div>

      <dl class="info-grid info-grid-4">
        <div class="info-cell"><dt>Ultima versione</dt><dd class="mono">${esc(latest.tag || '—')}</dd></div>
        <div class="info-cell"><dt>Uscita</dt><dd>${esc(fmtDate(latest.date))}</dd></div>
        <div class="info-cell"><dt>La tua</dt><dd class="${p.installed_tag ? 'mono' : 'info-vuoto'}">${p.installed_tag ? esc(p.installed_tag) : 'non installata'}</dd></div>
        <div class="info-cell"><dt>Dimensione</dt><dd>${esc(fmtSize(latest.download && latest.download.size))}</dd></div>
      </dl>

      <h3 class="section-title">
        ${indiceInstallata > 0 ? `Cosa cambia rispetto alla tua versione (${indiceInstallata} ${indiceInstallata === 1 ? 'rilascio' : 'rilasci'})` : 'Cronologia rilasci'}
      </h3>
      ${releases || '<p style="color:var(--muted);font-size:13px">Nessuna release pubblicata.</p>'}
    </div>`;

  const gia = !$('#drawer').hidden;
  $('#drawer').hidden = false;
  $('#drawer-backdrop').hidden = false;
  // Un ridisegno automatico non deve rubare il fuoco a chi sta leggendo.
  if (!gia && !opzioni.silenzioso) apriConFuoco($('#drawer'));
}

function closeDrawer() {
  $('#drawer').hidden = true;
  $('#drawer-backdrop').hidden = true;
  S.drawerRepo = '';
  restituisciFuoco();
}

function openSettings() {
  const st = S.boot.settings || {};
  $('#set-auto').checked = st.auto_refresh !== false;
  $('#set-notify').checked = st.notify !== false;
  $('#set-version').textContent = S.boot.version || '—';
  $('#set-checked').textContent = S.checkedAt
    ? `Ultimo controllo ${relTime(S.checkedAt)}`
    : 'Nessun controllo ancora';
  renderHidden();
  renderAccountRiga();
  renderOauth();
  $('#settings').hidden = false;
  $('#settings-backdrop').hidden = false;
  apriConFuoco($('#settings'));
}

async function renderHidden() {
  const box = $('#hidden-list');
  if (!box) return;
  const nascosti = (await api('hidden_repos')) || [];
  if (!nascosti.length) {
    box.innerHTML = '';
    box.hidden = true;
    return;
  }
  box.hidden = false;
  box.innerHTML =
    '<p class="section-title">Traduzioni nascoste</p>' +
    nascosti.map((r) => `
      <div class="hidden-row">
        <span>${esc(r)}</span>
        <button class="btn btn-quiet" data-unhide="${esc(r)}">Mostra</button>
      </div>`).join('');
}

function closeSettings() {
  $('#settings').hidden = true;
  $('#settings-backdrop').hidden = true;
  restituisciFuoco();
}

/* -------------------------------------------------- eventi da Python - */

/* Un catalogo arriva da due parti: subito all'avvio, dall'ultimo salvato, e
 * poi dal controllo vero su GitHub. Stesso trattamento per entrambi. */
function applicaCatalogo(payload) {
  S.projects = payload.projects || [];
  S.summary = payload.summary || {};
  S.library = payload.library || {};
  S.proposals = payload.proposals || [];
  S.rate = payload.rate_remaining;
  S.checkedAt = payload.checked_at;
  S.source = payload.source || '';
  if (payload.hub_update) S.hubUpdate = payload.hub_update;
  if (payload.auth) S.auth = payload.auth;
  render();
  renderAccountRiga();
  mostraAvviso(payload.error);
}

window.hubEvent = function (msg) {
  const { event, payload } = msg || {};

  if (event === 'catalog') {
    applicaCatalogo(payload);
  } else if (event === 'loading') {
    $('#progress').hidden = !payload;
    $('#btn-refresh').disabled = !!payload;
    $('.icon-refresh').classList.toggle('is-spinning', !!payload);
  } else if (event === 'status') {
    toast(payload.text, payload.kind === 'loading' ? 'info' : payload.kind);
  } else if (event === 'install') {
    handleInstallEvent(payload);
  } else if (event === 'installer') {
    handleInstallerEvent(payload);
  } else if (event === 'hubupdate') {
    const btn = $('#hub-update-get');
    if (payload.phase === 'download') {
      btn.disabled = true;
      btn.textContent = `${Math.round(payload.percent || 0)}%`;
    } else {
      btn.disabled = false;
      btn.textContent = payload.phase === 'done' ? 'Scaricata' : 'Scarica';
    }
  } else if (event === 'auth') {
    if (payload.setup) {
      // Cambio di credenziali, non di sessione: qui non si chiude niente,
      // perche' subito dopo parte l'accesso di prova.
      S.auth = Object.assign({}, S.auth, payload.state || {});
      renderAccount();
      renderAccountRiga();
      renderOauth();
    } else if (payload.ok) {
      S.auth = Object.assign({}, S.auth, { logged_in: !!payload.login, login: payload.login });
      renderAccount();
      renderAccountRiga();
      closeModals();
    } else {
      $('#login-error').textContent = payload.error || 'Accesso non riuscito.';
      $('#login-error').hidden = false;
    }
  } else if (event === 'error') {
    toast(payload.message || 'Errore imprevisto', 'error');
  }
};

function handleInstallEvent(p) {
  const card = document.querySelector(`.card[data-repo="${CSS.escape(p.repo)}"]`);

  if (p.phase === 'download') {
    // Dire solo "43%" non basta: su una connessione lenta la gente vuole
    // sapere quanto manca prima di decidere se aspettare.
    const pezzi = [];
    if (p.total) pezzi.push(`${fmtSize(p.done)} di ${fmtSize(p.total)}`);
    const v = fmtSpeed(p.speed);
    if (v) pezzi.push(v);
    const eta = fmtEta(p.eta);
    if (eta) pezzi.push(`${eta} rimanenti`);

    // Al primo blocco la card va ridisegnata, perche' i pulsanti cambiano:
    // "Installa / Dettagli" diventa "percentuale / Annulla". Dopo basta
    // aggiornare i numeri sul posto, senza ricostruire nulla.
    const primoBlocco = !S.installing[p.repo];
    S.installing[p.repo] = { percent: p.percent || 0, testo: pezzi.join(' · ') };

    if (primoBlocco || !card) {
      renderGrid();
      return;
    }

    if (card) {
      const bar = card.querySelector('.card-progress > div');
      if (bar) bar.style.width = `${p.percent || 0}%`;
      const btn = card.querySelector('.card-actions .btn-primary');
      if (btn) btn.textContent = `${Math.round(p.percent || 0)}%`;
      const riga = card.querySelector('.card-download');
      if (riga) { riga.textContent = S.installing[p.repo].testo; riga.hidden = false; }
    } else {
      renderGrid();
    }
    return;
  }

  if (p.phase === 'run') {
    // Scaricato: ora lavora l'installer, senza finestra. Le sue righe
    // arrivano come eventi "installer" e finiscono sotto la card e nei
    // dettagli, al posto della console nera.
    S.installing[p.repo] = { percent: 100, fase: 'run', testo: 'Installazione in corso…' };
    S.registri[p.repo] = [];
    delete S.esiti[p.repo];
    renderGrid();
    aggiornaDettagli(p.repo);
    return;
  }

  delete S.installing[p.repo];
  if (p.esito) S.esiti[p.repo] = Object.assign({ azione: 'install' }, p.esito);
  renderGrid();
  aggiornaDettagli(p.repo);
}

/* Le operazioni dell'installer che partono dal menu Altro, e le righe che
 * scrive mentre lavora (installazione compresa). */
function handleInstallerEvent(p) {
  const repo = p.repo;

  if (p.riga !== undefined) {
    const righe = S.registri[repo] || (S.registri[repo] = []);
    righe.push(p.riga);
    if (righe.length > 300) righe.shift();

    if (S.installing[repo]) {
      S.installing[repo].testo = p.riga;
      const card = document.querySelector(`.card[data-repo="${CSS.escape(repo)}"]`);
      const sotto = card && card.querySelector('.card-download');
      if (sotto) { sotto.textContent = p.riga; sotto.hidden = false; }
    }
    // Solo il testo, non tutto il pannello: ridisegnarlo a ogni riga farebbe
    // saltare lo scorrimento a chi sta leggendo.
    const registro = S.drawerRepo === repo && $('#drawer-operazione .registro-vivo');
    if (registro) {
      registro.textContent = righe.slice(-8).join('\n');
      registro.hidden = false;
    }
    return;
  }

  if (p.fase === 'inizio') {
    S.operazioni[repo] = p.azione;
    S.registri[repo] = [];
    delete S.esiti[repo];
  } else if (p.fase === 'fine') {
    delete S.operazioni[repo];
    if (p.azione !== 'completo') {
      S.esiti[repo] = Object.assign({ azione: p.azione }, p.esito || {});
    }
  }
  aggiornaDettagli(repo);
}

/* Se i dettagli di quella traduzione sono aperti, li si rimette in pari. */
function aggiornaDettagli(repo) {
  if (S.drawerRepo === repo && !$('#drawer').hidden) {
    openDrawer(repo, { silenzioso: true });
  }
}

/* ------------------------------------------------------------- eventi UI - */

function chiudiMenu() {
  $$('.menu').forEach((m) => { m.hidden = true; });
  $$('[data-menu-altro]').forEach((b) => b.setAttribute('aria-expanded', 'false'));
}

/* Il gioco parte da Steam o dal launcher RSI: l'hub da' solo il via. Il
 * pulsante resta fermo un paio di secondi, perche' Steam ci mette un attimo
 * a comparire e un secondo clic impaziente avvierebbe il gioco due volte. */
async function avviaGioco(repo, pulsante) {
  if (pulsante) pulsante.disabled = true;
  const r = await api('avvia_gioco', repo);
  if (r && !r.ok) toast(r.error || 'Non sono riuscito ad avviare il gioco.', 'error');
  setTimeout(() => { if (pulsante && document.contains(pulsante)) pulsante.disabled = false; }, 2500);
}

document.addEventListener('click', (ev) => {
  const el = ev.target.closest('[data-install],[data-open],[data-url],[data-cover],[data-folder],[data-external],[data-vote],[data-cancel],[data-unhide],[data-star],[data-gioca],[data-azione],[data-conferma],[data-scegli-cartella],[data-dimentica-cartella],[data-menu-altro],[data-chiudi-esito]');

  // Un clic fuori dal menu Altro lo chiude; uno su una sua voce anche, dopo
  // averla eseguita (tranne la conferma, che deve restare lì per il secondo).
  const menuAperto = document.querySelector('.menu:not([hidden])');
  if (menuAperto && (!el || (!el.closest('.menu') && el.dataset.menuAltro === undefined))) {
    chiudiMenu();
  }
  if (!el) return;

  if (el.dataset.menuAltro !== undefined) {
    const menu = el.parentElement.querySelector('.menu');
    const apri = menu.hidden;
    chiudiMenu();
    if (apri) {
      menu.hidden = false;
      el.setAttribute('aria-expanded', 'true');
      const prima = menu.querySelector('.menu-voce:not([disabled])');
      if (prima) prima.focus();
    }
    return;
  }
  if (el.dataset.conferma !== undefined) {
    if (el.dataset.armato) {
      chiudiMenu();
      api('azione_installer', el.dataset.repo, el.dataset.conferma);
    } else {
      el.dataset.armato = '1';
      el.dataset.testo = el.textContent;
      el.textContent = 'Premi di nuovo per confermare';
      el.classList.add('is-armato');
      setTimeout(() => {
        if (!document.contains(el)) return;
        delete el.dataset.armato;
        el.textContent = el.dataset.testo;
        el.classList.remove('is-armato');
      }, 4000);
    }
    return;
  }
  if (el.closest('.menu')) chiudiMenu();

  if (el.dataset.gioca !== undefined) {
    avviaGioco(el.dataset.gioca, el);
  } else if (el.dataset.azione !== undefined) {
    api('azione_installer', el.dataset.repo, el.dataset.azione);
  } else if (el.dataset.scegliCartella !== undefined) {
    api('scegli_cartella_gioco', el.dataset.scegliCartella);
  } else if (el.dataset.dimenticaCartella !== undefined) {
    api('dimentica_cartella_gioco', el.dataset.dimenticaCartella);
  } else if (el.dataset.chiudiEsito !== undefined) {
    delete S.esiti[el.dataset.chiudiEsito];
    const pannello = $('#drawer-operazione');
    if (pannello) pannello.innerHTML = '';
  } else if (el.dataset.star !== undefined) {
    ev.stopPropagation();
    toggleStar(el.dataset.star);
  } else if (el.dataset.cancel !== undefined) {
    el.disabled = true;
    el.textContent = 'Annullo…';
    api('cancel_install', el.dataset.cancel);
  } else if (el.dataset.unhide !== undefined) {
    api('unhide_repo', el.dataset.unhide);
  } else if (el.dataset.vote !== undefined) {
    vote(el.dataset.vote);
  } else if (el.dataset.install !== undefined) {
    api('install', el.dataset.install);
  } else if (el.dataset.open !== undefined) {
    openDrawer(el.dataset.open);
  } else if (el.dataset.cover !== undefined) {
    api('pick_cover', el.dataset.cover);
  } else if (el.dataset.folder !== undefined) {
    api('open_game_folder', el.dataset.folder);
  } else if (el.dataset.url) {
    api('open_external', el.dataset.url);
  } else if (el.hasAttribute('data-external')) {
    ev.preventDefault();
    api('open_external', el.getAttribute('href'));
  }
});

on('#btn-refresh', 'click', () => api('refresh', true));
on('#btn-settings', 'click', openSettings);
on('#drawer-close', 'click', closeDrawer);
on('#drawer-backdrop', 'click', closeDrawer);
on('#settings-close', 'click', closeSettings);
on('#settings-backdrop', 'click', closeSettings);
on('#banner-dismiss', 'click', () => api('mark_seen'));

on('#btn-bmc', 'click', () => api('open_external', S.boot.bmc_url));
on('#btn-follow', 'click', toggleFollow);
on('#btn-profile', 'click', () => api('open_external', S.boot.profile_url));
on('#btn-data', 'click', () => api('open_data_folder'));

on('#set-auto', 'change', (e) => api('set_setting', 'auto_refresh', e.target.checked));
on('#set-notify', 'change', (e) => api('set_setting', 'notify', e.target.checked));

on('#search', 'input', (e) => { S.query = e.target.value; renderGrid(); });
on('#sort', 'change', (e) => {
  S.sort = e.target.value;
  renderGrid();
  api('set_setting', 'sort', S.sort);
});

$$('.chip').forEach((chip) => {
  chip.addEventListener('click', () => {
    applyFilter(chip.dataset.filter);
    api('set_setting', 'filter', S.filter);
  });
});

$$('.stat-click').forEach((cella) => {
  const vai = () => {
    applyFilter(cella.dataset.filter);
    api('set_setting', 'filter', S.filter);
    $('#grid').scrollIntoView({ behavior: 'smooth', block: 'start' });
  };
  cella.addEventListener('click', vai);
  cella.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); vai(); }
  });
});

function applyFilter(nome) {
  S.filter = nome || 'tutte';
  $$('.chip').forEach((c) => c.classList.toggle('is-active', c.dataset.filter === S.filter));
  renderGrid();
}

/*
 * Scorciatoie. Regola d'oro: non devono mai scattare mentre qualcuno sta
 * scrivendo, altrimenti digitare "1" in un campo cambierebbe il filtro sotto
 * le dita. Da qui il controllo su dove si trova il fuoco.
 */
const FILTRI_RAPIDI = { 1: 'tutte', 2: 'mie', 3: 'aggiornare', 4: 'installate' };

function sto_scrivendo() {
  const el = document.activeElement;
  if (!el) return false;
  return (
    el.tagName === 'INPUT' ||
    el.tagName === 'TEXTAREA' ||
    el.tagName === 'SELECT' ||
    el.isContentEditable
  );
}

document.addEventListener('keydown', (ev) => {
  if (ev.key === 'Escape') {
    // Un menu aperto si chiude per primo: e' la cosa piu' "sopra" di tutte.
    if (document.querySelector('.menu:not([hidden])')) {
      chiudiMenu();
      return;
    }
    // Prima svuota la ricerca, poi chiude: Esc su una lista filtrata deve
    // riportare la lista intera, non far sparire la finestra sbagliata.
    if (document.activeElement === $('#search') && S.query) {
      $('#search').value = '';
      S.query = '';
      renderGrid();
      return;
    }
    closeDrawer();
    closeSettings();
    closeModals();
    return;
  }

  if (ev.key === 'F5' || (ev.ctrlKey && ev.key === 'r')) { ev.preventDefault(); api('refresh', true); }
  if (ev.ctrlKey && ev.key === 'f') { ev.preventDefault(); $('#search').focus(); }

  if (sto_scrivendo() || ev.ctrlKey || ev.altKey || ev.metaKey) return;

  if (ev.key === '/') { ev.preventDefault(); $('#search').focus(); return; }
  if (ev.key === '?') { ev.preventDefault(); openModal('#modal-tasti'); return; }
  if (ev.key === ',') { ev.preventDefault(); openSettings(); return; }
  if (ev.key === 'r' || ev.key === 'R') { api('refresh', true); return; }
  if (ev.key === 'p' || ev.key === 'P') { ev.preventDefault(); apriProposta(); return; }

  const filtro = FILTRI_RAPIDI[ev.key];
  if (filtro) {
    applyFilter(filtro);
    api('set_setting', 'filter', S.filter);
  }
});

on('#tasti-chiudi', 'click', closeModals);
on('#account-azione', 'click', () => {
  if ((S.auth || {}).logged_in) api('logout');
  else startLogin();
});
on('#btn-tasti', 'click', () => openModal('#modal-tasti'));

/* ------------------------------------------------- modali, accesso, voti - */

function openModal(id) {
  $('#modal-backdrop').hidden = false;
  $(id).hidden = false;
  apriConFuoco($(id));
}

function closeModals() {
  $('#modal-backdrop').hidden = true;
  $('#modal-propose').hidden = true;
  $('#modal-login').hidden = true;
  $('#modal-oauth').hidden = true;
  $('#modal-tasti').hidden = true;
  $('#propose-error').hidden = true;
  $('#login-error').hidden = true;
  $('#oauth-error').hidden = true;
  restituisciFuoco();
}

async function startLogin() {
  const r = await api('login_start');
  if (!r || !r.ok) {
    toast((r && r.error) || 'Accesso non riuscito.', 'error');
    return;
  }
  $('#login-error').hidden = true;

  // Con l'accesso a un clic non c'e' nessun codice: il browser e' gia'
  // aperto sulla pagina di autorizzazione e qui si aspetta e basta.
  const unClic = r.mode === 'browser';
  $('#login-attesa').hidden = !unClic;
  $('#login-codice').hidden = unClic;
  $('#login-open').hidden = unClic;

  if (!unClic) {
    S.loginUrl = r.url || 'https://github.com/login/device';
    $('#login-code').textContent = r.user_code || '—';
    $('#login-url').textContent = S.loginUrl.replace(/^https?:\/\//, '');
  }
  openModal('#modal-login');
}

/*
 * Stelle, voti e proposte sono azioni di GitHub: farle dentro l'hub richiede
 * un accesso, e chiedere a chiunque di passare dal device flow per mettere
 * una stella non e' realistico. Quindi senza accesso non si blocca nulla: si
 * apre la pagina giusta su GitHub, dove quasi tutti sono gia' collegati.
 * L'accesso in-app resta una comodita' per chi lo vuole, non un pedaggio.
 */
function suGitHub(url, messaggio) {
  if (!url) return;
  api('open_external', url);
  if (messaggio) toast(messaggio, 'info');
}

function collegato() {
  return !!(S.auth || {}).logged_in;
}

async function toggleStar(repo) {
  const progetto0 = S.projects.find((p) => p.repo === repo);
  if (!collegato()) {
    suGitHub(
      progetto0 && progetto0.url,
      'Ti ho aperto la pagina su GitHub: il pulsante Star è in alto a destra.'
    );
    return;
  }
  const r = await api('toggle_star', repo);
  if (!r || !r.ok) {
    toast((r && r.error) || 'Non riuscito.', 'error');
    return;
  }
  // Si aggiorna subito la lista locale: aspettare il giro completo dei dati
  // farebbe sembrare il pulsante insensibile.
  const elenco = new Set((S.auth.starred || []));
  if (r.starred) elenco.add(repo); else elenco.delete(repo);
  S.auth = Object.assign({}, S.auth, { starred: Array.from(elenco) });
  const progetto = S.projects.find((p) => p.repo === repo);
  if (progetto) progetto.stars = Math.max(0, (progetto.stars || 0) + (r.starred ? 1 : -1));
  renderGrid();
}

async function toggleFollow() {
  if (!collegato()) {
    suGitHub(
      S.boot.profile_url,
      'Ti ho aperto il profilo su GitHub: il pulsante Follow è sotto il nome.'
    );
    return;
  }
  const r = await api('toggle_follow');
  if (!r || !r.ok) {
    toast((r && r.error) || 'Non riuscito.', 'error');
    return;
  }
  S.auth = Object.assign({}, S.auth, { following: r.following });
  renderFollow();
}

async function vote(number) {
  if (!collegato()) {
    const proposta = (S.proposals || []).find((p) => String(p.number) === String(number));
    suGitHub(
      proposta && proposta.url,
      'Ti ho aperto la proposta su GitHub: vota con la reazione 👍.'
    );
    return;
  }
  const key = String(number);
  const r = await api('toggle_vote', Number(number));
  if (!r || !r.ok) {
    toast((r && r.error) || 'Voto non riuscito.', 'error');
    return;
  }
  if (r.voted) S.voted[key] = true;
  else delete S.voted[key];
  renderBoard();
}

async function sendProposal() {
  const title = $('#propose-title').value.trim();
  const body = $('#propose-body').value.trim();
  const err = $('#propose-error');

  if (!title) {
    err.textContent = 'Scrivi almeno il nome del gioco.';
    err.hidden = false;
    return;
  }
  $('#propose-send').disabled = true;
  const r = await api('create_proposal', title, body);
  $('#propose-send').disabled = false;

  if (!r || !r.ok) {
    err.textContent = (r && r.error) || 'Invio non riuscito.';
    err.hidden = false;
    return;
  }
  $('#propose-title').value = '';
  $('#propose-body').value = '';
  closeModals();
  toast('Proposta inviata: ora la comunità può votarla.', 'ok');
}

function apriProposta(gioco = '') {
  if (!collegato()) {
    // Il modulo di GitHub arriva gia' compilato: all'utente resta solo da
    // scrivere il nome del gioco e premere invio.
    // Il modulo ha gia' un titolo ("[Proposta] "): va sostituito, non
    // aggiunto. Con due parametri title GitHub ne usa uno solo, e il nome
    // del gioco cercato poteva perdersi per strada.
    let url = S.boot.suggest_url;
    if (gioco) {
      const indirizzo = new URL(url);
      indirizzo.searchParams.set('title', `[Proposta] ${gioco}`);
      url = indirizzo.toString();
    }
    suGitHub(url, 'Ti ho aperto il modulo su GitHub, già compilato.');
    return;
  }
  openModal('#modal-propose');
  $('#propose-title').value = gioco;
  $('#propose-title').focus();
}

on('#btn-propose', 'click', () => apriProposta());
on('#empty-propose', 'click', () => apriProposta(S.query.trim()));
on('#propose-cancel', 'click', closeModals);
on('#propose-send', 'click', sendProposal);

on('#btn-account', 'click', () => {
  if (!(S.auth || {}).configured) {
    // Non e' un guasto e non e' un blocco: tutto funziona passando da GitHub.
    // Chi pubblica l'hub trova in Impostazioni come attivarlo per tutti.
    toast(
      'L’accesso dentro l’hub non è attivo, ma non serve: stelle, voti e ' +
      'proposte si fanno lo stesso passando da GitHub. Si attiva dalle impostazioni.',
      'info'
    );
    return;
  }
  if ((S.auth || {}).logged_in) api('logout');
  else startLogin();
});

on('#login-cancel', 'click', () => {
  api('login_cancel');
  closeModals();
});
on('#login-open', 'click', async () => {
  try { await navigator.clipboard.writeText($('#login-code').textContent.trim()); } catch (e) { /* non e' grave */ }
  api('open_external', S.loginUrl);
});

on('#modal-backdrop', 'click', () => {
  api('login_cancel');
  closeModals();
});

on('#notice-retry', 'click', () => api('refresh', true));
on('#btn-clear-covers', 'click', async (e) => {
  e.target.disabled = true;
  await api('clear_cover_cache');
  e.target.disabled = false;
});
on('#hub-update-get', 'click', () => api('download_hub_update'));
on('#hub-update-later', 'click', () => {
  S.updateDismissed = true;
  renderHubUpdate();
});

/* ------------------------------------------- accesso con un clic: attivarlo - */
/*
 * GitHub non concede client OAuth anonimi: per autenticare qualcuno, qualcuno
 * deve aver registrato un'applicazione. Non si aggira. Quello che si aggira e'
 * il costo: qui la registrazione e' un pulsante che apre il modulo GitHub gia'
 * compilato, e le due stringhe si incollano in questa finestra invece che in un
 * file Python da ricompilare. Chi scarica l'hub non vede niente di tutto
 * questo, perche' le credenziali viaggiano dentro l'exe.
 */

/* Chi vede questa sezione. Nessuno, tranne chi pubblica l'hub: per un utente
 * "registra un'applicazione su GitHub" e' un'istruzione senza senso, le sue
 * credenziali arrivano gia' dentro l'eseguibile. Si mostra solo se l'hub gira
 * dai sorgenti o con --setup (`autore`), se su questo PC la procedura e' gia'
 * stata fatta (`source === 'file'`), o dopo cinque clic sulla versione. */
function setupVisibile() {
  // Niente piu' apertura automatica quando le credenziali sono salvate sul
  // PC: anche per chi pubblica e' roba da tirare fuori quando serve, non da
  // vedere ogni volta che si aprono le impostazioni.
  const a = S.auth || {};
  return !!(a.autore || S.setupSbloccato);
}

/* Lo stato del collegamento dell'utente, con l'unica azione che ha senso in
 * quel momento. E' l'informazione che mancava: "sono collegato o no?". */
function renderAccountRiga() {
  const riga = $('#account-riga');
  if (!riga) return;
  const a = S.auth || {};
  if (!a.configured) {
    riga.hidden = true;
    return;
  }
  riga.hidden = false;
  if (a.logged_in) {
    $('#account-stato').innerHTML = `Collegato come <strong>${esc(a.login || '—')}</strong>`;
    $('#account-azione').textContent = 'Esci';
  } else {
    $('#account-stato').textContent = 'Non collegato';
    $('#account-azione').textContent = 'Accedi con GitHub';
  }
}

function renderOauth() {
  const attivo = $('#oauth-attivo');
  const daFare = $('#oauth-da-fare');
  if (!attivo || !daFare) return;

  const a = S.auth || {};
  if (!setupVisibile()) {
    attivo.hidden = true;
    daFare.hidden = true;
    return;
  }

  const pronto = !!a.one_click;
  attivo.hidden = !pronto;
  daFare.hidden = pronto;
  if (!pronto) return;

  const cid = a.client_id || S.oauth.client_id || '';
  $('#oauth-id').textContent = cid ? abbrevia(cid) : '—';
  // "app" = compilata nell'eseguibile, quindi valida per tutti gli utenti;
  // "file" = salvata solo su questo PC dalla procedura guidata.
  const dove = a.source === 'file' ? ' — salvata su questo PC' : ' — inclusa nell’hub';
  $('#oauth-dove').textContent = cid ? dove : '';
  // Solo se le credenziali stanno nel file: quando arrivano dall'eseguibile
  // sono gia' in config.py, non c'e' niente da copiare ne' da rimuovere.
  $('#oauth-forget').hidden = a.source !== 'file';
  $('#oauth-config').hidden = a.source !== 'file';
}

/* Il Client ID non e' un segreto, ma nemmeno qualcosa da leggere: se ne
 * mostrano le estremita', che bastano a riconoscerlo. */
function abbrevia(valore) {
  return valore.length <= 14 ? valore : `${valore.slice(0, 8)}…${valore.slice(-4)}`;
}

async function apriOauth() {
  const info = await api('oauth_setup');
  if (!info) return;
  S.oauth = info;
  $('#oauth-v-nome').textContent = info.app_name || '';
  $('#oauth-v-home').textContent = info.homepage || '';
  $('#oauth-v-callback').textContent = info.callback || '';
  $('#oauth-error').hidden = true;
  $('#oauth-id-input').value = '';
  $('#oauth-secret-input').value = '';
  openModal('#modal-oauth');
}

function erroreOauth(testo) {
  const box = $('#oauth-error');
  box.textContent = testo;
  box.hidden = false;
}

async function salvaOauth() {
  const bottone = $('#oauth-save');
  const cid = $('#oauth-id-input').value.trim();
  const secret = $('#oauth-secret-input').value.trim();

  if (!cid || !secret) {
    erroreOauth('Servono entrambe le stringhe: Client ID e client secret.');
    return;
  }

  bottone.disabled = true;
  bottone.textContent = 'Controllo…';
  const r = await api('oauth_save', cid, secret);
  bottone.disabled = false;
  bottone.textContent = 'Salva e prova';

  if (!r || !r.ok) {
    erroreOauth((r && r.error) || 'Non riesco a salvare le credenziali.');
    return;
  }

  closeModals();
  toast('Credenziali salvate. Provo l’accesso.', 'ok');
  // La prova del nove: un accesso vero. Se le credenziali sono sbagliate lo si
  // scopre adesso, non il giorno che serve.
  startLogin();
}

/*
 * Le due righe da incollare in config.py. Si prendono dai campi se sono
 * compilati, altrimenti da quelle gia' salvate: GitHub il client secret lo
 * mostra **una volta sola**, e chi avesse chiuso la finestra senza copiarlo
 * dovrebbe altrimenti rigenerarlo per una dimenticanza.
 */
const COPIATE = 'Righe copiate: incollale in hub/config.py e ricompila.';

async function copiaPerConfig() {
  const campoId = $('#oauth-id-input');
  const cid = campoId ? campoId.value.trim() : '';
  const secret = campoId ? $('#oauth-secret-input').value.trim() : '';

  if (cid && secret) {
    copiaTesto(`OAUTH_CLIENT_ID = "${cid}"\nOAUTH_CLIENT_SECRET = "${secret}"`, COPIATE);
    return;
  }

  const r = await api('oauth_config_snippet');
  if (r && r.ok) copiaTesto(r.testo, COPIATE);
  else if (!$('#modal-oauth').hidden) erroreOauth((r && r.error) || 'Niente da copiare.');
  else toast((r && r.error) || 'Niente da copiare.', 'error');
}

async function copiaTesto(testo, messaggio) {
  try {
    await navigator.clipboard.writeText(testo);
    toast(messaggio, 'ok');
  } catch (e) {
    toast('Non riesco a copiare: selezionalo a mano.', 'error');
  }
}

/*
 * Client ID e secret stanno uno sotto l'altro su GitHub, con due pulsanti di
 * copia quasi identici: invertirli e' l'errore piu' facile del mondo. Invece
 * di segnalarlo, si sistema. Il riconoscimento e' sui formati: il secret e'
 * 40 esadecimali, il Client ID comincia per Ov/Iv o e' 20 esadecimali.
 */
const RE_SECRET = /^[0-9a-f]{40}$/;
const RE_ID = /^(?:[OI]v[0-9A-Za-z.]{6,60}|[0-9a-f]{20})$/;

function sistemaCampi() {
  const campoId = $('#oauth-id-input');
  const campoSecret = $('#oauth-secret-input');
  const a = campoId.value.trim();
  const b = campoSecret.value.trim();
  if (RE_SECRET.test(a) && RE_ID.test(b)) {
    campoId.value = b;
    campoSecret.value = a;
    toast('Erano invertite: le ho rimesse a posto.', 'info');
  }
}

/* Cinque clic sul numero di versione: e' l'idioma con cui Android nasconde
 * le opzioni sviluppatore, e va bene per lo stesso motivo — chi non lo sa non
 * ci arriva per caso, chi lo sa non deve ricordarsi altro. */
let clicVersione = 0;
let timerVersione = null;
on('#set-version', 'click', () => {
  if (setupVisibile()) return;
  clearTimeout(timerVersione);
  timerVersione = setTimeout(() => { clicVersione = 0; }, 1500);
  if (++clicVersione < 5) return;
  clicVersione = 0;
  S.setupSbloccato = true;
  renderOauth();
  toast('Attivazione dell’accesso sbloccata.', 'info');
});

on('#oauth-open', 'click', apriOauth);
on('#oauth-apri-github', 'click', () => {
  api('oauth_register');
  toast('Premi “Register application” in fondo alla pagina.', 'info');
});
on('#oauth-save', 'click', salvaOauth);
on('#oauth-cancel', 'click', closeModals);
on('#oauth-copia-config', 'click', copiaPerConfig);
on('#oauth-config', 'click', copiaPerConfig);
on('#oauth-forget', 'click', async () => {
  // Lo stato nuovo arriva con l'evento 'auth' che Python emette da solo:
  // qui basta svuotare la copia locale e ridisegnare.
  await api('oauth_forget');
  S.oauth = {};
  renderOauth();
});

/* Un solo campo che si corregge da solo appena ha entrambe le stringhe. */
$$('#oauth-id-input, #oauth-secret-input').forEach((campo) => {
  campo.addEventListener('paste', () => setTimeout(sistemaCampi, 0));
  campo.addEventListener('change', sistemaCampi);
  campo.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter') salvaOauth();
  });
});

$$('#modal-oauth .copia').forEach((btn) => {
  btn.addEventListener('click', () => {
    const sorgente = $(btn.dataset.copia);
    if (sorgente) copiaTesto(sorgente.textContent.trim(), 'Copiato.');
  });
});

/* ---------------------------------------------------------------- avvio - */

renderSkeleton();

window.addEventListener('pywebviewready', async () => {
  const boot = await api('bootstrap');
  if (boot) {
    S.boot = boot;
    S.auth = boot.auth || {};
    S.voted = {};
    (boot.voted || []).forEach((n) => { S.voted[String(n)] = true; });
    $('#bmc-label').textContent = (boot.bmc_url || '').replace(/^https?:\/\//, '');
    $('#brand-sub').textContent = `Le traduzioni di ${boot.user}`;
    renderAccount();
    renderAccountRiga();
    renderFollow();
    renderOauth();

    const st = boot.settings || {};
    if (st.sort) { S.sort = st.sort; $('#sort').value = st.sort; }
    if (st.filter) applyFilter(st.filter);

    // L'ultimo catalogo riuscito, se c'e': la griglia e' piena da subito
    // invece di aspettare la rete. Il controllo vero e' gia' partito, e se
    // arriva prima di qui non va sovrascritto con dati piu' vecchi.
    if (boot.catalogo && !S.projects.length) applicaCatalogo(boot.catalogo);

    // Il catalogo puo' essere gia' arrivato prima di questi dati: ridisegnamo
    // la bacheca, altrimenti i voti gia' dati resterebbero senza evidenza.
    renderBoard();
  }
});
