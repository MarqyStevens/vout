# vout

Jednoduchá, self-hosted, offline-first webová aplikácia na elektronické hlasovanie obecného / miestneho zastupiteľstva (SR legislatíva).

## Obrazovky
- **Mobil poslanca (`/vote`):** Prihlásenie cez QR kód alebo 4-miestny PIN, virtuálna **kartička prítomnosti v sále**, odpočet a hlasovanie jedným ťukom (**ZA / PROTI / ZDRŽAL SA**).
- **Ovládanie zapisovateľa (`/admin`):** Správa zasadnutí, dynamického programu, prezenčky, 4 slovenských kvór, odpočtu (`10s / 15s / 20s / 30s / bez limitu`, `+10s`, okamžité uzavretie), opakovaných hlasovaní, manuálnych zásahov s povinným audit logom a exportov.
- **Projektor / TV v sále (`/display`):** Mená poslancov a ich prítomnosť, počas odpočtu len fajočky (`✓ HLASOVAL`), po uplynutí času okamžitý menovitý výsledok a jednoznačný verdikt (**SCHVÁLENÉ / NESCHVÁLENÉ**).

## Rýchle spustenie (Linux / Fedora / Raspberry Pi)

```bash
./start.sh
```

Po spustení vypíše aplikácia presnú lokálnu aj Wi-Fi adresu pre mobily a projektor (predvolený port `8000`).

- **Predvolený PIN zapisovateľa (`/admin`):** `1234` *(zmena cez `VOUT_ADMIN_PIN=xxxx ./start.sh`)*
- **Demo zasadnutie:** Pri prvom spustení sa automaticky vytvorí testovacie zasadnutie s 13 vymyslenými poslancami (PINy `1001` až `1013`).

## Výstupy a právne pravidlá
- **Tlačiteľné `Hlasovanie` (HTML → PDF)**, **Word (`.docx`)**, **Markdown (`.md`)**, **Excel CSV (`.csv`)** a **tlačiteľné QR/PIN karty** pre poslancov.
- Právny základ (zák. 369/1990 Zb., 401/1990 Zb., 138/1991 Zb., Štatút mesta Košice, Rokovací poriadok MČ Košice-Dargovských hrdinov) je zdokumentovaný v [knowledge/domain-rules.md](knowledge/domain-rules.md).
