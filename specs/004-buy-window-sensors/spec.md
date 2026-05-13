# Feature Specification: Cztery Sensory Optymalnych Okien Zakupu Energii

**Feature Branch**: `[004-buy-window-sensors]`  
**Created**: 2026-05-13  
**Status**: Draft  
**Input**: User description: "do dodania cztery nowe sensory ceny; najlepsze okienko zakupu energii w dzien i w nocy, na dzisiaj i na jutro; okienko nocne musi sie zawierac w godzinach 00-06, okienko dzienne w godzinach 10-16; okienko musi trwac dwie godziny; jezeli wiecej niz jedno okienko ma taka sama cene minimalna, wtedy w nocnym wybieramy to, ktore konczy sie blizej godziny 6, a w dzien wybieramy to, ktore zaczyna sie blizej godziny 13; do wyliczania okienka trzeba uzywac cen zakupu; sensor powinien wystawiac wartosc godziny startu w formacie HH:MM; w atrybutach powinna byc srednia cena z okienka w zaokragleniu do 3 miejsc po przecinku oraz flaga, czy cena jest ujemna"

## Clarifications

### Session 2026-05-13

- Q: Jaka ma byc rozdzielczosc startow kandydackich 2-godzinnych okien? → A: Kandydackie okna moga zaczynac sie tylko o pelnej godzinie.
- Q: Jak maja zachowac sie jutrzejsze sensory, jezeli atrybut `prices_tomorrow` sensora ceny zakupu jest pusta lista? → A: Jutrzejsze sensory pozostaja `unavailable`.
- Q: Jakie dokladnie nazwy kluczy atrybutow maja publikowac nowe sensory zakupu? → A: `price` i `is_negative`.
- Q: Z jakiego kontraktu danych wejsciowych korzystaja sensory zakupu? → A: Z istniejacego payloadu cen zakupu z kluczami `prices_today` i `prices_tomorrow`, gdzie kazdy rekord godzinowy musi zawierac `time` i `price`.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Dzisiejsze okna zakupu dzien i noc (Priority: P1)

Uzytkownik chce widziec osobne sensory dla najlepszego nocnego i dziennego dwugodzinnego okna zakupu energii dla biezacego dnia, aby szybko podjac decyzje bez recznego porownywania wszystkich godzin.

**Why this priority**: Najwieksza wartosc operacyjna dotyczy decyzji podejmowanych jeszcze tego samego dnia, wiec wynik dla dzisiaj jest podstawowym zastosowaniem tej funkcji.

**Independent Test**: Przy kompletnych danych cen zakupu dla biezacego dnia uzytkownik otrzymuje dwa nowe sensory, z ktorych kazdy pokazuje godzine startu najlepszego dwugodzinnego okna oraz atrybuty sredniej ceny i informacji o cenie ujemnej.

**Acceptance Scenarios**:

1. **Given** dostepne sa kompletne dane cen zakupu dla biezacej nocy w zakresie 00:00-06:00, **When** system wyznacza nocny sensor dla dzisiaj, **Then** publikuje godzine startu najlepszego dwugodzinnego okna w formacie `HH:MM`.
2. **Given** dostepne sa kompletne dane cen zakupu dla biezacego dnia w zakresie 10:00-18:00, **When** system wyznacza dzienny sensor dla dzisiaj, **Then** publikuje godzine startu najlepszego dwugodzinnego okna w formacie `HH:MM`.
3. **Given** ktorykolwiek z dzisiejszych sensorow ma wyznaczone poprawne okno, **When** uzytkownik sprawdza jego atrybuty, **Then** widzi atrybut `price` ze srednia cena wybranego okna zaokraglona do 3 miejsc po przecinku oraz atrybut `is_negative` informujacy, czy cena okna jest ujemna.

---

### User Story 2 - Jutrzejsze okna zakupu dzien i noc (Priority: P2)

Uzytkownik chce rowniez widziec dwa analogiczne sensory dla jutra, aby zaplanowac zakup energii z wyprzedzeniem osobno dla nocy i dnia.

**Why this priority**: Planowanie na jutro rozszerza wartosc funkcji, ale bazuje na tych samych zasadach decyzyjnych co sensory dla biezacego dnia.

**Independent Test**: Przy kompletnych danych cen zakupu dla jutra uzytkownik otrzymuje dwa osobne sensory dla jutrzejszej nocy i jutrzejszego dnia, z tym samym formatem stanu i takim samym zakresem atrybutow jak sensory dzisiejsze.

**Acceptance Scenarios**:

1. **Given** dostepne sa kompletne dane cen zakupu dla jutrzejszej nocy i jutrzejszego dnia, **When** system wyznacza sensory dla jutra, **Then** publikuje osobne wyniki dla nocnego i dziennego okresu kolejnego dnia.
2. **Given** jutrzejsze sensory zostaly wyznaczone, **When** uzytkownik porownuje je z sensorami dla dzisiaj, **Then** kazdy sensor korzysta wylacznie z danych swojego dnia i swojego zakresu czasu.
3. **Given** atrybut `prices_tomorrow` sensora ceny zakupu jest pusta lista, **When** system probuje wyznaczyc nocny i dzienny sensor dla jutra, **Then** oba jutrzejsze sensory pozostaja `unavailable`.

---

### User Story 3 - Przewidywalny wybor i bezpieczne zachowanie graniczne (Priority: P3)

Uzytkownik chce, aby nowe sensory zachowywaly sie przewidywalnie przy remisach cenowych, brakach danych oraz cenach ujemnych, tak aby publikowany wynik byl jednoznaczny i wiarygodny.

**Why this priority**: Sensory rekomendacyjne musza stosowac stale zasady wyboru, bo nawet niewielka niejednoznacznosc prowadzi do mylacych decyzji zakupowych.

**Independent Test**: Przy remisach i niekompletnych danych nowe sensory stosuja stale reguly rozstrzygania albo pozostaja niedostepne, a przy cenach ponizej zera publikuja jednoznaczna informacje o ujemnym wyniku.

**Acceptance Scenarios**:

1. **Given** dwa lub wiecej nocnych kandydatow ma taka sama minimalna srednia cene, **When** system wybiera wynik nocnego sensora, **Then** wskazuje okno konczace sie najblizej godziny 06:00.
2. **Given** dwa lub wiecej dziennych kandydatow ma taka sama minimalna srednia cene, **When** system wybiera wynik dziennego sensora, **Then** wskazuje okno rozpoczynajace sie najblizej godziny 13:00.
3. **Given** srednia cena wybranego okna jest mniejsza od zera, **When** sensor publikuje atrybuty, **Then** flaga ceny ujemnej ma wartosc prawda.
4. **Given** dla danego dnia i zakresu czasu nie ma wiarygodnych danych pozwalajacych wyznaczyc pelne dwugodzinne okno, **When** system probuje wyznaczyc wynik, **Then** dotkniety sensor nie publikuje pozornie poprawnej godziny startu.

### Edge Cases

- Co dzieje sie, gdy kilka nocnych okien ma taka sama najnizsza srednia cene? Wybrane zostaje to, ktore konczy sie najblizej godziny 06:00.
- Co dzieje sie, gdy kilka dziennych okien ma taka sama najnizsza srednia cene? Wybrane zostaje to, ktore zaczyna sie najblizej godziny 13:00.
- Co dzieje sie, gdy dwa dzienne okna o tej samej minimalnej cenie zaczynaja sie w jednakowej odleglosci od 13:00? System wybiera wczesniejsze z nich, aby zachowac deterministyczny wynik.
- Co dzieje sie, gdy srednia cena wybranego okna wynosi dokladnie 0? Flaga ceny ujemnej pozostaje wylaczona.
- Co dzieje sie, gdy dane sa kompletne dla dzisiaj, ale nie dla jutra? Dzisiejsze sensory publikuja wynik niezaleznie, a jutrzejsze pozostaja niedostepne.
- Co dzieje sie, gdy atrybut `prices_tomorrow` jest obecny, ale zawiera pusta liste? Jutrzejsze sensory pozostaja niedostepne, bo pusty payload nie stanowi wiarygodnego zestawu danych kandydackich.
- Co dzieje sie, gdy rekord w payloadzie cen zakupu nie zawiera `time` lub `price`, albo `price` nie jest liczba? Taki rekord nie stanowi wiarygodnego kandydata, a jesli przez to nie da sie wyznaczyc pelnego okna, dotkniety sensor pozostaje niedostepny.
- Co dzieje sie, gdy w ocenianym zakresie nie ma pelnego dwugodzinnego okna z wiarygodnymi danymi? Dotkniety sensor pozostaje niedostepny zamiast publikowac czesciowy wynik.
- Co dzieje sie, gdy srednia cena ma wiecej niz 3 miejsca po przecinku? Publikowana wartosc atrybutu ceny jest zaokraglana do 3 miejsc po przecinku.
- Co dzieje sie, gdy payload zawiera rekordy z czasami, ktore nie wskazuja pelnej godziny startu albo sugeruja start okna poza pelna godzina? Takie rekordy nie tworza osobnych kandydackich startow, bo kandydackie okna moga zaczynac sie tylko o pelnej godzinie.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST dodac dokladnie cztery nowe sensory wynikowe: nocny dzisiaj, dzienny dzisiaj, nocny jutro i dzienny jutro.
- **FR-001a**: System MUST publikowac nowe sensory obok juz istniejacych encji integracji, bez zmiany liczby ani funkcjonalnosci istniejacych sensorow.
- **FR-002**: System MUST wyznaczac wszystkie cztery sensory wylacznie na podstawie cen zakupu energii.
- **FR-003**: System MUST wyznaczac sensory dla dzisiaj tylko z danych przypisanych do dzisiejszego dnia, a sensory dla jutra tylko z danych przypisanych do jutrzejszego dnia.
- **FR-003a**: System MUST traktowac pusty payload `prices_tomorrow` jako brak wiarygodnych danych dla jutra i w takiej sytuacji utrzymywac oba jutrzejsze sensory w stanie `unavailable`.
- **FR-003b**: System MUST korzystac z istniejacego zrodla cen zakupu udostepniajacego payloady `prices_today` i `prices_tomorrow`, gdzie kazdy rekord godzinowy zawiera wymagane pola `time` oraz `price`.
- **FR-004**: System MUST oceniac dla sensorow nocnych tylko kandydackie okna o dlugosci dokladnie 2 godzin, mieszczace sie w calosci pomiedzy 00:00 a 06:00 czasu lokalnego.
- **FR-005**: System MUST oceniac dla sensorow dziennych tylko kandydackie okna o dlugosci dokladnie 2 godzin, mieszczace sie w calosci pomiedzy 10:00 a 18:00 czasu lokalnego.
- **FR-005a**: System MUST dopuszczac jako kandydatow tylko okna rozpoczynajace sie o pelnej godzinie.
- **FR-006**: System MUST obliczac cene kazdego kandydackiego okna jako srednia cene zakupu z calego dwugodzinnego przedzialu.
- **FR-007**: System MUST wybierac jako wynik sensora okno z najnizsza srednia cena zakupu w zakresie dnia i pory obslugiwanej przez dany sensor.
- **FR-008**: System MUST publikowac stan kazdego sensora jako godzine startu wybranego okna w formacie `HH:MM`.
- **FR-009**: System MUST publikowac w atrybucie `price` srednia cene wybranego okna zaokraglona do 3 miejsc po przecinku.
- **FR-010**: System MUST publikowac w atrybucie `is_negative` flage logiczna informujaca, czy srednia cena wybranego okna jest mniejsza od zera.
- **FR-011**: System MUST przy remisie minimalnej ceny dla nocnych kandydatow wybierac okno, ktore konczy sie najblizej godziny 06:00.
- **FR-012**: System MUST przy remisie minimalnej ceny dla dziennych kandydatow wybierac okno, ktore zaczyna sie najblizej godziny 13:00.
- **FR-012a**: System MUST przy dalszym remisie po zastosowaniu reguly bliskosci do 13:00 wybierac wczesniejsze dzienne okno, aby wynik byl deterministyczny.
- **FR-013**: System MUST traktowac sensor jako niedostepny, jesli dla jego dnia i zakresu czasu nie da sie wiarygodnie wyznaczyc pelnego dwugodzinnego okna.
- **FR-014**: System MUST publikowac atrybuty ceny i flagi ceny ujemnej tylko wtedy, gdy sensor ma wyznaczone poprawne okno.
- **FR-015**: System MUST utrzymywac niezaleznosc wynikow pomiedzy dniem i noca oraz pomiedzy dzisiaj i jutrem, tak aby brak danych lub zmiana ceny w jednym wycinku nie zmienialy pozostalych trzech sensorow poza ich wlasnym zakresem.

### Key Entities *(include if feature involves data)*

- **Dzienny Zestaw Cen Zakupu**: Zbior cen zakupu przypisanych do jednego dnia lokalnego, wykorzystywany do wyznaczenia okien dla dzisiaj albo dla jutra.
- **Godzinowy Rekord Ceny Zakupu**: Jedna wartosc ceny zakupu przypisana do znacznika czasu w polach `time` i `price`, stanowiaca podstawowy element payloadu `prices_today` albo `prices_tomorrow`.
- **Kandydackie Okno Zakupu**: Dwugodzinny przedzial czasu nalezacy w calosci do nocnego albo dziennego zakresu, oceniany pod katem sredniej ceny zakupu.
- **Ranking Okien Zakupu**: Uporzadkowany zbior kandydackich okien dla jednego dnia i jednej pory, w ktorym pierwsze miejsce zajmuje okno o najnizszej sredniej cenie po zastosowaniu reguly rozstrzygania remisow.
- **Sensor Okna Zakupu**: Wynikowa encja publikujaca godzine startu najlepszego okna oraz atrybuty `price` i `is_negative`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Przy kompletnych danych cen zakupu dla obu dni i obu zakresow czasu uzytkownik otrzymuje cztery nowe sensory, z ktorych kazdy wskazuje poprawna godzine startu najlepszego okna dla swojego zakresu.
- **SC-002**: W 100% przypadkow publikowana cena okna odpowiada sredniej cenie wybranego dwugodzinnego przedzialu i jest prezentowana z dokladnoscia do 3 miejsc po przecinku.
- **SC-003**: W 100% przypadkow, gdy srednia cena wybranego okna jest ujemna, odpowiadajacy sensor publikuje flage ceny ujemnej ustawiona na prawda.
- **SC-004**: W 100% przypadkow remisow cenowych sensory nocne wybieraja okno konczace sie najblizej 06:00, a sensory dzienne wybieraja okno rozpoczynajace sie najblizej 13:00.
- **SC-005**: W 100% przypadkow niekompletnych danych tylko dotkniety sensor pozostaje niedostepny i nie publikuje pozornie poprawnej godziny startu ani atrybutow.
- **SC-006**: Wdrozenie funkcji nie zmienia liczby ani funkcjonalnosci sensorow, ktore istnialy w integracji przed dodaniem tych czterech nowych encji.

## Assumptions

- Istniejace zrodlo cen zakupu udostepnia osobne zestawy danych dla dzisiaj i dla jutra.
- Wejsciowe dane cen zakupu sa dostarczane przez istniejace payloady `prices_today` i `prices_tomorrow`, a kazdy poprawny rekord zawiera `time` i `price`.
- Pusta lista `prices_tomorrow` jest interpretowana jako brak danych dla jutra, a nie jako poprawny przypadek z zerowa liczba kandydatow.
- Dane cenowe pozwalaja wyznaczyc srednia cene dla kolejnych dwugodzinnych okien mieszczacych sie w wymaganych zakresach czasu.
- Kandydackie okna sa porownywane tylko dla startow przypadajacych o pelnej godzinie.
- Publikowany kontrakt atrybutow nowych sensorow uzywa kluczy `price` i `is_negative`.
- Stan sensora ma prezentowac tylko godzine startu, poniewaz przy stalej dlugosci 2 godzin moment zakonczenia wynika jednoznacznie z wybranego okna.
- Flaga ceny ujemnej odnosi sie do sredniej ceny wybranego okna, a nie do pojedynczego punktu cenowego z jego wnetrza.
- Gdy kilka dziennych okien o tej samej minimalnej cenie zaczyna sie w jednakowej odleglosci od 13:00, bezpiecznym domyslnym rozstrzygnieciem jest wybor wczesniejszego startu.
- Gdy system nie moze wiarygodnie wyznaczyc pelnego dwugodzinnego okna dla danego sensora, bezpieczniejsze jest pozostawienie sensora niedostepnym niz publikacja niepelnej rekomendacji.