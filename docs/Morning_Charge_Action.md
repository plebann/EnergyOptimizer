# Zachowanie poranne (04:00) — Opis akcji

## Cel

Zapewnienie wystarczającej ilości energii w magazynie na pokrycie zapotrzebowania gospodarstwa domowego w godzinach wysokiej taryfy energii elektrycznej poprzez ładowanie z sieci w tańszej taryfie nocnej.

## Wyzwalacz

- Stała godzina harmonogramu: 04:00
- Możliwość ręcznego wywołania przez serwis `energy_optimizer.morning_grid_charge`

## Wejścia (koncepcyjne)

- Aktualny SOC baterii i dostępna pojemność magazynu
- Polityki SOC (limity minimalne/maksymalne)
- Docelowy SOC programu 2 (ładowanie z sieci)
- Przewidywane zużycie energii w godzinach wysokiej taryfy:
  - Zużycie domowe (z czujników w okienkach 4-godzinnych)
  - Zużycie Pompy Ciepła (integracja zewnętrzna)
  - Zużycie CWU (integracja zewnętrzna) - tymczasowo niedostępne
- Przewidywana produkcja fotowoltaiczna (z integracją Solcast)
- Współczynnik wydajności PV (domyślnie 0.9)
- Współczynnik kompensacji PV (sensor: PV Forecast Compensation)
- Straty dzienne falownika
- Sprawność magazynu (domyślnie 90%)
- Margines bezpieczeństwa (domyślnie 1.1 = +10%)
- Sensor godziny końca wysokiej taryfy (używany do wyznaczenia okna obliczeń)
- Ustawienie włączenia Pompy Ciepła (jeśli wyłączone, zużycie PC = 0)

## Przebieg decyzji (wysoki poziom)

1. **Walidacja konfiguracji**: Sprawdź czy wszystkie wymagane sensory są skonfigurowane i dostępne
2. **Sprawdzenie balansowania**: Jeśli trwa balansowanie, pomiń akcję i wyloguj stan „balancing ongoing”.
3. **Obliczenie rezerwy energii**: Ile energii użytecznej jest obecnie w magazynie (ponad minimalny SOC)
4. **Obliczenie zapotrzebowania**: Ile energii będzie potrzebne w godzinach wysokiej taryfy (6:00–koniec taryfy z sensora)
   - Suma zużycia domowego z czujników
   - Zapytanie serwisu `heat_pump_predictor.calculate_forecast_energy` o zużycie Pompy Ciepła
   - Dodanie strat falownika proporcjonalnie do czasu (straty_dzienne / 24 × liczba_godzin) **z marginesem**
   - Korekta na margines bezpieczeństwa
5. **Obliczenie produkcji PV**: Suma prognozy PV z integracji Solcast dla godzin wysokiej taryfy, skorygowana kompensacją PV oraz współczynnikiem wydajności (domyślnie 0.9).
6. **Porównanie zapotrzebowanie vs dostępne źródła**:
   - Jeśli **rezerwa + prognoza PV >= zapotrzebowanie**: Brak akcji, energia wystarczy
   - Jeśli **deficyt > 0**: Oblicz ile energii załadować uwzględniając sprawność magazynu i zaplanuj doładowanie

### Szczegóły decyzyjne

**Algorytm obliczania deficytu:**
1. Bazowe zapotrzebowanie = zużycie_domowe + zużycie_PC
2. Zapotrzebowanie skorygowane = bazowe × margines_bezpieczeństwa (1.1)
3. Zapotrzebowanie całkowite = skorygowane + straty_falownika (również z marginesem)
4. Deficyt przed sprawnością = zapotrzebowanie_całkowite - rezerwa - prognoza_PV
5. Deficyt do załadowania = deficyt / sprawność (np. 15.4 / 0.9 = 17.1 kWh)

**Sprawność magazynu**: W praktyce energia do załadowania uwzględnia straty na ładowaniu i rozładowaniu: `wymagane / (0.9 × 0.9)`.

**Prognoza PV**: Suma prognozy z `detailedForecast` jest liczona dla okna 6:00–koniec taryfy, korygowana kompensacją PV (średnia z kompensacji „dzisiejszej” i z sensora PV Forecast Compensation), a następnie mnożona przez współczynnik wydajności PV.

**Godzina wystarczalności PV (nowe)**:
1. Dla każdej godziny okna 6:00–koniec taryfy wyznacz godzinowe zapotrzebowanie: zużycie_domowe + zużycie_PC + straty (z marginesem).
2. Wyznacz godzinową produkcję PV z prognozy (z uwzględnieniem współczynnika wydajności).
3. Znajdź pierwszą godzinę, w której produkcja PV w tej godzinie pokrywa zapotrzebowanie (godzina wystarczalności).
4. Oblicz deficyt dla okna 6:00–koniec taryfy **oraz** 6:00–godzina wystarczalności.
5. Jeżeli deficyt do godziny wystarczalności jest większy — **to on** jest używany do planowania ładowania.

Ta poprawka zapobiega sytuacji, w której późny wzrost PV maskuje deficyt wczesnych godzin.

**Obliczanie prądu ładowania** (algorytm zaawansowany z ograniczeniami prądu):

Magazyn ma różne limity prądu ładowania w zależności od zakresu SOC:
- 0-50% SOC: max 23A
- 50-70% SOC: max 18A
- 70-90% SOC: max 9A
- 90-100% SOC: max 5A

Algorytm:
1. Oblicz docelowy SOC na podstawie deficytu energii
2. Podziel ładowanie na fazy odpowiadające zakresom SOC
3. Dla każdej fazy oblicz ile energii będzie ładowane oraz czas przy maksymalnym prądzie
4. Sprawdź czy można załadować całość w 2h przy maksymalnych prądach:
   - **Jeśli TAK**: oblicz wymagany średni prąd = `(deficyt × 1000) / (2h × napięcie)`
     - Wybierz mniejszą wartość z: wymagany średni prąd lub maksymalny prąd dla aktualnego zakresu SOC
   - **Jeśli NIE**: ustaw maksymalny prąd (23A) - ładowanie zajmie więcej niż 2h
5. Zaokrąglij do pełnego ampera w górę

Ten algorytm zapewnia:
- Bezpieczne ładowanie z poszanowaniem limitów dla różnych zakresów SOC
- Optymalizację czasu ładowania (nie ładuje za szybko jeśli nie jest to potrzebne)
- Możliwość ładowania w 2h oknie nocnej taryfy

**Uwaga**: wynik prądu może się różnić od prostego wzoru $(kWh/2h \times 1000)/V$ ze względu na ograniczenia prądu w poszczególnych fazach SOC.

## Wpływ na maszynę stanów

- NORMAL → CHARGING_FROM_GRID, gdy wymagane jest ładowanie magazynu z sieci

## Efekty sterowania (koncepcyjne)

- Ustaw docelowy SOC programu 2 (ładowanie z sieci) na obliczoną wartość
- Ustaw prąd ładowania z sieci na obliczoną wartość (2h okno ładowania)
- Falownik automatycznie rozpocznie ładowanie do osiągnięcia docelowego SOC

## Obsługa błędów

**UWAGA**: Do ustalenia w przyszłości.

Należy określić zachowanie systemu w przypadku:
- Serwis `heat_pump_predictor.calculate_forecast_energy` nie odpowiada lub zwraca błąd
- Sensor `solcast_pv_forecast_forecast_today` jest niedostępny lub brak atrybutu prognozy
- Sensor godziny końca taryfy ma nieprawidłową wartość lub jest niedostępny
- Sensor `average_daily_losses` jest niedostępny

Możliwe strategie:
- Użycie wartości domyślnych/historycznych
- Pominięcie akcji ładowania (bezpieczne podejście)
- Zalogowanie ostrzeżenia i kontynuacja z częściowymi danymi

**Aktualny stan (implementacja)**:
- Brak sensora końca taryfy → domyślnie 13:00 (z logiem warning)
- Brak PV forecast → PV = 0 kWh (warning)
- Brak serwisu HP → HP = 0 kWh (warning)
- Brak sensora PV w konfiguracji → używany jest fallback do `pv_forecast_today` jeśli dostępny
- Wyłączona Pompa Ciepła → HP = 0 kWh (informacja debug)
- Brak szczegółowej prognozy PV (`detailedForecast`) → PV = 0 kWh (warning)
- Trwa balansowanie → akcja poranna pomijana, log „balancing ongoing”

## Logowanie i powiadomienia

- Zaloguj typ decyzji: brak akcji / ładowanie zaplanowane
- Zapisz kluczowe wejścia (rezerwa, zapotrzebowanie, deficyt, prognoza PV, docelowy SOC, prąd ładowania)
- Logi zawierają także: zużycie Pompy Ciepła i prognozę PV (jeśli dostępne)
- Podaj krótkie uzasadnienie widoczne dla użytkownika
- Użyj ujednoliconego systemu logowania `log_decision_unified` z pełnym kontekstem

## Przykład działania

### Scenariusz: Niewystarczająca rezerwa

**Wejścia:**
- Aktualny SOC: 45%, Min SOC: 20%, Max SOC: 100%
- Pojemność: 37 Ah × 576V = 21.3 kWh
- Sprawność: 90%, Margines: 1.1
- Przewidywane zużycie domowe 6:00-13:00: 6 kWh
- Przewidywane zużycie PC: 14 kWh
- Straty dzienne: 2.4 kWh
- Przewidywana produkcja PV: 2 kWh

**Decyzja:**
1. Rezerwa: (45% - 20%) × 21.3 = 5.3 kWh
2. Zapotrzebowanie: (6 + 14) × 1.1 + 0.7 = 22.7 kWh
3. Deficyt: (22.7 - 5.3 - 2.0) / 0.9 = 17.1 kWh do załadowania
4. Target SOC: 100% (deficyt przekracza możliwości)
5. Prąd: (17.1 / 2 × 1000) / 576 = 15 A

**Akcja:**
- Ustaw Program 2 SOC na 100%
- Ustaw prąd ładowania na 15 A
- Log: "Battery charging to 100%, deficit 17.1 kWh, reserve 5.3 kWh, required 22.7 kWh, PV 2.0 kWh, current 15 A"
