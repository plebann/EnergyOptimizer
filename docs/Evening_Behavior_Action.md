# Zachowanie wieczorne (22:00) — Opis akcji

## Cel

Zapobieganie nieefektywnemu rozładowaniu magazynu w nocy oraz wymuszenie pełnego balansowania, gdy jest wymagane.

## Wyzwalacz

- Stała godzina harmonogramu: 22:00

## Wejścia (koncepcyjne)

- Sprawdzenie flagi balansowania oraz kiedy została ustawiona
- Prognoza PV na jutro (po korekcie sprawności)
- Aktualna prognoza PV i bieżąca produkcja PV (do aktualizacji sensora kompensacji)
- Aktualny SOC i dostępna pojemność
- Polityki SOC (limity minimalne/maksymalne)
- Przewidywane zapotrzebowanie na energię elektryczną
- Flagi włączenia systemu i trybów ręcznych

## Przebieg decyzji (wysoki poziom)

1. **Sprawdzenie potrzeby balansowania**: Czy flaga balansowania jest ustawiona oraz kiedy została ustawiona
1a. **Aktualizacja sensora kompensacji PV**: Przepisz wartości „dzisiaj” do „wczoraj”, zapisz bieżącą prognozę i produkcję PV jako „dzisiaj”, zaktualizuj wartość sensora.
2. **Balansowanie wymagane**: Wejdź w tryb balansowania i ustaw cel pełnego SOC (100%) na noc (czyli program 6, 1 i 2)
3. **Balansowanie niewymagane**: Oceń zapas energii w magazynie w porównaniu z przewidywanym zapotrzebowaniem oraz prognozą PV na następny dzień.
4. **Niewystarczający zapas energii w magazynie**: Zamroź SOC, aby uniknąć rozładowania w nocy (ustaw minimalny SOC równy bieżącemu SOC w programie 6 i 1).
5. **W pozostałych przypadkach**: Przywróć tryb normalny i ustaw docelowy minimalny SOC w programie 6, 1 i 2.

### Szczegóły decyzyjne
1. Sprawdzanie potrzeby balansowania.
Jeżeli jest ustawiona flaga balansowania oznacza, że mamy priorytet balansowania. Żeby określić, czy należy uruchomić balansowanie, należy sprawdzić:
- czy minęło więcej niż 2 dni od ustawienia flagi balansowania?
-- jeżeli tak, bezwarunkowo balansowanie jest wymagane
-- jeżeli nie, sprawdź, czy magazyn ma szansę się naładować jutro z produkcji PV. Aby to określić porównaj przewidywane zapotrzebowanie na energię elektryczną z prognozą produkcji PV oraz pojemnością magazynu
2. Ocena zapasu energii.
W tym celu należy po pierwsze sprawdzić, kiedy wypada godzina niezależności PV. Niezależność PV oznacza, że w danej godzinie będzie większa prognozowana skorygowana produkcja PV niż przewidywane zapotrzebowanie na energię w tej godzinie.
Jeżeli w dniu następnym takiej godziny nie istnieje (zapotrzebowanie przekracza produkcję) - mamy niewystarczający zapas energii.
Jeżeli taka godzina została określona, sumujemy zapotrzebowanie na energię elektryczną od godziny 22 do tej wyliczonej godziny. Od tej wartości odejmujemy prognozowaną skorygowaną produkcję PV oraz dostępną energię w magazynie (zawsze energię użyteczną, tj. przy założeniu rozładowania do poziomu MinSOC). Jeżeli liczba jest większa od zera (niedobór energii) mamy niewystarczający zapas energii. W przeciwnym razie możemy ustawić tryb normalny i używać energii z magazynu na potrzeby domu (optymalizacja kosztów dystrybucji).

## Wpływ na maszynę stanów

- NORMAL → BALANCING, gdy balansowanie jest wymagane (flaga balansowania ustawiona + warunki czasowe lub prognozy PV).
- NORMAL → RUNNING_FROM_GRID, gdy wymagane jest zamrożenie SOC w celu uniknięcia rozładowania.
- BALANCING → NORMAL po osiągnięciu docelowego SOC (lub po porannym cut-off).
- RUNNING_FROM_GRID → NORMAL po porannym cut-off.

## Efekty sterowania (koncepcyjne)

- Ustaw tryb pracy falownika pod bezpieczne zachowanie nocne.
- Ustaw cele SOC programów dla balansowania (program 6 oraz odzwierciedlony program 1, jeśli potrzebne).
- Włącz lub wyłącz ładowanie z sieci zgodnie z decyzją.
- Przy zamrożeniu SOC ustaw minimalny SOC równy bieżącemu SOC, aby zablokować rozładowanie.

## Logowanie i powiadomienia

- Zaloguj typ decyzji: balansowanie / praca z sieci / normalny.
- Zapisz kluczowe wejścia (dni od ostatniego balansowania, prognoza PV, SOC).
- Podaj krótkie uzasadnienie widoczne dla użytkownika.
