# Feature Specification: Rozszerzenie Sensorów Okna Najniższej Ceny Sprzedaży

**Feature Branch**: `[002-midday-buy-window]`  
**Created**: 2026-05-07  
**Last Modified**: 2026-06-01  
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

### Session 2026-06-01

- Q: Jak traktować cenę sprzedaży poniżej 0,05 PLN/kWh? → A: Traktować jako 0 PLN/kWh przed jakimikolwiek obliczeniami okna.
- Q: Jak wyznaczać okno, gdy danego dnia w przedziale 08:00-16:00 wystąpią godziny z ceną zerową i ich liczba przekracza 2? → A: Okno obejmuje wszystkie godziny z ceną zerową (nadal w ramach 08:00-16:00), zamiast stosować standardową długość 8 kwadransów.
- Q: Jak wyznaczać okno, gdy liczba godzin zerowych wynosi 2 lub mniej? → A: Stosować standardowy algorytm wyboru okna o długości 8 kwadransów (ceny zerowe są wtedy po prostu najtańszymi kandydatami).
- Q: Jaki atrybut ma zostać dodany do sensora dzisiejszego okna? → A: Atrybut `is_active` zwracający `on`, gdy bieżący czas lokalny mieści się pomiędzy godziną rozpoczęcia a zakończenia okna, lub `off` w pozostałych przypadkach. Atrybut nie jest publikowany, gdy sensor jest `unavailable`.
- Q: Czy sensor jutrzejszy również otrzymuje atrybut `is_active`? → A: Nie, atrybut `is_active` dotyczy wyłącznie sensora dzisiejszego.
- Q: Jak wyznaczyć zakres tekstowy okna, gdy godziny zerowe w przedziale 08:00-16:00 są nieciągłe (np. 09:00 i 11:00 są zerowe, ale 10:00 nie)? → A: Okno rozciąga się od początku najwcześniejszej godziny zerowej do końca najpóźniejszej, obejmując przerwy z niezerowymi cenami (np. wynik: `09:00-12:00`).
- Q: Czy FR-002 (długość okna dokładnie 8 kwadransów) obowiązuje również w trybie zerowym (FR-016)? → A: Okno ma zawsze minimum 8 kwadransów; w trybie zerowym (ponad 2 godziny zerowe) jest rozszerzane powyżej 8 kwadransów — FR-002 wyznacza podłogę, FR-016 nadpisuje górną granicę.
- Q: Kiedy jest wyliczany atrybut `is_active` sensora dzisiejszego? → A: Wyłącznie przy aktualizacji danych cenowych (data-driven); nie jest wymagany osobny timer czasowy.
- Q: W trybie zerowym okno może obejmować przerwy z niezerowymi cenami — czy atrybut `price` uwzględnia kwadranse przerw? → A: Tak, `price` jest średnią arytmetyczną ze wszystkich kwadransów w oknie, w tym kwadransów przerw (które mogą mieć wartość większą niż 0 po normalizacji progu).
- Q: Kiedy sensor ma być `unavailable` w trybie zerowym (ponad 2 godziny zerowe)? → A: Tylko gdy w przedziale 08:00-16:00 brak jakichkolwiek danych cenowych dla danego dnia.

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

---

### User Story 4 - Obsługa dni z zerową ceną sprzedaży (Priority: P1)

Użytkownik Home Assistant chce, aby w dniach, gdy ceny sprzedaży są bardzo niskie lub zerowe, system prawidłowo identyfikował okno obejmujące wszystkie tanio wycenione godziny, zamiast sztucznie ograniczać je do standardowych 2 godzin.

**Why this priority**: Ceny zerowe lub bliskie zeru mogą wystąpić na rynku energii i wymagają odrębnej logiki wyznaczania okna, aby decyzje o ładowaniu baterii były optymalne.

**Independent Test**: Przy dniu z 4 godzinami cen zerowych (po zastosowaniu progu 0,05 PLN/kWh) w przedziale 08:00-16:00 sensor wyznacza okno obejmujące wszystkie 4 godziny, a nie tylko 2.

**Acceptance Scenarios**:

1. **Given** dane sprzedaży zawierają godziny z ceną poniżej 0,05 PLN/kWh, **When** integracja przetwarza dane wejściowe, **Then** wszystkie ceny poniżej 0,05 PLN/kWh są traktowane jako 0 przed wyznaczaniem okna.
2. **Given** w przedziale 08:00-16:00 danego dnia są 3 lub więcej godzin z ceną zerową (po zastosowaniu progu), **When** integracja wyznacza okno środka dnia, **Then** okno obejmuje wszystkie te godziny, a nie tylko 8 kwadransów.
3. **Given** w przedziale 08:00-16:00 danego dnia są 2 lub mniej godzin z ceną zerową (po zastosowaniu progu), **When** integracja wyznacza okno środka dnia, **Then** stosuje standardowy algorytm wyboru okna o długości 8 kwadransów (traktując godziny zerowe jako najtańsze kandydatury).
4. **Given** żaden dzień nie ma godzin z ceną zerową, **When** integracja wyznacza okno środka dnia, **Then** stosuje standardowy algorytm wyboru okna o długości 8 kwadransów bez żadnych zmian.

---

### User Story 5 - Atrybut `is_active` w sensorze dzisiejszego okna (Priority: P2)

Użytkownik Home Assistant chce wiedzieć na bieżąco, czy trwa teraz wyznaczone okno najtańszej sprzedaży, bez konieczności porównywania aktualnej godziny z zakresem tekstowym.

**Why this priority**: Atrybut `is_active` umożliwia bezpośrednie użycie sensora w automatyzacjach i dashboardach bez dodatkowych szablonów porównujących czas.

**Independent Test**: O godzinie 10:30, gdy wyznaczone okno to `10:00-12:00`, atrybut `is_active` sensora dzisiejszego zwraca `on`. O godzinie 13:00 zwraca `off`.

**Acceptance Scenarios**:

1. **Given** sensor dzisiejszego okna ma wyznaczony zakres, **When** bieżący czas lokalny mieści się pomiędzy godziną rozpoczęcia a zakończenia okna, **Then** atrybut `is_active` zwraca `on`.
2. **Given** sensor dzisiejszego okna ma wyznaczony zakres, **When** bieżący czas lokalny leży poza zakresem okna, **Then** atrybut `is_active` zwraca `off`.
3. **Given** sensor dzisiejszego okna jest w stanie `unavailable`, **When** użytkownik sprawdza atrybuty sensora, **Then** atrybut `is_active` nie jest publikowany.
4. **Given** sensor jutrzejszego okna ma wyznaczony zakres, **When** użytkownik sprawdza atrybuty sensora jutrzejszego, **Then** atrybut `is_active` nie jest dostępny (dotyczy tylko sensora dzisiejszego).

### Edge Cases

- Co dzieje się, gdy średnia cena wybranego okna ma więcej niż 2 miejsca po przecinku? System publikuje wartość `price` zaokrągloną do 2 miejsc po przecinku.
- Co dzieje się, gdy dane sprzedaży dla jutra nie są jeszcze dostępne, ale dane dla dziś są kompletne? Jutrzejszy sensor pozostaje `unavailable`, a bieżący sensor działa bez zmian.
- Co dzieje się, gdy dla dziś i jutra wypada ten sam przedział czasu, ale z inną średnią ceną? Każdy sensor publikuje własny zakres i własną wartość `price` niezależnie od drugiego.
- Co dzieje się, gdy dane wejściowe dla jednego z dni zawierają wartości nienumeryczne albo chwilowo niedostępne? Tylko wynik zależny od tego zestawu danych nie powinien publikować pozornie poprawnej wartości.
- Co dzieje się, gdy sensor dla danego dnia przechodzi w stan `unavailable`? Atrybut `price` nie jest wtedy publikowany, aby nie pozostawiać pozornie poprawnej lub nieaktualnej wartości liczbowej.
- Co dzieje się, gdy ceny w przedziale 08:00-16:00 mają wartości poniżej 0,05 PLN/kWh, ale nie wszystkie wynoszą 0? System najpierw sprowadza wszystkie wartości poniżej 0,05 do zera, a następnie stosuje regułę zerowych godzin.
- Co dzieje się, gdy liczba godzin zerowych wynosi dokładnie 2? System stosuje standardowe okno 8 kwadransów (reguła rozszerzonego okna wymaga ściśle więcej niż 2 godziny).
- Co dzieje się, gdy liczba godzin zerowych wynosi 3 lub więcej? Okno rozciąga się od początku najwcześniejszej zerowej godziny do końca najpóźniejszej zerowej godziny w przedziale 08:00-16:00, obejmując przerwy z niezerowymi cenami (np. przy godzinach zerowych 09:00 i 11:00 wynik to `09:00-12:00`).
- Co dzieje się, gdy dla dnia objętego trybem zerowym w przedziale 08:00-16:00 nie ma żadnych danych cenowych? Sensor dla tego dnia przechodzi w stan `unavailable`.
- Co dzieje się z atrybutem `is_active` sensora dzisiejszego, gdy sensor jest `unavailable`? Atrybut `is_active` nie jest wtedy publikowany.
- Co dzieje się z atrybutem `is_active` sensora jutrzejszego? Sensor jutrzejszy nie posiada atrybutu `is_active`.
- Co dzieje się z atrybutem `is_active` dokładnie w momencie startu lub końca okna? Graniczne momenty (godzina startu włącznie, godzina końca wyłącznie) rozstrzygane są tak, aby wynik był przewidywalny i spójny z formatem `HH:MM-HH:MM`.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST nadal wyznaczać oba wynikowe sensory wyłącznie na podstawie ceny sprzedaży i ignorować cenę zakupu przy obliczaniu okna oraz ceny średniej.
- **FR-002**: System MUST dla każdego dnia wyznaczać okno o długości co najmniej 8 kolejnych kwadransów, wyłącznie w przedziale 08:00-16:00 czasu lokalnego; w trybie standardowym okno ma długość dokładnie 8 kwadransów, a w trybie zerowym (FR-016) może być dłuższe.
- **FR-003**: System MUST traktować każdą wejściową pełną godzinę ceny sprzedaży jako 4 kolejne kwadranse z tą samą wartością ceny przy budowaniu kandydatów okna.
- **FR-004**: System MUST pozostawić bez zmian dotychczasowy bieżący sensor tekstowy publikujący wynik dla bieżącego dnia lokalnego w formacie `HH:MM-HH:MM`.
- **FR-005**: System MUST dodać do bieżącego sensora wynikowego dodatkowy atrybut `price`.
- **FR-006**: System MUST wyznaczać wartość `price` jako średnią arytmetyczną ceny sprzedaży ze wszystkich kwadransów należących do wybranego okna, w tym kwadransów przerw w trybie zerowym (kwadranse obejmowane przez span okna, lecz z niezerową ceną, są wliczane do średniej).
- **FR-007**: System MUST publikować wartość `price` jako liczbę typu float zaokrągloną do 2 miejsc po przecinku, reprezentującą PLN/kWh.
- **FR-008**: System MUST publikować osobny, analogiczny sensor tekstowy dla jutrzejszego dnia lokalnego, używający tych samych reguł wyboru okna, tego samego formatu tekstowego i analogicznego atrybutu `price`.
- **FR-009**: System MUST wyznaczać sensor jutrzejszy wyłącznie z zestawu danych cenowych przeznaczonego dla jutra, a nie z zestawu danych bieżącego dnia.
- **FR-010**: System MUST aktualizować tylko ten sensor, którego odpowiadający mu zestaw danych cenowych zmienia wynik wyznaczonego okna lub wartość `price`.
- **FR-011**: System MUST ustawiać odpowiedni sensor tekstowy w stanie `unavailable` w trybie standardowym (FR-017), jeśli dla odpowiadającego mu dnia brak danych godzinowych nie pozwala po rozbiciu wyznaczyć pełnego okna długości 8 kwadransów.
- **FR-012**: System MUST wybierać najwcześniejsze okno, gdy więcej niż jedno okno ma ten sam najniższy koszt sprzedaży dla danego dnia.
- **FR-013**: System MUST zachować spójność wyniku obu sensorów z lokalnym sposobem prezentacji czasu używanym przez integrację.
- **FR-014**: System MUST nie publikować atrybutu `price`, gdy odpowiadający mu sensor tekstowy jest w stanie `unavailable`.
- **FR-015**: System MUST traktować każdą cenę sprzedaży poniżej 0,05 PLN/kWh jako 0 PLN/kWh przed wyznaczaniem okna środka dnia (dotyczy obu sensorów: dzisiejszego i jutrzejszego).
- **FR-016**: System MUST, gdy w przedziale 08:00-16:00 danego dnia liczba godzin z ceną zerową (po zastosowaniu progu z FR-015) przekracza 2, wyznaczać okno jako zakres od początku najwcześniejszej godziny zerowej do końca najpóźniejszej godziny zerowej w tym przedziale (obejmując ewentualne przerwy z niezerowymi cenami); wynikowe okno ma długość co najmniej 8 kwadransów.
- **FR-017**: System MUST, gdy liczba godzin z ceną zerową wynosi 2 lub mniej, stosować standardowy algorytm wyboru okna o długości dokładnie 8 kwadransów, traktując godziny zerowe jako najtańszych kandydatów.
- **FR-018**: System MUST dodać atrybut `is_active` do sensora dzisiejszego okna, zwracający `on` gdy bieżący czas lokalny mieści się pomiędzy godziną rozpoczęcia (włącznie) a godziną zakończenia (wyłącznie) wyznaczonego okna, lub `off` w pozostałych przypadkach; wartość ta jest przeliczana wyłącznie przy aktualizacji danych cenowych (bez osobnego timera).
- **FR-019**: System MUST nie publikować atrybutu `is_active`, gdy sensor dzisiejszego okna jest w stanie `unavailable`.
- **FR-020**: System MUST nie dodawać atrybutu `is_active` do sensora jutrzejszego okna.
- **FR-021**: System MUST w trybie zerowym (FR-016) ustawiać odpowiedni sensor tekstowy w stanie `unavailable` wyłącznie wtedy, gdy w przedziale 08:00-16:00 brak jakichkolwiek danych cenowych dla odpowiadającego dnia.

### Key Entities *(include if feature involves data)*

- **Dzienne Dane Ceny Sprzedaży**: Zestaw cen sprzedaży przypisany do konkretnego dnia lokalnego, z którego każda pełna godzina jest interpretowana jako 4 kolejne kwadranse o tej samej wartości.
- **Okno Środka Dnia**: Zakres czasu mieszczący się całkowicie pomiędzy 08:00 a 16:00 dla jednego dnia lokalnego; w trybie standardowym obejmuje dokładnie 8 kolejnych kwadransów, a w trybie zerowym obejmuje span od najwcześniejszej do najpóźniejszej godziny zerowej (co najmniej 8 kwadransów).
- **Średnia Cena Okna**: Wartość informacyjna odpowiadająca średniej cenie sprzedaży z wybranego okna środka dnia, prezentowana jako `price` w PLN/kWh.
- **Sensor Dzisiejszego Okna Sprzedaży**: Istniejący wynik tekstowy pokazujący wybrany przedział czasu dla bieżącego dnia oraz jego średnią cenę i atrybut aktywności `is_active`.
- **Sensor Jutrzejszego Okna Sprzedaży**: Nowy wynik tekstowy pokazujący wybrany przedział czasu dla kolejnego dnia oraz jego średnią cenę (bez atrybutu `is_active`).
- **Próg Ceny Zerowej**: Wartość graniczna 0,05 PLN/kWh, poniżej której cena sprzedaży jest sprowadzana do 0 przed obliczeniami okna.
- **Rozszerzone Okno Zerowe**: Okno środka dnia wyznaczane jako zakres od początku najwcześniejszej godziny zerowej do końca najpóźniejszej godziny zerowej w przedziale 08:00-16:00, stosowane gdy liczba takich godzin przekracza 2; może obejmować przerwy z niezerowymi cenami.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Przy kompletnych danych sprzedaży dla bieżącego dnia użytkownik otrzymuje ten sam zakres czasu co wcześniej oraz dodatkową wartość `price`, bez potrzeby wykonywania ręcznych obliczeń średniej.
- **SC-002**: W 100% przypadków wartość `price` odpowiada średniej arytmetycznej z wybranego okna i jest prezentowana z dokładnością do 2 miejsc po przecinku.
- **SC-003**: Przy kompletnych danych sprzedaży dla jutra użytkownik otrzymuje osobny sensor dla jutrzejszego okna wraz z analogiczną wartością `price` przed rozpoczęciem tego dnia.
- **SC-004**: W 100% przypadków niewystarczających danych tylko sensor zależny od niekompletnego zestawu przechodzi w stan `unavailable` i nie publikuje pozornie poprawnego zakresu czasu ani ceny średniej.
- **SC-005**: W 100% przypadków zmiana wyłącznie ceny zakupu nie zmienia ani wyznaczonego okna, ani wartości `price` dla żadnego z wynikowych sensorów.
- **SC-006**: W 100% przypadków, gdy sensor dla danego dnia jest `unavailable`, atrybut `price` nie występuje w opublikowanym stanie tego sensora.
- **SC-007**: W 100% przypadków każda cena sprzedaży poniżej 0,05 PLN/kWh jest traktowana jako 0 przed wyznaczaniem okna, zarówno dla dnia dzisiejszego, jak i jutrzejszego.
- **SC-008**: W 100% przypadków, gdy liczba godzin zerowych w przedziale 08:00-16:00 przekracza 2, sensor publikuje okno obejmujące wszystkie te godziny, a nie tylko standardowe 8 kwadransów.
- **SC-009**: W 100% przypadków atrybut `is_active` sensora dzisiejszego poprawnie zwraca `on` lub `off` w zależności od bieżącego czasu lokalnego, i nie jest publikowany gdy sensor jest `unavailable`.
- **SC-010**: Sensor jutrzejszego okna nigdy nie posiada atrybutu `is_active`.

## Assumptions

- W integracji istnieją odrębne zestawy danych cen sprzedaży dla bieżącego dnia i dla jutra.
- Dotychczasowe reguły wyboru okna, rozstrzygania remisów, długości okna i stanu `unavailable` pozostają poprawne i mają zostać zachowane bez zmian (o ile nie są nadpisywane przez nowe reguły zerowe).
- Średnia cena okna jest liczona jako średnia arytmetyczna ze wszystkich kwadransów należących do wybranego okna (niezależnie od jego długości).
- Dane ceny sprzedaży dla obu dni są dostępne dla kolejnych pełnych godzin w przedziale 08:00-16:00 i mogą zostać rozbite na 4 kolejne kwadranse o tej samej wartości ceny.
- Oba sensory korzystają z tego samego lokalnego sposobu prezentacji czasu używanego już przez integrację.
- Próg ceny zerowej (0,05 PLN/kWh) jest stały i nie jest konfigurowalny przez użytkownika.
- Rozszerzone okno zerowe jest wyznaczane jako ciągły span od początku najwcześniejszej godziny zerowej do końca najpóźniejszej godziny zerowej w przedziale 08:00-16:00, nawet jeśli między nimi występują godziny z niezerową ceną (np. 09:00, 11:00 zero → wynik `09:00-12:00`).
- Atrybut `is_active` jest obliczany dynamicznie przy każdej aktualizacji sensora dzisiejszego i odzwierciedla bieżący czas lokalny systemu Home Assistant.
