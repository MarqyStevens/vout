# Doménové a právne pravidlá (`vout`)

> **Účel dokumentu:** Záväzná referencia právnych a procesných pravidiel pre návrh, implementáciu a overenie hlasovacieho systému **vout**.  
> **Zdroje:** Výlučne primárne dokumenty v `knowledge/raw/` (pozri [sources.md](sources.md)) a overená prax MČ Košice-Dargovských hrdinov.  
> **Jazyková konvencia:** Právne pojmy a UI sú v slovenčine; v zátvorkách v backtickoch sú anglické kódové identifikátory (napr. `majority_present`) pre jednoznačné mapovanie 1:1 do databázy a kódu.  
> **Upozornenie:** Každé pravidlo cituje presný §/článok zdroja. Pred prvým ostrým nasadením odporúčame tento prehľad odkontrolovať s právnikom úradu / kontrolórom MČ.

---

## 1. Hierarchia právnych predpisov

1. **Zákon SNR č. 369/1990 Zb. o obecnom zriadení** *(účinný od 15. 7. 2026)* — základný rámec pre všetky obce na SR; pre mestské časti Košíc platí primerane v otázkach neupravených zákonom o meste Košice (§ 14 ods. 1 zák. 401/1990 Zb.).
2. **Zákon SNR č. 401/1990 Zb. o meste Košice** *(účinný od 24. 10. 2026)* — osobitná úprava pre mesto Košice a jeho mestské časti (počet poslancov, pôsobnosť MiZ, miestna rada, prednosta).
3. **Zákon SNR č. 138/1991 Zb. o majetku obcí** *(účinný od 1. 1. 2025)* — osobitné kvalifikované kvóra pre nakladanie s majetkom (najmä dôvod hodný osobitného zreteľa).
4. **Štatút mesta Košice** *(úplné znenie k 1. 1. 2026)* — deľba pôsobností medzi mesto a MČ pri zverenom majetku (napr. § 53, § 64, § 72, § 84).
5. **Rokovací poriadok MiZ MČ Košice-Dargovských hrdinov** *(2018 v znení dodatkov č. 1–3; posledná zmena účinná od 29. 6. 2023)* — podrobné pravidlá rokovania a hlasovania.  
   *(Pozn.: Pripravuje sa nový Rokovací poriadok MČ — preto všetky lokálne pravidlá musia byť v appke konfigurovateľné, nie zadrôtované natvrdo.)*

---

## 2. Účastníci zasadnutia a hlasovacie právo

| Rola | Hlasuje? | Ráta sa do prítomných / kvóra? | Právny základ |
| --- | :---: | :---: | --- |
| **Poslanec MiZ / OZ** (`councilor`) | **ÁNO** | **ÁNO** | § 12 ods. 7 zák. 369/1990 Zb. *(pozn.: po zložení sľubu podľa Čl. 3 ods. 4 RP)* |
| **Zástupca starostu** (`deputy_mayor`) | **ÁNO** *(je to poslanec)* | **ÁNO** | § 15a ods. 1 zák. 401/1990 Zb. („Zástupca starostu môže byť len poslanec miestneho zastupiteľstva.“) |
| **Starosta** (`mayor`) | **NIE** | **NIE** | § 13 ods. 3 písm. a) zák. 369/1990 Zb. („Funkcia starostu je nezlučiteľná s funkciou poslanca.“) |
| **Prednosta MÚ** (`office_head`) | **NIE** *(hlas poradný)* | **NIE** | § 17a ods. 3 zák. 401/1990 Zb. („zúčastňuje sa zasadnutí MiZ a MR s hlasom poradným.“) |
| **Zapisovateľ / Admin** (`admin`) | **NIE** | **NIE** | Organizačno-technické zabezpečenie (Čl. 16 ods. 2 RP) |

- **Počet poslancov (`total_councilors`):**
  - Pre MČ Košice-Dargovských hrdinov (nad 20 000 obyvateľov → 11 až 13 poslancov podľa § 14 ods. 2 písm. d) zák. 401/1990 Zb.) je aktuálne ustanovený počet **13 poslancov** (3 volebné obvody: 3 + 5 + 5).
  - V systéme `vout` musí byť `total_councilors` konfigurovateľné pre každé zasadnutie/obec (od 3 poslancov vyššie).
  - **Pozor na neobsadený mandát vs. neprítomnosť:** Zákonné kvóra „všetkých poslancov“ vychádzajú z celkového počtu poslancov zastupiteľstva zvoleného/určeného pre dané volebné obdobie (`total_councilors`, resp. obsadených mandátov podľa aktuálnej právnej praxe — v appke vždy explicitne zobraziť a uložiť číslo `total_councilors` platné pre dané zasadnutie).

---

## 3. Uznášaniaschopnosť (`quorum_to_convene`)

- **Pravidlo:** Zastupiteľstvo je spôsobilé rokovať a uznášať sa vtedy, ak je prítomná **nadpolovičná väčšina všetkých poslancov**:
  $$\text{min\_present} = \left\lfloor \frac{\text{total\_councilors}}{2} \right\rfloor + 1$$
  - Pri **13 poslancoch** (MČ Furča): minimum prítomných je **7 poslancov**.
- **Právny základ:** § 12 ods. 7 zák. 369/1990 Zb.; Čl. 6 ods. 2 Rokovacieho poriadku MiZ.
- **Miestna / obecná rada** *(ak sa systém použije aj pre radu)*: uznášaniaschopná pri prítomnosti nadpolovičnej väčšiny všetkých členov rady; uznesenie prijíma nadpolovičnou väčšinou všetkých členov rady (§ 14 ods. 5 zák. 369/1990 Zb.; § 16 ods. 5 zák. 401/1990 Zb.; Čl. 13 ods. 7 RP).
- **Požiadavka na softvér:**
  - Pred spustením hlasovania aj v momente jeho uzavretia systém overuje `present_count >= floor(total_councilors / 2) + 1`.
  - Ak počas zasadnutia počet prítomných klesne pod hranicu uznášaniaschopnosti, `/admin` aj `/display` musia výrazne zobraziť stav **NEUZNÁŠANIASCHOPNÉ** a neuznať prípadné hlasovanie ako schválené.

---

## 4. Typy kvór (väčšín) a presné vzorce výpočtu

Všetky výpočty vychádzajú z počtu hlasov **ZA (`for`)** oproti prahu `required_for`:

| `quorum_type` | Slovenský názov | Presný vzorec (`required_for`) | Kedy sa použije (právny základ) |
| --- | --- | --- | --- |
| `majority_present` | **Nadpolovičná väčšina prítomných poslancov** *(predvolené)* | `floor(present / 2) + 1` | • Štandardné uznesenia MiZ/OZ (§ 12 ods. 7 zák. 369/1990; Čl. 9 ods. 9 RP)<br>• Schválenie programu bez zmeny návrhu (Čl. 6 ods. 5 RP)<br>• Zmena/doplnenie rokovacieho poriadku (Čl. 17 ods. 2 RP)<br>• Voľba členov miestnej rady a orgánov MiZ (Čl. 3 ods. 6, Čl. 13 ods. 5 RP)<br>• Procedurálne rozhodnutia (Čl. 1 ods. 2, Čl. 7 ods. 5 RP) |
| `majority_all` | **Nadpolovičná väčšina všetkých poslancov** | `floor(total / 2) + 1` | • **Zmena návrhu programu na začiatku zasadnutia** (§ 12 ods. 5 zák. 369/1990; Čl. 6 ods. 5 RP)<br>• Voľba a odvolanie hlavného kontrolóra (§ 18a ods. 3 a 10 zák. 369/1990)<br>• Zmluva o spolupráci obcí / združenie obcí (§ 20a ods. 4, § 20b ods. 5 zák. 369/1990)<br>• Zrušenie obchodnej verejnej súťaže z výnimočných dôvodov (§ 9a ods. 7 zák. 138/1991)<br>• Uznesenia miestnej/obecnej rady (§ 16 ods. 5 zák. 401/1990; § 14 ods. 5 zák. 369/1990)<br>• Schválenie/zmena Štatútu mesta Košice na MZ (§ 18 ods. 2 zák. 401/1990) |
| `three_fifths_present` | **Trojpätinová (3/5) väčšina prítomných poslancov** | `ceil(3 * present / 5)` *(celočíselne: `(3 * present + 4) // 5`)* | • **Prijatie všeobecne záväzného nariadenia (VZN)** (§ 12 ods. 7 zák. 369/1990; Čl. 10 ods. 5 RP) |
| `three_fifths_all` | **Trojpätinová (3/5) väčšina všetkých poslancov** | `ceil(3 * total / 5)` *(celočíselne: `(3 * total + 4) // 5`)* | • **Potvrdenie uznesenia pozastaveného starostom** — prelomenie veta (§ 13 ods. 8 zák. 369/1990; Čl. 9 ods. 11 RP)<br>• **Prevod majetku z dôvodu hodného osobitného zreteľa** (§ 9a ods. 15 písm. f) zák. 138/1991)<br>• **Nájom majetku z dôvodu hodného osobitného zreteľa** (§ 9aa ods. 2 písm. e) zák. 138/1991)<br>• Koncesné zmluvy (§ 9 ods. 2 písm. g) zák. 138/1991)<br>• Darovanie nehnuteľného majetku medzi mestom a MČ (§ 6a ods. 2 zák. 138/1991)<br>• Vyhlásenie miestneho referenda o odvolaní starostu (§ 8a ods. 3 zák. 401/1990) |

> **Poznámka k výpočtu v kóde:** Používať výhradne **celočíselnú aritmetiku** (`(n // 2) + 1` a `(3 * n + 4) // 5`), nikdy `float` (eliminuje chyby zaokrúhľovania v pohyblivej rádovej čiarke).

### Kontrolná tabuľka kvór pre 13 poslancov (MČ Košice-Dargovských hrdinov)

| Prítomných (`present`) | Uznášaniaschopné? | `majority_present` | `majority_all` | `three_fifths_present` | `three_fifths_all` |
| :---: | :---: | :---: | :---: | :---: | :---: |
| 0–6 | **NIE** | — | — | — | — |
| 7 | ÁNO | **4** | **7** | **5** *(4,2 → 5)* | **8** *(7,8 → 8)* |
| 8 | ÁNO | **5** | **7** | **5** *(4,8 → 5)* | **8** |
| 9 | ÁNO | **5** | **7** | **6** *(5,4 → 6)* | **8** |
| 10 | ÁNO | **6** | **7** | **6** *(6,0 → 6)* | **8** |
| 11 | ÁNO | **6** | **7** | **7** *(6,6 → 7)* | **8** |
| 12 | ÁNO | **7** | **7** | **8** *(7,2 → 8)* | **8** |
| 13 | ÁNO | **7** | **7** | **8** *(7,8 → 8)* | **8** |

---

## 5. Priebeh hlasovania, stavy hlasov a špeciálne situácie

### 5.1 Stavy prítomnosti a hlasu
- **Prítomnosť poslanca v danom okamihu (`is_present`):** `true` (prítomný v sále) alebo `false` (neprítomný / odišiel).
  - Pre zápisnicu je užitočné evidovať aj stav prezenčnej listiny (`present` / `excused` / `unexcused`) a logovať neskoré príchody a predčasné odchody (v reálnych zápisniciach MČ Furča sa píšu kurzívou pri príslušnom bode, napr. *„o 16:15 prišiel poslanec X“*).
  - **Snapshot prítomných pri uzavretí hlasovania:** Každé uzavreté hlasovanie si musí natvrdo zmraziť `present_count` a presný zoznam prítomných poslancov v momente uzavretia (neskorší príchod/odchod poslanca nesmie spätne meniť výsledok už uzavretého hlasovania!).
- **Stavy hlasu prítomného poslanca (`vote_value`):**
  - `for` — **ZA**
  - `against` — **PROTI**
  - `abstain` — **ZDRŽAL SA**
  - `not_voted` — **NEHLASOVAL** *(prítomný poslanec, ktorý do uzavretia hlasovania neklikol žiadnu možnosť)*
  - *(Neprítomný poslanec má v zápise daného hlasovania status `absent` — **NEPRÍTOMNÝ** a nezapočítava sa do `present_count`.)*
- **Účinok `abstain` a `not_voted`:** Obidva stavy zvyšujú `present_count` (menovateľ), ale nepridávajú hlas do `for` (čitateľ). V praxi tak pôsobia proti dosiahnutiu potrebnej väčšiny.

### 5.2 Poradie hlasovania a typy bodov
- **Schvaľovanie programu na začiatku zasadnutia (§ 12 ods. 5 zák. 369/1990; Čl. 6 ods. 5 RP):**
  - Najprv sa hlasuje o bodoch zverejneného návrhu programu.
  - Ak je navrhnutá zmena/doplnenie programu → kvórum `majority_all`.
  - Ak nie je navrhnutá zmena → schválenie celého programu ako uznesenia → `majority_present`.
- **Pozmeňujúce a doplňujúce návrhy (Čl. 9 ods. 7, Čl. 10 ods. 4 RP):**
  - Hlasuje sa **najprv o pozmeňujúcich návrhoch** (v poradí, v akom boli predložené), **potom o zvyšku / celku** návrhu uznesenia alebo VZN.
  - V systéme jeden bod programu môže obsahovať ľubovoľný počet hlasovaní (napr. pozmeňujúci návrh 1, pozmeňujúci návrh 2, pôvodný/upravený návrh celku).
- **Variantné návrhy a oddelené hlasovanie (Čl. 9 ods. 3–5 RP):**
  - Možnosť pridať pod jedným bodom viac hlasovaní (Variant A, Variant B, alebo jednotlivé časti uznesenia).
- **Procedurálne návrhy (Čl. 7 ods. 5 RP):**
  - Napr. návrh na ukončenie diskusie (hlasuje sa bez diskusie, `majority_present`), prerušenie rokovania (Čl. 7 ods. 8 RP), zmena poradia bodov.
  - Zapisovateľ musí vedieť kedykoľvek pridať ad-hoc procedurálne hlasovanie.
- **Diskusia a interpelácie (Čl. 9 ods. 8 RP):**
  - Z diskusie a interpelácií sa uznesenia neprijímajú (body bez povinnosti hlasovania).
- **Opakované hlasovanie (Čl. 9 ods. 6 RP):**
  - Pôvodné uzavreté hlasovanie sa **nikdy nemaže ani neprepisuje**. Spustí sa nové hlasovanie pod ďalším poradovým číslom (`vote_number + 1`) s odkazom na pôvodné hlasovanie / poznámkou *„opakované hlasovanie“*.
- **Voľba hlavného kontrolóra (2. kolo — § 18a ods. 3 zák. 369/1990):**
  - 1. kolo vyžaduje `majority_all`; ak nikto nezíska, 2. kolo rozhoduje relatívna väčšina platných hlasov / žreb. *(Edge case mimo bežného ZA/PROTI/ZDRŽAL SA — v MVP stačí evidovať samostatne alebo cez štandardné hlasovania pre jednotlivých kandidátov.)*
- **Tajné hlasovanie (Čl. 9 ods. 6 RP):**
  - Ak MiZ uznesením rozhodne o tajnom hlasovaní, volí hlasovaciu komisiu. **MVP `vout` je určené výhradne na verejné menovité hlasovanie**; tajné hlasovanie zostáva na hlasovaciu komisiu (lístky), kým sa prípadne neprijme osobitná úprava v rokovacom poriadku.

---

## 6. KRITICKÉ PRÁVNE UPOZORNENIE: „Zdvihnutím ruky“ v platnom Rokovacom poriadku MČ Furča

V aktuálne platnom Rokovacom poriadku MČ Košice-Dargovských hrdinov (2018 + dodatky 1–3) je explicitne uvedené:
- **Čl. 6 ods. 5:** *„Poslanci hlasujú **zdvihnutím ruky**.“* (schvaľovanie programu)
- **Čl. 9 ods. 6:** *„**Pokiaľ MiZ nerozhodne inak**, hlasuje sa verejne, **zdvihnutím ruky**. Sčítanie hlasov sa vykonáva skrutátormi, ktorí sa vzájomne kontrolujú.“* (uznesenia)
- **Čl. 10 ods. 4:** *„Hlasuje sa **zdvihnutím ruky**, pričom najprv sa hlasuje o pozmeňujúcich návrhoch…“* (nariadenia / VZN — **bez doložky „pokiaľ MiZ nerozhodne inak“!**)

### Dôsledok pre nasadenie na MČ Furča:
1. **Do schválenia nového Rokovacieho poriadku:**
   - Pre bežné uznesenia možno na úvod zasadnutia prijať procedurálne uznesenie (`majority_present`, odkaz na Čl. 9 ods. 6 a Čl. 1 ods. 2 RP), že MiZ bude hlasovať elektronicky cez systém `vout` (a skrutátori/overovatelia vizuálne potvrdzujú výsledok na obrazovke).
   - **Pri VZN (Čl. 10 ods. 4)** a zmene programu (Čl. 6 ods. 5) odporúčame do prijatia nového RP hlasovať elektronicky **súbežne so zdvihnutím ruky** (alebo potvrdiť ručne), aby nikto nemohol napadnúť procesnú platnosť VZN na prokuratúre!
2. **Čo zakotviť do pripravovaného nového Rokovacieho poriadku (odporúčané body):**
   - Výslovné povolenie elektronického hlasovacieho systému (vrátane webovej aplikácie na zariadeniach poslancov) pre všetky verejné hlasovania (program, uznesenia aj VZN).
   - Explicitné pravidlo pre stav **`NEHLASOVAL`**: ak prítomný poslanec neodovzdá hlas v stanovenom čase do uzavretia hlasovania, eviduje sa ako *nehlasoval* (započítava sa do prítomných).
   - Pravidlo pre **technický výpadok** jednotlivého zariadenia (poslanec ihneď nahlási predsedajúcemu a hlasuje verejne ústne/zdvihnutím ruky; zapisovateľ vykoná manuálny záznam s audit logom) a celkový výpadok systému (prechod na hlasovanie zdvihnutím ruky).
   - Pravidlo pre **námietku / opakovanie hlasovania** bezodkladne po zobrazení výsledku na projekcii.
   - Zverejňovanie výpisu menovitých hlasovaní ako prílohy zápisnice.

---

## 7. Formát zápisníc, uznesení a výpisu hlasovaní (prax MČ Furča)

Overené na zverejnených PDF zo zasadnutí 23 (17. 6. 2026) a 24 (16. 9. 2026) na `kosice-dh.sk`:

### 7.1 Konvencie číslovania
- **Zasadnutia:** priebežné číslo vo volebnom období (`1. ustanovujúce zasadnutie`, `23. zasadnutie`, `24. zasadnutie`).
- **Body programu (`item_number`):** textový reťazec (nie len integer!), lebo pri dodatočne vložených bodoch sa používajú aj desatinné čísla (`6.1`, `8.1`) alebo podbody (`a)`, `b)`).
- **Hlasovania (`vote_number`):** priebežné celé číslo `1, 2, 3…` v rámci jedného zasadnutia.
- **Uznesenia (`resolution_number`):** priebežné číslo v rámci kalendárneho roka vo formáte `NNN/RRRR` (napr. `207/2026`).
  - **Dôležité:** Neschválený návrh (napr. neprešlý pozmeňujúci návrh) **nedostáva číslo uznesenia** (`resolution_number = NULL`).

### 7.2 Štruktúra výstupu „Hlasovanie“ (tlačiteľné PDF na web MČ)
- **Strana 1 — `Prezenčná listina`:**
  - Hlavička zasadnutia (názov, číslo, dátum).
  - Číslovaný abecedný zoznam všetkých poslancov (`1.` až `N.`): `Priezvisko Meno, zúčastnil/a sa` / `nezúčastnil sa` *(+ voliteľne poznámka o ospravedlnení / neskorom príchode / skoršom odchode)*.
- **Od strany 2 — `HLASOVANIE POSLANCOV`:**
  Pre každé hlasovanie štruktúrovaný blok v poradí:
  1. `Číslo hlasovania : [N]`
  2. `Číslo bodu : [item_number]`
  3. Názov bodu programu *(+ prívlastok, napr. `– pozmeňujúci návrh`, `– doplnenie`, `– pôvodný návrh`, `– opakované hlasovanie`)*
  4. `Uznesenie: č. [NNN/RRRR]` *(prázdne pri neschválenom návrhu)*
  5. Typ kvóra a verdikt: **SCHVÁLENÉ** / **NESCHVÁLENÉ** *(+ potrebný počet hlasov ZA)*
  6. Súhrn: `Za : X`, `Proti : Y`, `Zdržali sa : Z`, `Nehlasovali : W`, `Prítomní : P`
  7. Menovité zoznamy abecedne podľa `Priezvisko Meno` *(nenulové kategórie)*: `Za : …`, `Proti : …`, `Zdržali sa : …`, `Nehlasovali : …`

### 7.3 Súhrnná veta do Zápisnice (kopírovateľná pre zapisovateľku)
- Pod každým uznesením v Zápisnici MČ Furča je jednoznačná veta:
  > `Hlasovanie: za [X], proti [Y], zdržal sa [Z], nehlasoval [W], uznesenie bolo schválené.` *(resp. `nebolo schválené.`)*
- Povinné náležitosti zápisnice (Čl. 16 ods. 1 RP): kto rokovanie viedol, počet prítomných poslancov, schválený program, vystúpenia v diskusii, obsah rokovania, prijaté uznesenia; podpisy: **starosta**, **prednosta MÚ**, **2 overovatelia zápisnice** (a zapisovateľ); lehota vyhotovenia: **do 10 pracovných dní**.

---

## 8. Architektonický dopad na `vout` (konfigurovateľnosť)

Keďže aplikácia je určená pre akúkoľvek obec/MČ na SR a Rokovací poriadok MČ Furča sa má meniť, v kóde **nesmie byť natvrdo zadrôtované** nič lokálne:
- Názov obce / MČ, orgánu (Miestne zastupiteľstvo / Obecné zastupiteľstvo / Mestské zastupiteľstvo / Miestna rada).
- Počet poslancov (`total_councilors`) a zoznam poslancov per zasadnutie (s menom, priezviskom, titulom, prípadne obvodom/klubom).
- Formát číslovania uznesení (`NNN/RRRR`) a počiatočné poradové číslo uznesenia v roku.
- Predvolené kvórum (`majority_present`) s možnosťou výberu ktoréhokoľvek zo 4 zákonných kvór pred spustením hlasovania (a s vizuálnym upozornením pri zmene programu / VZN / osobitnom zreteli).
- Audit log ako append-only (nezmazateľný) záznam každej zmeny prítomnosti, hlasu, otvorenia/uzavretia hlasovania a manuálneho zásahu zapisovateľa.
