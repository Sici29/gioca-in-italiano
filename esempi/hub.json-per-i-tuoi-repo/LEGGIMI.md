# hub.json corretti, uno per repo

Ogni file va rinominato in `hub.json` e messo nella root del repo omonimo.
Rispetto a quelli che hai adesso cambia questo:

| Repo | Cosa cambia | Perche' |
|---|---|---|
| **Fatekeeper** | `steam_appid` da `"2498620"` a `2186990` | 2498620 su Steam e' **King Krieg**, un altro gioco. Era l'origine della copertina sbagliata. |
| **NTE** | `steam_appid` da `null` a `4508340`, tolto `cover_url` | Il gioco su Steam c'e' (`NTE: Neverness to Everness`). Il `cover_url` di rawg.io rispondeva 404. |
| **Star Citizen** | tolto `cover_url`, aggiunto `non_su_steam: true` | Quell'URL era un segnaposto mai valido (`x2o0x2o0...`). Il flag dice all'hub di non cercarlo su Steam. |
| **ARK** | `steam_appid` da stringa a numero | Funzionava gia', ma il numero e' il tipo giusto. |
| **Aniimo** | file nuovo | Non aveva `hub.json`: l'hub lo trovava dal nome del repo, ma cosi' e' esplicito. |

Non sono obbligatori: l'hub funziona lo stesso. Servono a togliere ogni
ambiguita' e a non dipendere dalla ricerca per nome.

## `game_build`: dire a che versione del gioco arriva la traduzione

E' il campo nuovo. L'hub confronta la versione del gioco installato con quella
che la traduzione copre, e lo dice sulla card e nei dettagli. Con `game_build`
il confronto e' esatto; senza, l'hub ripiega sulle date e dice le stesse cose
con meno sicurezza.

Il numero da mettere e' il **buildid di Steam**, quello che Steam scrive nel
suo `appmanifest_<appid>.acf`:

```
"D:\SteamLibrary\steamapps\appmanifest_4126040.acf"
   "buildid"    "25525975"     <- questo
```

I valori nei file qui dentro sono quelli letti sul tuo PC il 26 settembre 2026.

> **Attenzione.** Non e' il numero di build che compare nei nomi dei tuoi
> rilasci. "supporto Steam build 3595896" e' il numero interno di Aniimo;
> Steam per lo stesso gioco usa 25525975. Sono due numerazioni che non si
> parlano, e confonderle fa dire all'hub che il gioco e' avanti di ventidue
> milioni di build. Per questo l'hub non prova a indovinarlo dai nomi dei
> rilasci: si fida solo di quello che scrivi qui.

**Va aggiornato a ogni rilascio.** Se lo lasci indietro, l'hub dira' "il gioco
e' stato aggiornato dopo questa traduzione" anche quando non e' vero. Se non
te la senti di tenerlo aggiornato, **toglilo**: senza, l'hub usa le date, che
si aggiornano da sole e non mentono mai a tuo sfavore.

Per i giochi fuori Steam c'e' `game_version`, dove basta la serie della patch:
Star Citizen dichiara `"4.10"`, e l'hub la confronta con quello che legge nel
`build_manifest.id` del gioco (`sc-alpha-4.10.0`). Le revisioni minori non
contano: 4.10.0 e 4.10.2 sono la stessa patch per chi ci gioca.

ARK non ce l'ha perche' non risulta installato sul tuo PC: aggiungilo quando
pubblichi il prossimo aggiornamento, leggendolo dal suo `appmanifest`.

## Star Citizen: la copertina

Non essendo su Steam, l'hub gli disegna una copertina propria. Per metterne una
vera hai due strade:

1. dall'hub, **Dettagli**, passa col mouse sulla copertina e premi
   **Cambia immagine**
   (vale solo sul tuo PC);
2. carichi l'immagine da qualche parte e ne metti l'indirizzo in `cover_url`
   nel `hub.json` (vale per tutti quelli che usano l'hub).

Per la seconda, il posto piu' comodo e' il repo stesso: metti il file in
`assets/` e usa l'URL `raw.githubusercontent.com`, per esempio
`https://raw.githubusercontent.com/Sici29/SC-Italian-Translation/main/assets/cover.jpg`.
Il formato ideale e' 460x215.
