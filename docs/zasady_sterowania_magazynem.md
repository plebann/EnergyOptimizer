# Zasady sterowania magazynem energii - specyfikacja algorytmu

## CEL OPTYMALIZACJI

**Minimalizacja rachunku za energię elektryczną w ujęciu 12-miesięcznym** poprzez:
- Maksymalizację autokonsumpcji energii z PV
- Eliminację poboru energii z sieci w taryfie wysokiej
- Budowanie depozytu prosumeckiego w miesiącach wysokiej produkcji PV na pokrycie zużycia w miesiącach niskiej produkcji
- Wykorzystanie arbitrażu cenowego (sprzedaż po wysokich cenach RCE, kupno w niskiej taryfie G12, nie więcej niż wartość produkcji PV danego dnia)

**Strategia:** Konserwatywna - priorytet to unikanie kupowania energii w drogiej taryfie, nawet kosztem niewykorzystania okazji do arbitrażu.

---

## PARAMETRY SYSTEMU

### Instalacja:
- Moc PV: 13 kWp
- Pojemność magazynu: 21 kWh
- Moc falownika: 12 kW
- Sprawność magazynu (round-trip): 90%
- Limity SOC: min 20% (taryfa niska), min 10% (taryfa wysoka)

### Taryfa G12 (ceny netto):
- **Taryfa niska:** 46,35 gr/kWh energia + 14,28 gr/kWh przesył = **60,63 gr/kWh**
  - Godziny: 22:00-6:00 + 13:00-15:00 (zimą) / 15:00-17:00 (latem)
- **Taryfa wysoka:** 70,18 gr/kWh energia + 54,24 gr/kWh przesył = **124,42 gr/kWh**
  - Godziny: pozostałe

### Rozliczenia prosumenckie:
- System: net-billing z depozytem prosumenckim
- Współczynnik RCE: 1,23
- Depozyt pokrywa tylko koszt energii (nie przesył, nie opłaty stałe)
- Niewykorzystany depozyt: maksymalnie 30% wartości produkcji danego miesiąca do wypłaty po 12 miesiącach

### Progi decyzyjne:
- **Próg opłacalności eksportu:** 95,1 gr/kWh netto
    - Wzór: `(cena_energii + dystrybucja) × 0,9 + dystrybucja × 3,33`
    - Dla taryfy niskiej: `(0,3718 + 0,005 + 0,1161) * 0,9 + (0,1161 + 0,005) * 3,33 = 0,951 zł/kWh`
- **Próg blokady ładowania PV:** `średnia(dołek) < 0,8 × średnia(produkcja_PV) × 0,9`

### Dodatkowe sterowanie:
- **Bojler CWU:** 270L, pompa ciepła, grzanie do 40-50°C
- **Balansowanie magazynu:** co 10 dni pełne naładowanie do 100%

---

## MOMENTY AKCJI I ZASADY STEROWANIA

**Tabela skrótowa (stan aktualny):**

| Obszar | Okno | Kluczowe wejścia | Główna decyzja |
| --- | --- | --- | --- |
| Poranne ładowanie | 06:00 → `tariff_end_hour` | SOC, prognozy PV i zużycia, straty, balancing ongoing | Ładuj z sieci do wyliczonego SOC lub brak akcji |
| Popołudniowe ładowanie | `tariff_start_hour` → 22:00 | SOC, prognozy PV i zużycia, straty, ceny sprzedaży, program 4 | Ładuj z sieci (z arbitrażem) lub reset programu 4 |
| Zachowanie wieczorne | 22:00 → 04:00 | balancing interval, próg PV, reserve, grid assist | Balancing, preservation lub powrót do min SOC |

### **00:00 - ANALIZA DZIENNYCH CEN RCE**

**TODO:** Proces niezaimplementowany w obecnym decision engine.

**Cel:** Identyfikacja kluczowych okien czasowych na podstawie cen RCE na cały dzień.

**Dane wejściowe:**
- Lista 24 cen RCE na dzień bieżący i następny (zewnętrzna integracja, z rozdzielczością 15 minut)
- Prognoza produkcji PV na dzień bieżący i następny (zewnętrzna integracja, z rozdzielczością pół godziny)
- Prognoza zużycia energii (dom + pompa ciepła, customowe sensory i zewnętrzna integracja)

**Algorytm identyfikacji okien:**

```
# 1. Identyfikacja godzin produkcji PV
godziny_produkcji_PV = godziny WHERE prognoza_PV(h) > 0,5 kW

# 2. Identyfikacja dołka dziennego
# Szukaj najniższych cen w oknie produkcji PV
IF długość(godziny_produkcji_PV) > 0:
    potencjalne_dołki = godziny_produkcji_PV WHERE RCE(h) < percentyl_25(RCE w godziny_produkcji_PV)
    
    # Oblicz ile godzin potrzeba do pełnego naładowania
    wolne_miejsce_w_magazynie = pojemność_magazynu - aktualny_SoC
    prognoza_nadwyżek_PV(h) = max(0, prognoza_PV(h) - prognoza_zużycia(h))
    
    godziny_potrzebne = 0
    energia_skumulowana = 0
    FOR h IN potencjalne_dołki (sorted by RCE ascending):
        energia_skumulowana += prognoza_nadwyżek_PV(h)
        godziny_potrzebne += 1
        IF energia_skumulowana >= wolne_miejsce_w_magazynie:
            BREAK
    
    dołek_dzienny = {
        start: pierwsza godzina z potencjalne_dołki,
        koniec: start + godziny_potrzebne,
        średnia_cena: średnia(RCE dla tych godzin)
    }
ELSE:
    dołek_dzienny = NULL

# 3. Identyfikacja szczytu porannego
# Szukaj godziny z maksymalną ceną w oknie porannym
godziny_poranne = 6:00 do 12:00
max_cena_poranna = max(RCE(h) FOR h IN godziny_poranne)
szczytowa_godzina_poranna = argmax(RCE(h) FOR h IN godziny_poranne)

# Rozszerz okienko o sąsiednie godziny jeśli cena > 90% max
próg_90_procent = max_cena_poranna × 0,9
wybrane_godziny_poranne = [szczytowa_godzina_poranna]

# Sprawdź godziny przed szczytową
h = szczytowa_godzina_poranna - 1
WHILE h >= 6:00 AND RCE(h) >= próg_90_procent:
    dodaj h na początek wybrane_godziny_poranne
    h = h - 1

# Sprawdź godziny po szczytowej
h = szczytowa_godzina_poranna + 1
WHILE h <= 12:00 AND RCE(h) >= próg_90_procent:
    dodaj h na koniec wybrane_godziny_poranne
    h = h + 1

szczyt_poranny = {
    godzina_start: pierwsza wybrana godzina,
    godzina_koniec: ostatnia wybrana godzina,
    godziny: wybrane_godziny_poranne,
    szczytowa_godzina: szczytowa_godzina_poranna,
    średnia_cena: średnia(RCE(h) FOR h IN wybrane_godziny_poranne),
    max_cena: max_cena_poranna
}

# 4. Identyfikacja szczytu wieczornego
# Szukaj godziny z maksymalną ceną w oknie wieczornym
godziny_wieczorne = 16:00 do 22:00
max_cena_wieczorna = max(RCE(h) FOR h IN godziny_wieczorne)
szczytowa_godzina_wieczorna = argmax(RCE(h) FOR h IN godziny_wieczorne)

# Rozszerz okienko o sąsiednie godziny jeśli cena > 90% max
próg_90_procent = max_cena_wieczorna × 0,9
wybrane_godziny_wieczorne = [szczytowa_godzina_wieczorna]

# Sprawdź godziny przed szczytową
h = szczytowa_godzina_wieczorna - 1
WHILE h >= 16:00 AND RCE(h) >= próg_90_procent:
    dodaj h na początek wybrane_godziny_wieczorne
    h = h - 1

# Sprawdź godziny po szczytowej
h = szczytowa_godzina_wieczorna + 1
WHILE h <= 22:00 AND RCE(h) >= próg_90_procent:
    dodaj h na koniec wybrane_godziny_wieczorne
    h = h + 1

szczyt_wieczorny = {
    godzina_start: pierwsza wybrana godzina,
    godzina_koniec: ostatnia wybrana godzina,
    godziny: wybrane_godziny_wieczorne,
    szczytowa_godzina: szczytowa_godzina_wieczorna,
    średnia_cena: średnia(RCE(h) FOR h IN wybrane_godziny_wieczorne),
    max_cena: max_cena_wieczorna
}
```

**Zapisz do pamięci:** `dołek_dzienny`, `szczyt_poranny`, `szczyt_wieczorny` (dostępne dla kolejnych akcji w ciągu dnia)

---

### **04:00 - ŁADOWANIE PORANNE Z SIECI (TARYFA NISKA)**

**Cel:** Załadowanie magazynu z taniej taryfy nocnej, aby pokryć zużycie w taryfie wysokiej.

**Dane wejściowe:**
- Aktualny SoC magazynu
- Prognoza produkcji PV na dzień bieżący (okno 6:00 → `tariff_end_hour`)
- Prognoza zużycia (dom + PC) w oknie 6:00 → `tariff_end_hour`
- Straty falownika w oknie porannym
- Informacja, czy trwa balansowanie (balancing ongoing)

**Algorytm:**

```
# 1. Sprawdź, czy balansowanie jest w toku
IF balancing_ongoing:
    pomiń_akcję()

# 2. Okno obliczeń: 6:00 → tariff_end_hour
okno = 6:00 do tariff_end_hour

# 3. Oblicz zapotrzebowanie w oknie (dom + PC + straty, z marginesem)
required_kwh = suma(zapotrzebowania_w_oknie)

# 4. Oblicz rezerwę energii w magazynie (powyżej min_soc)
reserve_kwh = energia_użyteczna_z_magazynu

# 5. Oblicz prognozę PV w oknie (z kompensacją i efektywnością)
pv_kwh = prognoza_PV(okno)

# 6. Wyznacz deficyt (pełne okno vs godzina wystarczalności)
deficyt_full = required_kwh - reserve_kwh - pv_kwh
deficyt_suff = required_sufficiency_kwh - reserve_kwh - pv_sufficiency_kwh
deficyt = max(deficyt_full, deficyt_suff)

# 7. Jeśli deficyt > 0, wyznacz target SOC i prąd ładowania
IF deficyt > 0:
    ładuj_z_sieci(deficyt)
ELSE:
    nie_ładuj()
```

**Sprawność magazynu**:
- Jeśli rozładowuję energię już zgromadzoną w magazynie, sprawność liczona jest **jednorazowo** (strata na rozładowaniu).
- Jeśli muszę najpierw doładować z sieci, aby tę energię później rozładować, sprawność liczona jest **podwójnie** (ładowanie i rozładowanie): `wymagane / (0.9 × 0.9)`.

**Akcje:**
- `ładuj_z_sieci(ilość_kWh)` - włącz tryb force charge z sieci do osiągnięcia docelowego SoC
- `nie_ładuj()` - pozostaw magazyn w trybie normalnym

---

### **WSCHÓD SŁOŃCA - DECYZJA O BLOKOWANIU ŁADOWANIA Z PV**

**TODO:** Proces niezaimplementowany w obecnym decision engine.

**Cel:** Ustalić, czy opłaca się zablokować ładowanie magazynu z PV w oczekiwaniu na niższe ceny RCE w dołku dziennym.

**Dane wejściowe:**
- `dołek_dzienny` (wyznaczony o 00:00)
- `szczyt_wieczorny` (wyznaczony o 00:00)
- `szczyt_poranny_jutro` (z prognozy na dzień następny)
- Aktualna cena RCE (w godzinie wschodu słońca)
- Prognoza produkcji PV w godzinach rano (wschód-dołek)

**Algorytm:**

```
# 1. Sprawdź prognozę PV vs pojemność magazynu i zużycie
suma_prognoza_PV_dziś = suma(prognoza_PV(h) FOR h IN cały_dzień)
wolne_miejsce_w_magazynie = (100% - aktualny_SoC) × pojemność_magazynu
przewidywane_zużycie_dziś = suma(prognoza_zużycia(h) FOR h IN cały_dzień)

IF suma_prognoza_PV_dziś <= (wolne_miejsce_w_magazynie + przewidywane_zużycie_dziś):
    # PV nie wystarczy żeby napełnić magazyn przy dzisiejszym zużyciu
    # Nie ma sensu blokować - ładuj normalnie
    nie_blokuj_ładowania()
    zapisz_flagę("czekam_na_dołek" = FALSE)
    RETURN

# 2. Sprawdź czy szczyt wieczorny ma wystarczająco wyższą cenę niż dołek
IF szczyt_wieczorny.max_cena < 1,2 × dołek_dzienny.średnia_cena:
    # Szczyt wieczorny nie jest o 20% wyższy od dołka
    # Arbitraż niewystarczająco opłacalny
    nie_blokuj_ładowania()
    zapisz_flagę("czekam_na_dołek" = FALSE)
    RETURN

# 3. Oblicz średnią cenę w godzinach produkcji przed dołkiem
godziny_przed_dołkiem = wschód_słońca DO dołek_dzienny.start
IF długość(godziny_przed_dołkiem) == 0:
    nie_blokuj_ładowania()
    zapisz_flagę("czekam_na_dołek" = FALSE)
    RETURN

średnia_cena_przed_dołkiem = średnia(RCE(h) FOR h IN godziny_przed_dołkiem)

# 4. Sprawdź podstawowy warunek opłacalności arbitrażu
IF dołek_dzienny.średnia_cena >= 0,8 × średnia_cena_przed_dołkiem × 0,9:
    # Dołek nie jest wystarczająco tani w porównaniu do cen przed nim
    nie_blokuj_ładowania()
    zapisz_flagę("czekam_na_dołek" = FALSE)
    RETURN

# 5. Sprawdź czy będzie opłacalna sprzedaż później
najlepsza_cena_sprzedaży = max(
    szczyt_wieczorny.max_cena IF szczyt_wieczorny != NULL ELSE 0,
    szczyt_poranny_jutro.max_cena IF szczyt_poranny_jutro != NULL ELSE 0
)

koszt_arbitrażu = dołek_dzienny.średnia_cena × 0,9  # ładowanie w dołku ze stratą sprawności
potencjalny_zysk = najlepsza_cena_sprzedaży - koszt_arbitrażu

# 6. Decyzja końcowa
IF najlepsza_cena_sprzedaży > 95,1 gr/kWh AND potencjalny_zysk > 10 gr/kWh:
    # Arbitraż opłacalny - wszystkie warunki spełnione
    blokuj_ładowanie_z_PV()
    zapisz_flagę("czekam_na_dołek" = TRUE)
ELSE:
    # Lepiej ładować normalnie na autokonsumpcję
    nie_blokuj_ładowania()
    zapisz_flagę("czekam_na_dołek" = FALSE)
```

**Akcje:**
- `blokuj_ładowanie_z_PV()` - ustaw priorytet: PV → dom, nadwyżki PV → eksport (nie do magazynu)
- `nie_blokuj_ładowania()` - ustaw priorytet normalny: PV → dom → magazyn → eksport

**Uwaga:** Blokada ładowania zostanie zniesiona w momencie `dołek_dzienny.start` (patrz akcja "DOŁEK DZIENNY")

---

### **SZCZYT PORANNY - SPRZEDAŻ PORANNA**

**TODO:** Proces niezaimplementowany w obecnym decision engine.

**Cel:** Sprzedać energię z magazynu po wysokiej cenie RCE, zachowując wystarczającą ilość na potrzeby domu do momentu rozpoczęcia produkcji PV.

**Czas wykonania:** `szczyt_poranny.szczytowa_godzina` (jeśli szczyt_poranny != NULL)

**Dane wejściowe:**
- Aktualny SoC magazynu
- `szczyt_poranny.max_cena`
- Prognoza zużycia energii do momentu rozpoczęcia znaczącej produkcji PV (np. do godz. 9:00-10:00)
- Prognoza produkcji PV

**Algorytm:**

```
# 1. Sprawdź czy szczyt poranny istnieje i czy cena jest wystarczająco wysoka
IF szczyt_poranny == NULL OR szczyt_poranny.max_cena < 95,1 gr/kWh:
    nie_sprzedawaj()
    RETURN

# 2. Określ moment kiedy PV zacznie znacząco produkować
godzina_startu_PV = pierwsza_godzina WHERE prognoza_PV(h) > 1,0 kW
IF godzina_startu_PV == NULL:
    godzina_startu_PV = 12:00  # konserwatywne założenie

# 3. Oblicz ile energii potrzeba na dom do godziny_startu_PV
godziny_do_pokrycia = obecna_godzina DO godzina_startu_PV
energia_potrzebna = suma(prognoza_zużycia(h) FOR h IN godziny_do_pokrycia)

# 4. Oblicz ile energii można sprzedać
dostępna_energia = (aktualny_SoC - 10%) × pojemność_magazynu  # zostaw 10% minimum
energia_do_sprzedaży = max(0, dostępna_energia - energia_potrzebna)

# 5. Dodatkowy bufor bezpieczeństwa (konserwatywna strategia)
energia_do_sprzedaży = energia_do_sprzedaży × 0,8  # zostaw 20% marginesu

# 6. Decyzja
IF energia_do_sprzedaży > 0,5 kWh:  # minimalna ilość która ma sens
    sprzedaj_z_magazynu(energia_do_sprzedaży)
ELSE:
    nie_sprzedawaj()
```

**Akcje:**
- `sprzedaj_z_magazynu(ilość_kWh)` - włącz tryb force discharge do sieci przez określony czas
    - Czas rozładowania = `ilość_kWh / moc_falownika` (max 12 kW)
    - Jednocześnie: dom zasilany z magazynu

---

### **DOŁEK DZIENNY - WŁĄCZENIE ŁADOWANIA Z PV**

**TODO:** Proces niezaimplementowany w obecnym decision engine.

**Cel:** Rozpocząć ładowanie magazynu z PV w momencie najniższych cen RCE (jeśli wcześniej było zablokowane).

**Czas wykonania:** `dołek_dzienny.start` (jeśli dołek_dzienny != NULL i flaga "czekam_na_dołek" == TRUE)

**Algorytm:**

```
IF flaga("czekam_na_dołek") == TRUE:
    # Odblokuj ładowanie z PV
    przywróć_priorytet_normalny()  # PV → dom → magazyn → eksport
    zapisz_flagę("czekam_na_dołek" = FALSE)
    
    # Ładuj magazyn do pełna z nadwyżek PV
    cel_ładowania = 100%
ELSE:
    # Nie było blokady, kontynuuj normalnie
    kontynuuj_bez_zmian()
```

**Akcje:**
- `przywróć_priorytet_normalny()` - PV → dom → magazyn → eksport
- Magazyn będzie się ładował naturalnie z nadwyżek PV aż do pełna

---

### **Popołudniowe ładowanie z sieci (koniec taryfy dziennej)**

**Cel:**
1. Pokryć zapotrzebowanie do 22:00 po zakończeniu taryfy dziennej.
2. Opcjonalnie doładować pod arbitraż, jeśli cena sprzedaży spełnia próg.

**Dane wejściowe:**
- Aktualny SoC magazynu
- Docelowy SOC programu 4 (ładowanie z sieci)
- `tariff_start_hour` (start okna) oraz stały koniec okna: 22:00
- Prognoza zużycia (dom + PC) w oknie `tariff_start_hour` → 22:00
- Prognoza PV w oknie `tariff_start_hour` → 22:00 (z kompensacją, bez `pv_efficiency`)
- Straty falownika w oknie
- `sell_window_price` i `min_arbitrage_price`
- `pv_forecast_today`, `pv_forecast_remaining`, `pv_production_sensor` (do urealnienia prognozy dla arbitrażu)
- `sell_window_start_hour` (okno sprzedaży)
- Flaga `afternoon_grid_assist`

**Algorytm:**

```
# 1. Okno obliczeń: tariff_start_hour → 22:00
okno = tariff_start_hour do 22:00

# 2. Oblicz zapotrzebowanie w oknie (dom + PC + straty, z marginesem)
required_kwh = suma(zapotrzebowania_w_oknie)

# 3. Oblicz rezerwę energii w magazynie (powyżej min_soc)
reserve_kwh = energia_użyteczna_z_magazynu

# 4. Oblicz prognozę PV w oknie (z kompensacją, bez pv_efficiency)
pv_kwh = prognoza_PV(okno)

# 5. Deficyt bazowy
deficyt = required_kwh - reserve_kwh - pv_kwh

# 6. Arbitraż (opcjonalny)
IF sell_price > min_arbitrage_price AND forecast_adjusted dostępny:
    surplus_kwh = nadwyżki_PV(teraz → sell_window_start)
    free_after = pojemność - (energia_bieżąca + required_kwh)
    arb_limit = max(free_after - surplus_kwh, 0)
    arbitrage_kwh = min(arb_limit, forecast_adjusted)
ELSE:
    arbitrage_kwh = 0

# 7. Deficyt całkowity i decyzja
base_deficit = max(deficyt, 0)
total_deficit = base_deficit + arbitrage_kwh
grid_assist = base_deficit > 0

IF total_deficit <= 0:
    # reset programu 4 do min_soc
    nie_ładuj()
ELSE:
    ładuj_z_sieci(total_deficit)
```

**Akcje:**
- Ustaw SOC programu 4 i prąd ładowania z sieci
- Ustaw `afternoon_grid_assist` na podstawie deficytu bazowego
- Przy braku deficytu: przywróć SOC programu 4 do minimum

---

### **SZCZYT WIECZORNY - SPRZEDAŻ WIECZORNA**

**TODO:** Proces niezaimplementowany w obecnym decision engine.

**Cel:** Sprzedać energię z magazynu po wysokiej cenie wieczornej, uwzględniając prognozy na następny dzień.

**Czas wykonania:** `szczyt_wieczorny.szczytowa_godzina` (jeśli szczyt_wieczorny != NULL)

**Dane wejściowe:**
- Aktualny SoC magazynu
- `szczyt_wieczorny.max_cena` (dzisiaj)
- `szczyt_poranny_jutro` (z prognozy na jutro)
- Prognoza produkcji PV na jutro
- Prognoza zużycia na wieczór (do 22:00)

**Algorytm:**

```
# 1. Sprawdź czy szczyt wieczorny istnieje
IF szczyt_wieczorny == NULL:
    nie_sprzedawaj()
    RETURN

cena_wieczór_dziś = szczyt_wieczorny.max_cena
cena_poranek_jutro = szczyt_poranny_jutro.max_cena IF szczyt_poranny_jutro != NULL ELSE 0

# 2. Oblicz ile energii potrzeba na dom do 22:00
godziny_do_22 = obecna_godzina DO 22:00
energia_na_dom_do_22 = suma(prognoza_zużycia(h) FOR h IN godziny_do_22)

# 3. Oblicz dostępną energię do sprzedaży
dostępna_energia = (aktualny_SoC - 20%) × pojemność_magazynu  # zostaw 20% minimum
energia_po_pokryciu_domu = max(0, dostępna_energia - energia_na_dom_do_22)

# 4. Sprawdź prognozę na jutro
suma_prognoza_PV_jutro = suma(prognoza_PV_jutro(h) FOR h IN cały_dzień_jutro)
wolne_miejsce_w_magazynie_teraz = (100% - aktualny_SoC) × pojemność_magazynu

# 5. LOGIKA DECYZYJNA

# Przypadek 1: Bardzo wysoka cena dziś - sprzedaj "wszystko"
IF cena_wieczór_dziś > 95,1 gr/kWh:
    energia_do_sprzedaży = energia_po_pokryciu_domu × 0,9  # zostaw 10% margines
    sprzedaj_z_magazynu(energia_do_sprzedaży)
    RETURN

# Przypadek 2: Cena dziś lepsza niż jutro rano
IF cena_wieczór_dziś > cena_poranek_jutro:
    # Lepiej sprzedać dziś
    
    # Ale sprawdź czy jutro nie będzie problemu z niedoborem energii
    IF suma_prognoza_PV_jutro < wolne_miejsce_w_magazynie_teraz:
        # Jutro słaba produkcja PV, nie zapełni magazynu
        # Sprzedaj tylko tyle, ile się nie zmieści jutro
        nadwyżka = energia_po_pokryciu_domu - (wolne_miejsce_w_magazynie_teraz - suma_prognoza_PV_jutro)
        energia_do_sprzedaży = max(0, nadwyżka)
    ELSE:
        # Jutro dobra produkcja, magazyn i tak się zapełni
        energia_do_sprzedaży = energia_po_pokryciu_domu × 0,8  # zostaw 20% margines
    
    IF energia_do_sprzedaży > 0,5 kWh:
        sprzedaj_z_magazynu(energia_do_sprzedaży)
    ELSE:
        nie_sprzedawaj()
    RETURN

# Przypadek 3: Cena dziś niższa niż jutro, ale jutro nie zmieści się w magazynie
IF suma_prognoza_PV_jutro > wolne_miejsce_w_magazynie_teraz:
    # Nadwyżka PV jutro i tak się nie zmieści, więc można sprzedać część dziś
    nadwyżka_jutro = suma_prognoza_PV_jutro - wolne_miejsce_w_magazynie_teraz
    energia_do_sprzedaży = min(energia_po_pokryciu_domu, nadwyżka_jutro)
    
    IF energia_do_sprzedaży > 0,5 kWh:
        sprzedaj_z_magazynu(energia_do_sprzedaży)
    ELSE:
        nie_sprzedawaj()
    RETURN

# Przypadek 4: W pozostałych przypadkach - nie sprzedawaj
# (cena jutro lepsza + energia się zmieści w magazynie)
nie_sprzedawaj()
```

**Akcje:**
- `sprzedaj_z_magazynu(ilość_kWh)` - force discharge przez obliczony czas
- Jednocześnie dom zasilany z magazynu (priorytet magazyn → dom → sieć)

---

### **22:00 - ZACHOWANIE WIECZORNE**

**Cel:** 
1. Balansowanie magazynu, gdy jest wymagane (parametryzowane interwałem i progiem PV).
2. Ochrona energii na noc (preservation) do 04:00, gdy grozi niedobór.
3. Przywrócenie trybu normalnego, jeśli nie ma przesłanek do ochrony.

**Dane wejściowe:**
- Data ostatniego pełnego balansowania magazynu
- `balancing_interval_days` oraz `balancing_pv_threshold`
- Prognoza produkcji PV na jutro
- Aktualny SoC magazynu, min/max SOC
- `afternoon_grid_assist`
- Prognozy zużycia (20:00–04:00) oraz straty falownika
- Programy SOC: prog1/prog2/prog6 oraz max charge current

**Algorytm:**

```
# 1. Aktualizacja sensora kompensacji PV (wartości „dzisiaj” → „wczoraj”)
zaktualizuj_pv_compensation()

# 2. Balansowanie
balancing_due = brak_ostatniego_balansu LUB dni_od_ostatniego_balansu >= balancing_interval_days
IF balancing_due AND pv_forecast_tomorrow < balancing_pv_threshold:
    ustaw_prog1_prog2_prog6_na_100%
    ustaw_max_charge_current
    ustaw_balancing_ongoing
    RETURN

# 3. Preservation do 04:00
required_to_04 = zapotrzebowanie(20:00-24:00) + zapotrzebowanie(00:00-04:00)
reserve_kwh = energia_użyteczna_z_magazynu
battery_space = pojemność - energia_bieżąca
pv_with_efficiency = pv_forecast_tomorrow × 0.9

IF afternoon_grid_assist OR reserve_kwh < required_to_04 OR pv_with_efficiency < battery_space:
    ustaw_prog1_i_prog6_na_bieżący_SOC
    RETURN

# 4. Przywrócenie trybu normalnego
IF prog6_soc > min_soc:
    ustaw_prog1_prog2_prog6_na_min_soc
```

**Akcje:**
- `ładuj_do_100%_i_utrzymuj_do_06:00()` - force charge do 100%, potem blokada rozładowania do 6:00 rano
- `blokuj_rozładowanie_magazynu()` - ustaw minimum SoC na aktualną wartość do 6:00 rano
- `pozwól_naturalne_rozładowanie()` - ustaw minimum SoC na 20%

---

## STEROWANIE BOJLEREM CWU

**TODO:** Proces niezaimplementowany w obecnym decision engine.

**Cel:** Wykorzystać bojler jako elastyczny "magazyn ciepła" do optymalizacji zużycia energii.

### **Zasady ogólne:**

```
# Priorytetowe grzanie (automatyczne)
IF (taryfa_niska_aktywna OR nadwyżki_PV > 2 kW) AND temperatura_bojlera < 45°C:
    włącz_grzanie_CWU()

IF temperatura_bojlera >= 45°C OR (taryfa_wysoka AND brak_nadwyżek_PV):
    wyłącz_grzanie_CWU()

# Awaryjne ograniczenie (gdy grozi niedobór energii)
IF przewidywany_SoC_przed_22:00 < 30% AND taryfa_wysoka_aktywna:
    wyłącz_grzanie_CWU()
    ogranicz_temperaturę_do(40°C)
```

### **Dodatkowe wykorzystanie w strategii arbitrażu (opcjonalne):**

```
# Jeśli wieczorem planowana jest sprzedaż po wysokiej cenie
IF (szczyt_wieczorny.max_cena > 95,1 gr/kWh) AND (nadwyżki_PV_w_południe > 3 kW):
    # Zamiast ładować magazyn elektryczny, przegrzej bojler
    IF temperatura_bojlera < 50°C:
        priorytet_grzanie_CWU()  # zużyj nadwyżki PV na CWU zamiast ładować magazyn
    # To zwalnia miejsce w magazynie elektrycznym na arbitraż wieczorem
```

**Parametry:**
- Temperatura docelowa standardowa: 40-45°C
- Temperatura maksymalna: 50-55°C (limit pompy ciepła CWU)
- Energia dostępna w bojlerze: ~8-10 kWh (przy ΔT = 30-35°C)

---

## PRIORYTETY PRZEPŁYWU ENERGII

**TODO:** Proces niezaimplementowany w obecnym decision engine.

### **Podczas produkcji PV:**

**Normalny tryb (bez blokad):**
```
1. PV → zużycie domu (bezpośrednio)
2. PV → ładowanie magazynu (jeśli wolne miejsce)
3. PV → eksport do sieci (jeśli magazyn pełny)
```

**Tryb "czekam na dołek" (blokada ładowania):**
```
1. PV → zużycie domu (bezpośrednio)
2. PV → eksport do sieci
   (magazyn NIE jest ładowany, czeka na tańsze ceny w dołku)
```

### **Podczas zużycia (brak produkcji PV):**

**Taryfa niska (22:00-6:00, 13:00-15:00 zimą / 15:00-17:00 latem):**
```
1. Sieć → dom (tania taryfa)
2. Magazyn → dom (jeśli SoC > minimum)
   
   WYJĄTEK: Jeśli flaga "blokuj_rozładowanie" aktywna:
   1. Sieć → dom (oszczędzamy magazyn na wysoką taryfę)
```

**Taryfa wysoka (pozostałe godziny):**
```
1. Magazyn → dom (priorytet, unikamy drogiej sieci)
2. Sieć → dom (tylko gdy magazyn < minimum SoC)
```

### **Podczas sprzedaży (force discharge):**
```
1. Magazyn → dom (dom zasilany z magazynu)
2. Magazyn → sieć (eksport)
```

---

## ZARZĄDZANIE FLAGAMI I STANEM

**TODO:** Proces niezaimplementowany w obecnym decision engine.

### **Flagi globalne:**
- `czekam_na_dołek` (BOOL) - czy zablokowano ładowanie z PV w oczekiwaniu na dołek
- `blokuj_rozładowanie` (BOOL) - czy zablokować rozładowanie magazynu w nocy
- `data_ostatniego_balansowania` (DATE) - kiedy ostatni raz pełne naładowanie do 100%

### **Dane cache (dzienne):**
- `dołek_dzienny` {start, koniec, średnia_cena}
- `szczyt_poranny` {godziny, szczytowa_godzina, średnia_cena, max_cena}
- `szczyt_wieczorny` {godziny, szczytowa_godzina, średnia_cena, max_cena}
- `szczyt_poranny_jutro` {j.w. ale na dzień następny}
- `szczyt_wieczorny_jutro` {j.w. ale na dzień następny}

### **Prognozy (aktualizowane):**
- `prognoza_PV(h)` - prognoza produkcji PV dla każdej godziny
- `skorygowana_prognoza_PV(h)` - po korekcie o 13:00/15:00
- `prognoza_zużycia(h)` - prognoza zużycia (dom + PC) dla każdej godziny

---

## UWAGI IMPLEMENTACYJNE

1. **Wszystkie ceny RCE są w PLN/MWh netto** (bez VAT)
2. **Sprawność magazynu 90%** uwzględniana w każdym obliczeniu arbitrażu
3. **Marginesy bezpieczeństwa:**
   - Przy sprzedaży: zostaw 10-20% marginesu energii
   - Przy obliczaniu niedoborów: dodaj 20% marginesu
4. **Minimum SoC:**
   - Taryfa niska: 20%
   - Taryfa wysoka: 10%
   - NIGDY nie rozładowuj poniżej tych progów
5. **Strategia konserwatywna:** W razie wątpliwości priorytet ma unikanie poboru z sieci w wysokiej taryfie, nawet kosztem niewykorzystania okazji do arbitrażu
6. **Balansowanie magazynu:** Co 10 dni wymuszenie pełnego cyklu ładowania do 100% i utrzymania przez noc (dla zdrowia baterii)
7. **Sterowanie falownikiem (Solarman):** używaj dedykowanego programu (np. Program 1) i ustawiaj `number.inverter_program_<n>_soc`, `select.inverter_work_mode` (Selling First / Zero Export to Load), `select.inverter_program_<n>_charging` (grid/disabled), prądy `inverter_battery_max_charging_current` / `inverter_battery_max_discharging_current` / `inverter_battery_grid_charging_current` oraz `number.inverter_grid_max_export_power`; godzina startu programu `time.inverter_program_<n>_time` może być użyta do aktywacji profilu. Jeśli automatyka korzysta z wielu programów czasowych, przypisz: P2=04:00 (ładowanie z sieci), P3=szczyt poranny, P4=niskotarifowe doładowanie dzienne (start może być korygowany inną automatyzacją), P5=szczyt wieczorny 17-21, P6=22:00 (balansowanie). Przy balansowaniu ustaw SOC w P6 oraz odzwierciedlij cel SOC w P1 (opcjonalnie P2).


## FORMAT DANYCH SENSORA CEN
Sensor cen ma atrybut **prices**
Jest to lista obiektów o takiej strukturze:
```
    dtime: '2026-02-18 00:15:00'
    period: 00:00 - 00:15
    rce_pln: '437.00'
    business_date: '2026-02-18'
```

---

## CHECKLIST PRZED KAŻDĄ AKCJĄ

Przed wykonaniem jakiejkolwiek akcji sprawdź:

- [ ] Czy nie naruszam limitów SoC (min 10%/20%, max 100%)?
- [ ] Czy nie spowoduje to poboru z sieci w wysokiej taryfie?
- [ ] Czy uwzględniłem prognozę na następny dzień?
- [ ] Czy zostawiłem wystarczający margines bezpieczeństwa?
- [ ] Czy akcja jest zgodna z konserwatywną strategią?

---

*Dokument wersja 1.0 - specyfikacja algorytmu sterowania magazynem energii*