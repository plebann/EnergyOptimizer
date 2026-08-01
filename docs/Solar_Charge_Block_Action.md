# Solar Charge Block — opis akcji

## Cel

`Solar Charge Block` opóźnia ładowanie baterii z PV, gdy eksport energii
słonecznej nadal ma wysoką wartość. Akcja chroni jednocześnie przed sytuacją,
w której prognozowana nadwyżka PV nie zmieści się później w baterii.

Jedynym efektem sterującym akcji jest zmiana maksymalnego prądu ładowania:

- `0 A`, gdy ładowanie ma pozostać zablokowane;
- `DEFAULT_MAX_CHARGE_CURRENT`, gdy ładowanie ma zostać przywrócone.

Akcja nie zmienia trybu pracy falownika, nie zapisuje SOC aktywnego programu
i nie korzysta z `min_soc_pv`. Nie uruchamia ani nie wspiera Forced Battery
Discharge — energia już zgromadzona w baterii nie jest sprzedawana przez tę
akcję.

## Wyzwalanie

- Scheduler uruchamia kontrolę co godzinę o `:01` w czasie dnia.
- Akcję można uruchomić ręcznie przez serwis
  `energy_optimizer.solar_charge_block`.
- Guardy biznesowe znajdują się w samej logice decyzji, dlatego wywołanie
  ręczne i harmonogram zachowują się tak samo.
- Przed początkiem Morning Sell Window akcja nie wykonuje żadnej zmiany.

## Dane wejściowe

- bieżąca cena sprzedaży z `sell_price_sensor`;
- cena i czas początku wewnętrznego sensora Morning Sell Window;
- cena wewnętrznego sensora Midday Avoidance Window
  (`midday_sell_window`, z dotychczasowym fallbackiem ceny);
- prognoza PV od bieżącej godziny do zachodu słońca;
- prognoza PV dla bieżącej godziny;
- wolne miejsce w baterii z `battery_space_sensor`;
- lokalne zapotrzebowanie w bieżącej godzinie;
- encja `max_charge_current_entity`.

Brak wymaganej ceny, prognozy PV, czasu zachodu lub informacji o wolnym
miejscu w baterii powoduje pominięcie akcji bez zmiany falownika.

## Próg ceny

Dynamiczny próg odblokowania jest liczony na podstawie ceny Morning Sell
Window i ceny Midday Avoidance Window:

```text
threshold = midday_avoidance_price
            + 0.2 * (morning_sell_price - midday_avoidance_price)
```

Reguła działa bez dodatkowych wyjątków również wtedy, gdy cena Midday
Avoidance Window wynosi zero albo jest ujemna.

- `current_sell_price < threshold` → przywróć domyślny maksymalny prąd
  ładowania;
- `current_sell_price >= threshold` → sprawdź guardy pojemności i bieżącej
  nadwyżki PV.

## Guardy PV

Blokada jest aktywowana tylko wtedy, gdy oba warunki są prawdziwe:

1. prognozowana nadwyżka PV do zachodu słońca przekracza wolne miejsce
   w baterii;
2. prognoza PV w bieżącej godzinie przekracza lokalne zapotrzebowanie
   uwzględniające zużycie domu, pompę ciepła, straty i margines `1.1`.

Jeśli którykolwiek ze znanych warunków ceny lub PV staje się fałszywy po
rozpoczęciu Morning Sell Window, akcja przywraca
`DEFAULT_MAX_CHARGE_CURRENT`.

## Przebieg decyzji

```mermaid
flowchart TD
  start["Run Solar Charge Block"] --> morning{"Morning Sell Window started?"}
  morning -->|No| skip_before["Skip without changes"]
  morning -->|Yes| data{"Required data available?"}
  data -->|No| skip_missing["Skip without changes"]
  data -->|Yes| price{"Current sell price >= threshold?"}
  price -->|No| restore["Restore default max charge current"]
  price -->|Yes| capacity{"PV surplus > free battery space?"}
  capacity -->|No| restore
  capacity -->|Yes| hourly{"Current-hour PV > demand?"}
  hourly -->|No| restore
  hourly -->|Yes| block["Set max charge current to 0 A"]
```

## Przywrócenie i bezpieczeństwo

Solar Charge Block sam przywraca domyślny prąd ładowania, gdy znane warunki
blokady przestają być spełnione. Istniejąca akcja Midday Avoidance Window
restore pozostaje dodatkową ochroną na wypadek pominięcia kontroli godzinowej.

Brak danych nie jest traktowany jako fałszywy warunek: w takim przypadku nie
jest wykonywane ani blokowanie, ani przywrócenie.

## Logowanie

Logi rozróżniają:

- pominięcie przed Morning Sell Window;
- pominięcie z powodu brakujących danych;
- przywrócenie z powodu ceny, pojemności lub bieżącego bilansu PV;
- blokadę wraz z cenami, progiem i wartościami guardów PV.
