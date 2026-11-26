# vout — Kontext projektu a zadanie

## Účel projektu
**vout** je jednoduchá, spoľahlivá, open-source, self-hosted webová aplikácia na elektronické hlasovanie miestneho / obecného zastupiteľstva (prvé nasadenie: MČ Košice-Dargovských hrdinov / Furča, ale architektúra musí byť obecne konfigurovateľná pre akúkoľvek obec/MČ na Slovensku).

Motivácia: nahradiť ručné zdvíhanie rúk a ručné zapisovanie, vyhnúť sa subscription SaaS appkám ktoré zanikajú, aj komerčným 600 €/zasadnutie systémom.

## Záväzné architektonické a funkčné požiadavky

### 1. Platforma a prevádzka
- **Webapp (mobile-first, PWA-friendly):** Žiadne natívne iOS/Android appky. Poslanci sa pripájajú z vlastného mobilu cez prehliadač.
- **Self-hosted & offline-first:** Musí bežať lokálne v zasadačke na bežnom laptope (Fedora), mini-PC (ThinkCentre) alebo Raspberry Pi bez závislosti na internete či externom cloude.
- **Preferovaný stack (jednoduchý, udržiavateľný na roky):**
  - Backend: **Python (FastAPI) + SQLite** (jeden databázový súbor) + **WebSockets** (alebo SSE) pre real-time synchronizáciu mobilov, admina a projektora.
  - Frontend: Čistý, rýchly mobilný HTML/CSS/JS (bez zbytočne ťažkého Node/build toolchainu, pokiaľ na to nie je silný dôvod).

### 2. Roly a obrazovky
1. **`/vote` — Poslanec (mobil):**
   - Prihlásenie cez unikátny session QR kód alebo osobný PIN pre dané zasadnutie (žiadne zložité účty/heslá, ale cudzí človek v sále nemôže hlasovať za poslanca).
   - Vidí svoje meno, aktuálne zasadnutie (názov, dátum), potvrdenie prítomnosti (prezenčka) a aktuálne otvorené hlasovanie (číslo hlasovania + názov bodu).
   - Hlasuje ťuknutím: **ZA / PROTI / ZDRŽAL SA**. Kým je hlasovanie otvorené, môže svoj hlas prekliknúť. Kto nehlasuje do uzavretia, je evidovaný ako **NEHLASOVAL** (zodpovednosť poslanca — systém mu „neutiera zadok“).
2. **`/admin` — Zapisovateľ / Predsedajúci (laptop):**
   - Chránené admin heslom/PINom.
   - Zakladanie zasadnutí (názov, číslo, dátum, zoznam poslancov, generovanie QR/PIN prístupov).
   - Dynamická správa programu počas schôdze: pridávať body, odoberať body, presúvať poradie, pridávať podbody / pozmeňujúce a procedurálne návrhy.
   - Výber typu kvóra pred spustením hlasovania, otvorenie a uzavretie hlasovania, možnosť spustiť opakované hlasovanie pod novým číslom (pôvodné uzavreté hlasovanie sa nikdy tajne nemaže).
   - Plné právo zapisovateľa doplniť alebo upraviť prítomnosť či hlas poslanca (manual override pri probléme) — **každý zásah zapisovateľa musí byť zaznamenaný v audit logu** s timestampom a dôvodom/označením.
   - Export záznamov a zápisnice.
3. **`/display` — Projektor / TV v sále (read-only):**
   - Čistý, vysoko čitateľný prehľad pre sálu a verejnosť: názov zasadnutia, aktuálny bod, počet prítomných, stav hlasovania, po uzavretí menovitý výsledok a jednoznačný verdikt (**SCHVÁLENÉ / NESCHVÁLENÉ**).

### 3. Kvóra (SR legislatíva — overené v `knowledge/domain-rules.md`)
Každé hlasovanie musí mať voliteľný typ potrebnej väčšiny a správny automatický výpočet výsledku (celočíselná aritmetika; uznášaniaschopnosť = `floor(total / 2) + 1`):
- `majority_present` — Nadpolovičná väčšina prítomných poslancov (`floor(present / 2) + 1`): štandardné uznesenia (§ 12 ods. 7 zák. 369/1990 Zb.)
- `majority_all` — Nadpolovičná väčšina všetkých poslancov (`floor(total / 2) + 1`): zmena návrhu programu (§ 12 ods. 5), kontrolór (§ 18a), zmluvy obcí (§ 20a, § 20b), zrušenie OVS (§ 9a ods. 7 zák. 138/1991 Zb.)
- `three_fifths_present` — Trojpätinová (3/5) väčšina prítomných poslancov (`ceil(3 * present / 5)`): prijatie VZN (§ 12 ods. 7 zák. 369/1990 Zb.)
- `three_fifths_all` — Trojpätinová (3/5) väčšina všetkých poslancov (`ceil(3 * total / 5)`): prelomenie veta starostu (§ 13 ods. 8 zák. 369/1990 Zb.), prevod/nájom majetku z dôvodu hodného osobitného zreteľa (§ 9a, § 9aa zák. 138/1991 Zb.), koncesie, referendum o odvolaní starostu
*(Všetky presné paragrafy, lokálne pravidlá MČ Furča a upozornenia k platnému Rokovaciemu poriadku sú v [knowledge/domain-rules.md](knowledge/domain-rules.md).)*

### 4. Výstupy & Transparentnosť
- **Tlačiteľný záznam (Print-ready HTML → PDF):** Zasadnutie, dátum, prezenčka, zoznam všetkých hlasovaní (č. 1, 2, 3…), presný názov bodu, typ kvóra, súhrn (ZA / PROTI / ZDRŽAL SA / NEHLASOVAL), verdikt a menovitý výpis hlasovania každého poslanca.
- **Upraviteľný export pre zapisovateľa:** DOCX a/alebo Markdown + CSV, aby sa dal ľahko vložiť do oficiálnej zápisnice.
- **Audit log:** Nezmazateľný časový záznam každej kľúčovej udalosti (prihlásenie, potvrdenie prítomnosti, hlas, zmena hlasu, uzavretie, manual override zapisovateľa).

### 5. Hygiena repozitára & GDPR
- Toto repo obsahuje **len zdrojový kód, testy, verejnú doménovú knižnicu (`knowledge/`), verejné zoznamy volených poslancov bez PINov a kontaktov (`presets/`) a anonymizované demo/seed dáta**.
- Nikdy necommitovať reálne SQLite databázy, exporty z ostrých zasadnutí, PINy/QR tokeny ani súkromné kontaktné/osobné údaje (`*.db`, `data/`, `exports/`, `sensitive/`, `.env` sú v `.gitignore`).
- Súkromné a interné podklady (napr. neanonymizované kontakty, interné úradné dokumenty, lokálne PINy) patria výhradne do `sensitive/`, nikdy nie do `knowledge/` ani do `data/`.

## Prvý krok v novom chate
1. Navrhnúť konkrétny dátový model (SQLite schému), API/WebSocket protokol a štruktúru súborov pre MVP.
2. Dohodnúť s používateľom špecifiká podľa Rokovacieho poriadku (napr. počet poslancov, presné pravidlo pre prítomnosť/nehlasoval, formát zápisnice).
3. Postaviť funkčné lokálne MVP a otestovať ho z reálneho mobilu na lokálnej Wi-Fi.
