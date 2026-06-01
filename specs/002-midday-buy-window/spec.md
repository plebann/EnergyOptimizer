# Feature Specification: Rozszerzenie Sensorów Okna Najniższej Ceny Zakupu

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

- Q: Na podstawie którego sensora cenowego liczymy wynikowe okno? → A: Wyłącznie na podstawie ceny zakupu.
- Q: Jakiego formatu tekstowego używa wynikowy sensor? → A: `HH:MM-HH:MM`.
- Q: Jak traktować dane wejściowe, jeśli sensor ceny zakupu udostępnia kolejne pełne godziny zamiast gotowych kwadransów? → A: Każdą godzinę należy rozbić na 4 kolejne kwadranse z tą samą wartością ceny, a długość okna nadal liczyć w kwadransach.

### Session 2026-05-09

- Q: Jak ma być prezentowana średnia cena wybranego okna? → A: Jako dodatkowy atrybut `price`, liczba typu float z dokładnością do 2 miejsc po przecinku, wyrażająca PLN/kWh.
- Q: Czy jutrzejszy sensor ma działać według tych samych reguł co obecny sensor? → A: Tak, z zachowaniem dotychczasowych reguł wyboru, niedostępności i formatu wyniku, ale zasilanymi danymi dla jutra.
- Q: Co ma się stać z atrybutem `price`, gdy odpowiadający sensor jest `unavailable`? → A: Atrybut `price` nie jest wtedy publikowany.

### Session 2026-05-31

- Q: Jak system ma się zachować, jeśli w danych cen zakupu dla danego dnia występują ceny zerowe lub niższe niż 0,05 PLN/kWh? → A: Takie ceny należy traktować jako zerowe, a wynikowe okno `midday-buy` musi objąć cały zakres od pierwszego do ostatniego takiego wystąpienia w tym dniu.
- Q: Czy reguła obejmowania wszystkich cen zerowych ma pierwszeństwo przed standardowym wyborem najtańszego 8-kwadransowego okna? → A: Tak, reguła zerowych lub quasi-zerowych cen ma pierwszeństwo i dopiero przy jej braku stosuje się dotychczasowe reguły wyboru zwykłego okna.
- Q: Jak należy wyznaczać atrybut `is_active` dla opublikowanego okna? → A: `is_active` ma wartość `on`, gdy bieżący lokalny czas używany przez integrację mieści się pomiędzy czasem startu i końca opublikowanego okna, a w przeciwnym razie `off`.
- Q: Czy atrybut `is_active` ma być publikowany, gdy sensor jest `unavailable` albo okno nie zostało poprawnie wyznaczone? → A: Nie, w takim przypadku atrybut `is_active` nie jest publikowany.
- Q: Czy dodanie `is_active` zmienia zasady wyznaczania okna albo atrybutu `price`? → A: Nie, `is_active` jest wyłącznie dodatkową informacją o tym, czy aktualny lokalny czas mieści się w już opublikowanym przedziale.
- Q: Jak interpretować `is_active` dla sensora jutrzejszego okna? → A: Dla sensora jutrzejszego `is_active` nie ma sensu biznesowego, więc atrybut może być pominięty.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Odczyt najtańszego okna zakupu z ceną średnią i statusem aktywności (Priority: P1)

Użytkownik Home Assistant chce nadal widzieć osobny sensor tekstowy dla najtańszego okna zakupu energii w środku dnia, ale dodatkowo potrzebuje od razu średniej ceny tego okna oraz informacji, czy to opublikowane okno jest aktywne w bieżącej chwili.

**Why this priority**: To rozszerza już działający wynik o brakujące informacje decyzyjne, bez zmiany podstawowego przepływu korzystania z sensora.

**Independent Test**: Przy dostępnych danych ceny zakupu dla bieżącego dnia w przedziale 08:00-16:00 użytkownik widzi poprawnie wyznaczony sensor tekstowy dla okna środka dnia oraz dodatkowe atrybuty ceny średniej i aktywności dla tego samego okna.

**Acceptance Scenarios**:

1. **Given** dostępne są dane ceny zakupu dla kolejnych pełnych godzin środka dnia bieżącego dnia i nie występują w nich ceny zerowe ani niższe niż 0,05 PLN/kWh, **When** integracja wyznacza najtańsze okno, **Then** użytkownik widzi sensor tekstowy z zakresem czasu odpowiadającym najtańszemu ciągłemu oknu długości 8 kolejnych kwadransów.
2. **Given** najtańsze okno dla bieżącego dnia zostało wyznaczone, **When** użytkownik sprawdza atrybuty sensora wynikowego, **Then** widzi dodatkową wartość `price` równą średniej cenie z tego okna, zapisaną jako liczba float z 2 miejscami po przecinku i interpretowaną jako PLN/kWh.
3. **Given** bieżący lokalny czas używany przez integrację mieści się pomiędzy czasem startu i końca opublikowanego okna dla bieżącego dnia, **When** użytkownik sprawdza atrybuty sensora wynikowego, **Then** widzi `is_active` o wartości `on`.
4. **Given** bieżący lokalny czas używany przez integrację nie mieści się pomiędzy czasem startu i końca opublikowanego okna dla bieżącego dnia, **When** użytkownik sprawdza atrybuty sensora wynikowego, **Then** widzi `is_active` o wartości `off`.
5. **Given** cena zakupu różni się od ceny sprzedaży, **When** integracja wyznacza bieżące okno środka dnia, **Then** wynik, wartość `price` i wartość `is_active` opierają się wyłącznie na oknie wyznaczonym z ceny zakupu.

---

### User Story 2 - Priorytetowe objęcie wszystkich zerowych cen zakupu (Priority: P2)

Użytkownik chce, aby w dniach, w których zakup energii jest chwilowo darmowy lub quasi-darmowy, wynikowe okno `midday-buy` obejmowało cały zakres takich okazji, zamiast wybierać tylko standardowe 8-kwadransowe minimum.

**Why this priority**: Wystąpienie zerowych lub niemal zerowych cen jest szczególnym przypadkiem biznesowym o najwyższej wartości operacyjnej, więc musi mieć pierwszeństwo nad zwykłym rankingiem okien.

**Independent Test**: Jeżeli w danych cen zakupu dla danego dnia występuje co najmniej jedna cena równa 0 lub niższa niż 0,05 PLN/kWh, użytkownik widzi wynikowe okno obejmujące cały zakres od pierwszego do ostatniego takiego wystąpienia w tym dniu.

**Acceptance Scenarios**:

1. **Given** w danych cen zakupu dla bieżącego dnia występują ceny równe 0 PLN/kWh w więcej niż jednym punkcie czasu, **When** integracja wyznacza wynikowe okno `midday-buy`, **Then** publikuje okno obejmujące cały zakres od pierwszego do ostatniego wystąpienia takiej ceny.
2. **Given** w danych cen zakupu dla danego dnia występują ceny dodatnie niższe niż 0,05 PLN/kWh, **When** integracja wyznacza wynikowe okno `midday-buy`, **Then** traktuje te ceny jak zerowe i również obejmuje cały zakres od pierwszego do ostatniego takiego wystąpienia.
3. **Given** w tym samym dniu istnieje standardowe 8-kwadransowe okno o niższej średniej cenie niż część dnia bez cen zerowych, **When** występują jakiekolwiek ceny zerowe lub quasi-zerowe, **Then** reguła objęcia wszystkich takich wystąpień ma pierwszeństwo przed standardowym wyborem zwykłego okna.

---

### User Story 3 - Odczyt analogicznego okna dla jutra (Priority: P3)

Użytkownik chce otrzymać drugi, analogiczny sensor dla jutrzejszego okna cenowego, aby mógł planować działania z wyprzedzeniem bez mieszania danych bieżącego i kolejnego dnia.

**Why this priority**: Rozszerzenie na kolejny dzień daje nową wartość planistyczną, ale opiera się na już istniejącym i zrozumiałym wzorcu działania sensora.

**Independent Test**: Przy dostępnych danych zakupu dla jutra użytkownik widzi osobny sensor dla jutrzejszego okna w tym samym formacie oraz z analogicznym atrybutem średniej ceny, bez publikowania `is_active`.

**Acceptance Scenarios**:

1. **Given** dostępne są dane zakupu dla jutra, **When** integracja wyznacza jutrzejsze okno środka dnia, **Then** publikuje osobny sensor tekstowy z wynikiem w formacie `HH:MM-HH:MM` dla jutrzejszego przedziału czasu.
2. **Given** jutrzejsze okno zostało wyznaczone, **When** użytkownik sprawdza atrybuty jutrzejszego sensora, **Then** widzi analogiczną wartość `price` obliczoną ze średniej ceny wybranego jutrzejszego okna.
3. **Given** jutrzejsze okno zostało wyznaczone, **When** użytkownik sprawdza atrybuty jutrzejszego sensora, **Then** nie widzi atrybutu `is_active`, ponieważ dla jutrzejszego okna nie ma on sensu biznesowego.
4. **Given** dostępne są zarówno dane bieżące, jak i jutrzejsze, **When** integracja aktualizuje sensory, **Then** każdy sensor korzysta wyłącznie z danych odpowiadających swojemu dniowi i nie nadpisuje wyniku drugiego.

---

### User Story 4 - Zachowanie bez zmian poza nowymi atrybutami informacyjnymi i regułą zerowych cen (Priority: P4)

Użytkownik chce, aby rozszerzenie nie zmieniło dotychczasowych reguł działania sensora w dniach bez cen zerowych lub quasi-zerowych oraz aby oba sensory zachowywały się przewidywalnie przy brakach danych, remisach i stanach `unavailable`.

**Why this priority**: Rozszerzenie funkcjonalności nie może obniżyć wiarygodności już działającego sensora ani wprowadzić niespójności między dniami.

**Independent Test**: Przy dniach bez cen zerowych lub quasi-zerowych obowiązują dotychczasowe reguły wyboru najwcześniejszego remisu i długości 8 kwadransów, a przy niepełnych danych tylko dotknięty sensor przechodzi w stan `unavailable` bez publikowania atrybutów zależnych od poprawnie wyznaczonego okna.

**Acceptance Scenarios**:

1. **Given** dla jednego z dni brakuje danych pozwalających zbudować pełne okno zgodnie z obowiązującą regułą wyboru dla tego dnia, **When** integracja próbuje wyznaczyć wynik dla tego dnia, **Then** odpowiedni sensor przechodzi w stan `unavailable` zamiast publikować niepełny wynik.
2. **Given** dla danego dnia nie występują ceny zerowe ani quasi-zerowe i istnieje więcej niż jedno standardowe okno z takim samym najniższym kosztem zakupu, **When** integracja wybiera wynik, **Then** nadal wybiera najwcześniejsze takie okno.
3. **Given** użytkownik porównuje nową wersję sensora z poprzednim zachowaniem dla dnia bez cen zerowych lub quasi-zerowych, **When** pomija nowe atrybuty `price` oraz `is_active`, **Then** czas okna i reguły jego wyboru pozostają niezmienione.
4. **Given** sensor dla danego dnia jest `unavailable`, **When** użytkownik sprawdza jego atrybuty, **Then** atrybuty `price` oraz `is_active` nie są publikowane.

### Edge Cases

- Co dzieje się, gdy średnia cena wybranego okna ma więcej niż 2 miejsca po przecinku? System publikuje wartość `price` zaokrągloną do 2 miejsc po przecinku.
- Co dzieje się, gdy dane zakupu dla jutra nie są jeszcze dostępne, ale dane dla dziś są kompletne? Jutrzejszy sensor pozostaje `unavailable`, a bieżący sensor działa bez zmian.
- Co dzieje się, gdy dla dziś i jutra wypada ten sam przedział czasu, ale z inną średnią ceną? Każdy sensor publikuje własny zakres i własną wartość `price` niezależnie od drugiego.
- Co dzieje się, gdy dane wejściowe dla jednego z dni zawierają wartości nienumeryczne albo chwilowo niedostępne? Tylko wynik zależny od tego zestawu danych nie powinien publikować pozornie poprawnej wartości.
- Co dzieje się, gdy sensor dla danego dnia przechodzi w stan `unavailable`? Atrybut `price` nie jest wtedy publikowany, aby nie pozostawiać pozornie poprawnej lub nieaktualnej wartości liczbowej.
- Co dzieje się, gdy sensor dla danego dnia przechodzi w stan `unavailable`? Atrybut `is_active` również nie jest wtedy publikowany, aby nie sugerować poprawnie wyznaczonego i aktualnie ocenionego okna.
- Co dzieje się, gdy użytkownik sprawdza atrybuty sensora jutrzejszego okna? Atrybut `is_active` pozostaje pominięty nawet wtedy, gdy jutrzejsze okno zostało poprawnie wyznaczone.
- Co dzieje się, gdy w danym dniu występuje tylko jedno zerowe lub quasi-zerowe wskazanie ceny zakupu? Wynikowe okno obejmuje co najmniej punkt czasu odpowiadający temu wystąpieniu i nie może go pominąć.
- Co dzieje się, gdy zerowe lub quasi-zerowe ceny zakupu występują w kilku rozdzielonych blokach czasu? Wynikowe okno obejmuje cały zakres od pierwszego do ostatniego takiego wystąpienia, nawet jeśli pomiędzy nimi występują wyższe ceny.
- Co dzieje się, gdy w danym dniu nie występują ceny równe 0 ani niższe niż 0,05 PLN/kWh? System stosuje standardowe reguły wyboru najtańszego ciągłego okna długości 8 kwadransów bez dodatkowych wyjątków.
- Co dzieje się, gdy bieżący lokalny czas jest dokładnie równy czasowi startu albo końca opublikowanego okna? `is_active` przyjmuje wartość `on`, ponieważ taki czas nadal mieści się w opublikowanym przedziale.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST wyznaczać oba wynikowe sensory wyłącznie na podstawie ceny zakupu i ignorować cenę sprzedaży przy obliczaniu okna oraz ceny średniej.
- **FR-002**: System MUST dla każdego dnia szukać jednego wynikowego okna wyłącznie w przedziale 08:00-16:00 czasu lokalnego.
- **FR-003**: System MUST traktować każdą wejściową pełną godzinę ceny zakupu jako 4 kolejne kwadranse z tą samą wartością ceny przy budowaniu kandydatów okna.
- **FR-004**: System MUST pozostawić bez zmian dotychczasowy bieżący sensor tekstowy publikujący wynik dla bieżącego dnia lokalnego w formacie `HH:MM-HH:MM`.
- **FR-005**: System MUST dodać do bieżącego sensora wynikowego dodatkowy atrybut `price`.
- **FR-006**: System MUST wyznaczać wartość `price` jako średnią arytmetyczną ceny zakupu ze wszystkich kwadransów należących do wybranego okna.
- **FR-007**: System MUST publikować wartość `price` jako liczbę typu float zaokrągloną do 2 miejsc po przecinku, reprezentującą PLN/kWh.
- **FR-008**: System MUST publikować osobny, analogiczny sensor tekstowy dla jutrzejszego dnia lokalnego, używający tych samych reguł wyboru okna, tego samego formatu tekstowego i analogicznego atrybutu `price`.
- **FR-009**: System MUST wyznaczać sensor jutrzejszy wyłącznie z zestawu danych cenowych przeznaczonego dla jutra, a nie z zestawu danych bieżącego dnia.
- **FR-010**: System MUST aktualizować tylko ten sensor, którego odpowiadający mu zestaw danych cenowych zmienia wynik wyznaczonego okna lub wartość `price`.
- **FR-011**: System MUST ustawiać odpowiedni sensor tekstowy w stanie `unavailable`, jeśli dla odpowiadającego mu dnia brak danych wejściowych nie pozwala wyznaczyć poprawnego wynikowego okna zgodnie z obowiązującą regułą wyboru dla tego dnia.
- **FR-012**: System MUST traktować każdą cenę zakupu równą 0 PLN/kWh oraz każdą cenę zakupu niższą niż 0,05 PLN/kWh jako cenę zerową.
- **FR-013**: System MUST, gdy dla danego dnia występuje co najmniej jedna cena zerowa lub quasi-zerowa, wyznaczać wynikowe okno `midday-buy` jako pełny zakres czasu od pierwszego do ostatniego takiego wystąpienia w tym dniu.
- **FR-014**: System MUST stosować regułę z FR-013 z pierwszeństwem przed standardowym wyborem najtańszego ciągłego okna długości 8 kolejnych kwadransów.
- **FR-015**: System MUST, gdy dla danego dnia nie występuje żadna cena zerowa ani quasi-zerowa, wybierać najtańsze ciągłe okno długości dokładnie 8 kolejnych kwadransów w przedziale 08:00-16:00 czasu lokalnego.
- **FR-016**: System MUST wybierać najwcześniejsze standardowe okno, gdy więcej niż jedno standardowe okno ma ten sam najniższy koszt zakupu dla danego dnia.
- **FR-017**: System MUST zachować spójność wyniku obu sensorów z lokalnym sposobem prezentacji czasu używanym przez integrację.
- **FR-018**: System MUST nie publikować atrybutu `price`, gdy odpowiadający mu sensor tekstowy jest w stanie `unavailable`.
- **FR-019**: System MUST publikować dla sensora bieżącego dnia dodatkowy atrybut `is_active`, gdy odpowiadające mu okno zostało poprawnie wyznaczone.
- **FR-020**: System MUST wyznaczać wartość `is_active` względem lokalnego czasu używanego przez integrację oraz opublikowanego przedziału czasu sensora bieżącego dnia.
- **FR-021**: System MUST ustawiać `is_active` na `on`, gdy bieżący lokalny czas jest pomiędzy czasem startu i końca opublikowanego okna bieżącego dnia, włącznie z granicami tego przedziału.
- **FR-022**: System MUST ustawiać `is_active` na `off`, gdy bieżący lokalny czas nie mieści się w opublikowanym przedziale czasu sensora bieżącego dnia.
- **FR-023**: System MUST nie publikować atrybutu `is_active`, gdy sensor bieżącego dnia jest w stanie `unavailable` albo gdy jego okno nie zostało poprawnie wyznaczone.
- **FR-024**: System MUST nie publikować atrybutu `is_active` dla sensora jutrzejszego okna, nawet gdy to okno zostało poprawnie wyznaczone.
- **FR-025**: System MUST traktować dodanie atrybutu `is_active` jako zmianę wyłącznie informacyjną, która nie zmienia reguł wyznaczania okna ani sposobu obliczania atrybutu `price`.

### Key Entities *(include if feature involves data)*

- **Dzienne Dane Ceny Zakupu**: Zestaw cen zakupu przypisany do konkretnego dnia lokalnego, z którego każda pełna godzina jest interpretowana jako 4 kolejne kwadranse o tej samej wartości.
- **Standardowe Okno Środka Dnia**: Ciągły kandydat do oceny mieszczący się całkowicie pomiędzy 08:00 a 16:00 i obejmujący 8 kolejnych kwadransów dla jednego dnia lokalnego, używany wtedy, gdy w danym dniu nie występują ceny zerowe ani quasi-zerowe.
- **Rozszerzone Okno Zerowych Cen Zakupu**: Wynikowy zakres czasu obejmujący cały przedział od pierwszego do ostatniego wystąpienia ceny zakupu równej 0 albo niższej niż 0,05 PLN/kWh w obrębie jednego dnia lokalnego.
- **Średnia Cena Okna**: Wartość informacyjna odpowiadająca średniej cenie zakupu z wybranego okna środka dnia, prezentowana jako `price` w PLN/kWh.
- **Status Aktywności Okna Bieżącego Dnia**: Wartość informacyjna `is_active` określająca, czy bieżący lokalny czas używany przez integrację mieści się w opublikowanym przedziale wybranego okna bieżącego dnia.
- **Sensor Dzisiejszego Okna Zakupu**: Istniejący wynik tekstowy pokazujący wybrany przedział czasu dla bieżącego dnia oraz jego średnią cenę.
- **Sensor Jutrzejszego Okna Zakupu**: Nowy wynik tekstowy pokazujący wybrany przedział czasu dla kolejnego dnia oraz jego średnią cenę.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Przy kompletnych danych zakupu dla bieżącego dnia użytkownik otrzymuje poprawny zakres czasu oraz dodatkową wartość `price`, bez potrzeby wykonywania ręcznych obliczeń średniej.
- **SC-002**: W 100% przypadków wartość `price` odpowiada średniej arytmetycznej z wybranego okna i jest prezentowana z dokładnością do 2 miejsc po przecinku.
- **SC-003**: Przy kompletnych danych zakupu dla jutra użytkownik otrzymuje osobny sensor dla jutrzejszego okna wraz z analogiczną wartością `price` przed rozpoczęciem tego dnia.
- **SC-004**: W 100% przypadków wystąpienia co najmniej jednej ceny zakupu równej 0 albo niższej niż 0,05 PLN/kWh wynikowe okno obejmuje cały zakres od pierwszego do ostatniego takiego wystąpienia w danym dniu.
- **SC-005**: W 100% przypadków niewystarczających danych tylko sensor zależny od niekompletnego zestawu przechodzi w stan `unavailable` i nie publikuje pozornie poprawnego zakresu czasu ani ceny średniej.
- **SC-006**: W 100% przypadków zmiana wyłącznie ceny sprzedaży nie zmienia ani wyznaczonego okna, ani wartości `price` dla żadnego z wynikowych sensorów.
- **SC-007**: W 100% przypadków, gdy sensor dla danego dnia jest `unavailable`, atrybut `price` nie występuje w opublikowanym stanie tego sensora.
- **SC-008**: W 100% przypadków dni bez cen zerowych ani quasi-zerowych zachowują dotychczasową regułę wyboru najtańszego ciągłego okna długości 8 kwadransów oraz najwcześniejszego remisu.
- **SC-009**: W 100% przypadków poprawnie wyznaczonego okna bieżącego dnia atrybut `is_active` ma wartość `on`, gdy bieżący lokalny czas mieści się w opublikowanym przedziale tego okna, oraz `off` poza tym przedziałem.
- **SC-010**: W 100% przypadków, gdy sensor bieżącego dnia jest `unavailable` albo okno nie zostało poprawnie wyznaczone, atrybut `is_active` nie występuje w opublikowanym stanie tego sensora.
- **SC-011**: W 100% przypadków sensor jutrzejszego okna nie publikuje atrybutu `is_active`, nawet gdy samo jutrzejsze okno i atrybut `price` zostały poprawnie wyznaczone.

## Assumptions

- W integracji istnieją odrębne zestawy danych cen zakupu dla bieżącego dnia i dla jutra.
- Dotychczasowe reguły wyboru standardowego okna, rozstrzygania remisów, długości okna i stanu `unavailable` pozostają poprawne i mają zostać zachowane bez zmian dla dni bez cen zerowych ani quasi-zerowych.
- Średnia cena okna jest liczona jako średnia arytmetyczna ze wszystkich kwadransów należących do wybranego okna.
- Dane ceny zakupu dla obu dni są dostępne dla kolejnych pełnych godzin w przedziale 08:00-16:00 i mogą zostać rozbite na 4 kolejne kwadranse o tej samej wartości ceny.
- Oba sensory korzystają z tego samego lokalnego sposobu prezentacji czasu używanego już przez integrację.
- Reguła objęcia wszystkich cen zerowych lub quasi-zerowych dotyczy całego danego dnia lokalnego i wyznacza zakres od pierwszego do ostatniego takiego wystąpienia, tak aby żadne z nich nie zostało pominięte.
- Ocena, czy opublikowane okno jest aktualnie aktywne, może być wykonana na podstawie tego samego lokalnego czasu używanego przez integrację do prezentacji zakresu godzin.
- Dla sensora jutrzejszego okna sama informacja o przedziale i atrybucie `price` jest wystarczająca, więc `is_active` pozostaje niepublikowane.