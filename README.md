# vout

Jednoduchá, self-hosted webová aplikácia na hlasovanie obecného / miestneho zastupiteľstva.

Navrhnutá pre reálne zasadnutia bez mesačných poplatkov, bez cloudových závislostí a bez drahého hardvéru:
- **Mobil poslanca (`/vote`):** Funguje v každom prehliadači (iOS / Android), potvrdenie prítomnosti, hlasovanie jedným ťukom (**ZA / PROTI / ZDRŽAL SA**).
- **Ovládanie zapisovateľa (`/admin`):** Správa zasadnutí, dynamické dopĺňanie/presúvanie/mazanie bodov a procedurálnych návrhov, výber kvóra, spúšťanie a uzatváranie hlasovaní, manuálne doplnenie/override s audit logom.
- **Projektor / TV v sále (`/display`):** Živý stav hlasovania a okamžité menovité výsledky pre poslancov aj verejnosť.
- **Výstupy:** Tlačiteľný prehľad hlasovaní (HTML/PDF) a upraviteľný export pre zápisnicu (DOCX / Markdown / CSV).
- **Offline-first:** Beží lokálne na laptope, ThinkCentre alebo Raspberry Pi s jedným SQLite súborom.
