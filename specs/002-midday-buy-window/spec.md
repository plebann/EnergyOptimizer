# Feature Specification: Rozszerzenie Sensorów Okna Najniższej Ceny Sprzedaży

**Feature Branch**: `[002-midday-buy-window]`  
**Created**: 2026-05-07  
**Status**: Draft  
**Input**: User description: "w specyfikacji 002 trzeba wprowadzić zmiany; sensor w tej chwili zachowuje się prawidłowo, ale należy rozbudować jego funkcjonalności; w sensorze wynikowym trzeba dodać atrybut `price`, którego wartością będzie średnia cena z wyznaczonego okienka (w typie float, z 2 miejscami po przecinku, wartość powinna wyrażać PLN/kWh); dodatkowo trzeba dodać analogiczny sensor, ale dla jutrzejszego okienka cenowego; w tym celu zamiast atrybutu `prices_today` należy użyć atrybutu `prices_tomorrow`; reszta zachowania powinna zostać bez zmian"

## Clarifications

### Session 2026-05-07

- Q: Gdy kilka okien 8-kwadransowych ma identyczny najniższy koszt, którą regułę wyboru wynikowego okna mamy przyjąć? → A: Wybierz najwcześniejsze okno.
- Q: Gdy brakuje kompletnych danych do wyznaczenia pełnego okna 8 kwadransów, jaki stan ma przyjmować sensor tekstowy? → A: Stan `unavailable`.
- Q: Do którego dnia ma odnosić się wyznaczane okno 08:00-16:00? → A: Do bieżącego dnia lokalnego.

### Session 2026-05-08

- Q: Na podstawie którego sensora cenowego liczymy wynikowe okno? → A: Wyłącznie na podstawie ceny sprzedaży.
- Q: Jakiego formatu tekstowego używa wynikowy sensor? → A: `HH:MM-HH:MM`.
- Q: Jak traktować dane wejściowe, jeśli sensor ceny sprzedaży udostępnia kolejne pełne godziny zamiast gotowych kwadransów? → A: Każdą godzinę należy rozbić na 4 kolejne kwadranse z tą samą wartością ceny, a długość okna nadal liczyć w kwadransach.

### Session 2026-05-09

- Q: Jak ma być prezentowana średnia cena wybranego okna? → A: Jako dodatkowy atrybut `price`, liczba typu float z dokładnością do 2 miejsc po przecinku, wyrażająca PLN/kWh.
- Q: Czy jutrzejszy sensor ma działać według tych samych reguł co obecny sensor? → A: Tak, z zachowaniem dotychczasowych reguł wyboru, niedostępności i formatu wyniku, ale zasilanymi danymi dla jutra.
- Q: Co ma się stać z atrybutem `price`, gdy odpowiadający sensor jest `unavailable`? → A: Atrybut `price` nie jest wtedy publikowany.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Odczyt najtańszego okna sprzedaży z ceną średnią (Priority: P1)

Użytkownik Home Assistant chce nadal widzieć osobny sensor tekstowy dla najtańszego okna sprzedaży energii w środku dnia, ale dodatkowo potrzebuje od razu średniej ceny tego okna, aby podejmować decyzję bez ręcznego liczenia.

**Why this priority**: To rozszerza już działający wynik o brakującą informację decyzyjną, bez zmiany podstawowego przepływu korzystania z sensora.

**Independent Test**: Przy dostępnych danych ceny sprzedaży dla bieżącego dnia w przedziale 08:00-16:00 użytkownik widzi ten sam poprawnie wyznaczony sensor tekstowy z oknem długości 8 kolejnych kwadransów oraz dodatkowy atrybut ceny średniej dla tego samego okna.

**Acceptance Scenarios**:

1. **Given** dostępne są dane ceny sprzedaży dla kolejnych pełnych godzin środka dnia bieżącego dnia, **When** integracja wyznacza najtańsze okno, **Then** użytkownik widzi istniejący sensor tekstowy z zakresem czasu odpowiadającym najtańszemu ciągłemu oknu długości 8 kwadransów.
2. **Given** najtańsze okno dla bieżącego dnia zostało wyznaczone, **When** użytkownik sprawdza atrybuty sensora wynikowego, **Then** widzi dodatkową wartość `price` równą średniej cenie z tego okna, zapisaną jako liczba float z 2 miejscami po przecinku i interpretowaną jako PLN/kWh.
3. **Given** cena sprzedaży różni się od ceny zakupu, **When** integracja wyznacza bieżące okno środka dnia, **Then** wynik i wartość `price` opierają się wyłącznie na cenie sprzedaży.

---

### User Story 2 - Odczyt analogicznego okna dla jutra (Priority: P2)

Użytkownik chce otrzymać drugi, analogiczny sensor dla jutrzejszego okna cenowego, aby mógł planować działania z wyprzedzeniem bez mieszania danych bieżącego i kolejnego dnia.

**Why this priority**: Rozszerzenie na kolejny dzień daje nową wartość planistyczną, ale opiera się na już istniejącym i zrozumiałym wzorcu działania sensora.

**Independent Test**: Przy dostępnych danych sprzedaży dla jutra użytkownik widzi osobny sensor dla jutrzejszego okna w tym samym formacie oraz z analogicznym atrybutem średniej ceny.

**Acceptance Scenarios**:

1. **Given** dostępne są dane sprzedaży dla jutra, **When** integracja wyznacza jutrzejsze okno środka dnia, **Then** publikuje osobny sensor tekstowy z wynikiem w formacie `HH:MM-HH:MM` dla jutrzejszego przedziału czasu.
2. **Given** jutrzejsze okno zostało wyznaczone, **When** użytkownik sprawdza atrybuty jutrzejszego sensora, **Then** widzi analogiczną wartość `price` obliczoną ze średniej ceny wybranego jutrzejszego okna.
3. **Given** dostępne są zarówno dane bieżące, jak i jutrzejsze, **When** integracja aktualizuje sensory, **Then** każdy sensor korzysta wyłącznie z danych odpowiadających swojemu dniowi i nie nadpisuje wyniku drugiego.

---

### User Story 3 - Zachowanie bez zmian poza nowym zakresem danych (Priority: P3)

Użytkownik chce, aby rozszerzenie nie zmieniło dotychczasowych reguł działania istniejącego sensora i aby oba sensory zachowywały się przewidywalnie przy brakach danych lub remisach.

**Why this priority**: Rozszerzenie funkcjonalności nie może obniżyć wiarygodności już działającego sensora ani wprowadzić niespójności między dniami.

**Independent Test**: Przy niepełnych danych dla dziś lub jutra tylko dotknięty sensor przechodzi w stan `unavailable`, a reguły wyboru najwcześniejszego remisu oraz długości okna pozostają takie same jak wcześniej.

**Acceptance Scenarios**:

1. **Given** dla jednego z dni brakuje danych pozwalających zbudować pełne okno długości 8 kwadransów, **When** integracja próbuje wyznaczyć wynik dla tego dnia, **Then** odpowiedni sensor przechodzi w stan `unavailable` zamiast publikować niepełny wynik.
2. **Given** istnieje więcej niż jedno okno z takim samym najniższym kosztem sprzedaży dla danego dnia, **When** integracja wybiera wynik, **Then** nadal wybiera najwcześniejsze takie okno.
3. **Given** użytkownik porównuje nową wersję bieżącego sensora z poprzednim zachowaniem, **When** pomija nowy atrybut `price`, **Then** czas okna i reguły jego wyboru pozostają niezmienione.

### Edge Cases

- Co dzieje się, gdy średnia cena wybranego okna ma więcej niż 2 miejsca po przecinku? System publikuje wartość `price` zaokrągloną do 2 miejsc po przecinku.
- Co dzieje się, gdy dane sprzedaży dla jutra nie są jeszcze dostępne, ale dane dla dziś są kompletne? Jutrzejszy sensor pozostaje `unavailable`, a bieżący sensor działa bez zmian.
- Co dzieje się, gdy dla dziś i jutra wypada ten sam przedział czasu, ale z inną średnią ceną? Każdy sensor publikuje własny zakres i własną wartość `price` niezależnie od drugiego.
- Co dzieje się, gdy dane wejściowe dla jednego z dni zawierają wartości nienumeryczne albo chwilowo niedostępne? Tylko wynik zależny od tego zestawu danych nie powinien publikować pozornie poprawnej wartości.
- Co dzieje się, gdy sensor dla danego dnia przechodzi w stan `unavailable`? Atrybut `price` nie jest wtedy publikowany, aby nie pozostawiać pozornie poprawnej lub nieaktualnej wartości liczbowej.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST nadal wyznaczać oba wynikowe sensory wyłącznie na podstawie ceny sprzedaży i ignorować cenę zakupu przy obliczaniu okna oraz ceny średniej.
- **FR-002**: System MUST dla każdego dnia szukać jednego ciągłego okna wyłącznie w przedziale 08:00-16:00 czasu lokalnego, o długości dokładnie 8 kolejnych kwadransów.
- **FR-003**: System MUST traktować każdą wejściową pełną godzinę ceny sprzedaży jako 4 kolejne kwadranse z tą samą wartością ceny przy budowaniu kandydatów okna.
- **FR-004**: System MUST pozostawić bez zmian dotychczasowy bieżący sensor tekstowy publikujący wynik dla bieżącego dnia lokalnego w formacie `HH:MM-HH:MM`.
- **FR-005**: System MUST dodać do bieżącego sensora wynikowego dodatkowy atrybut `price`.
- **FR-006**: System MUST wyznaczać wartość `price` jako średnią arytmetyczną ceny sprzedaży ze wszystkich kwadransów należących do wybranego okna.
- **FR-007**: System MUST publikować wartość `price` jako liczbę typu float zaokrągloną do 2 miejsc po przecinku, reprezentującą PLN/kWh.
- **FR-008**: System MUST publikować osobny, analogiczny sensor tekstowy dla jutrzejszego dnia lokalnego, używający tych samych reguł wyboru okna, tego samego formatu tekstowego i analogicznego atrybutu `price`.
- **FR-009**: System MUST wyznaczać sensor jutrzejszy wyłącznie z zestawu danych cenowych przeznaczonego dla jutra, a nie z zestawu danych bieżącego dnia.
- **FR-010**: System MUST aktualizować tylko ten sensor, którego odpowiadający mu zestaw danych cenowych zmienia wynik wyznaczonego okna lub wartość `price`.
- **FR-011**: System MUST ustawiać odpowiedni sensor tekstowy w stanie `unavailable`, jeśli dla odpowiadającego mu dnia brak danych godzinowych nie pozwala po rozbiciu wyznaczyć pełnego okna długości 8 kwadransów.
- **FR-012**: System MUST wybierać najwcześniejsze okno, gdy więcej niż jedno okno ma ten sam najniższy koszt sprzedaży dla danego dnia.
- **FR-013**: System MUST zachować spójność wyniku obu sensorów z lokalnym sposobem prezentacji czasu używanym przez integrację.
- **FR-014**: System MUST nie publikować atrybutu `price`, gdy odpowiadający mu sensor tekstowy jest w stanie `unavailable`.

### Key Entities *(include if feature involves data)*

- **Dzienne Dane Ceny Sprzedaży**: Zestaw cen sprzedaży przypisany do konkretnego dnia lokalnego, z którego każda pełna godzina jest interpretowana jako 4 kolejne kwadranse o tej samej wartości.
- **Okno Środka Dnia**: Ciągły kandydat do oceny mieszczący się całkowicie pomiędzy 08:00 a 16:00 i obejmujący 8 kolejnych kwadransów dla jednego dnia lokalnego.
- **Średnia Cena Okna**: Wartość informacyjna odpowiadająca średniej cenie sprzedaży z wybranego okna środka dnia, prezentowana jako `price` w PLN/kWh.
- **Sensor Dzisiejszego Okna Sprzedaży**: Istniejący wynik tekstowy pokazujący wybrany przedział czasu dla bieżącego dnia oraz jego średnią cenę.
- **Sensor Jutrzejszego Okna Sprzedaży**: Nowy wynik tekstowy pokazujący wybrany przedział czasu dla kolejnego dnia oraz jego średnią cenę.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Przy kompletnych danych sprzedaży dla bieżącego dnia użytkownik otrzymuje ten sam zakres czasu co wcześniej oraz dodatkową wartość `price`, bez potrzeby wykonywania ręcznych obliczeń średniej.
- **SC-002**: W 100% przypadków wartość `price` odpowiada średniej arytmetycznej z wybranego okna i jest prezentowana z dokładnością do 2 miejsc po przecinku.
- **SC-003**: Przy kompletnych danych sprzedaży dla jutra użytkownik otrzymuje osobny sensor dla jutrzejszego okna wraz z analogiczną wartością `price` przed rozpoczęciem tego dnia.
- **SC-004**: W 100% przypadków niewystarczających danych tylko sensor zależny od niekompletnego zestawu przechodzi w stan `unavailable` i nie publikuje pozornie poprawnego zakresu czasu ani ceny średniej.
- **SC-005**: W 100% przypadków zmiana wyłącznie ceny zakupu nie zmienia ani wyznaczonego okna, ani wartości `price` dla żadnego z wynikowych sensorów.
- **SC-006**: W 100% przypadków, gdy sensor dla danego dnia jest `unavailable`, atrybut `price` nie występuje w opublikowanym stanie tego sensora.

## Assumptions

- W integracji istnieją odrębne zestawy danych cen sprzedaży dla bieżącego dnia i dla jutra.
- Dotychczasowe reguły wyboru okna, rozstrzygania remisów, długości okna i stanu `unavailable` pozostają poprawne i mają zostać zachowane bez zmian.
- Średnia cena okna jest liczona jako średnia arytmetyczna ze wszystkich 8 kwadransów należących do wybranego okna.
- Dane ceny sprzedaży dla obu dni są dostępne dla kolejnych pełnych godzin w przedziale 08:00-16:00 i mogą zostać rozbite na 4 kolejne kwadranse o tej samej wartości ceny.
- Oba sensory korzystają z tego samego lokalnego sposobu prezentacji czasu używanego już przez integrację.
