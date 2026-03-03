# Sprzedaż w szczycie porannym — Opis akcji

## Cel

Sprzedaż nadwyżki energii z magazynu w oknie porannego szczytu cenowego, gdy bateria dysponuje
energią powyżej poziomu niezbędnego do pokrycia zapotrzebowania do godziny wystarczalności PV
(lub końca taryfy dziennej).

Akcja operuje **jedną gałęzią** — nie rozgałęzia się po cenie jak akcja wieczorna. Warunkiem
sprzedaży jest wyłącznie istnienie nadwyżki energetycznej i możliwość obniżenia SOC poniżej
aktualnego poziomu.

## Wyzwalacz

- Godzina z sensora porannego szczytu cenowego: `morning_max_price_hour_sensor` (domyślnie 07:00)
- Możliwość ręcznego wywołania przez serwis `energy_optimizer.morning_peak_sell`

## Wejścia (koncepcyjne)

- Aktualny SOC baterii i parametry magazynu (pojemność, napięcie, sprawność)
- Polityki SOC (limity minimalne/maksymalne)
- Docelowy SOC programu 3 (rozładowanie do sieci)
- Cena porannego szczytu (`morning_max_price_sensor`)
- Minimalna cena arbitrażu (`min_arbitrage_price`, PLN/MWh) — **logowana, nie blokuje** akcji
- Przewidywane zużycie energii w oknie od teraz+1h do końca taryfy dziennej:
  - Zużycie domowe (z czujników w okienkach 4-godzinnych)
  - Zużycie Pompy Ciepła (integracja zewnętrzna)
- Przewidywana produkcja PV (Solcast) z kompensacją prognozy i efektywnością PV
- Straty dzienne falownika
- Margines bezpieczeństwa (domyślnie 1.1 = +10%)
- Sensor godziny końca taryfy dziennej: `tariff_end_hour_sensor` (domyślnie 13:00)
- Encja trybu pracy falownika (`work_mode_entity`)
- Encja limitu mocy eksportu (`export_power_entity`)
- Tryb testowy sprzedaży (`test_sell_mode`)

## Przebieg decyzji (wysoki poziom)

1. **Walidacja wejść**: SOC baterii i encja Prog3 SOC muszą być dostępne; brak ceny porannej → wyjście bez akcji.
2. **Obliczenie okna**: `start = now+1h`, `end = tariff_end_hour`.
3. **Zebranie prognoz**: zużycie domowe, HP, PV (z kompensacją), straty — dla okna godzinowego.
4. **Model Sufficiency Window**:
   - Szukaj pierwszej godziny (`sufficiency_hour`), gdy prognoza PV pokrywa godzinowe zapotrzebowanie.
   - Jeśli `sufficiency_reached = True`: oblicz `required_kwh` i `pv_kwh` tylko do `sufficiency_hour`.
   - Jeśli `sufficiency_reached = False`: użyj pełnego okna do `tariff_end_hour`.
5. **Obliczenie nadwyżki**: `surplus = max(reserve_kwh + pv_forecast_kwh - required_kwh, 0)`.
6. **Brak nadwyżki** → `no_action`.
7. **Obliczenie target SOC**: `max(current_soc - kwh_to_soc(surplus), min_soc)`.
8. **target SOC >= current SOC** → `no_action` (nie ma czego rozładowywać).
9. **Obliczenie export_power** i zapis do falownika (poza test mode) → sprzedaż zaplanowana.

## Diagram (Mermaid)

```mermaid
flowchart TD
  MS_start([Run morning peak sell]) --> MS_forecasts[Collect forecasts: now+1h to tariff_end]
  MS_no_action[No action]

  MS_forecasts --> MS_suff{Sufficiency reached?}
  MS_suff -->|yes| MS_suff_window[required/pv: sums until sufficiency_hour]
  MS_suff -->|no| MS_full_window[required/pv: full-window sums]

  MS_suff_window --> MS_base_surplus{Base surplus > 0?}
  MS_full_window --> MS_base_surplus
  MS_base_surplus -->|no| MS_no_action
  MS_base_surplus -->|yes| MS_space{Base surplus > free_space?}

  MS_space -->|yes| MS_price{Morning price > evening price?}
  MS_price -->|yes| MS_sel_base[select_surplus = base surplus]
  MS_price -->|no| MS_sel_fit[select_surplus = free_space minus base surplus; floor at 0]

  MS_space -->|no| MS_to22[Compute surplus to 22:00]
  MS_to22 --> MS_to22_gate{surplus_to_22 > free_space?}
  MS_to22_gate -->|no| MS_no_action
  MS_to22_gate -->|yes| MS_sel_22[select_surplus = smaller of base surplus and surplus_to_22 minus free_space]

  MS_sel_base --> MS_sel_check{selected surplus > 0?}
  MS_sel_fit --> MS_sel_check
  MS_sel_22 --> MS_sel_check
  MS_sel_check -->|no| MS_no_action
  MS_sel_check -->|yes| MS_target[Calculate target_soc and export_power]

  MS_target --> MS_target_check{target_soc < current_soc?}
  MS_target_check -->|no| MS_no_action
  MS_target_check -->|yes| MS_sell[Sell scheduled]
```

### Szczegóły decyzyjne

**Model Sufficiency Window:**

Zamiast stałego okna do `tariff_end_hour`, algorytm wyznacza punkt, od którego PV
samo pokryje godzinowe zapotrzebowanie:

1. Dla każdej godziny `h` w oknie oblicz: `demand[h] = (usage[h] + hp[h] + losses_hourly) × margin`.
2. Znajdź pierwszą godzinę `sufficiency_hour`, dla której `pv_forecast[h] >= demand[h]`.
3. Jeśli `sufficiency_reached`:
   - `required_kwh = Σ demand[h]` dla `h < sufficiency_hour`
   - `pv_forecast_kwh = Σ pv_forecast[h]` dla `h < sufficiency_hour`
4. Jeśli nie: użyj sum dla całego okna.

Cel modelu: energia potrzebna jest jedynie do momentu, gdy PV zacznie samo pokrywać
zapotrzebowanie — każda kWh powyżej tej granicy to nadwyżka do sprzedaży.

**Nadwyżka energii:**
- Formula: `surplus_kwh = max(reserve_kwh + pv_forecast_kwh - required_kwh, 0)`
- `reserve_kwh = (current_soc - min_soc) / 100 × capacity_ah × voltage / 1000 × efficiency`

**Brak clampu do produkcji PV:**
- W przeciwieństwie do akcji wieczornej, morning sell **nie ogranicza** nadwyżki do wartości
  `pv_production_sensor`. O poranku dzienna produkcja PV jeszcze nie jest miarodajnym wskaźnikiem.

**Rola ceny i progu arbitrażu:**
- Cena poranna (`morning_max_price_sensor`) jest **wymagana** — brak → wyjście bez akcji.
- `min_arbitrage_price` jest **logowany** do danych decyzji jako `threshold_price`.
- Cena **nie blokuje** sprzedaży — brak rozgałęzienia `price > threshold`.
- Jedyne warunki aktywacji eksportu: `surplus_kwh > 0` ORAZ `target_soc < current_soc`.

**Docelowy SOC:**
- Formula: `target_soc = max(current_soc - kwh_to_soc(surplus_kwh), min_soc)`
- Zaokrąglany w górę do pełnego procentu przed zapisem do encji.

**Moc eksportu:**
- Formula: `round((surplus_kwh × 1000 + 250) / 100) × 100` W.
- Minimum: 100 W.

**Godzina przywrócenia (restore_hour):**
- `restore_hour = (morning_max_price_hour + 1) % 24`
- Domyślnie: sell_hour = 7 → restore o 8:00.

## Wpływ na maszynę stanów

- NORMAL → SELLING_TO_GRID dla akcji `sell`, gdy aktywowany jest eksport energii (`Export First`)
  i ustawiony docelowy SOC programu 3.

## Efekty sterowania (koncepcyjne)

- Ustawienie trybu pracy falownika na `Export First`
- Zapis danych przywrócenia (`sell_restore`) do pamięci runtime i trwałego storage HA:
  - Oryginalny tryb pracy, encja i wartość Prog3 SOC, `restore_hour`, `sell_type = "morning"`
- Ustawienie docelowego SOC programu 3
- Ustawienie limitu mocy eksportu
- W trybie testowym (`test_sell_mode`) wyłącznie logowanie decyzji bez zapisu do falownika

## Obsługa błędów

- Brak SOC baterii lub encji Prog3 SOC → zakończenie na etapie walidacji wejścia
- Brak ceny porannej (`morning_max_price_sensor`) → wyjście bez akcji i log z powodem
- Brak `tariff_end_hour_sensor` → fallback do 13:00 (z logiem warning)
- Brak `morning_max_price_hour_sensor` → fallback do 7:00 (z logiem warning); restore_hour = 8
- Brak prognozy PV / serwisu HP / strat → przyjmowane wartości 0 zgodnie z helperami
- Nadwyżka = 0 → `no_action` z logiem powodu
- `target_soc >= current_soc` → `no_action` z logiem „target SOC does not require discharge"

## Logowanie i powiadomienia

- Zaloguj typ decyzji: `sell` / `no_action`
- Zaloguj kluczowe parametry: `current_soc`, `target_soc`, `surplus_kwh`, `export_power_w`,
  `morning_price`, `threshold_price`
- Zaloguj parametry okna: `start_hour`, `end_hour`, `reserve_kwh`, `required_kwh`,
  `pv_forecast_kwh`, `heat_pump_kwh`, `losses_kwh`
- Dodaj informacje o sufficiency: `sufficiency_hour`, `sufficiency_reached`
- Dodaj informację o `test_sell_mode`
- Użyj ujednoliconego systemu logowania `log_decision_unified`
