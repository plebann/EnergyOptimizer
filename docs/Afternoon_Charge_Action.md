# Zachowanie popołudniowe (koniec taryfy) — Opis akcji

## Cel

Zapewnienie odpowiedniego poziomu energii w magazynie na wieczór i noc (do 22:00) poprzez planowanie ładowania z sieci po zakończeniu taryfy dziennej.

## Wyzwalacz

- Godzina z sensora końca taryfy: `tariff_end_hour`
- Możliwość ręcznego wywołania przez dedykowany serwis (do ustalenia)

## Wejścia (koncepcyjne)

- Aktualny SOC baterii i dostępna pojemność magazynu
- Polityki SOC (limity minimalne/maksymalne)
- Docelowy SOC programu 2 (ładowanie z sieci)
- Przewidywane zużycie energii w oknie popołudniowym:
  - Zużycie domowe (z czujników w okienkach 4‑godzinnych)
  - Zużycie Pompy Ciepła (integracja zewnętrzna)
  - Zużycie CWU (integracja zewnętrzna) - tymczasowo niedostępne
- Przewidywana produkcja fotowoltaiczna (z integracją Solcast), z uwzględnieniem kompensacji prognozy na podstawie bieżącej produkcji (bez użycia współczynnika `pv_efficiency`)
- Straty dzienne falownika
- Sprawność magazynu (domyślnie 90%):
   - przy wyznaczaniu rezerwy uwzględnia straty **tylko na rozładowaniu**
   - przy wyznaczaniu energii do załadowania uwzględnia straty **na ładowaniu i rozładowaniu**
- Margines bezpieczeństwa (domyślnie 1.1 = +10%)
- Sensor godziny startu taryfy: `tariff_start_hour` **(nowy, wymagany do okna obliczeń)**
- Sensor godziny końca taryfy: `tariff_end_hour` (wyzwalacz akcji)
- Ustawienie włączenia Pompy Ciepła (jeśli wyłączone, zużycie PC = 0)

## Przebieg decyzji (wysoki poziom)

1. **Walidacja konfiguracji**: Sprawdź czy wszystkie wymagane sensory są skonfigurowane i dostępne
2. **Obliczenie rezerwy energii**: Ile energii użytecznej jest obecnie w magazynie (ponad minimalny SOC)
3. **Obliczenie zapotrzebowania**: Ile energii będzie potrzebne w oknie `tariff_start_hour` → 22:00
   - Suma zużycia domowego z czujników
   - Zapytanie serwisu `heat_pump_predictor.calculate_forecast_energy` o zużycie Pompy Ciepła
   - Dodanie strat falownika proporcjonalnie do czasu (straty_dzienne / 24 × liczba_godzin) **z marginesem**
   - Korekta na margines bezpieczeństwa
4. **Obliczenie produkcji PV**: Suma prognozy PV z integracji Solcast dla okna `tariff_start_hour` → 22:00, z kompensacją prognozy (bez użycia `pv_efficiency`)
5. **Porównanie zapotrzebowanie vs dostępne źródła**:
   - Jeśli **rezerwa + prognoza PV >= zapotrzebowanie**: Brak akcji, energia wystarczy
   - Jeśli **deficyt > 0**: Oblicz ile energii załadować uwzględniając sprawność magazynu i zaplanuj doładowanie

### Szczegóły decyzyjne

**Algorytm obliczania deficytu:**
1. Bazowe zapotrzebowanie = zużycie_domowe + zużycie_PC
2. Zapotrzebowanie skorygowane = bazowe × margines_bezpieczeństwa (1.1)
3. Zapotrzebowanie całkowite = skorygowane + straty_falownika (również z marginesem)
4. Deficyt przed sprawnością = zapotrzebowanie_całkowite - rezerwa - prognoza_PV
5. Deficyt do załadowania = deficyt / sprawność (np. 15.4 / 0.9 = 17.1 kWh)

**Sprawność magazynu**:
- Dla rezerwy (energia dostępna z magazynu): jeśli w magazynie jest 1 kWh, rozładuję 0.9 kWh → uwzględniamy **tylko** straty rozładowania.
- Dla energii do załadowania: aby uzyskać wymaganą energię po rozładowaniu, trzeba załadować więcej z uwzględnieniem strat ładowania i rozładowania, np. `wymagane / (0.9 × 0.9)`.

**Prognoza PV**: Suma prognozy z `detailedForecast` liczona dla okna `tariff_start_hour` → 22:00, z kompensacją prognozy (bez użycia `pv_efficiency`).

**Obliczanie prądu ładowania**: jak w porannym scenariuszu (algorytm wielofazowy z limitami prądu).

## Wpływ na maszynę stanów

- NORMAL → CHARGING_FROM_GRID, gdy wymagane jest ładowanie magazynu z sieci

## Efekty sterowania (koncepcyjne)

- Ustaw docelowy SOC programu 2 (ładowanie z sieci) na obliczoną wartość
- Ustaw prąd ładowania z sieci na obliczoną wartość (okno do 22:00)
- Falownik automatycznie rozpocznie ładowanie do osiągnięcia docelowego SOC

## Obsługa błędów

**UWAGA**: Do ustalenia w przyszłości.

Należy określić zachowanie systemu w przypadku:
- Sensor `tariff_start_hour` jest niedostępny lub ma nieprawidłową wartość
- Serwis `heat_pump_predictor.calculate_forecast_energy` nie odpowiada lub zwraca błąd
- Sensor PV forecast jest niedostępny lub brak atrybutu prognozy

Możliwe strategie:
- Użycie wartości domyślnych/historycznych
- Pominięcie akcji ładowania (bezpieczne podejście)
- Zalogowanie ostrzeżenia i kontynuacja z częściowymi danymi

## Logowanie i powiadomienia

- Zaloguj typ decyzji: brak akcji / ładowanie zaplanowane
- Zapisz kluczowe wejścia (rezerwa, zapotrzebowanie, deficyt, prognoza PV, docelowy SOC, prąd ładowania)
- Podaj krótkie uzasadnienie widoczne dla użytkownika
- Użyj ujednoliconego systemu logowania `log_decision_unified` z pełnym kontekstem
