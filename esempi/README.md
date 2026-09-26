# Il file `hub.json`

Va nella **root** di ogni repo di traduzione. E' il marcatore che dice all'hub
"questo repo e' una traduzione", ed e' anche il posto dove correggere quello
che l'hub non riesce a indovinare da solo.

Basta committarlo perche' la traduzione compaia nell'hub: non serve toccare il
codice dell'hub, e il repo puo' chiamarsi come vuoi.

## Campi

| Campo | Serve a | Se lo ometti |
|---|---|---|
| `nome_gioco` | Nome mostrato e usato per cercare su Steam | Viene ricavato dal nome del repo |
| `steam_appid` | Copertina presa dal gioco giusto, senza ambiguita' | L'hub cerca per nome su Steam |
| `cover_url` | Copertina presa da un URL tuo | Si usa Steam, poi una copertina generata |
| `non_su_steam` | `true` se il gioco su Steam non esiste proprio | L'hub prova comunque a cercarlo |
| `descrizione` | Riga sotto il titolo | Si usa la descrizione del repo su GitHub |
| `motore_installazione` | Tuo campo interno, l'hub lo mostra e basta | — |
| `nascondi` | `true` per tenere il repo fuori dall'hub | Il repo viene mostrato |

## Come trovare l'AppID giusto

E' il numero nell'indirizzo della pagina Steam:
`store.steampowered.com/app/`**`2186990`**`/Fatekeeper/`

Se sbagli numero l'hub se ne accorge: confronta il nome sulla scheda Steam con
`nome_gioco` e, se non combaciano, ignora l'AppID e avvisa nel pannello
dettagli invece di scaricare la copertina di un altro gioco.
