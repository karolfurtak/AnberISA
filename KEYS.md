# AnberISA — mapowanie przycisków per-ekran

Kody **REALNE** (egzemplarz Karola, źródło: AnberNet/konfiguracja, skill `rg40xx-input-mapping`):
A=304 · B=305 · Y=306 · X=307 · **R1=309** · **L2=314** · **R2=315** ·
pula{308,310,311,312,313}=**L1**/SELECT/START · MENU=354 · POWER=116 (`event0`) · D-pad=EV_ABS 16/17.

> Legenda na dole każdego ekranu MUSI zgadzać się z tą tabelą.

| Ekran | Przycisk (kod) | Akcja |
|---|---|---|
| MENU | A (304) | wybierz pozycję |
| MENU | D-pad ↑↓ (ABS 17) / L-stick | nawigacja |
| MENU | B (305) / MENU (354) | wyjście z apki |
| PUNKT | D-pad ↑↓ (ABS 17) | wybór pola |
| PUNKT | D-pad ←→ (ABS 16) | ± wartość |
| PUNKT | L1 (pula) / L2 (314) | krok − / + |
| PUNKT | R1 (309) | jednostka **ciśnienia** (cykl, per-ekran) |
| PUNKT | R2 (315) | jednostka **wysokości** |
| PUNKT | X (307) | ΔT (odchyłka od ISA) |
| PUNKT | B (305) | menu |
| TABELA | D-pad / L1 / L2 | pole / krok |
| TABELA | R1 (309) | jednostka ciśnienia |
| TABELA | A (304) | przelicz tabelę |
| TABELA | R2 (315) | zapis **CSV** |
| TABELA | B (305) przytrzymane ≥0,6 s | czyść wyniki |
| WYKRES | D-pad / L1 / L2 | pole / krok |
| WYKRES | R1 (309) | jednostka ciśnienia |
| WYKRES | A (304) | generuj wykres |
| WYKRES | B (305) przytrzymane ≥0,6 s | czyść podgląd |
| **INWERSJA** | D-pad ↑↓ (ABS 17) | wybór pola (Tryb / wartość / T·ΔT) |
| **INWERSJA** | D-pad ←→ (ABS 16) | ± wartość / zmiana trybu |
| **INWERSJA** | L1 (pula) / L2 (314) | krok − / + |
| **INWERSJA** | R1 (309) | jednostka ciśnienia |
| **INWERSJA** | X (307) | ΔT |
| **INWERSJA** | A (304) | oblicz |
| **INWERSJA** | **R2 (315)** | **generuj raport PDF** (z rozpisanymi obliczeniami) |
| **INWERSJA** | B (305) przytrzymane ≥0,6 s | czyść wynik/komunikaty |
| **INWERSJA** | B (305) | menu |
| NORMY | D-pad ↑↓ (ABS 17) / L-stick | przewijanie (±1 / ciągłe) |
| NORMY | L1 (pula) | −5 linii |
| NORMY | R1 (309) | +5 linii |
| NORMY | L2 (314) / R2 (315) | +20 linii (strona **w dół**) |
| NORMY | X (307) | −20 linii (strona **w górę**) |
| NORMY | B (305) | menu |

Uwagi:
- Krótkie B = wstecz/menu; **przytrzymane B (≥0,6 s)** = czyść (TABELA/WYKRES/INWERSJA).
  Fizyczny SELECT jest w puli {308,310,311,312,313} razem z L1/START (nieodróżnialne),
  więc „SEL=czyść" nie dało się zrealizować.
- W NORMACH strona w dół siedzi na kodach 314/315 (fizyczne L2/R2 tego egzemplarza —
  akcje nienaruszalne); stronę w górę dostał wolny X (307).

## INWERSJA — 4 tryby (przełączane polem „Tryb" ←/→)
0. `p → h_p` — wysokość ciśnieniowa
1. `ρ → h_ρ` — wysokość gęstościowa
2. `p, T → h_ρ` — gęstościowa z ciśnienia i temperatury
3. `h, T → h_ρ` — gęstościowa z wysokości i temperatury

**R2 (315)** w INWERSJI generuje PDF dla bieżącego trybu →
`/mnt/data/sprawozdania/raporty/AnberISA/inwersja_trybN_<data>.pdf`
(silnik `raport.py`, równania renderowane graficznie przez matplotlib mathtext).
Wcześniej R2 robił „wartość +" — dublowało D-pad → (stąd przeniesienie na raport).
