# Energy Optimizer Constitution

Ten dokument definiuje trwałe zasady rozwoju integracji `energy_optimizer`. Ma charakter normatywny: nowe funkcje, refaktoryzacje i decyzje architektoniczne SHOULD być oceniane względem tych reguł, a odstępstwa MUST być jawnie uzasadnione. Słowa `MUST`, `SHOULD`, `MAY` i `MUST NOT` są używane świadomie, w znaczeniu normatywnym, a nie jako zabieg stylistyczny.

## Vision & Scope

- Integracja MUST rozwijać Home Assistant jako warstwę decyzyjną dla domowego magazynu energii, a nie jako własny system akwizycji danych lub bezpośredni sterownik sprzętowy.
- Integracja MUST skupiać się na optymalizacji zachowań baterii na podstawie cen energii, stanu magazynu, prognoz PV, okien czasowych i reguł harmonogramu.
- Integracja SHOULD publikować do Home Assistant wynikowe decyzje, stany diagnostyczne, snapshoty harmonogramu oraz encje konfiguracyjne potrzebne do obserwowalności i kontroli działania.
- Zakres integracji MAY obejmować nowe scenariusze decyzyjne lub nowe encje pomocnicze tylko wtedy, gdy wspierają główny cel optymalizacji energii w istniejącym modelu HA.
- Integracja MUST NOT rozszerzać się w kierunku ogólnej platformy telemetrycznej, uniwersalnego klienta falowników ani niezależnego systemu prognozowania poza tym, co jest potrzebne do logiki optymalizacji.

## Project purpose

- Integracja MUST wyznaczać i uruchamiać scenariusze sterowania energią, takie jak ładowanie poranne, ładowanie popołudniowe, zachowanie nocne, sprzedaż energii oraz działania blokujące lub przywracające określone stany pracy.
- Integracja MUST opierać decyzje na stanach encji już obecnych w Home Assistant i traktować HA jako źródło prawdy dla cen, stanu baterii, prognoz oraz encji sterujących.
- Integracja SHOULD wystawiać do Home Assistant encje diagnostyczne i konfiguracyjne związane z baterią, cenami, harmonogramem, historią optymalizacji, balansowaniem i trybami kontrolnymi.
- Integracja MUST zachowywać czytelny ślad działania poprzez usługi domenowe, sensory śledzące decyzje i logowanie zdarzeń operacyjnych.

## Tech stack

- Kod integracji MUST pozostać implementacją w Pythonie zgodną z asynchronicznym modelem wykonania Home Assistant.
- Integracja MUST pozostawać Home Assistant custom component w domenie `energy_optimizer`, konfigurowanym przez `config_flow` i gotowym do dystrybucji przez HACS.
- Publiczne platformy encji MUST być ograniczane do tych, które są uzasadnione modelem domeny; bazowy zestaw platform tej integracji stanowią `sensor`, `binary_sensor` i `switch`, a każde rozszerzenie MUST być uzasadnione przypadkiem domenowym.
- Integracja SHOULD korzystać z mechanizmów natywnych Home Assistant, takich jak config entries, usługi domenowe, event listeners i restore-state, zamiast wprowadzać równoległe warstwy infrastrukturalne.
- Zależności zewnętrzne SHOULD pozostawać na poziomie integracji Home Assistant i encji HA; integracja MUST NOT uzależniać się od bibliotek zewnętrznych bez wyraźnej potrzeby domenowej.

## Architectural principles

- Każdy wpis konfiguracyjny MUST być obsługiwany przez pojedynczy coordinator odpowiedzialny za wspólny dostęp do odczytywanych stanów i współdzielone dane runtime.
- Odczyt danych SHOULD być scentralizowany, a encje SHOULD konsumować dane przez wspólną warstwę bazową zamiast duplikować bezpośrednie pobieranie stanów.
- Kod MUST pozostawać rozdzielony na moduły odpowiedzialności: obliczenia, logikę decyzyjną, sterowanie encjami HA, obsługę usług oraz harmonogramowanie.
- Pliki platform root-level MUST pełnić rolę warstwy rejestracji encji i integracji z `hass.data`, a nie miejsca dla ciężkiej logiki biznesowej.
- Logika scenariuszy decyzyjnych SHOULD być utrzymywana jako osobna warstwa domenowa, możliwa do uruchomienia zarówno przez scheduler, jak i przez usługi ręczne.
- Sterowanie urządzeniami MUST odbywać się przez usługi i encje Home Assistant; integracja MUST NOT wprowadzać równoległego kanału sterowania omijającego HA.
- Encje przechowujące stan diagnostyczny lub kontrolny SHOULD wykorzystywać mechanizmy przywracania stanu, gdy utrata danych po restarcie pogarszałaby obserwowalność lub ciągłość działania.

## Naming & conventions

- Domena logiczna, namespace i identyfikatory integracji MUST używać nazwy `energy_optimizer`.
- `unique_id` encji MUST być stabilne i powiązane z `config_entry.entry_id`, aby ograniczać migracje i zachować spójność rejestru encji.
- Encje SHOULD należeć do jednego logicznego urządzenia integracji identyfikowanego przez `(energy_optimizer, entry_id)`, o ile nie powstanie mocny powód domenowy do innego modelu urządzeń.
- Nazewnictwo encji SHOULD preferować `translation_key`; nowe encje MUST NOT wprowadzać zbędnych, twardo zakodowanych nazw, jeśli mogą korzystać z translacji.
- `device_class`, `state_class` i `native_unit_of_measurement` MUST odzwierciedlać semantykę danych zgodnie z modelami Home Assistant.
- Encje konfiguracyjne SHOULD być oznaczane `EntityCategory.CONFIG`, a encje diagnostyczne SHOULD być oznaczane `EntityCategory.DIAGNOSTIC`, gdy odpowiada to ich funkcji.
- Nazwy usług domenowych MUST pozostawać krótkie, opisowe i spójne z językiem scenariuszy decyzyjnych.
- Logowanie MUST używać lokalnego loggera modułowego i SHOULD rozróżniać poziomy `debug`, `info`, `warning` i `error` zgodnie z wagą zdarzenia.

## Constraints & non-goals

- Integracja MUST pozostać konfigurowana przez UI; nowe funkcje MUST NOT wymagać YAML jako podstawowego kanału konfiguracji.
- Integracja MUST zakładać, że źródła cen, prognoz PV, telemetrii baterii i encji sterujących są dostarczane przez inne integracje lub istniejące encje HA.
- Integracja MUST degradować się w sposób kontrolowany, gdy funkcje opcjonalne nie są skonfigurowane albo gdy część danych wejściowych jest niedostępna lub nienumeryczna.
- Integracja MUST NOT brać odpowiedzialności za pełny lifecycle komunikacji z falownikiem, zewnętrznymi API cenowymi lub własnym systemem gromadzenia danych historycznych poza potrzebami lokalnej logiki optymalizacji.
- Rozbudowa projektu SHOULD faworyzować obserwowalność, testowalność i przewidywalność decyzji nad wzrost liczby funkcji.
- Dokument ten definiuje kierunek i reguły rozwoju; nie jest pełnym opisem bieżącej implementacji i MUST być aktualizowany wtedy, gdy zmieniają się trwałe zasady projektu, a nie tylko chwilowy stan kodu.

## Quality, Testing & Observability

- Kluczowe ścieżki decyzyjne (wybór scenariuszy ładowania/rozładowania) MUST mieć testy jednostkowe lub integracyjne z deterministycznymi danymi wejściowymi.
- Testy obliczeń SHOULD być niezależne od Home Assistant i opierać się na czystych funkcjach domenowych.
- Nowe funkcje optymalizacji MUST dodawać przynajmniej jedną formę obserwowalności: sensor diagnostyczny, atrybut stanu, event lub wpis logu, który pozwala odtworzyć tok decyzji.
- Logowanie błędów i degradacji SHOULD być spójne i zawierać informacje niezbędne do debugowania bez wchodzenia w kod.