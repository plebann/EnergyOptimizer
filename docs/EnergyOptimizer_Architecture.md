# EnergyOptimizer - Architektura Integracji HACS

**Home Assistant Energy Storage Management System**

Wersja 1.0 | Styczeń 2026

---

## Spis treści

1. [Wprowadzenie](#1-wprowadzenie)
2. [Architektura wysokiego poziomu](#2-architektura-wysokiego-poziomu)
3. [Warstwa danych](#3-warstwa-danych)
4. [Warstwa logiki biznesowej](#4-warstwa-logiki-biznesowej)
5. [Warstwa sterowania](#5-warstwa-sterowania)
6. [Integracja z Home Assistant](#6-integracja-z-home-assistant)
7. [Podsumowanie](#7-podsumowanie)

---

## 1. Wprowadzenie

### 1.1. Cel dokumentu

Niniejszy dokument przedstawia architekturę integracji HACS (Home Assistant Community Store) dla systemu zarządzania magazynem energii EnergyOptimizer. Integracja implementuje algorytm optymalizacji opisany w dokumencie specyfikacji zasad sterowania magazynem energii.

### 1.2. Zakres systemu

System EnergyOptimizer jest dedykowanym rozwiązaniem dla instalacji fotowoltaicznej z magazynem energii, które minimalizuje koszty energii elektrycznej poprzez:

- Maksymalizację autokonsumpcji energii z PV
- Eliminację poboru energii z sieci w taryfie wysokiej
- Budowanie depozytu prosumenckiego w okresach wysokiej produkcji PV
- Wykorzystanie arbitrażu cenowego na rynku energii

**Strategia:** Konserwatywna - priorytet to unikanie kupowania energii w drogiej taryfie, nawet kosztem niewykorzystania okazji do arbitrażu.

### 1.3. Parametry instalacji

| Parametr | Wartość |
|----------|---------|
| Moc PV | 13 kWp |
| Pojemność magazynu | 21 kWh |
| Falownik | Deye SUN-5-25K-SG01HP3 (12 kW) |
| Sprawność magazynu | 90% (round-trip) |
| Taryfa | G12 (dwustrefowa) |

---

## 2. Architektura wysokiego poziomu

### 2.1. Komponenty systemu

System składa się z następujących głównych komponentów:

- **EnergyOptimizer Integration Core** - rdzeń integracji HACS, koordynator logiki biznesowej
- **Data Layer** - warstwa zbierania i przetwarzania danych z zewnętrznych integracji
- **Decision Engine** - silnik decyzyjny implementujący algorytm optymalizacji
- **Control Layer** - warstwa sterowania poprzez encje Home Assistant
- **Scheduler** - harmonogram czasowy akcji
- **State Machine** - zarządzanie stanem systemu i flagami

### 2.2. Integracje zewnętrzne

System integruje się z następującymi zewnętrznymi komponentami Home Assistant:

| Integracja | Repository | Przeznaczenie |
|------------|-----------|---------------|
| Solarman | davidrapan/ha-solarman | Sterowanie falownikiem Deye |
| Solcast | BJReplay/ha-solcast-solar | Prognoza produkcji PV |
| RCE PSE | Lewa-Reka/ha-rce-pse | Ceny RCE (15 min) |
| Heat Pump Predictor | plebann/HeatPumpPredictor | Prognoza zużycia PC |
| Energy Meter | Encja HA | Pomiary energii |
| Home Consumption | Encje HA | Prognoza zużycia domu |

### 2.3. Przepływ danych

Architektura opiera się na event-driven model z okresowymi akcjami czasowymi:

1. **Coordinator** zbiera dane z zewnętrznych integracji (ceny RCE, prognozy PV, prognozy zużycia)
2. **Data Layer** przetwarza i agreguje dane w odpowiedniej granulacji czasowej
3. **Decision Engine** wykonuje algorytm optymalizacji zgodnie z harmonogramem akcji
4. **State Machine** aktualizuje flagi i stan systemu
5. **Control Layer** wysyła komendy poprzez encje Home Assistant (number, select, switch)
6. **Sensory** publikują stan systemu i decyzje do Home Assistant

### 2.4. Diagram przepływu danych

```
┌─────────────────────────────────────────────────────────────┐
│                    External Integrations                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │ Solarman │  │ Solcast  │  │ RCE PSE  │  │   HPP    │   │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘   │
└───────┼─────────────┼─────────────┼─────────────┼──────────┘
        │             │             │             │
        ▼             ▼             ▼             ▼
┌─────────────────────────────────────────────────────────────┐
│                      Data Layer                              │
│  - Aggregation  - Interpolation  - Normalization            │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    Decision Engine                           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │Daily Analysis│  │Morning Charge│  │  PV Blocking │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │  Peak Sale   │  │Valley Charge │  │  Afternoon   │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
│  ┌──────────────┐                                           │
│  │   Evening    │         State Machine                     │
│  └──────────────┘                                           │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    Control Layer                             │
│  Interaction via HA entities (number, select, switch)       │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│              Solarman Integration (Deye Inverter)           │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Warstwa danych

### 3.1. Sensory wejściowe

Sensory wejściowe pobierają dane z zewnętrznych integracji. Wszystkie sensory są **read-only** z perspektywy EnergyOptimizer.

#### 3.1.1. Dane z Solarman (falownik Deye)

- **`sensor.battery_soc`** - aktualny stan naładowania magazynu (%)
- **`sensor.pv_power`** - aktualna moc produkcji PV (kW)
- **`sensor.battery_power`** - aktualna moc ładowania/rozładowania (+/- kW)
- **`sensor.grid_power`** - aktualna moc poboru/eksportu z/do sieci (+/- kW)
- **`sensor.load_power`** - aktualna moc zużycia domu (kW)

#### 3.1.2. Dane z Solcast

- **`sensor.solcast_pv_forecast_today`** - prognoza produkcji PV na dziś (lista wartości co 30 min, kW)
- **`sensor.solcast_pv_forecast_forecast_remaining_today`** - prognoza pozostałej produkcji PV na dziś (kWh)
- **`sensor.solcast_pv_forecast_tomorrow`** - prognoza produkcji PV na jutro (lista wartości co 30 min, kW)

#### 3.1.3. Dane z RCE PSE

- **`sensor.rce_prices_today`** - lista cen RCE na dziś (96 wartości po 15 min, PLN/kWh)
- **`sensor.rce_prices_tomorrow`** - lista cen RCE na jutro (96 wartości po 15 min, PLN/kWh)

#### 3.1.4. Dane z Heat Pump Predictor

- **`sensor.heat_pump_consumption_forecast`** - prognoza zużycia pompy ciepła (jako serwis, parametry wejściowe to godzina od, godzina do, wyjście to kWh)

#### 3.1.5. Dane zużycia domu

- **`sensor.load_daily_usage`** - statystyki dzisiejszego zużycia energii przez dom (z wyłączeniem pompy ciepła i CWU, kWh)
- **`sensor.load_usage_history`** - historia średniego zużycia energii przez dom (za ostatnie 4 tygodnie, bez PC i CWU, kWh)
- **`sensor.load_usage_00_04`** - historia zużycia w godzinach 00-04, kWh
- **`sensor.load_usage_04_08`** - historia zużycia w godzinach 04-08, kWh
- **`sensor.load_usage_08_12`** - historia zużycia w godzinach 08-12, kWh
- **`sensor.load_usage_12_16`** - historia zużycia w godzinach 12-16, kWh
- **`sensor.load_usage_16_20`** - historia zużycia w godzinach 16-20, kWh
- **`sensor.load_usage_20_24`** - historia zużycia w godzinach 20-24, kWh

#### 3.1.6 Dane strat falownika

- **`sensor.inverter_total_losses_history`**
  - atrybut *daily rate* - średnia dobowa, kWh
  - atrybut *hourly rate* - średnia godzinowa, kWh

### 3.2. Sensory wewnętrzne (obliczane)

Sensory tworzone i aktualizowane przez EnergyOptimizer na podstawie algorytmu decyzyjnego.

#### 3.2.1. Wyniki analizy dziennej (00:00)

- **`sensor.energy_optimizer_valley_period`** - słownik z informacjami o dołku dziennym
  ```json
  {
    "start": "2026-01-30T11:00:00",
    "end": "2026-01-30T14:00:00",
    "avg_price": 0.45
  }
  ```

- **`sensor.energy_optimizer_morning_peak`** - słownik o szczycie porannym
  ```json
  {
    "start": "2026-01-30T07:00:00",
    "end": "2026-01-30T09:00:00",
    "peak_hour": "2026-01-30T08:00:00",
    "avg_price": 1.15,
    "max_price": 1.28
  }
  ```

- **`sensor.energy_optimizer_evening_peak`** - słownik o szczycie wieczornym
  ```json
  {
    "start": "2026-01-30T17:00:00",
    "end": "2026-01-30T20:00:00",
    "peak_hour": "2026-01-30T18:00:00",
    "avg_price": 1.22,
    "max_price": 1.35
  }
  ```

#### 3.2.2. Prognozowane zapotrzebowanie

- **`sensor.energy_optimizer_daily_deficit`** - przewidywany deficyt energii w taryfie wysokiej (kWh)
- **`sensor.energy_optimizer_required_charge`** - wymagane doładowanie magazynu z sieci (kWh)

#### 3.2.3. Stan systemu

- **`sensor.energy_optimizer_mode`** - aktualny tryb pracy
  - Wartości: `normal`, `waiting_for_valley`, `selling`, `buying`, `balancing`, `running_from_grid`, `error`

- **`sensor.energy_optimizer_next_action`** - opis następnej zaplanowanej akcji
  ```json
  {
    "action": "morning_peak_sale",
    "scheduled_time": "2026-01-30T08:00:00",
    "estimated_amount": 5.2
  }
  ```

- **`sensor.energy_optimizer_decision_log`** - historia ostatnich 10 decyzji z uzasadnieniem
  ```json
  [
    {
      "timestamp": "2026-01-30T04:00:00",
      "module": "MorningChargeModule",
      "decision": "charge_from_grid",
      "amount_kwh": 8.5,
      "reason": "Deficit 12.3 kWh in high tariff, PV forecast 3.8 kWh insufficient"
    }
  ]
  ```

### 3.3. Encje pomocnicze

Persystentne dane konfiguracyjne i stanowe zarządzane przez Home Assistant.

#### 3.3.1. Input Boolean (flagi)

- **`input_boolean.energy_optimizer_enabled`** - włączenie/wyłączenie całego systemu
- **`input_boolean.energy_optimizer_waiting_for_valley`** - flaga czekania na dołek cenowy
- **`input_boolean.energy_optimizer_running_from_grid`** - flaga bezpośredniego używania sieci
- **`input_boolean.energy_optimizer_dhw_boost`** - wymuszenie trybu boost CWU

#### 3.3.2. Input DateTime

- **`input_datetime.energy_optimizer_last_balancing`** - data ostatniego pełnego balansowania magazynu

#### 3.3.3. Input Number

- **`input_number.energy_optimizer_min_soc_low_tariff`** - minimalny SOC w taryfie niskiej (domyślnie 20%)
- **`input_number.energy_optimizer_min_soc_high_tariff`** - minimalny SOC w taryfie wysokiej (domyślnie 10%)
- **`input_number.energy_optimizer_export_threshold`** - próg opłacalności eksportu (domyślnie 95.1 gr/kWh)
- **`input_number.energy_optimizer_battery_days_between_balancing`** - liczba dni pomiędzy balansowaniem baterii

---

## 4. Warstwa logiki biznesowej

### 4.1. Coordinator

Koordynator jest głównym komponentem integracji odpowiedzialnym za cykl życia danych i synchronizację z Home Assistant.

#### 4.1.1. Cykl odświeżania

Coordinator używa `DataUpdateCoordinator` z Home Assistant z następującymi parametrami:

- **Update interval:** 5 minut (standardowe odświeżanie danych)
- **Fast update:** 1 minuta (podczas wykonywania akcji sterujących)
- **Error handling:** retry z wykładniczym back-off (1, 2, 5, 10 minut)

#### 4.1.2. Zbieranie danych

W każdym cyklu odświeżania Coordinator:

1. Odczytuje encje źródłowe z HA (`asyncio.gather` dla równoległości)
2. Waliduje dane (sprawdza kompletność i poprawność)
3. Agreguje dane do wewnętrznej struktury
4. Przekazuje dane do Decision Engine
5. Aktualizuje sensory publikowane w HA

### 4.2. Decision Engine

Silnik decyzyjny implementuje algorytm optymalizacji opisany w specyfikacji. Składa się z modułów odpowiadających poszczególnym momentom akcji.

#### 4.2.1. Struktura modułów

##### DailyAnalysisModule
Analiza dzienna (00:00), identyfikacja okien cenowych.

- **Metoda:** `analyze_daily_prices(rce_prices_today, rce_prices_tomorrow, pv_forecast)`
- **Wyjście:** `valley_period`, `morning_peak`, `evening_peak`
- **Opis:** Identyfikuje dołek dzienny i szczyty cenowe na podstawie cen RCE i prognozy PV

##### MorningChargeModule
Ładowanie poranne z sieci (04:00).

- **Metoda:** `calculate_morning_charge(soc, pv_forecast, consumption_forecast)`
- **Wyjście:** `charge_amount` (kWh) lub `None`
- **Opis:** Oblicza czy i ile energii doładować z taniej taryfy nocnej, żeby pokryć zapotrzebowanie na energię w taryfie wysokiej (do godziny 13/15). Dodatkowo dokonuje korekty prognozy PV

##### PVBlockingModule
Decyzja o blokowaniu ładowania z PV (wschód słońca).

- **Metoda:** `should_block_pv_charging(valley_period, evening_peak, morning_peak_tomorrow)`
- **Wyjście:** `True/False`
- **Opis:** Decyduje czy zablokować ładowanie magazynu z PV w oczekiwaniu na tańsze ceny w dołku

##### PeakSaleModule
Sprzedaż w szczytach (poranny/wieczorny).

- **Metoda:** `calculate_peak_sale(peak_info, soc, consumption_until_next)`
- **Wyjście:** `sale_amount` (kWh) lub `None`
- **Opis:** Oblicza ile energii można sprzedać w szczycie cenowym

##### ValleyChargeModule
Włączenie ładowania w dołku dziennym.

- **Metoda:** `activate_valley_charging()`
- **Wyjście:** akcja odblokowania ładowania PV
- **Opis:** Przywraca normalny priorytet ładowania gdy osiągnięto dołek cenowy

##### EveningBehaviorModule
Zachowanie wieczorne, balansowanie (22:00).

- **Metoda:** `evening_behavior(last_balancing_date, pv_forecast_tomorrow)`
- **Wyjście:** `balancing_needed`, `running_from_grid`
- **Opis:** Zarządza balansowaniem magazynu i bezpośrednim zasilaniem z sieci

#### 4.2.2. Przetwarzanie danych wejściowych

Przed wywołaniem modułów decyzyjnych, dane są przetwarzane do jednolitego formatu:

- **Agregacja czasowa:** dane z 15-min/30-min do godzinowych okien
- **Interpolacja:** uzupełnienie brakujących wartości (linear interpolation)
- **Normalizacja jednostek:** konwersja wszystkich mocy do kW i energii do kWh
- **Timezone handling:** obsługa zmian czasu (CET/CEST)

### 4.3. State Machine

Automat stanów zarządza trybami pracy systemu i zapewnia spójność działania.

#### 4.3.1. Stany systemu

- **NORMAL** - standardowa praca, PV → dom → magazyn → eksport
- **WAITING_FOR_VALLEY** - oczekiwanie na dołek, PV → dom → eksport (bez ładowania magazynu)
- **CHARGING_FROM_GRID** - wymuszone ładowanie z sieci (force charge)
- **SELLING_TO_GRID** - wymuszona sprzedaż do sieci (force discharge)
- **BALANCING** - pełne balansowanie magazynu do 100%
- **RUNNING_FROM_GRID** - zablokowane rozładowanie magazynu, całe zużycie domu zapokajane z sieci
- **ERROR** - stan błędu, system wstrzymany

#### 4.3.2. Przejścia stanów

Przejścia między stanami są sterowane przez Decision Engine i walidowane przez State Machine.

```python
transition_allowed = {
  NORMAL -> WAITING_FOR_VALLEY: if valley_blocking_enabled
  NORMAL -> CHARGING_FROM_GRID: if charge_action_triggered
  NORMAL -> SELLING_TO_GRID: if sale_action_triggered
  NORMAL -> BALANCING: if balancing_needed
  NORMAL -> RUNNING_FROM_GRID: if running_from_grid_flag
  
  WAITING_FOR_VALLEY -> NORMAL: if valley_start_time_reached
  
  CHARGING_FROM_GRID -> NORMAL: if target_soc_reached OR timeout
  SELLING_TO_GRID -> NORMAL: if target_energy_sold OR timeout
  BALANCING -> NORMAL: if soc == 100% AND time >= 06:00
  RUNNING_FROM_GRID -> NORMAL: if time >= 06:00
  
  * -> ERROR: if critical_failure
  ERROR -> NORMAL: if manual_reset
}
```

### 4.4. Moduły pomocnicze

#### 4.4.1. TariffManager

Zarządza logiką taryfy G12 z sezonowością (zima/lato).

**Metody:**
- `is_low_tariff(datetime) -> bool`
- `get_tariff_price(datetime) -> float`
- `get_high_tariff_hours_for_day(date) -> List[int]`

#### 4.4.2. ForecastProcessor

Przetwarza i agreguje dane prognozowe z różnych źródeł.

**Metody:**
- `aggregate_to_hourly(data, resolution) -> Dict[hour, value]`
- `interpolate_missing(data) -> Dict`
- `correct_forecast(actual, forecast, correction_factor) -> Dict`

#### 4.4.3. PriceAnalyzer

Analizuje ceny RCE i identyfikuje charakterystyczne okna czasowe.

**Metody:**
- `find_valley(prices, pv_hours) -> ValleyInfo`
- `find_peak(prices, time_window) -> PeakInfo`
- `calculate_arbitrage_profit(buy_price, sell_price, efficiency) -> float`

---

## 5. Warstwa sterowania

### 5.1. Control Layer

Warstwa sterowania tłumaczy decyzje Decision Engine na interakcje z encjami Home Assistant. **Wszystkie sterowania falownikiem odbywają się poprzez encje Solarman, bez bezpośredniego dostępu do rejestrów Modbus.**

**Programy czasowe Solarman (używane przez automatykę):**
- P1: 01:30 (stały)
- P2: 04:00 (stały)
- P3: 06:00 (stały)
- P4: 13:00 w zimie / 15:00 w lecie (okno niskiej taryfy G12, czas startu może być korygowany inną automatyzacją)
- P5: 15:00 w zimie / 17:00 w lecie (okno wieczornego szczytu 17-21)
- P6: 22:00 (stały)

P4 jest dopasowywany sezonowo do dziennych okien niskiej taryfy G12; pozostałe czasy są stałe. Czas programu 4 może być dostosowany przez inną automatyzację, ale ładowanie w niskiej taryfie dziennej zawsze używa programu 4. Decyzje (ładowanie poranne, korekta dzienna, wieczorne sprzedaże, balansowanie 22:00) powinny używać odpowiadającego programu czasowego do ustawień SOC/prądów/ładowania. Balansowanie o 22:00 powinno ustawiać SOC w programie 6 oraz odzwierciedlać cel SOC w programie 1 (dodatkowo można uzupełnić w programie 2).

#### 5.1.1. InverterController

Kontroler falownika Deye przez integrację Solarman - **sterowanie poprzez encje HA**.

##### Encje sterujące Solarman

Integracja Solarman udostępnia następujące encje sterujące (dla programów 1-6):

**Number entities:**
- `number.inverter_program_<n>_soc` - docelowy SOC dla programu `<n>` (%)
- `number.inverter_battery_max_charging_current` - maksymalny prąd ładowania (A)
- `number.inverter_battery_max_discharging_current` - maksymalny prąd rozładowania (A)
- `number.inverter_battery_grid_charging_current` - prąd ładowania z sieci (A)
- `number.inverter_grid_max_export_power` - maksymalna moc eksportu (W)

**Select entities:**
- `select.inverter_work_mode` - tryb pracy falownika
  - Opcje: `Zero Export to Load`, `Selling First`
- `select.inverter_program_<n>_charging` - ładowanie z sieci dla programu `<n>`
  - Opcje: `disabled`, `grid`

**Time entities:**
- `time.inverter_program_<n>_time` - godzina startu programu `<n>` (wykorzystywana do aktywacji profilu ładowania/rozładowania)

**Switch entities:**
- `switch.inverter_battery_grid_charging` - włączenie ładowania magazynu z sieci
- `switch.inverter_export_surplus` - włączenie eksportu do sieci

> Rekomendacja: użyć dedykowanego programu (np. Program 1) wyłącznie dla automatyki EnergyOptimizer. Pozostałe programy mogą pozostać do ręcznej konfiguracji użytkownika.

##### Metody InverterController

```python
async def set_battery_charge_from_grid(program: int, target_soc: float, grid_current_a: float | None = None):
    """
    Ustawia wymuszone ładowanie z sieci
    
    Akcje:
      1. Ustawia number.inverter_program_<program>_soc na target_soc
      2. Ustawia select.inverter_work_mode na 'Zero Export to Load'
      3. Ustawia select.inverter_program_<program>_charging na 'grid'
      4. Opcjonalnie ustawia number.inverter_battery_grid_charging_current na grid_current_a
      5. Włącza switch.inverter_battery_grid_charging
    """
    await hass.services.async_call(
      "number",
      "set_value",
      {"entity_id": f"number.inverter_program_{program}_soc", "value": target_soc},
    )
    await hass.services.async_call(
      "select",
      "select_option",
      {"entity_id": "select.inverter_work_mode", "option": "Zero Export to Load"},
    )
    await hass.services.async_call(
      "select",
      "select_option",
      {"entity_id": f"select.inverter_program_{program}_charging", "option": "grid"},
    )
    if grid_current_a is not None:
      await hass.services.async_call(
        "number",
        "set_value",
        {
          "entity_id": "number.inverter_battery_grid_charging_current",
          "value": grid_current_a,
        },
      )
    await hass.services.async_call(
      "switch",
      "turn_on",
      {"entity_id": "switch.inverter_battery_grid_charging"},
    )
```

```python
async def set_battery_discharge_to_grid(program: int, target_soc: float, export_power_w: float | None = None, max_discharge_a: float | None = None):
    """
    Ustawia wymuszone rozładowanie do sieci
    
    Akcje:
  1. Ustawia select.inverter_work_mode na 'Selling First'
  2. Ustawia number.inverter_program_<program>_soc na target_soc
  3. Opcjonalnie ustawia number.inverter_battery_max_discharging_current na max_discharge_a
  4. Opcjonalnie ustawia number.inverter_grid_max_export_power na export_power_w
  5. Włącza switch.inverter_export_surplus
    """
    await hass.services.async_call(
        "select", "select_option",
        {"entity_id": "select.inverter_work_mode", "option": "Selling First"}
    )
    await hass.services.async_call(
        "number", "set_value",
    {"entity_id": f"number.inverter_program_{program}_soc", "value": target_soc}
    )
    if max_discharge_a is not None:
          await hass.services.async_call(
              "number", "set_value",
        {"entity_id": "number.inverter_battery_max_discharging_current", "value": max_discharge_a}
      )
    if export_power_w is not None:
      await hass.services.async_call(
        "number", "set_value",
        {"entity_id": "number.inverter_grid_max_export_power", "value": export_power_w}
          )
      await hass.services.async_call(
          "switch", "turn_on",
          {"entity_id": "switch.inverter_export_surplus"}
      )
```

```python
async def block_pv_charging():
    """
    Blokuje ładowanie magazynu z PV (czekanie na dołek)
    
    Akcje:
  1. Ustawia number.inverter_battery_max_charging_current na 0
    
    Efekt: PV -> load, nadwyżki PV -> eksport (magazyn nie ładowany)
    """
    await hass.services.async_call(
      "number", "set_value",
      {"entity_id": "number.inverter_battery_max_charging_current", "value": 0}
    )
```

```python
async def restore_normal_priority():
    """
    Przywraca standardowy priorytet ładowania
    
    Akcje:
  1. Ustawia select.inverter_work_mode na 'Zero Export to Load'
    
    Efekt: PV -> load -> battery -> grid
    """
    await hass.services.async_call(
        "select", "select_option",
        {"entity_id": "select.inverter_work_mode", "option": "Zero Export to Load"}
    )
```

```python
async def set_minimum_soc(program: int, min_soc: float):
    """
    Ustawia minimalny poziom SOC (używane przy blokowaniu rozładowania)
    
    Akcje:
  1. Ustawia number.inverter_program_<program>_soc na min_soc (dla programu sterowanego przez automatykę)
    
    Efekt: Magazyn nie rozładuje się poniżej min_soc
    """
    await hass.services.async_call(
      "number", "set_value",
      {"entity_id": f"number.inverter_program_{program}_soc", "value": min_soc}
    )
```

```python
async def get_battery_state() -> BatteryState:
    """
    Odczytuje aktualny stan magazynu
    
    Zwraca:
    BatteryState object z polami:
    - soc: float (%)
    - power: float (kW, + = charging, - = discharging)
    - temperature: float (°C)
    - voltage: float (V)
    """
    soc = hass.states.get("sensor.battery_soc").state
    power = hass.states.get("sensor.battery_power").state
    # ... pozostałe sensory
    return BatteryState(soc=soc, power=power, ...)
```

#### 5.1.2. Mapowanie stanów i akcji

| Akcja Decision Engine | Encje Solarman | Wartości |
|-----------------------|----------------|----------|
| Ładowanie z sieci (04:00) | `select.inverter_work_mode`<br>`number.inverter_program_2_soc`<br>`select.inverter_program_2_charging`<br>`number.inverter_battery_grid_charging_current` | `Zero Export to Load`<br>Docelowy SOC programu 2 (P2 start 04:00)<br>`grid`<br>Prąd z sieci (A) według zapotrzebowania |
| Blokada ładowania PV | `number.inverter_battery_max_charging_current`<br>`select.inverter_program_<n>_charging` | `0`<br>`disabled` |
| Odblokowanie ładowania PV | `number.inverter_battery_max_charging_current`<br>`select.inverter_program_<n>_charging` | Domyślne max (np. 23 A)<br>`grid` |
| Sprzedaż w szczycie (poranny szczyt) | `select.inverter_work_mode`<br>`number.inverter_program_3_soc`<br>`number.inverter_battery_max_discharging_current`<br>`number.inverter_grid_max_export_power` | `Selling First`<br>Docelowy SOC programu 3 (P3 start 06:00)<br>Limit prądu rozładowania (A)<br>Limit eksportu (W) |
| Sprzedaż w szczycie (wieczorny szczyt) | `select.inverter_work_mode`<br>`number.inverter_program_5_soc`<br>`number.inverter_battery_max_discharging_current`<br>`number.inverter_grid_max_export_power` | `Selling First`<br>Docelowy SOC programu 5 (P5 start ~17:00, okno szczytu 17-21)<br>Limit prądu rozładowania (A)<br>Limit eksportu (W) |
| Blokada rozładowania | `number.inverter_program_<n>_soc` | Ustaw na aktualny SOC (freeze) |
| Balansowanie (22:00) | `select.inverter_work_mode`<br>`number.inverter_program_6_soc` **oraz** `number.inverter_program_1_soc` (opcjonalnie `number.inverter_program_2_soc`)<br>`number.inverter_battery_max_charging_current`<br>`select.inverter_program_6_charging` **oraz** `select.inverter_program_1_charging` (opcjonalnie `select.inverter_program_2_charging`) | `Zero Export to Load`<br>`100` w programie 6 i odzwierciedlony cel SOC w programie 1 (opcjonalnie w 2)<br>Domyślne max (np. 23 A)<br>`grid` |
| Korekta + doładowanie w niskiej taryfie dziennej | `select.inverter_work_mode`<br>`number.inverter_program_4_soc` (start korygowany inną automatyzacją)<br>`select.inverter_program_4_charging`<br>`number.inverter_battery_grid_charging_current` | `Zero Export to Load`<br>Docelowy SOC programu 4<br>`grid`<br>Prąd z sieci (A) według zapotrzebowania |

### 5.2. Scheduler

Harmonogram zarządza akcjami czasowymi zgodnie ze specyfikacją algorytmu.

#### 5.2.1. Stałe akcje czasowe

| Godzina | Moduł | Akcja |
|---------|-------|-------|
| 00:00 | DailyAnalysisModule | Analiza cen RCE, identyfikacja okien |
| 04:00 | MorningChargeModule | Ładowanie poranne z sieci (taryfa niska) |
| 13:00 / 15:00 | AfternoonChargeModule | Korekta prognozy i doładowanie (sezonowo) |
| 22:00 | EveningBehaviorModule | Zachowanie wieczorne, balansowanie |

#### 5.2.2. Dynamiczne akcje czasowe

Akcje wykonywane w czasie wyznaczonym przez DailyAnalysisModule:

- **Wschód słońca** - PVBlockingModule (decyzja o blokowaniu ładowania)
- **valley_period.start** - ValleyChargeModule (włączenie ładowania z PV)
- **morning_peak.peak_hour** - PeakSaleModule (sprzedaż poranna)
- **evening_peak.peak_hour** - PeakSaleModule (sprzedaż wieczorna)

#### 5.2.3. Implementacja schedulera

Scheduler używa `async_track_time_change` z Home Assistant.

```python
class ActionScheduler:
    def __init__(self, hass, coordinator):
        self.hass = hass
        self.coordinator = coordinator
        self.scheduled_actions = {}
        
    async def schedule_action(self, action_time: datetime, action_callable):
        """Zaplanuj akcję o określonej godzinie"""
        listener = async_track_point_in_time(
            self.hass, action_callable, action_time
        )
        self.scheduled_actions[action_time] = listener
        
    async def reschedule_daily(self):
        """Po analizie o 00:00 zaplanuj akcje dynamiczne"""
        self.cancel_all()
        
        # Pobierz wyniki analizy dziennej
        valley_period = self.coordinator.data.get("valley_period")
        morning_peak = self.coordinator.data.get("morning_peak")
        evening_peak = self.coordinator.data.get("evening_peak")
        
        # Zaplanuj akcje dynamiczne
        if valley_period:
            await self.schedule_action(
                valley_period["start"], 
                self._valley_charge_action
            )
        if morning_peak:
            await self.schedule_action(
                morning_peak["peak_hour"], 
                self._morning_sale_action
            )
        if evening_peak:
            await self.schedule_action(
                evening_peak["peak_hour"], 
                self._evening_sale_action
            )
```

---

## 6. Integracja z Home Assistant

### 6.1. Struktura katalogów

```
custom_components/energy_optimizer/
├── __init__.py              # Entry point, setup platformy
├── manifest.json            # Metadata integracji
├── config_flow.py           # Konfiguracja przez UI
├── const.py                 # Stałe (domeny, nazwy)
├── coordinator.py           # DataUpdateCoordinator
├── sensor.py                # Platforma sensorów
├── switch.py                # Platforma przełączników
├── services.yaml            # Definicje serwisów
├── strings.json             # Tłumaczenia UI
├── translations/
│   ├── en.json
│   └── pl.json
├── decision_engine/
│   ├── __init__.py
│   ├── daily_analysis.py
│   ├── morning_charge.py
│   ├── pv_blocking.py
│   ├── peak_sale.py
│   ├── valley_charge.py
│   ├── afternoon_charge.py
│   └── evening_behavior.py
├── controllers/
│   ├── __init__.py
│   ├── inverter.py          # InverterController
│   └── dhw.py               # DHWController (future)
├── utils/
│   ├── __init__.py
│   ├── tariff_manager.py
│   ├── forecast_processor.py
│   ├── price_analyzer.py
│   └── state_machine.py
└── scheduler/
    ├── __init__.py
    └── action_scheduler.py
```

### 6.2. Rejestracja platform

#### 6.2.1. Platforma Sensor

Rejestracja wszystkich sensorów wewnętrznych (obliczanych):

- `ValleyPeriodSensor` - sensor.energy_optimizer_valley_period
- `MorningPeakSensor` - sensor.energy_optimizer_morning_peak
- `EveningPeakSensor` - sensor.energy_optimizer_evening_peak
- `DailyDeficitSensor` - sensor.energy_optimizer_daily_deficit
- `RequiredChargeSensor` - sensor.energy_optimizer_required_charge
- `ModeSensor` - sensor.energy_optimizer_mode
- `NextActionSensor` - sensor.energy_optimizer_next_action
- `DecisionLogSensor` - sensor.energy_optimizer_decision_log

#### 6.2.2. Platforma Switch

Przełączniki do ręcznej kontroli (oprócz input_boolean):

- `ManualModeSwitch` - switch.energy_optimizer_manual_mode (wyłącza automatykę)

#### 6.2.3. Serwisy

Niestandardowe serwisy do wywołania z automatyzacji lub developerskich narzędzi:

- **`energy_optimizer.force_daily_analysis`** - wymuś ponowną analizę dzienną
- **`energy_optimizer.force_charge`** - ręczne wymuszone ładowanie
  - Parametry: `target_soc` (float)
- **`energy_optimizer.force_discharge`** - ręczne wymuszone rozładowanie
  - Parametry: `target_soc` (float), `power_w` (optional)
- **`energy_optimizer.reset_state`** - reset stanu maszyny (przejście do NORMAL)

### 6.3. Konfiguracja przez UI

Integracja umożliwia konfigurację przez interfejs użytkownika (config_flow). Użytkownik podaje następujące parametry:

#### 6.3.1. Encje źródłowe

**Z Solarman:**
- Sensor SOC magazynu
- Sensor mocy PV
- Sensor mocy magazynu
- Sensor mocy sieci
- Number - docelowy SOC dla wybranego programu (`number.inverter_program_<n>_soc`)
- Time - godzina startu programu (`time.inverter_program_<n>_time`)
- Select - tryb pracy (`select.inverter_work_mode`)
- Select - ładowanie z sieci dla programu (`select.inverter_program_<n>_charging`)
- Number - maks. prąd ładowania/rozładowania (`number.inverter_battery_max_charging_current`, `number.inverter_battery_max_discharging_current`)
- Number - prąd ładowania z sieci (`number.inverter_battery_grid_charging_current`)
- Number - maks. moc eksportu (`number.inverter_grid_max_export_power`)
- Switch - włączenie ładowania
- Switch - włączenie eksportu

**Z innych integracji:**
- Prognoza PV dziś (Solcast)
- Prognoza PV jutro (Solcast)
- Ceny RCE dziś (RCE PSE)
- Ceny RCE jutro (RCE PSE)
- Prognoza zużycia domu (encje użytkownika)
- Prognoza zużycia pompy ciepła (Heat Pump Predictor)

#### 6.3.2. Parametry instalacji

- Pojemność magazynu (kWh)
- Moc falownika (kW)
- Sprawność magazynu round-trip (%)
- Próg opłacalności eksportu (gr/kWh)
- Moc PV (kWp)

#### 6.3.3. Parametry taryfy G12

- Cena energii - taryfa niska (gr/kWh)
- Cena energii - taryfa wysoka (gr/kWh)
- Koszt przesyłu - taryfa niska (gr/kWh)
- Koszt przesyłu - taryfa wysoka (gr/kWh)

### 6.4. Persistence i storage

System wykorzystuje mechanizmy persystencji Home Assistant do zachowania stanu między restartami:

- **Store** - Zapisywanie skomplikowanych struktur danych
  - Historia decyzji (decision_log)
  - Konfiguracja zaawansowana
  - Cache prognoz

- **Input helpers** - Flagi, daty i parametry liczbowe
  - Automatycznie persystentne w HA
  - Łatwo dostępne w UI

- **Restore state** - Przywracanie stanu sensorów po restarcie HA
  - Ostatnie wartości valley_period, peaks
  - Aktualny mode systemu

### 6.5. Diagnostyka i debugowanie

Integracja dostarcza narzędzia diagnostyczne:

- **Logowanie szczegółowe** (poziom DEBUG) wszystkich decyzji
- **Sensor z historią** ostatnich 10 decyzji wraz z uzasadnieniem
- **Sensor następnej akcji** z czasem wykonania i szczegółami
- **Atrybuty sensorów** zawierające szczegółowe dane wejściowe
- **Serwis diagnostyczny** do testowania pojedynczych modułów
- **Atrybuty state machine** pokazujące możliwe przejścia i warunki

---

## 7. Podsumowanie

### 7.1. Kluczowe decyzje architektoniczne

- **Event-driven architecture** - System reaguje na zdarzenia czasowe i zmiany stanu, nie wymaga ciągłego poolingu

- **Modularność** - Każdy moment akcji zaimplementowany jako osobny moduł, łatwy w testowaniu i rozbudowie

- **Separacja warstw** - Wyraźny podział na Data Layer, Decision Engine i Control Layer

- **State Machine** - Jawne zarządzanie stanami zapewnia przewidywalność i bezpieczeństwo

- **Sterowanie przez encje HA** - Całe sterowanie falownikiem poprzez encje Solarman (number, select, switch), bez bezpośredniego dostępu do Modbus. To zapewnia:
  - Bezpieczeństwo - brak konfliktów z innymi automatyzacjami
  - Czytelność - wszystkie komendy widoczne w historii HA
  - Łatwość debugowania - możliwość ręcznego testowania przez UI
  - Niezależność od implementacji - działa z każdą wersją Solarman

- **Integracja z HA** - Pełne wykorzystanie mechanizmów Home Assistant (coordinator, config_flow, services)

### 7.2. Kolejne kroki implementacji

Sugerowana kolejność implementacji komponentów:

1. Coordinator i podstawowa struktura integracji HACS
2. Data Layer - zbieranie i przetwarzanie danych z istniejących integracji
3. TariffManager, ForecastProcessor, PriceAnalyzer (moduły pomocnicze)
4. DailyAnalysisModule (analiza cen i identyfikacja okien)
5. State Machine i InverterController (sterowanie przez encje HA)
6. Pozostałe moduły Decision Engine (kolejno wg harmonogramu):
   - MorningChargeModule
   - PVBlockingModule
   - ValleyChargeModule
   - PeakSaleModule
   - AfternoonChargeModule
   - EveningBehaviorModule
7. Scheduler i orkiestracja akcji czasowych
8. Sensory, serwisy i konfiguracja UI
9. Testy integracyjne i walidacja algorytmu

### 7.3. Zgodność ze specyfikacją

Niniejsza architektura w pełni implementuje wszystkie wymagania określone w dokumencie "Zasady sterowania magazynem energii - specyfikacja algorytmu", w tym:

- Wszystkie 7 momentów akcji (00:00, 04:00, wschód słońca, dołek, szczyty, 13:00/15:00, 22:00)
- Algorytmy identyfikacji okien cenowych (dołek, szczyty)
- Logikę arbitrażu z uwzględnieniem sprawności 90%
- Konserwatywną strategię minimalizacji kosztów
- Balansowanie magazynu co 10 dni
- Obsługę taryfy G12 z sezonowością
- Wszystkie progi decyzyjne i parametry systemu

### 7.4. Bezpieczeństwo i niezawodność

- **Walidacja danych** na każdym etapie przetwarzania
- **Error handling** z retry i fallback do bezpiecznych wartości
- **State machine** zapobiega niespójnym stanom
- **Limity bezpieczeństwa** (min/max SOC) egzekwowane na poziomie kontrolera
- **Timeout** dla akcji czasowych (automatyczne przejście do NORMAL)
- **Manual override** - możliwość ręcznego wyłączenia automatyki
- **Logging** wszystkich decyzji do analizy post-mortem

---

**Koniec dokumentu**

*Dokument stworzony dla projektu EnergyOptimizer*
*Wersja 1.0 | Styczeń 2026*
