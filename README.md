# Gioca in Italiano

Applicazione Windows che raccoglie in un unico posto tutte le traduzioni
italiane pubblicate su GitHub da [Sici29](https://github.com/Sici29): le trova
da sola, ne scarica le copertine da Steam, segnala quando esce un
aggiornamento, le installa senza aprire nessuna finestra e fa partire il
gioco.

Fino alla versione 1.0 si chiamava *Sici29 Hub*. Il nome e' cambiato solo
dove si vede: la cartella dei dati (`%LOCALAPPDATA%\Sici29Hub`), il repo del
catalogo e il resto degli identificativi interni sono rimasti gli stessi,
cosi' chi aveva gia' l'hub non perde accesso, preferenze e copertine.

---

## L'installer delle traduzioni, dentro l'hub

Prima "Installa" apriva la console nera dell'installer, col suo menu da
leggere e i suoi "Premi Invio". Adesso l'hub lo guida da dietro le quinte:
la finestra dell'installer non compare, e quello che scrive arriva nella
card e nei dettagli.

Si puo' perche' tutti e cinque gli installer, oltre al menu, hanno una
modalita' a comandi che non fa domande: `install`, `restore`, `check`. Il
nucleo e' lo stesso, le opzioni in piu' no - e un'opzione che l'installer non
conosce lo fa uscire con un errore - quindi ogni installer ha il suo profilo,
ricavato dal suo sorgente (`INSTALLER_PER_REPO` in `hub/config.py`). Un repo
puo' dichiararne uno proprio nel `hub.json`, alla voce `"installer"`:

```json
"installer": {
  "install": ["install", "--no-update-check"],
  "restore": ["restore"],
  "check":   ["check"]
}
```

La cartella del gioco **non** viene passata: ogni installer ha il suo modo di
trovarla e conosce il proprio gioco meglio dell'hub. Si aggiunge
`--game-dir` solo se l'utente l'ha indicata a mano dal menu *Altro*.

Il menu dell'installer e' diventato il menu **Altro** dei dettagli:
controlla la traduzione, reinstalla, ripristina i file originali (con
conferma a doppio clic), apri la cartella dei backup, indica la cartella del
gioco. Mancano solo le voci che l'hub fa gia' per conto suo - "controlla se
esiste una nuova versione" e "crediti" - e per tutto il resto c'e' *Apri
l'installer completo*, che lo apre com'era.

Dal risultato l'hub tira fuori quello che serve: il messaggio da mostrare,
la **lingua da scegliere nel gioco** in evidenza (e' la cosa che la gente
sbaglia: installa e continua a vedere l'inglese), e tutto il resto in un
riquadro da aprire. Le righe diagnostiche (statistiche, digest) restano
fuori; nel registro dell'hub, invece, finisce tutto.

### Da fare negli installer: una riga

Gli installer sono programmi Python impacchettati con PyInstaller, e quando
scrivono su una pipe invece che su una console tengono l'output in un buffer:
le righe arrivano all'hub **tutte insieme, a lavoro finito**. La variabile
`PYTHONUNBUFFERED` non serve, perche' gli eseguibili PyInstaller la
ignorano: provato. Nel frattempo l'hub mostra una barra che scorre, onesta,
invece di inventarsi delle fasi.

Il rimedio sta in ogni installer, una riga al posto di quella che gia' c'e':

```python
sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
```

Provato su un installer finto costruito allo stesso modo: senza, le righe
arrivano tutte a 5,1 secondi; con, a 0,2 - 1,2 - 2,2 - 3,2 - 4,2. L'hub non va
toccato: legge gia' le righe man mano che arrivano.

### Il pulsante Gioca

Quando la traduzione e' installata e in pari, il pulsante principale della
card diventa **Gioca**. I giochi Steam partono da Steam
(`steam://rungameid/...`), che resta padrone di overlay, salvataggi nel cloud
e aggiornamenti; Star Citizen parte dal launcher RSI, che l'hub trova
risalendo dalla cartella del gioco o dal registro di Windows. Per gli altri
l'hub non tira a indovinare quale eseguibile sia quello giusto.

---

## Cosa fa

### 1. Trova le traduzioni da solo

Pubblichi una nuova traduzione su GitHub e al controllo successivo compare
nell'hub, con copertina e cronologia dei rilasci. Non si tocca il codice.

Un repo dell'account viene riconosciuto come traduzione se soddisfa **almeno
uno** di questi criteri, in ordine di autorita':

1. **contiene `hub.json` nella root** — segnale definitivo, e porta con se' i
   metadati (nome del gioco, AppID Steam, copertina);
2. **ha uno dei topic riconosciuti** — `italian-translation`,
   `traduzione-italiana`, `italian-localization`, `fan-translation`;
3. **il nome segue una convenzione nota** — finisce per `-Italian-Translation`
   o `-Traduzione-Italiana`, oppure inizia per `Traduzione-`.

Sono sempre esclusi: fork, repo archiviati o privati, il repo-profilo
`Sici29`, e qualunque repo con `"nascondi": true` nel suo `hub.json`.

Per i repo futuri conviene il criterio 1: basta committare un `hub.json` e la
traduzione entra nell'hub comunque si chiami il repo. Lo schema completo sta
in [`esempi/README.md`](esempi/README.md).

Le regole vivono tutte in [`hub/config.py`](hub/config.py): se un domani cambi
convenzione, si tocca solo quel file.

### 2. Segnala gli aggiornamenti

A ogni controllo l'hub confronta l'ultimo tag pubblicato su GitHub con quello
che risulta installato sul PC e con l'ultimo che l'utente ha gia' visto:

- **Nuova** — traduzione mai vista prima nell'hub;
- **Aggiornata** — e' uscita una versione piu' recente di quella gia' vista;
- **Da aggiornare** — l'hub ha installato una versione, ma non e' l'ultima.

Il controllo parte all'avvio e poi ogni 30 minuti finche' l'hub resta aperto,
con una notifica di Windows quando trova qualcosa.

#### Le notifiche di Windows

Arrivano a nome di **Gioca in Italiano**, con la sua icona. Per mostrare una
notifica Windows vuole l'identita' di un'app registrata, e all'inizio si
prendeva in prestito quella di PowerShell, che finiva nel titolo. Ora l'hub
registra la sua a ogni avvio, sotto `HKEY_CURRENT_USER` (niente permessi di
amministratore), insieme al link `giocainitaliano:` usato dai pulsanti.

- **Una traduzione da aggiornare**: la copertina del gioco, la versione, la
  prima novita' delle note e il pulsante **Aggiorna**, che apre la scheda e fa
  partire l'aggiornamento.
- **Piu' traduzioni insieme**: una notifica sola, con i nomi.
- **Una traduzione nuova** e **una versione nuova dell'hub**: annunciate anche
  queste, al massimo tre notifiche per controllo.

Ogni versione si annuncia **una volta sola**: prima la stessa notifica tornava
a ogni controllo, cioe' ogni mezz'ora, finche' l'aggiornamento restava da
fare.

Chiunque puo' scrivere un link `giocainitaliano:` in una pagina web, quindi da
solo un link apre al massimo una scheda. Per far partire l'aggiornamento serve
il gettone che l'hub mette nella notifica, che vale una volta sola e scade
dopo 14 giorni. Se l'hub e' gia' aperto, il clic lancia un secondo avvio che
lascia il link in un file e si chiude, e il primo lo raccoglie.

Nelle impostazioni, **Prova una notifica** ne manda una di esempio.

### 3. Prende le copertine da Steam

Le copertine arrivano dal database pubblico di Steam, senza account ne' chiave
API. Le fonti vengono provate in quest'ordine, e si scende solo se la
precedente non da' un'immagine valida:

1. copertina scelta a mano dall'utente (**Cambia immagine**, passando col
   mouse sulla copertina nei dettagli);
2. `cover_url` dichiarato nel `hub.json`;
3. `steam_appid` dichiarato nel `hub.json`;
4. AppID trovato cercando il nome del gioco su Steam;
5. sito ufficiale dell'editore, per i giochi che su Steam non esistono;
6. copertina generata dall'hub.

Il punto 5 e' l'elenco `NON_STEAM_COVERS` in `hub/config.py`. Star Citizen sta
li': l'unica immagine che RSI pubblica e' il marchio su fondo trasparente, e
l'hub se ne accorge da solo, lo ridipinge in chiaro e lo compone sullo sfondo
che genera. Per aggiungere un gioco bastano una riga e l'URL del CDN
dell'editore — nessuna immagine viene copiata o ridistribuita.

Tutto viene normalizzato a 460x215 e messo in cache per due settimane, cosi'
la griglia resta coerente anche mescolando fonti diverse.

**Perche' serve tutta questa catena.** Steam serve le immagini in due modi: i
giochi piu' vecchi da un URL prevedibile (`/steam/apps/<id>/header.jpg`), i
titoli recenti da un percorso che contiene un hash diverso per ogni singolo
asset, impossibile da costruire a mano. Per questi ultimi l'hub legge l'URL
dall'API dello store e, quando anche quella risponde a vuoto, dal meta tag
`og:image` della pagina del gioco — che si e' rivelata la fonte piu'
affidabile di tutte.

**Contro gli abbinamenti sbagliati.** La ricerca per nome e' volutamente
severa: pesa le parole in comune e scarta i risultati troppo diversi. Senza
questo controllo, cercare "Star Citizen" (che su Steam non esiste) restituiva
la copertina di *Citizen Sleeper 2*. Allo stesso modo, se un `hub.json`
dichiara un AppID che sullo store ha un altro nome, l'hub lo ignora e lo
segnala nel pannello dettagli invece di scaricare la copertina sbagliata.

### 4. Raccoglie le richieste della comunità, con i voti

Una bacheca in fondo alla finestra mostra i giochi che la gente vorrebbe
tradotti, ordinati per voti, con l'etichetta **In lavorazione** su quelli già
avviati. Da lì si propone un gioco e si vota, restando dentro l'hub.

Sotto non c'è nessun server: **le proposte sono issue di GitHub** con
l'etichetta `proposta`, e **i voti sono le reazioni 👍**. Vuol dire zero
infrastruttura da mantenere, moderazione con gli strumenti che già usi, e la
bacheca resta consultabile anche dal sito di GitHub.

Proporre e votare non richiedono l'accesso: chi non e' collegato viene
portato sulla pagina giusta di GitHub, con il modulo gia' compilato.

### 5. Stelle, "segui", proposte e voti — senza dover fare l'accesso

Ogni traduzione mostra le sue stelle GitHub e si puo' stellare dalla
copertina; accanto al caffe' c'e' il pulsante per seguire l'autore. Sono il
modo gratuito di dare una mano, e per questo stanno accanto a quello a
pagamento invece che nascosti in un menu.

**Nessuna di queste azioni richiede di collegarsi.** Sono azioni di GitHub, e
chiedere a chiunque di passare dal device flow per mettere una stella non e'
realistico: chi non e' collegato viene portato direttamente sulla pagina
giusta di GitHub, dove quasi tutti sono gia' autenticati. La proposta arriva
perfino con il modulo gia' compilato.

L'accesso in-app resta **facoltativo**: serve solo a fare le stesse cose senza
aprire il browser, e alza il limite di richieste da 60 a 5.000 all'ora. I
permessi richiesti restano minimi: `public_repo` per stelle, proposte e voti,
`user:follow` per il segui.

### 6. Si aggiorna da solo

L'hub confronta la propria versione con l'ultima release pubblicata e, se e'
indietro, lo dice in cima alla finestra con un pulsante per scaricare.

Non si sostituisce l'eseguibile da solo mentre e' in esecuzione: scarica il
file nuovo e lo mostra in Esplora risorse. E' meno spettacolare di un
aggiornamento automatico, ma e' proprio il caso in cui un errore lascerebbe
l'utente senza applicazione.

Quando c'e' il catalogo pre-generato il controllo non costa nessuna richiesta:
la Action ci mette dentro anche l'ultima release dell'hub. Altrimenti si fa una
volta sola per sessione.

---

## Accesso con GitHub

**Serve solo a chi lo vuole**: senza accesso l'hub funziona per intero e le
azioni social passano dal browser (vedi sopra). Chi si collega le fa senza
uscire dalla finestra e ottiene un limite di richieste piu' alto.

### Un clic, non un codice da ricopiare

L'hub usa **authorization code + PKCE** su indirizzo di loopback: preme
"Accedi", il browser si apre gia' sulla pagina "Authorize" di GitHub — dove
quasi tutti sono gia' collegati — si preme il pulsante verde e si torna
nell'hub gia' autenticati. Niente codici da trascrivere.

Il device flow (il codice a otto caratteri) resta come **ripiego**, per quando
il client secret non e' configurato o la porta locale e' bloccata.

### Perche' il client secret sta dentro l'eseguibile

GitHub pretende il `client_secret` anche dalle app native, perche' non
distingue client pubblici da confidenziali. Nella sua guida alle buone
pratiche scrive pero' che per un'app pubblica — che il secret non puo'
comunque proteggerlo — **e' preferibile l'authorization code con PKCE al
device flow**. E' la strada che seguiamo.

A reggere la sicurezza e' PKCE: a ogni accesso l'hub genera un `code_verifier`
casuale e ne manda a GitHub solo l'impronta SHA-256. Il codice di
autorizzazione vale unicamente per chi conosce il verifier originale, che non
viaggia mai in chiaro e muore con la sessione. Un secret estratto dal binario,
da solo, non basta a farsi dare un token.

Le altre difese: si ascolta **solo su 127.0.0.1**, il parametro `state` viene
verificato al ritorno (altrimenti un sito qualunque potrebbe recapitare un
codice non richiesto), la porta si chiude subito dopo, e il token finisce
cifrato con DPAPI. Se un secret venisse compromesso, si revoca e si rigenera
dalla stessa pagina di GitHub.

### Come attivarlo — dall'hub, senza toccare il codice

**Chi scarica l'hub non fa niente di tutto questo**: trova l'accesso gia'
pronto, perche' le credenziali viaggiano dentro l'exe. Registrare
l'applicazione tocca solo a chi pubblica l'hub, una volta sola. GitHub non
concede client OAuth anonimi: per autenticare qualcuno, qualcuno deve aver
registrato un'applicazione. Non si aggira — si aggira il costo.

La sezione **non compare a chi scarica l'hub**: per un utente "registra
un'applicazione su GitHub" e' un'istruzione priva di senso, le sue credenziali
arrivano gia' dentro l'eseguibile. Si apre in tre modi, tutti fuori dalla
portata di chi passa di li' per caso:

- l'hub gira dai sorgenti (`python -m hub`);
- lo si avvia con `GiocaInItaliano.exe --setup`;
- **cinque clic sul numero di versione**, in fondo alle impostazioni.

E resta visibile per sempre su un PC dove la procedura e' gia' stata fatta,
perche' li' esiste il file cifrato delle credenziali.

**Impostazioni → "Attiva l'accesso con un clic"**, e da li':

1. **"Apri il modulo su GitHub"** apre la pagina di registrazione col modulo
   **gia' compilato** (nome, sito, callback): resta solo da premere *Register
   application*. Se GitHub un domani smettesse di accettare i campi
   precompilati, i tre valori sono nella finestra stessa, con un pulsante
   "Copia" ciascuno;
2. si incollano **Client ID** e **client secret** nei due campi. Se vengono
   invertiti — l'errore piu' probabile, i due pulsanti di copia su GitHub sono
   quasi identici — l'hub **se ne accorge dai formati e li rimette a posto**;
3. **"Salva e prova"**: l'hub verifica il Client ID con GitHub *prima* di
   aprire il browser, salva le credenziali **cifrate con DPAPI** nella cartella
   dati, e fa subito un accesso di prova. Se qualcosa non va lo si scopre
   adesso, non il giorno che serve.

### Portarle nell'eseguibile, senza farle passare dal repository

Da li' in poi l'accesso vale su quel PC. Perche' valga anche per **chi scarica
l'hub** le credenziali devono entrare nell'exe, e qui c'e' una trappola:

> GitHub fa **secret scanning** sui repository pubblici e i client secret OAuth
> li **revoca da solo** appena compaiono in un commit.

Scriverle in `config.py` e committare vuol dire quindi perderle. La strada
giusta e' `hub/credenziali.py`: un modulo normalissimo, che PyInstaller include
nell'eseguibile come tutti gli altri, ma che sta nel `.gitignore` e non finira'
mai in un commit.

```
# nell'hub: Impostazioni -> Copia le righe per config.py
python tools/imposta_credenziali.py     # le prende dagli appunti
.uilduild.ps1
```

Il comando accetta sia le due righe pronte sia le due stringhe nude, in
qualunque ordine, e non stampa mai il secret (`--mostra` lo maschera,
`--togli` rimuove il file). `config.py` resta con i campi vuoti, quindi il
repository e' pubblicabile com'e'.

Il pulsante *"Copia le righe per config.py"* sta anche nelle impostazioni
accanto allo stato, perche' GitHub il client secret lo mostra **una volta
sola**: le rilegge dal file cifrato, cosi' una dimenticanza non costa la
rigenerazione del secret.

Che l'eseguibile sia a posto lo dice la prima riga del log:
`accesso in-app: un clic (credenziali: app)` — `app` vuol dire "dentro
l'exe", cioe' valide per tutti.

La callback da registrare e' `http://127.0.0.1/callback`: GitHub ammette il
loopback e **non pretende che la porta coincida** con quella registrata,
quindi l'hub puo' usarne una libera al momento dell'accesso.

Precedenza: il file cifrato nella cartella dati **batte** i valori compilati
nell'eseguibile, cosi' un secret rigenerato si sostituisce senza ricompilare.
"Rimuovi le credenziali", nelle impostazioni, cancella il file e fa tornare in
vigore quelle dell'exe.

### Ogni utente entra col proprio account

Client ID e secret identificano **l'applicazione**, non una persona: sono la
targa dell'hub, non le chiavi dell'account di chi l'ha registrata. Chi preme
"Accedi" autorizza *il proprio* account GitHub, e il token che l'hub riceve e'
il suo: la stella finisce sul suo profilo, il "segui" parte da lui, la proposta
risulta aperta da lui. Nessuno entra nell'account dell'autore, e l'autore non
vede le credenziali di nessuno — GitHub non gliele manda.

Permessi richiesti, il minimo indispensabile: `public_repo` per stelle,
proposte e voti, `user:follow` per il segui. Nessun accesso ai repo privati.

Finche' non si attiva, l'hub funziona comunque **per intero**: stelle, voti e
proposte passano dal browser, e il pulsante di accesso dice dove si attiva
invece di sparire senza spiegare nulla.

---

## Come si usa senza mouse

| | |
|---|---|
| <kbd>/</kbd> | cerca |
| <kbd>1</kbd> <kbd>2</kbd> <kbd>3</kbd> <kbd>4</kbd> | tutte · i miei giochi · da aggiornare · installate |
| <kbd>R</kbd> | controlla gli aggiornamenti |
| <kbd>P</kbd> | proponi una traduzione |
| <kbd>,</kbd> | impostazioni |
| <kbd>Esc</kbd> | chiudi, o svuota la ricerca |
| <kbd>?</kbd> | l'elenco completo, dentro l'hub |

Nessuna scatta mentre si scrive in un campo, altrimenti digitare "1" in una
ricerca cambierebbe il filtro sotto le dita.

---

## La traduzione copre la versione che hai?

E' la domanda che decide se una traduzione funzionera' davvero, e per un bel
po' l'hub non se la poneva: mostrava l'ultima versione pubblicata e basta. Ma
una patch del gioco rimescola le stringhe, e una traduzione ferma a due patch
fa lascia pezzi di testo in inglese anche se e' "l'ultima disponibile".

Tre modi di rispondere, dal piu' solido al piu' debole; vince il primo che
da' un risultato:

1. **Build contro build.** Steam scrive il numero esatto della build
   installata nel suo `appmanifest`; se la traduzione dichiara `game_build`
   nel `hub.json`, il confronto e' aritmetico.
2. **Serie contro serie.** Per i giochi fuori Steam si confrontano le serie
   (4.10 contro 4.10): Star Citizen scrive `sc-alpha-4.10.0` nel suo
   `build_manifest.id` e i rilasci si chiamano `sc-4.10-r2`. Le revisioni
   minori non contano: 4.10.0 e 4.10.2 sono la stessa patch per chi ci gioca.
3. **Date.** Se nessuno dichiara niente, resta il fatto che Steam registra
   *quando* il gioco e' stato aggiornato l'ultima volta. Vale per qualunque
   gioco Steam senza che nessuno debba dichiarare nulla, ed e' il motivo per
   cui questo terzo modo esiste.

### Cosa l'hub non dice

Mai "incompatibile". Una patch puo' non toccare una riga di testo, e allora la
traduzione funziona benissimo anche con la build diversa. L'hub riferisce
quello che sa - "il gioco e' stato aggiornato dopo questa traduzione" - e
lascia la conclusione a chi legge. Quando non sa, tace: una rassicurazione
inventata e' peggio del silenzio, e un falso allarme ripetuto due volte rende
invisibile anche quello vero.

Per lo stesso motivo la build non si indovina dai nomi dei rilasci. Il primo
tentativo lo faceva: "Release 1.0.3595896.0: supporto Steam build 3595896"
sembrava dire tutto. Ma 3595896 e' il numero di build **interno di Aniimo**,
mentre Steam per lo stesso gioco scrive 25525975. Due numerazioni che non si
parlano: il confronto annunciava che il gioco era avanti di ventidue milioni
di build su una traduzione perfettamente allineata. Adesso il confronto esatto
richiede una dichiarazione esplicita, che e' l'unica cosa che puo' garantire
che i due numeri siano della stessa specie.

### Cosa compare, e dove

Le date di Steam dicono un fatto in una direzione sola. "Il gioco e' stato
aggiornato dopo la traduzione" e' vero e basta. "Non e' stato aggiornato
dopo", invece, **non prova** che la traduzione sia fatta per quella build: la
prima versione lo mostrava comunque con un pallino verde e la parola
"allineata", ed era una promessa che l'hub non poteva mantenere. Quindi:

| | nei dettagli | sulla card |
|---|---|---|
| in pari, confermato da build o serie dichiarata | si' | no, e' il caso normale |
| in pari, dedotto dalle date | **no** | no |
| gioco aggiornato dopo la traduzione | si' | solo se confermato |
| traduzione per un gioco piu' recente | si' | si' |

Sulla card un avviso vistoso su un indizio debole diventa un falso allarme, e
dopo due falsi allarmi nessuno guarda piu' nemmeno quello vero.

---

## Ogni gioco porta il suo colore

Python ricava dalla copertina il colore dominante e lo consegna
all'interfaccia come `--tinta`: da li' tinge il bordo e l'alone della card al
passaggio del mouse, il filo sul bordo dell'artwork e lo sfondo sotto
l'immagine nel pannello dei dettagli. E' quello che fa sembrare la griglia
costruita attorno a quei giochi invece che un elenco con delle immagini
dentro, e non costa niente: Pillow serviva gia' per normalizzare le copertine.

Non e' la media dei pixel, che darebbe un grigio fango su qualunque immagine.
I colori simili vengono raggruppati, neri bianchi e grigi scartati - non sono
una tinta - e fra i restanti vince quello che occupa piu' spazio **ed** e' piu'
vivo. Il risultato viene poi riportato in una banda fissa di saturazione e
luminosita': una copertina slavata e una fluorescente devono dare due colori
diversi ma ugualmente leggibili sul grafite. Se non resta niente (copertina in
bianco e nero) si torna all'ambra dell'hub.

Le altre rifiniture sono misurate per non farsi notare: se si vedono, sono
troppo lunghe. Due aloni larghissimi e una grana finissima sul fondo, perche'
il nero pieno su schermi grandi sembra plastica e mostra le bande di
gradiente; le card che entrano una dopo l'altra; i numeri in cima che salgono
al valore invece di comparire; la stella che scatta quando si accende, che e'
l'unico riscontro immediato di un'azione la cui conferma arriva dopo; le
righe che scorrono sulla barra di avanzamento, perche' la percentuale dice a
che punto sei e quelle dicono che si sta ancora muovendo.

Tutto quanto e' dentro `@media (prefers-reduced-motion: no-preference)`: chi
ha chiesto al sistema di ridurre le animazioni non ne vede nessuna.

---

## L'ordine "Per te"

E' il criterio predefinito, e non e' la data. Apre l'hub chi vuole sapere
"c'e' qualcosa da fare per me?", non "cos'e' uscito per ultimo", quindi
l'ordine segue quanto una traduzione ti riguarda:

1. un gioco che hai, con un aggiornamento che aspetta — con l'anello ambra
   attorno alla card, perche' e' quella che sei venuto a cercare;
2. un gioco che hai, traduzione non ancora installata;
3. un gioco che hai, gia' allineato;
4. tutto il resto, dalla piu' recente.

Sulle card del primo gruppo compare anche **cosa cambia**: una riga presa
dalle note di rilascio, che salta il titolo (ripete il nome del gioco, che sta
gia' due volte li' sopra) e pesca il primo punto elenco. Risponde alla domanda
che uno si fa davanti al pulsante "Aggiorna", senza aprire i dettagli.

I numeri in cima sono cliccabili: "Da aggiornare" e "Giochi rilevati" portano
al proprio elenco.

E una ricerca a vuoto non e' un vicolo cieco: e' il momento esatto in cui sai
cosa vorresti, quindi da li' si propone la traduzione cercata con un clic.

---

## Il filtro "solo i miei giochi"

L'hub sa quali giochi sono installati su questo PC e puo' mostrare solo le
traduzioni che ti servono davvero. Legge:

| Fonte | Come |
|---|---|
| **Steam** | i manifest `appmanifest_*.acf` di tutte le librerie dichiarate in `libraryfolders.vdf`, anche su altri dischi |
| **Epic Games** | i manifest `.item` in `ProgramData` |
| **GOG** | le chiavi di registro di GOG Galaxy |
| **Windows** | l'elenco dei programmi installati |
| **Ricerca su disco** | per i giochi che non compaiono da nessuna parte |

**Perche' serve anche la ricerca su disco.** Star Citizen e' il caso che l'ha
resa necessaria: il registro elenca solo "RSI Launcher" *senza percorso*, il
file di configurazione del launcher e' cifrato, e la cartella la sceglie
l'utente — sul PC di prova era `D:\Robert Space Industries`, con "Robert" al
singolare, quindi nessun percorso predefinito l'avrebbe trovata. L'hub cerca
allora la cartella del gioco sui dischi, fino a tre livelli di profondita' e
saltando le cartelle di sistema: circa due decimi di secondo. Il percorso
trovato viene ricordato, quindi dalla volta dopo il controllo e' immediato.

L'abbinamento avviene per AppID Steam quando c'e' — ed e' esatto — e per nome
negli altri casi. Non viene letto nulla di personale: solo nomi e percorsi di
installazione, e tutto resta sul PC.

---

## Avviare e compilare

Serve **Python 3.11+** e **Windows 10 (21H2) o 11**, dove il runtime WebView2
e' gia' installato di serie.

```powershell
# dai sorgenti, per sviluppare
pip install -r requirements.txt
.\run_dev.ps1

# per produrre dist\GiocaInItaliano.exe
.\build\build.ps1
```

Il punto di ingresso dell'eseguibile e' `main.py` nella root, non
`hub/__main__.py`: PyInstaller esegue lo script di avvio come modulo di primo
livello, quindi da li' un import relativo non funzionerebbe.

Icona e proprieta' del file (nome, versione, copyright) vengono **generate**
da `tools/make_icon.py` e `tools/make_version_info.py`, cosi' la versione
mostrata da Windows non puo' divergere da `hub/__init__.py`. Per un'icona tua,
basta mettere il tuo `build/icon.ico` e togliere quella riga da `build.ps1`.

Se l'eseguibile non parte, il motivo e' scritto in
`%LOCALAPPDATA%\Sici29Hub\hub.log`.

---

## Dove finiscono i dati

Tutto sotto `%LOCALAPPDATA%\Sici29Hub` (si apre dal pulsante **Apri cartella
dati**):

| | |
|---|---|
| `state.json` | versioni installate, novita' gia' viste, impostazioni |
| `covers\` | copertine in cache, con l'indice della fonte di ognuna |
| `cache\github.json` | risposte GitHub con il loro ETag |
| `downloads\` | installer scaricati |
| `hub.log` | registro degli eventi e degli errori |
| `account.bin` | il token GitHub, cifrato con DPAPI |

### Il limite di richieste a GitHub

Senza autenticazione l'API di GitHub concede **60 richieste all'ora per
indirizzo IP**. Un controllo completo ne usa **6**: una per l'elenco dei repo e
una per le release di ogni traduzione. Sono quindi una decina di controlli
completi all'ora, e il contatore si azzera da solo ogni ora — quello che vedi
nelle impostazioni e' quanto resta nell'ora in corso.

Due precisazioni misurate sul campo, non date per buone:

- gli ETag **fanno risparmiare banda ma non richieste**: una risposta `304` pesa
  sul limite esattamente come una `200`. La documentazione storica di GitHub
  dice il contrario, ma oggi non e' piu' vero;
- `hub.json` viene invece letto da `raw.githubusercontent`, che sta fuori
  dall'API e **non** intacca quelle 60 richieste. Per questo l'hub puo'
  cercare il marcatore su tutti i repo dell'account senza pensarci.

Per non esaurire il limite, l'hub non ricontrolla se l'ultimo controllo
riuscito risale a meno di 10 minuti prima (il pulsante **Controlla** forza
comunque l'aggiornamento), e sospende i controlli automatici quando restano
meno di 8 richieste.

### Come azzerare del tutto le richieste

Due strade, cumulabili:

**Il catalogo pre-generato.** La Action `catalogo-e-sito.yml` gira ogni tre ore
qui su GitHub — dove il `GITHUB_TOKEN` concede 5.000 richieste all'ora — e
scrive `catalog.json` con dentro repo, release e AppID Steam già risolti.
L'hub lo scarica da `raw.githubusercontent`, che **sta fuori dall'API e non ha
alcun limite**: un file solo invece di sei chiamate, e il contatore resta a 60.
Se il file manca o ha più di 36 ore, l'hub torna da solo all'API.

Il file si riscrive solo quando cambia qualcosa che conta (una release, un
`hub.json`, una proposta) e comunque una volta al giorno, per tenere fresca la
data: la data di generazione e i contatori di download, che cambiano a ogni
giro, da soli non bastano. Altrimenti sarebbe un commit ogni tre ore.

Il generatore controlla anche gli AppID dichiarati nei `hub.json`: se un numero
punta a un gioco con un altro nome lo scarta e lo cerca di nuovo, così un
errore non finisce in catalogo per tutti gli utenti.

**L'accesso a GitHub.** Chi si collega passa a 5.000 richieste all'ora.

Va detto che il problema è più piccolo di quanto sembri: il limite è **per
indirizzo IP**, non globale. Mille utenti hanno mille quote separate, non una
divisa in mille. Contano davvero solo chi sta dietro a un IP condiviso
(CGNAT di certi operatori, reti aziendali) e chi ricontrolla di continuo.

---

## Il sito

**https://sici29.github.io/gioca-in-italiano/** — una pagina per ogni
traduzione, pensata per chi cerca su Google "Aniimo traduzione italiana" e non
sa nemmeno che esiste GitHub. Ogni pagina dice subito cosa scaricare, quale
lingua scegliere nel gioco e come si torna all'originale, e mostra le novità
dell'ultima versione.

Lo genera `tools/genera_sito.py` dagli stessi dati del catalogo, con le stesse
copertine e gli stessi colori dell'hub, e lo pubblica la stessa Action del
catalogo, ogni tre ore. Non c'è niente da fare a mano: una release nuova, o una
traduzione nuova, finisce sul sito al giro successivo. La Action pubblica solo
se il sito è cambiato davvero: confronta l'impronta di quello appena generato
(`impronta.txt`) con quella del sito online.

Sono pagine statiche, senza JavaScript: si aprono al volo anche dal telefono e
Google le legge per intero. Ci sono i dati strutturati per i risultati di
ricerca e l'anteprima per chi condivide il link su WhatsApp, Telegram o Discord.

Il pulsante per scaricare l'hub compare da solo quando questo repo ha una
release con dentro l'exe. Finché non c'è, il sito non ne parla.

### Cosa si aggiorna da solo

Tutto, a ogni giro della Action (ogni tre ore):

- **i numeri in cima**: i giochi tradotti (i repo con almeno una release), i
  download (la somma delle ultime 12 release di ogni traduzione, arrotondata
  per difetto: "oltre 1.100") e la data dell'ultimo aggiornamento, cioè
  l'ultima release uscita. Il sito legge i dati appena scaricati
  (`--fresco`), non `catalog.json`, che si riscrive solo quando cambia
  qualcosa che conta;
- **le copertine**, riscaricate ogni volta da Steam, o dal `cover_url` del
  `hub.json` se c'è, e con loro la tinta di ogni gioco. La copertina scelta a
  mano nell'hub con "Cambia immagine" resta sul PC di chi l'ha scelta: per
  cambiarla sul sito si mette il `cover_url` nel `hub.json`;
- versioni, note di rilascio, pulsanti di download, proposte e il pulsante
  dell'app.

Siccome i download sono arrotondati, il sito si ripubblica davvero solo quando
un numero cambia di centinaio, o quando cambia qualcos'altro.

### Quello che il catalogo non sa

La lingua da scegliere nel gioco, il tasto per tornare all'originale, cosa fare
se l'installer non trova il gioco: stanno in `sito/giochi.json`, una voce per
repo. Sono tutte facoltative. Una traduzione nuova ha comunque la sua pagina,
con istruzioni generiche, ma una pagina precisa risponde alle domande prima che
arrivino.

### Farsi trovare prima da Google

Google trova il sito da solo seguendo i link (i README delle traduzioni, le
guide su Steam), ma ci mette settimane. Per accorciare i tempi:

1. [Google Search Console](https://search.google.com/search-console) →
   **Aggiungi proprietà** → **Prefisso URL** →
   `https://sici29.github.io/gioca-in-italiano/`;
2. come verifica scegli **File HTML**: il file che ti fa scaricare va messo in
   `sito/radice/` (tutto quello che sta lì finisce così com'è nella radice del
   sito), poi si fa il commit e si aspetta il giro della Action;
3. in **Sitemap** aggiungi `sitemap.xml`.

### Guardarlo prima di pubblicarlo

```powershell
python tools/genera_sito.py --uscita _sito
python -m http.server 8740 --directory _sito
```

e si apre `http://localhost:8740`. Con `--catalogo catalog.json` usa un catalogo
già scaricato invece di interrogare GitHub.

---

## Test

329 test, nessuna rete: tutto cio' che tocca GitHub o Steam e' simulato,
quindi girano in pochi secondi e anche su Linux (la Action `test.yml` li
esegue a ogni push). Si saltano da soli i sei che cifrano davvero con DPAPI,
che e' di Windows, e quelli che eseguono `app.js` se manca Node.

Quei tredici sono la parte insolita: caricano davvero l'interfaccia in Node,
con un finto `document` sotto, e chiamano le sue funzioni. Servono perche' la
logica di `app.js` - l'ordine delle card, la ricerca, la riga sotto il titolo -
si rompe restando sintatticamente valida: mostra la cosa sbagliata e non se ne
accorge nessuno. Di rimbalzo, un errore di sintassi in `app.js` fa fallire i
test invece di presentarsi come una finestra bianca.

Coprono soprattutto i punti dove e' gia' andato storto qualcosa:

- "Star Citizen" non deve agganciare *Citizen Sleeper 2*;
- un AppID sbagliato nel `hub.json` va smascherato confrontando il nome sullo
  store, ma un titolo troppo recente per avere una scheda va lasciato passare;
- i segnaposto minuscoli che Steam manda al posto di un 404 non sono copertine;
- la trasparenza di un PNG non deve diventare nera;
- uno `state.json` di una versione precedente deve acquisire i campi nuovi
  senza perdere i vecchi;
- il repo profilo non e' mai una traduzione;
- un catalogo con formato piu' recente, o vecchio di giorni, va ignorato;
- il giro completo dell'accesso a un clic deve restituire il token, e uno
  `state` falsificato deve essere rifiutato;
- un percorso di gioco gia' noto non deve far riscandire i dischi, e uno
  sparito non deve essere riusato;
- la cartella trovata su disco batte la voce senza percorso del registro;
- scritture concorrenti sulla cache di GitHub non devono fallire, e il file
  salvato deve restare JSON valido;
- Client ID e secret incollati al contrario devono essere rimessi a posto, e
  il file che li custodisce non deve contenerli in chiaro;
- un Client ID inesistente va bocciato *prima* di aprire il browser, ma una
  rete caduta non deve bloccare l'attivazione;
- le credenziali salvate dalla procedura guidata devono avere la precedenza su
  quelle compilate nell'eseguibile;
- la procedura di attivazione non deve comparire nell'eseguibile distribuito,
  ma deve aprirsi dai sorgenti e con `--setup`;
- le righe per `config.py` devono essere ricavabili dalle credenziali gia'
  salvate, non solo dai campi appena compilati;
- lo strumento che scrive `hub/credenziali.py` deve leggere sia le righe
  pronte sia le due stringhe nude, anche invertite, e `config.py` non deve
  mai contenere credenziali scritte a mano;
- la riga "cosa cambia" deve saltare il titolo delle note e pescare il primo
  punto elenco, e non dire niente quando non c'e' niente da dire;
- l'ordine "Per te" deve mettere un tuo gioco da aggiornare davanti a tutto;
- la ricerca deve trovare "Pokemon" scrivendo senza accento;
- la tinta di una copertina non deve essere il nero dello sfondo, che su una
  copertina di gioco e' quasi sempre il colore piu' esteso, e un'immagine
  senza colore deve ripiegare sull'ambra invece di restituire un grigio;
- la compatibilita' non deve pronunciarsi quando i dati non bastano, e non
  deve mai sollevare un'eccezione: gira su ogni traduzione a ogni controllo,
  e un errore li' svuoterebbe la griglia;
- dopo un'installazione lo stato della card deve cambiare **senza** chiedere
  niente a GitHub;
- un token revocato non deve rompere l'avvio: al primo 401 viene messo da
  parte, la richiesta riparte senza, e l'hub si scollega da solo avvisando
  una volta;
- alla finestra non devono mai arrivare eccezioni, URL o codici HTTP;
- una card non deve mostrare insieme "Nuova versione" e "Da aggiornare", e la
  parola "aggiornata" - che in italiano si legge "gia' a posto" - non deve
  comparire;
- dalle sole date non deve uscire un pallino verde;
- se GitHub non risponde la griglia resta quella dell'ultima volta, e una
  traduzione che non si e' potuta ricontrollare non deve sparire;
- le proposte devono arrivare davvero alla finestra (per un bel po' non ci
  arrivavano, e non se ne accorgeva nessuno perche' ancora non ce n'erano);
- nessun tag HTML delle note di rilascio deve arrivare al sito, e nemmeno un
  link che non sia web;
- una traduzione senza release non deve avere una pagina con un pulsante che
  non porta da nessuna parte, e il sito non deve nominare l'app finche' non c'e'
  un exe da scaricare;
- l'impronta del sito deve restare uguale se non cambia niente, altrimenti la
  Action ripubblicherebbe a ogni giro;
- `catalog.json` non va riscritto solo perche' sono cambiati data e download;
- la stessa notifica non deve tornare a ogni controllo, e un link
  `giocainitaliano:` scritto da altri non deve poter installare niente.

---

## Struttura

```
hub/
  config.py      regole di riconoscimento dei repo  <- si tocca solo questo
  ghclient.py    GitHub con cache ETag
  steam.py       ricerca AppID e copertine
  covers.py      risoluzione, ritaglio, cache, copertina generata
  scan.py        giochi installati sul PC
  catalog.py     mette tutto insieme e calcola gli stati
  installer.py   download con avanzamento e avvio
  links.py       segnalazioni GitHub precompilate
  auth.py        accesso a GitHub (PKCE + device flow, credenziali e token
                 cifrati con DPAPI)
  credenziali.py credenziali OAuth, generato e non versionato (vedi sopra)
  feed.py        lettura del catalogo pre-generato
  selfupdate.py  controllo della versione dell'hub
  singleton.py   una sola finestra per volta
  journal.py     registro eventi a rotazione
  api.py         ponte verso l'interfaccia
  web/           interfaccia (HTML/CSS/JS)
tools/
  build_catalog.py     genera catalog.json (gira in GitHub Actions)
  genera_sito.py       genera il sito (gira nella stessa Action)
  make_icon.py         disegna build/icon.ico
  make_version_info.py proprieta' del file per Windows
  preview.py           apre l'interfaccia nel browser con dati veri
sito/
  stile.css            l'aspetto del sito
  giochi.json          lingua, ripristino e note di ogni traduzione
  radice/              file copiati tali e quali nella radice del sito
tests/           329 test, senza rete
```

---

## Crediti

La tecnica per risolvere le copertine dagli endpoint pubblici di Steam prende
spunto da [DLSS5-Swapper](https://github.com/rakanki911/DLSS5-Swapper) di
Rakan Alkhaldi (licenza MIT), rivista e ampliata con il ripiego su `og:image`
e con i controlli contro gli abbinamenti sbagliati.

Le traduzioni distribuite da questo hub sono amatoriali e non ufficiali, non
affiliate ne' approvate dagli sviluppatori o dagli editori dei giochi. Marchi
e copertine appartengono ai rispettivi proprietari.

