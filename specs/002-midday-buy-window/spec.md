# Feature Specification: Okno Najniższej Ceny Sprzedaży w Środku Dnia

**Feature Branch**: `[002-midday-buy-window]`  
**Created**: 2026-05-07  
**Status**: Draft  
**Input**: User description: "w integracji są dwa sensory ceny - cena zakupu i cena sprzedaży na podstawie ceny zakupu wyznacz okienko najniższej ceny zakupu, które przypada w środku dnia środek dnia to pomiędzy 8 a 16 wyliczone okienko powinno mieć osobny sensor tekstowy, którego zawartość będzie np (12:00-14:00) okienko powinno mieć długość 8 kwadransów"

## Clarifications

### Session 2026-05-07

- Q: Gdy kilka okien 8-kwadransowych ma identyczny najniższy koszt, którą regułę wyboru wynikowego okna mamy przyjąć? → A: Wybierz najwcześniejsze okno.
- Q: Gdy brakuje kompletnych danych do wyznaczenia pełnego okna 8 kwadransów, jaki stan ma przyjmować sensor tekstowy? → A: Stan `unavailable`.
- Q: Do którego dnia ma odnosić się wyznaczane okno 08:00-16:00? → A: Do bieżącego dnia lokalnego.

### Session 2026-05-08

- Q: Na podstawie którego sensora cenowego liczymy wynikowe okno? → A: Wyłącznie na podstawie ceny sprzedaży.
- Q: Jakiego formatu tekstowego używa wynikowy sensor? → A: `HH:MM-HH:MM`.
- Q: Jak traktować dane wejściowe, jeśli sensor ceny sprzedaży udostępnia kolejne pełne godziny zamiast gotowych kwadransów? → A: Każdą godzinę należy rozbić na 4 kolejne kwadranse z tą samą wartością ceny, a długość okna nadal liczyć w kwadransach.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Odczyt najtańszego okna sprzedaży w środku dnia (Priority: P1)

Użytkownik Home Assistant chce zobaczyć osobny sensor tekstowy, który wskazuje najtańsze okno sprzedaży energii w środku dnia, aby mógł szybko rozpoznać najlepszy przedział czasowy dla działań zależnych od ceny sprzedaży.

**Why this priority**: To jest bezpośrednia wartość tej funkcji i minimalny użyteczny rezultat dla użytkownika.

**Independent Test**: Przy dostępnych danych ceny sprzedaży dla kolejnych pełnych godzin w przedziale 08:00-16:00 użytkownik widzi osobny sensor tekstowy z jednym, poprawnie wyznaczonym oknem o długości 8 kolejnych kwadransów, liczonym po rozbiciu każdej godziny na 4 kwadranse.

**Acceptance Scenarios**:

1. **Given** dostępne są dane ceny sprzedaży dla kolejnych pełnych godzin środka dnia, **When** integracja wyznacza najtańsze okno, **Then** użytkownik widzi osobny sensor tekstowy z zakresem czasu odpowiadającym najtańszemu ciągłemu oknu długości 8 kwadransów, wyliczonemu po rozbiciu każdej godziny na 4 kwadranse z tą samą ceną.
2. **Given** cena sprzedaży różni się od ceny zakupu, **When** integracja wyznacza okno środka dnia, **Then** wynik opiera się wyłącznie na cenie sprzedaży.
3. **Given** dostępne są także dane cenowe dla kolejnego dnia, **When** integracja wyznacza okno środka dnia, **Then** wynik dotyczy wyłącznie przedziału 08:00-16:00 bieżącego dnia lokalnego.

---

### User Story 2 - Użycie okna w automatyzacjach i decyzjach (Priority: P2)

Użytkownik chce otrzymać wynik w jednoznacznym formacie tekstowym, aby móc wykorzystać go w dashboardach, automatyzacjach lub dalszej logice wspierającej decyzje dzienne.

**Why this priority**: Sama kalkulacja nie daje praktycznej wartości, jeśli wynik nie jest łatwy do odczytu i wykorzystania poza kodem.

**Independent Test**: Użytkownik może odczytać wartość sensora jako pojedynczy przedział czasu w spójnym formacie i odróżnić go od innych sensorów cenowych.

**Acceptance Scenarios**:

1. **Given** najtańsze okno zostało wyznaczone, **When** użytkownik odczytuje wartość sensora, **Then** otrzymuje pojedynczy zakres czasu zapisany jako przedział początku i końca okna w formacie `HH:MM-HH:MM`, na przykład `12:00-14:00`.
2. **Given** dane ceny sprzedaży zmieniają się, **When** zmiana wpływa na najtańsze okno środka dnia, **Then** opublikowana wartość sensora odzwierciedla nowy przedział.

---

### User Story 3 - Przewidywalne zachowanie przy brakach danych (Priority: P3)

Użytkownik chce, aby integracja zachowywała się przewidywalnie, gdy dane ceny sprzedaży są niepełne albo niewystarczające do wyznaczenia pełnego okna, aby nie opierać decyzji na wyniku pozornie poprawnym.

**Why this priority**: Błędnie wyznaczone okno byłoby gorsze niż jawny brak wyniku, bo mogłoby prowadzić do złych decyzji dziennych.

**Independent Test**: Przy braku pełnych danych dla całego wymaganego okna integracja nie publikuje mylącego wyniku i ustawia sensor w stanie `unavailable`.

**Acceptance Scenarios**:

1. **Given** w przedziale 08:00-16:00 nie ma wystarczających danych godzinowych do zbudowania po rozbiciu ciągłego okna długości 8 kwadransów, **When** integracja próbuje wyznaczyć wynik, **Then** ustawia sensor w stanie `unavailable` zamiast publikować pozornie poprawny przedział czasu.
2. **Given** istnieje więcej niż jedno okno z takim samym najniższym kosztem sprzedaży, **When** integracja wybiera wynik, **Then** wybiera najwcześniejsze takie okno, tak aby wynik był powtarzalny.

### Edge Cases

- Co dzieje się, gdy dane ceny sprzedaży istnieją tylko dla części godzin w przedziale 08:00-16:00 i po rozbiciu nie pozwalają zbudować pełnego okna 8 kwadransów? Sensor przechodzi w stan `unavailable`.
- Co dzieje się, gdy dwa lub więcej okien mają dokładnie taki sam najniższy łączny koszt sprzedaży? System wybiera najwcześniejsze takie okno.
- Co dzieje się, gdy cena zakupu jest niższa lub wyższa od ceny sprzedaży, ale użytkownik oczekuje okna wyznaczanego tylko z ceny sprzedaży?
- Co dzieje się, gdy dane wejściowe zawierają wartości nienumeryczne albo chwilowo niedostępne?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST wyznaczać wynik wyłącznie na podstawie `sell-price sensor`.
- **FR-002**: System MUST ignorować sensor ceny zakupu przy obliczaniu opisywanego okna.
- **FR-003**: System MUST szukać okna wyłącznie w przedziale środka dnia od 08:00 do 16:00 czasu lokalnego.
- **FR-003a**: System MUST wyznaczać okno wyłącznie dla bieżącego dnia lokalnego.
- **FR-004**: System MUST wyznaczać jedno ciągłe okno o długości dokładnie 8 kolejnych kwadransów.
- **FR-004a**: System MUST traktować każdą wejściową pełną godzinę ceny sprzedaży jako 4 kolejne kwadranse z tą samą wartością ceny przy budowaniu kandydatów okna.
- **FR-005**: System MUST publikować wyliczone okno jako osobny sensor tekstowy odrębny od istniejących sensorów cenowych.
- **FR-006**: System MUST prezentować wynik sensora jako pojedynczy zakres początku i końca wyznaczonego okna w formacie `HH:MM-HH:MM`, na przykład `12:00-14:00`.
- **FR-006a**: System MUST budować wyliczenie z danych udostępnionych przez współdzielony stan integracji dla `sell-price sensor`, a nie przez bezpośredni odczyt encji z warstwy publikującej sensor wynikowy.
- **FR-007**: System MUST aktualizować opublikowany wynik, gdy zmiana danych ceny sprzedaży zmienia najtańsze okno w środku dnia.
- **FR-008**: System MUST ustawiać sensor tekstowy w stanie `unavailable`, jeśli brak danych godzinowych nie pozwala po rozbiciu wyznaczyć pełnego okna długości 8 kwadransów.
- **FR-009**: System MUST wybierać najwcześniejsze okno, gdy więcej niż jedno okno ma ten sam najniższy koszt sprzedaży.
- **FR-010**: System MUST zachować spójność wyniku z lokalnym sposobem prezentacji czasu używanym przez integrację.

### Key Entities *(include if feature involves data)*

- **Cena Sprzedaży**: Dane wejściowe opisujące koszt sprzedaży energii w kolejnych pełnych godzinach, z których każda jest na potrzeby obliczeń rozbijana na 4 kolejne kwadranse o tej samej wartości ceny.
- **Okno Środka Dnia**: Każdy ciągły kandydat do oceny mieszczący się całkowicie pomiędzy 08:00 a 16:00 i obejmujący 8 kolejnych kwadransów.
- **Sensor Okna Sprzedaży**: Publikowany wynik tekstowy pokazujący wybrany przedział czasu odpowiadający najtańszemu oknu sprzedaży w środku dnia, wyliczony z współdzielonego stanu `sell-price sensor`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Gdy dostępne są kompletne dane godzinowe ceny sprzedaży dla środka dnia, użytkownik otrzymuje jeden opublikowany wynik wskazujący najtańsze okno o długości 8 kwadransów, wyliczone po rozbiciu każdej godziny na 4 kwadranse.
- **SC-002**: W 100% przypadków zmiana wyłącznie sensora ceny zakupu nie zmienia wyliczonego okna środka dnia.
- **SC-003**: W 100% przypadków niewystarczających danych system ustawia sensor w stanie `unavailable` i nie publikuje pozornie poprawnego zakresu czasu.
- **SC-004**: Użytkownik może odczytać wynik w jednoznacznym formacie zakresu czasu bez potrzeby wykonywania dodatkowych obliczeń.
- **SC-005**: Gdy jednocześnie dostępne są dane cenowe dla dziś i dla jutra, wynik odnosi się do bieżącego dnia lokalnego.

## Assumptions

- W integracji istnieją odrębne źródła danych dla ceny zakupu i ceny sprzedaży.
- Dane ceny sprzedaży są dostępne dla kolejnych pełnych godzin w przedziale 08:00-16:00 i mogą zostać rozbite na 4 kolejne kwadranse o tej samej wartości ceny.
- Zakres środka dnia jest interpretowany jako okna w całości mieszczące się pomiędzy 08:00 a 16:00 bieżącego dnia lokalnego.
- Przy remisie najtańszych okien integracja wybiera najwcześniejsze okno.
- Przy niewystarczających danych wejściowych sensor przechodzi w stan `unavailable`.
