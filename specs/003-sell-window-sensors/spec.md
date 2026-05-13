# Feature Specification: Cztery Sensory Optymalnych Okien Sprzedazy Energii

**Feature Branch**: `[003-add-sell-window-sensors]`  
**Created**: 2026-05-11  
**Status**: Draft  
**Input**: User description: "stworzenie 4 sensorow wyliczajacych optymalne godziny sprzedazy energii; cena sprzedazy rano i wieczorem, na dzisiaj i na jutro; wszystkie okienka powinny miec 1 godzine dlugosci; powinny polegac na cenie sprzedazy; powinny wybierac okienka z maksymalna cena sprzedazy; dla okienka porannego w godzinach pomiedzy 4 a 10, dla okienka wieczornego w godzinach pomiedzy 16 a 22; kazdy z sensorow powinien zwracac godzine startu okienka w formacie HH:MM; w atrybutach powinna byc cena danego okienka oraz godzina startu i cena drugiego najlepszego okienka danego typu; jezeli ceny pierwszego i drugiego najlepszego okienka sa takie same, wtedy najlepsze okienko powinno byc wczesniej, drugie najlepsze pozniej; dodatkowy atrybut to o ile procent drugie okienko jest gorsze od pierwszego"

## Clarifications

### Session 2026-05-11

- Q: Jaka ma byc rozdzielczosc startow kandydackich 1-godzinnych okien? → A: Tylko pelne godziny startu.
- Q: Jak wyznaczac cene 1-godzinnego okna, jesli dane zrodlowe w jego obrebie zawieraja wiecej niz jeden punkt cenowy? → A: Ten przypadek nie wystepuje, bo wejscie zawsze zawiera jedna wartosc ceny dla jednej pelnej godziny.
- Q: Jaka precyzje maja miec atrybuty cenowe i procentowy? → A: `price` i `second_window_price` z 3 miejscami po przecinku, procent z 1 miejscem po przecinku.
- Q: Czy ten feature ma zastepowac istniejace sensory, czy dodawac nowe? → A: Ma dodawac 4 nowe sensory i nie moze zmieniac liczby ani funkcjonalnosci istniejacych sensorow integracji.
- Q: Jakie dokladnie nazwy kluczy atrybutow mamy ustalic dla nowych sensorow? → A: `price`, `second_window_start`, `second_window_price`, `second_window_gap_pct`.
- Q: Czy nowe sensory zakupu maja wejsc do aktywnego feature 003? → A: Nie, feature 003 pozostaje bez zmian i obejmuje tylko sensory okien sprzedazy; sensory zakupu wymagaja osobnego przyszlego feature.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Dodatkowe dzisiejsze okna sprzedazy (Priority: P1)

Uzytkownik chce widziec dwa dodatkowe sensory dla biezacego dnia, osobno dla porannego i wieczornego okresu sprzedazy, aby bez recznego porownywania wskazac najlepsza godzine oddania energii do sieci bez utraty dotychczasowych sensorow integracji.

**Why this priority**: Najwieksza wartosc operacyjna dotyczy decyzji podejmowanych jeszcze tego samego dnia, dlatego sensory dla dzisiaj sa podstawowym wynikiem funkcji.

**Independent Test**: Przy kompletnych danych ceny sprzedazy dla dzisiaj uzytkownik otrzymuje dwa dodatkowe sensory zwracajace godzine startu najlepszego jednogodzinnego okna dla poranka i wieczoru oraz atrybuty potrzebne do porownania z drugim najlepszym wyborem, a istniejace sensory pozostaja bez zmian.

**Acceptance Scenarios**:

1. **Given** dostepne sa kompletne dane ceny sprzedazy dla dzisiejszego poranka, **When** system wyznacza sensor poranny dla dzisiaj, **Then** sensor publikuje godzine startu najlepszego jednogodzinnego okna w formacie `HH:MM`.
2. **Given** dostepne sa kompletne dane ceny sprzedazy dla dzisiejszego wieczoru, **When** system wyznacza sensor wieczorny dla dzisiaj, **Then** sensor publikuje godzine startu najlepszego jednogodzinnego okna w formacie `HH:MM`.
3. **Given** dla wybranego okna istnieje ranking co najmniej dwoch poprawnych kandydatow, **When** uzytkownik sprawdza atrybuty sensora, **Then** widzi `price`, `second_window_start`, `second_window_price` oraz `second_window_gap_pct`.

---

### User Story 2 - Dodatkowe jutrzejsze okna sprzedazy (Priority: P2)

Uzytkownik chce rowniez widziec dwa dodatkowe analogiczne sensory dla jutra, aby zaplanowac sprzedaz energii z wyprzedzeniem osobno dla poranka i wieczoru bez zmiany dzialania juz istniejacych sensorow.

**Why this priority**: Planowanie na jutro rozszerza wartosc funkcji, ale bazuje na tym samym modelu podejmowania decyzji co sensory dla dzisiaj.

**Independent Test**: Przy kompletnych danych ceny sprzedazy dla jutra uzytkownik otrzymuje dwa dodatkowe osobne sensory dla jutrzejszego poranka i wieczoru z tym samym formatem stanu i tym samym zakresem atrybutow co nowe sensory dzisiejsze, a istniejace sensory integracji pozostaja bez zmian.

**Acceptance Scenarios**:

1. **Given** dostepne sa kompletne dane ceny sprzedazy dla jutrzejszego poranka i wieczoru, **When** system wyznacza sensory dla jutra, **Then** publikuje osobne wyniki dla porannego i wieczornego okresu jutrzejszego dnia.
2. **Given** jutrzejsze sensory zostaly wyznaczone, **When** uzytkownik porownuje je z sensorami dla dzisiaj, **Then** kazdy sensor korzysta tylko z danych swojego dnia i swojego okresu.

---

### User Story 3 - Przewidywalny ranking bez regresji (Priority: P3)

Uzytkownik chce, aby nowe sensory zachowywaly sie przewidywalnie w przypadku remisow cenowych, brakow danych albo sytuacji, w ktorej procentowe porownanie nie moze byc wiarygodnie policzone, a jednoczesnie aby wdrozenie funkcji nie powodowalo regresji w juz istniejacych sensorach integracji.

**Why this priority**: Sensory decyzyjne musza byc jednoznaczne i nie moga publikowac mylacych wynikow w sytuacjach granicznych.

**Independent Test**: Przy remisach i niepelnych danych nowe sensory zachowuja stale zasady rankingu, a przy danych niewystarczajacych nie publikuja pozornie poprawnych wskazan, podczas gdy istniejace sensory integracji zachowuja swoja dotychczasowa liczbe i funkcjonalnosc.

**Acceptance Scenarios**:

1. **Given** dwa lub wiecej kandydackie okna maja taka sama najwyzsza cene sprzedazy, **When** system ustala ranking, **Then** jako najlepsze wybiera najwczesniejsze okno, a jako drugie najlepsze kolejne pozniejsze okno o tej samej cenie.
2. **Given** dane dla jednego z okresow lub dni sa niekompletne, **When** system nie moze wiarygodnie ustalic najlepszego i drugiego najlepszego okna, **Then** dotkniety sensor nie publikuje mylacego wyniku.
3. **Given** cena najlepszego okna wynosi zero, **When** system wyznacza procentowa przewage nad drugim oknem, **Then** nie publikuje procentowej wartosci, ktorej nie da sie sensownie zinterpretowac.
4. **Given** integracja publikuje juz inne sensory zwiazane z cenami i oknami sprzedazy, **When** nowa funkcja zostaje dodana, **Then** liczba i funkcjonalnosc istniejacych sensorow nie ulega zmianie.

### Edge Cases

- Co dzieje sie, gdy dwa albo wiecej okien maja taka sama najwyzsza cene? Ranking jest rozstrzygany chronologicznie, od najwczesniejszego okna do pozniejszych.
- Co dzieje sie, gdy brak pelnych danych dla calego zakresu porannego albo wieczornego? Dotkniety sensor pozostaje niedostepny zamiast wskazywac czesciowo policzony wynik.
- Co dzieje sie, gdy rekord godzinowy w ocenianym zakresie nie zawiera wymaganego `time` lub `price`, albo `price` nie jest liczba? Taki rekord jest traktowany jako niewiarygodny dla rankingu, a jesli przez to nie zostaja dwa poprawne kandydackie okna, dotkniety sensor pozostaje niedostepny.
- Co dzieje sie, gdy cena najlepszego okna wynosi zero? Atrybut procentowej roznicy nie jest publikowany, bo porownanie wzgledem zera jest niejednoznaczne.
- Co dzieje sie, gdy publikowane ceny lub procent maja wiecej cyfr po przecinku niz oczekiwano? Ceny sa publikowane z dokladnoscia do 3 miejsc po przecinku, a procent z dokladnoscia do 1 miejsca po przecinku.
- Co dzieje sie, gdy poranne i wieczorne okna tego samego dnia maja identyczne ceny? Kazdy sensor pozostaje niezalezny i rankinguje tylko swoj zakres czasu.
- Co dzieje sie, gdy dla dnia lub okresu mozna wskazac najlepsze okno, ale nie da sie wiarygodnie wyznaczyc drugiego najlepszego? Sensor nie publikuje czesciowego rankingu, aby nie sugerowac kompletnej analizy.
- Co dzieje sie, gdy payload zawiera rekordy godzinowe poza zakresem 04:00-10:00 albo 16:00-22:00? Sa ignorowane przez sensory obslugujace inny zakres i nie wplywaja na ranking ani dostepnosc poza swoim zakresem.
- Co dzieje sie, gdy w tym samym dniu i dla tej samej pelnej godziny startu wystepuje wiecej niz jeden rekord? Taka sytuacja jest traktowana jako niewiarygodne dane dla dotknietego wycinka dnia i zakresu, wiec odpowiadajacy mu sensor pozostaje niedostepny.
- Co dzieje sie z juz istniejacymi sensorami integracji po dodaniu tej funkcji? Pozostaja dostepne i nie zmieniaja swojej liczby ani dotychczasowej funkcjonalnosci.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST dodac dokladnie cztery nowe sensory wynikowe: poranny dzisiaj, wieczorny dzisiaj, poranny jutro i wieczorny jutro, publikowane obok juz istniejacych sensorow integracji, a nie w miejsce istniejacych encji.
- **FR-001a**: System MUST nie zmieniac liczby ani funkcjonalnosci juz istniejacych sensorow integracji w ramach wdrozenia tych czterech nowych sensorow.
- **FR-001b**: System MUST ograniczac zakres tego feature do czterech nowych sensorow okien sprzedazy; sensory okien zakupu pozostaja poza zakresem i wymagaja osobnego feature.
- **FR-001c**: System MUST publikowac cztery nowe sensory z translation-backed naming oraz stabilna tozsamoscia encji scoped do config entry, tak aby reloady nie zmienialy semantyki tych encji ani nie redefiniowaly juz istniejacych sensorow.
- **FR-002**: System MUST wyznaczac wszystkie cztery sensory wylacznie na podstawie ceny sprzedazy energii.
- **FR-003**: System MUST wyznaczac sensory dla dzisiaj tylko z danych przypisanych do dzisiejszego dnia, a sensory dla jutra tylko z danych przypisanych do jutrzejszego dnia.
- **FR-003a**: System MUST interpretowac pojedynczy rekord wejsciowy jako jedna wartosc ceny przypisana do jednej pelnej godziny startu wskazanej w polu czasu.
- **FR-003b**: System MUST korzystac z istniejacego zrodla cen sprzedazy udostepniajacego payloady `prices_today` i `prices_tomorrow`, gdzie kazdy payload zawiera rekordy godzinowe z wymaganymi polami `time` oraz `price`.
- **FR-004**: System MUST oceniac dla sensorow porannych tylko jednogodzinne okna mieszczace sie w calosci pomiedzy 04:00 a 10:00 czasu lokalnego.
- **FR-005**: System MUST oceniac dla sensorow wieczornych tylko jednogodzinne okna mieszczace sie w calosci pomiedzy 16:00 a 22:00 czasu lokalnego.
- **FR-005a**: System MUST dopuszczac jako kandydatow tylko okna rozpoczynajace sie o pelnej godzinie.
- **FR-005b**: System MUST ignorowac rekordy godzinowe, ktorych czas startu wypada poza zakresem obslugiwanym przez dany sensor; takie rekordy nie stanowia kandydatow i nie moga zmieniac rankingu ani dostepnosci innych wycinkow.
- **FR-006**: System MUST wybierac jako wynik sensora to jednogodzinne okno z najwyzsza cena sprzedazy, ktore nalezy do dnia i zakresu czasu obslugiwanego przez dany sensor.
- **FR-007**: System MUST publikowac stan kazdego sensora jako godzine startu wybranego okna w formacie `HH:MM`.
- **FR-008**: System MUST publikowac w atrybucie `price` cene wybranego najlepszego okna z dokladnoscia do 3 miejsc po przecinku.
- **FR-009**: System MUST publikowac w atrybutach `second_window_start` oraz `second_window_price` godzine startu w formacie `HH:MM` i cene drugiego najlepszego okna z dokladnoscia do 3 miejsc po przecinku, z tego samego dnia i tego samego zakresu czasu.
- **FR-010**: System MUST tworzyc ranking kandydackich okien przez sortowanie malejaco po cenie sprzedazy i, przy remisie cenowym, rosnaco po godzinie startu.
- **FR-011**: System MUST wybierac jako najlepsze okno pierwszy element rankingu, a jako drugie najlepsze okno drugi element rankingu.
- **FR-012**: System MUST wyrazac dodatkowy atrybut `second_window_gap_pct` jako nieujemna informacje o tym, o ile drugie najlepsze okno jest gorsze cenowo od najlepszego okna wzgledem wartosci najlepszego okna, z dokladnoscia do 1 miejsca po przecinku.
- **FR-012a**: System MUST stosowac powyzsze zaokraglenia tylko do publikowanych atrybutow sensora; precyzja danych zrodlowych i obliczen wewnetrznych moze byc wieksza niz publikowana precyzja 3 miejsc dla cen i 1 miejsca dla procentu.
- **FR-013**: System MUST nie publikowac atrybutu procentowego, jesli cena najlepszego okna wynosi zero.
- **FR-014**: System MUST traktowac sensor jako niedostepny, jesli dla jego dnia i zakresu czasu nie da sie wiarygodnie wyznaczyc zarowno najlepszego, jak i drugiego najlepszego jednogodzinnego okna.
- **FR-014a**: System MUST uznawac za niedostepny tylko ten sensor, ktorego wlasny wycinek dnia i zakresu czasu nie zawiera co najmniej dwoch poprawnych kandydatow z powodu brakujacych godzin, brakujacego `time` lub `price`, nienumerycznej ceny albo zduplikowanych rekordow dla tej samej pelnej godziny startu.
- **FR-015**: System MUST utrzymywac niezaleznosc wynikow pomiedzy porankiem i wieczorem oraz pomiedzy dniem dzisiejszym i jutrzejszym, tak aby zmiana danych jednego sensora nie zmieniala pozostalych trzech poza ich wlasnym zakresem.

### Key Entities *(include if feature involves data)*

- **Dzienny Zestaw Cen Sprzedazy**: Zbior rekordow cen sprzedazy odnoszacych sie do jednego dnia lokalnego, gdzie kazdy rekord zawiera znacznik czasu pelnej godziny i jedna wartosc ceny dla tej godziny.
- **Kandydackie Okno Sprzedazy**: Jednogodzinny przedzial czasu rozpoczynajacy sie o pelnej godzinie i nalezacy do porannego albo wieczornego zakresu, oceniany pod katem ceny sprzedazy.
- **Ranking Okien Sprzedazy**: Uporzadkowana lista kandydackich okien dla jednego dnia i jednego zakresu czasu, z ktorej wybierane sa pierwsze dwa miejsca.
- **Nowy Sensor Okna Sprzedazy**: Wynikowa dodatkowa encja pokazujaca godzine startu najlepszego okna oraz atrybuty `price`, `second_window_start`, `second_window_price` i `second_window_gap_pct`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Przy kompletnych danych dla obu dni i obu zakresow czasu uzytkownik otrzymuje cztery nowe sensory, z ktorych kazdy wskazuje poprawna godzine startu najlepszego okna w swoim zakresie, bez utraty juz istniejacych sensorow integracji.
- **SC-002**: W 100% przypadkow remisow cenowych pomiedzy najlepszymi kandydatami sensory wybieraja wczesniejsze okno jako najlepsze i nastepne chronologicznie okno jako drugie najlepsze.
- **SC-003**: Uzytkownik moze odczytac z jednego widoku sensora zarowno najlepsza, jak i zapasowa godzine sprzedazy dla kazdego obslugiwanego dnia i okresu, bez recznego porownywania zrodlowych cen.
- **SC-004**: W 100% przypadkow niekompletnych danych sensor nie publikuje czesciowego rankingu ani pozornie poprawnej godziny startu.
- **SC-005**: W 100% przypadkow, w ktorych procentowa roznica jest publikowana, przedstawia ona nieujemna procentowa przewage najlepszego okna nad drugim najlepszym.
- **SC-006**: W 100% przypadkow publikowane ceny maja dokladnosc do 3 miejsc po przecinku, a publikowana roznica procentowa do 1 miejsca po przecinku.
- **SC-007**: W 100% przypadkow wdrozenie funkcji nie zmienia liczby ani funkcjonalnosci sensorow, ktore istnialy w integracji przed dodaniem tych czterech nowych encji.

## Assumptions

- Istniejace zrodlo cen sprzedazy udostepnia osobne payloady `prices_today` oraz `prices_tomorrow`, ktore pozwalaja porownac jednogodzinne okna w wymaganych zakresach czasu.
- Wejscie ma postac rekordow godzinowych `time` plus `price`, a kazdy rekord opisuje dokladnie jedna pelna godzine.
- Jednogodzinne okno musi miescic sie w calosci wewnatrz zadanego zakresu, dlatego ostatni poprawny start dla poranka przypada przed 10:00, a dla wieczoru przed 22:00.
- Kandydackie okna sa porownywane tylko dla startow przypadajacych o pelnej godzinie.
- Rekordy godzinowe poza obslugiwanym zakresem czasu sa ignorowane przez dany sensor zamiast byc reinterpretowane jako kandydaci.
- Zduplikowane rekordy dla tej samej pelnej godziny startu nie sa oczekiwanym wejsciem; jesli pojawia sie w ocenianym wycinku dnia i zakresu, wynik dla tego sensora jest traktowany jako niewiarygodny.
- Atrybuty cenowe sa zaokraglane do 3 miejsc po przecinku, a atrybut procentowy do 1 miejsca po przecinku.
- Prezentacja czasu dla stanu i atrybutow korzysta z lokalnej konwencji czasu stosowanej juz przez integracje.
- Gdy system nie moze ustalic dwoch wiarygodnych okien rankingowych dla danego sensora, bezpieczniejszym zachowaniem jest brak wyniku niz publikacja niepelnej sugestii.
- Istniejace sensory integracji pozostaja poza zakresem zmian funkcjonalnych i musza zachowac swoje dotychczasowe zachowanie.
- Sensory okien zakupu nie naleza do zakresu feature 003 i powinny zostac opisane w osobnej przyszlej specyfikacji.
