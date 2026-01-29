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
  - Dla taryfy niskiej: `(0,4635 + 0,1428) × 0,9 + 0,1428 × 3,33 = 1,021 zł/kWh`
- **Próg blokady ładowania PV:** `średnia(dołek) < 0,8 × średnia(produkcja_PV) × 0,9`

### Dodatkowe sterowanie:
- **Bojler CWU:** 270L, pompa ciepła, grzanie do 40-50°C
- **Balansowanie magazynu:** co 10 dni pełne naładowanie do 100%

---

## MOMENTY AKCJI I ZASADY STEROWANIA

### **00:00 - ANALIZA DZIENNYCH CEN RCE**

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
- Prognoza produkcji PV na dzień bieżący
- Prognoza zużycia (dom + PC) w godzinach taryfy wysokiej (6:00-13:00 zimą / 6:00-15:00 latem)
- Prognoza produkcji PV na dzień następny
- Ceny RCE na dzień następny (szczyt_poranny_jutro, szczyt_wieczorny_jutro)

**Algorytm:**

```
# 1. Określ godziny wysokiej taryfy do pokrycia
miesiąc = obecny_miesiąc()
IF miesiąc IN [4, 5, 6, 7, 8, 9]:  # kwiecień-wrzesień (LATO)
    godziny_wysokiej_taryfy = 6:00 do 15:00 oraz 17:00 do 22:00
ELSE:  # październik-marzec (ZIMA)
    godziny_wysokiej_taryfy = 6:00 do 13:00 oraz 15:00 do 22:00

# 2. Oblicz całkowite zapotrzebowanie w godzinach wysokiej taryfy
zużycie_dom = suma(prognoza_zużycia_dom(h) FOR h IN godziny_wysokiej_taryfy)
zużycie_PC = suma(prognoza_zużycia_PC(h) FOR h IN godziny_wysokiej_taryfy)
zużycie_CWU = suma(prognoza_zużycia_CWU(h) FOR h IN godziny_wysokiej_taryfy)
całkowite_zużycie = zużycie_dom + zużycie_PC + zużycie_CWU

# 3. Oblicz dostępną produkcję PV w godzinach wysokiej taryfy
produkcja_PV = suma(prognoza_PV(h) FOR h IN godziny_wysokiej_taryfy)

# 4. Oblicz dostępną energię z magazynu
dostępna_energia_z_magazynu = (aktualny_SoC - 20%) × pojemność_magazynu

# 5. Oblicz deficyt energii
deficyt = całkowite_zużycie - produkcja_PV - dostępna_energia_z_magazynu

# 6. Decyzja o ładowaniu
IF deficyt > 0:
    # Nie wystarczy energii na pokrycie godzin wysokiej taryfy
    doładuj = min(deficyt × 1,1, wolne_miejsce_w_magazynie)  # 10% margines bezpieczeństwa
    ładuj_z_sieci(doładuj)
ELSE:
    # Wystarczy energii, nie ładuj
    nie_ładuj()
```

**Akcje:**
- `ładuj_z_sieci(ilość_kWh)` - włącz tryb force charge z sieci do osiągnięcia docelowego SoC
- `nie_ładuj()` - pozostaw magazyn w trybie normalnym

---

### **WSCHÓD SŁOŃCA - DECYZJA O BLOKOWANIU ŁADOWANIA Z PV**

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
  - Jednocześnie: dom zasilany z sieci (aby energia z magazynu szła do eksportu)

---

### **DOŁEK DZIENNY - WŁĄCZENIE ŁADOWANIA Z PV**

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

### **13:00 (ZIMĄ) / 15:00 (LATEM) - ŁADOWANIE W NISKIEJ TARYFIE DZIENNEJ + KOREKTA**

**Cel:** 
1. Skorygować prognozy na podstawie rzeczywistej produkcji PV do tej pory
2. Doładować magazyn z sieci w taryfie niskiej, jeśli potrzeba

**Dane wejściowe:**
- Aktualna godzina (13:00 zimą, 15:00 latem)
- Prognoza produkcji PV na dzień bieżący (oryginalna z rana)
- Rzeczywista produkcja PV od wschodu słońca do teraz
- Aktualny SoC magazynu
- `szczyt_wieczorny` (z analizy o 00:00)
- Prognoza zużycia na popołudnie i wieczór

**Algorytm:**

```
# 1. KOREKTA PROGNOZY PV
godziny_od_wschodu = wszystkie_godziny od wschód_słońca DO obecna_godzina
suma_rzeczywista_PV = suma(rzeczywista_produkcja_PV(h) FOR h IN godziny_od_wschodu)
suma_prognoza_PV = suma(prognoza_PV(h) FOR h IN godziny_od_wschodu)

IF suma_prognoza_PV > 0:
    współczynnik_korekty = suma_rzeczywista_PV / suma_prognoza_PV
ELSE:
    współczynnik_korekty = 0

# Skoryguj pozostałą prognozę na popołudnie
godziny_pozostałe = obecna_godzina+1 DO zachód_słońca
FOR h IN godziny_pozostałe:
    skorygowana_prognoza_PV(h) = prognoza_PV(h) × współczynnik_korekty

# 2. PROGNOZA STANU MAGAZYNU WIECZOREM
przewidywana_produkcja_PV_popołudnie = suma(skorygowana_prognoza_PV(h) FOR h IN godziny_pozostałe)
przewidywane_zużycie_popołudnie = suma(prognoza_zużycia(h) FOR h IN obecna_godzina DO 22:00)

przewidywane_SoC_wieczorem = aktualny_SoC + (przewidywana_produkcja_PV_popołudnie - przewidywane_zużycie_popołudnie) / pojemność_magazynu

# 3. DECYZJA O ŁADOWANIU Z SIECI
# Sprawdź czy będzie sprzedaż wieczorem
IF szczyt_wieczorny != NULL AND szczyt_wieczorny.max_cena > 95,1 gr/kWh:
    # Chcemy mieć pełny magazyn na sprzedaż wieczorem
    cel_SoC = 100%
    
    IF przewidywane_SoC_wieczorem < cel_SoC:
        niedobór = (cel_SoC - przewidywane_SoC_wieczorem) × pojemność_magazynu
        doładuj = min(niedobór, wolne_miejsce_w_magazynie)
        ładuj_z_sieci(doładuj)
    ELSE:
        nie_ładuj()
ELSE:
    # Nie będzie sprzedaży, ale sprawdź czy wystarczy na wieczór bez poboru z sieci w wysokiej taryfie
    godziny_wysokiej_taryfy_wieczorem = obecna_godzina DO 22:00
    zużycie_w_wysokiej = suma(prognoza_zużycia(h) FOR h IN godziny_wysokiej_taryfy_wieczorem)
    dostępna_energia_z_PV = przewidywana_produkcja_PV_popołudnie
    dostępna_energia_z_magazynu = (przewidywane_SoC_wieczorem - 20%) × pojemność_magazynu
    
    suma_dostępnej_energii = dostępna_energia_z_PV + dostępna_energia_z_magazynu
    
    IF suma_dostępnej_energii < zużycie_w_wysokiej:
        # Nie wystarczy - doładuj z sieci w niskiej taryfie
        niedobór = zużycie_w_wysokiej - suma_dostępnej_energii
        doładuj = min(niedobór × 1,2, wolne_miejsce_w_magazynie)  # 20% margines
        ładuj_z_sieci(doładuj)
    ELSE:
        nie_ładuj()
```

**Akcje:**
- `ładuj_z_sieci(ilość_kWh)` - ładowanie z sieci w taryfie niskiej

**Uwaga:** To jest ostatni moment w ciągu dnia na tanie ładowanie z sieci (poza nocą).

---

### **SZCZYT WIECZORNY - SPRZEDAŻ WIECZORNA**

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
1. Balansowanie magazynu (co 10 dni pełne naładowanie)
2. Przygotowanie magazynu na noc w zależności od prognozy na jutro

**Dane wejściowe:**
- Data ostatniego pełnego balansowania magazynu
- Aktualny SoC magazynu
- Prognoza produkcji PV na jutro

**Algorytm:**

```
# 1. SPRAWDŹ CZY POTRZEBNE BALANSOWANIE
dni_od_ostatniego_balansowania = dzisiaj - data_ostatniego_balansowania

IF dni_od_ostatniego_balansowania >= 10:
    # Wymuszenie pełnego naładowania i utrzymania
    ładuj_do_100%_i_utrzymuj_do_06:00()
    zapisz_datę_balansowania(dzisiaj)
    RETURN

# 2. OPTYMALIZACJA NA PODSTAWIE PROGNOZY NA JUTRO
suma_prognoza_PV_jutro = suma(prognoza_PV_jutro(h) FOR h IN cały_dzień_jutro)
wolne_miejsce_w_magazynie = (100% - aktualny_SoC) × pojemność_magazynu

# Jeśli jutro słaba produkcja PV i nie zapełni magazynu
IF suma_prognoza_PV_jutro < wolne_miejsce_w_magazynie:
    # Zablokuj rozładowanie magazynu - niech dom czerpie z sieci w niskiej taryfie
    # Oszczędzamy energię w magazynie na godziny wysokiej taryfy jutro
    blokuj_rozładowanie_magazynu()
    # Dom będzie zasilany bezpośrednio z sieci (tania taryfa nocna)
ELSE:
    # Jutro dobra produkcja, magazyn się zapełni
    # Pozwól magazynowi rozładować się naturalnie
    pozwól_naturalne_rozładowanie()
    # Magazyn może zasilać dom w nocy, spadnie do ~20% przed 6:00

```

**Akcje:**
- `ładuj_do_100%_i_utrzymuj_do_06:00()` - force charge do 100%, potem blokada rozładowania do 6:00 rano
- `blokuj_rozładowanie_magazynu()` - ustaw minimum SoC na aktualną wartość do 6:00 rano
- `pozwól_naturalne_rozładowanie()` - ustaw minimum SoC na 20%

---

## STEROWANIE BOJLEREM CWU

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
1. Magazyn → dom (jeśli SoC > minimum)
2. Sieć → dom (tania taryfa)
   
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
1. Magazyn → sieć (eksport)
2. Sieć → dom (dom zasilany z sieci, nie z magazynu)
   (cała energia z magazynu idzie na eksport)
```

---

## ZARZĄDZANIE FLAGAMI I STANEM

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

1. **Wszystkie ceny RCE są w PLN/kWh netto** (bez VAT)
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