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

### 3. Kvóra (SR legislatíva — zákon 369/1990 Zb. & Rokovací poriadok)
Každé hlasovanie musí mať voliteľný typ potrebnej väčšiny a správny automatický výpočet výsledku:
- Nadpolovičná väčšina prítomných poslancov (štandardné uznesenia)
- Nadpolovičná väčšina všetkých poslancov
- Trojpätinová (3/5) väčšina všetkých poslancov (VZN, majetkové prevody)
- Trojpätinová (3/5) väčšina prítomných poslancov (ak vyžaduje rokovací poriadok)
*(Pred finálnym dolaďovaním overiť detaily proti konkrétnemu Rokovaciemu poriadku MČ.)*

### 4. Výstupy & Transparentnosť
- **Tlačiteľný záznam (Print-ready HTML → PDF):** Zasadnutie, dátum, prezenčka, zoznam všetkých hlasovaní (č. 1, 2, 3…), presný názov bodu, typ kvóra, súhrn (ZA / PROTI / ZDRŽAL SA / NEHLASOVAL), verdikt a menovitý výpis hlasovania každého poslanca.
- **Upraviteľný export pre zapisovateľa:** DOCX a/alebo Markdown + CSV, aby sa dal ľahko vložiť do oficiálnej zápisnice.
- **Audit log:** Nezmazateľný časový záznam každej kľúčovej udalosti (prihlásenie, potvrdenie prítomnosti, hlas, zmena hlasu, uzavretie, manual override zapisovateľa).

### 5. Hygiena repozitára & GDPR
- Toto repo obsahuje **len zdrojový kód, testy a anonymizované demo/seed dáta**.
- Nikdy necommitovať reálne SQLite databázy, exporty z ostrých zasadnutí, PINy ani osobné údaje poslancov (`*.db`, `data/`, `exports/`, `.env` sú v `.gitignore`).

## Prvý krok v novom chate
1. Navrhnúť konkrétny dátový model (SQLite schému), API/WebSocket protokol a štruktúru súborov pre MVP.
2. Dohodnúť s používateľom špecifiká podľa Rokovacieho poriadku (napr. počet poslancov, presné pravidlo pre prítomnosť/nehlasoval, formát zápisnice).
3. Postaviť funkčné lokálne MVP a otestovať ho z reálneho mobilu na lokálnej Wi-Fi.
