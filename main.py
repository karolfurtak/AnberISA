#!/usr/bin/env python3
"""AnberISA — interaktywny frontend SDL2 dla biblioteki ISA na Anbernic.

Atmosfera wzorcowa ISO 2533:1975 / ICAO Doc 7488/3 / US Std Atmosphere 1976.

Ekrany: MENU → PUNKT / TABELA / WYKRES / INWERSJA / NORMY.

Sterowanie (wewnątrz ekranu):
  D-pad ↑/↓       — nawigacja między polami (zmiennymi)
  D-pad ←/→       — zmiana wartości aktywnego pola (krok mały)
                    w TABELI po obliczeniu: przewijanie wyników
  L1 / L2         — zmniejsz / zwiększ KROK (precyzja, o rząd wielkości)
  R1              — jednostka CIŚNIENIA (per ekran: hPa/Pa/mmHg/inHg)
  R2              — jednostka WYSOKOŚCI (PUNKT) / zapis CSV (TABELA)
  A (BTN_SOUTH)   — wykonaj akcję ekranu (oblicz / generuj)
  B (BTN_EAST)    — wstecz (w menu = wyjście)
  B przytrzymane  — czyść wyniki (TABELA / WYKRES / INWERSJA)
  X (BTN_NORTH)   — cykl ΔT (w NORMACH: strona w górę)
  Y               — cykl kroku (dodatkowo)
  UWAGA: realne kody evdev tego egzemplarza ≠ kanoniczne — patrz
         konfiguracja.md / skill rg40xx-input-mapping (R1=309, L2=314, R2=315, Y=306,
         L1/SEL/START = pula {308,310,311,312,313}).
  MENU            — wyjście do menu Anbernica

Mapowanie kodów evdev — referencja: rg40xx-buttons (event1):
  A=304, B=305, X=307, Y=308, L1=310, R1=311, L2=312, R2=313,
  SELECT=314, START=315, MENU=354, BTN_MODE=316 (oba honorowane jako exit).
  D-pad: ABS_HAT0X=16, ABS_HAT0Y=17 (dyskretne ±1).

Diagnostyka: w prawym górnym rogu wyświetla się ostatni kod EV_KEY,
co pozwala dopasować fizyczne przyciski tej konsoli do ich kodów.
"""
import os, sys, ctypes, struct, time
from pathlib import Path

os.environ.pop('SDL_VIDEODRIVER', None)
os.environ['PYSDL2_DLL_PATH'] = '/usr/lib'

import sdl2
from power_screen import ScreenPowerToggle
from PIL import Image, ImageDraw, ImageFont

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from isa_lib import isa, pressure_altitude, density_altitude
from isa_lib import constants as C

# ── stałe wyświetlania ───────────────────────────────────────────────────────
W, H = 640, 480
FONT_PATH = '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf'
FONT_SM, FONT_MD, FONT_LG = 12, 15, 20

BG  = (10, 14, 22, 255)
FG  = (210, 220, 230, 255)
ACC = (80, 180, 255, 255)
GRN = (80, 220, 120, 255)
YEL = (255, 210, 60, 255)
RED = (255, 90, 80, 255)
DIM = (120, 130, 145, 255)
SEL = (255, 230, 90, 255)
SEP = (40, 55, 75, 255)

LOG = Path('/mnt/data/anberisa.log')
PREF = Path('/mnt/data/anberisa_prefs.json')   # preferencje (jednostki/tryb/krok) — przeżywają restart
WYK_DIR = Path('/mnt/data/anberisa_wykresy')
WYK_DIR.mkdir(parents=True, exist_ok=True)
TAB_DIR = Path('/mnt/data/anberisa_tabele')
TAB_DIR.mkdir(parents=True, exist_ok=True)

# ── evdev — gamepad (event1) ────────────────────────────────────────────────
EV_KEY, EV_ABS = 1, 3
_EV = struct.Struct('llHHi')
EV_SIZE = _EV.size

# Kody przycisków RG40XX V (event1). Kanonicznie (dokumentacyjnie): A=304 B=305
# X=307 Y=308, TL/TR/TL2/TR2=310-313, SELECT=314 START=315. REALNA mapa TEGO
# egzemplarza (patrz KEYS.md): R1=309, L2=314, R2=315, Y=306,
# pula {308,310,311,312,313} = L1/SELECT/START (nieodróżnialne).
BTN_A, BTN_B, BTN_X = 304, 305, 307
BTN_MODE = 316
KEY_MENU = 354
EXIT_KEYS = {BTN_MODE, KEY_MENU}
B_HOLD_CLEAR_S = 0.6   # przytrzymanie B >= tyle sekund = czyść (TABELA/WYKRES/INWERSJA)

# Lewy analog (RG40XX V, event1) — empiryczne kody z anbercc/main.py:
# ABS code 3 = oś Y lewej gałki, zakres ~±4096.
ABS_LY_CODE = 3
ANALOG_DEADZONE = 400      # ~10% z 4096 (RG40XX V zakres ±4096)
ANALOG_MAX      = 4096
ANALOG_SLOW_MS  = 120
ANALOG_FAST_MS  = 20

# AnberISA: tryby kroku — D-pad ←→ używa wybranego mnożnika; Y cykluje.
STEP_MODES = [0.001, 0.01, 0.1, 1, 10, 100, 1000, 10000, 100000]

# ── modele danych ekranów ───────────────────────────────────────────────────
UNITS = ['m', 'ft', 'km']           # jednostki wysokości
DT_CYCLE = [0.0, 15.0, -15.0, 30.0] # ISA, ISA+15, ISA-15, ISA+30
# Jednostki ciśnienia (cykl R1, osobno per ekran): (etykieta, Pa/jednostkę, miejsca po przecinku)
P_UNITS = [('hPa', 100.0, 3), ('Pa', 1.0, 2), ('mmHg', 133.322368, 3), ('inHg', 3386.389, 3)]


# Górny limit WPROWADZANEGO ciśnienia [Pa] (INWERSJA). Powyżej p0 apka nie
# clampuje po cichu: tryb 0 pokazuje komunikat "poza zakresem ISA", tryby 2/3
# liczą poprawną (ujemną) wysokość gęstościową. 150 kPa pokrywa każdy realny wyż.
P_INPUT_MAX = 150_000.0


# ── główna klasa aplikacji ──────────────────────────────────────────────────
class AnberISA:
    def __init__(self):
        # Rotacja logu: powyżej 200 kB zostaw tylko ostatnie ~50 kB
        try:
            if LOG.exists() and LOG.stat().st_size > 200_000:
                LOG.write_bytes(LOG.read_bytes()[-50_000:])
        except Exception:
            pass
        self.log = LOG.open('a', encoding='utf-8')
        self.log.write(f'\n[{time.strftime("%H:%M:%S")}] start\n'); self.log.flush()

        if sdl2.SDL_Init(sdl2.SDL_INIT_VIDEO | sdl2.SDL_INIT_EVENTS) != 0:
            self.log.write(f'SDL_Init FAIL: {sdl2.SDL_GetError()}\n'); self.log.flush()

        self.win = sdl2.SDL_CreateWindow(
            b'AnberISA',
            sdl2.SDL_WINDOWPOS_UNDEFINED, sdl2.SDL_WINDOWPOS_UNDEFINED,
            0, 0,
            sdl2.SDL_WINDOW_FULLSCREEN_DESKTOP | sdl2.SDL_WINDOW_SHOWN
        )
        self.ren = sdl2.SDL_CreateRenderer(self.win, -1, sdl2.SDL_RENDERER_SOFTWARE)
        if not self.ren:
            self.ren = sdl2.SDL_CreateRenderer(self.win, -1, 0)

        self.img = Image.new('RGBA', (W, H), BG)
        self.draw = ImageDraw.Draw(self.img)
        self.fsm = ImageFont.truetype(FONT_PATH, FONT_SM)
        self.fmd = ImageFont.truetype(FONT_PATH, FONT_MD)
        self.flg = ImageFont.truetype(FONT_PATH, FONT_LG)

        # gamepad
        self.gp_fd = None
        try:
            self.gp_fd = os.open('/dev/input/event1', os.O_RDONLY | os.O_NONBLOCK)
            self.log.write('gamepad event1 OK\n'); self.log.flush()
            # Wyłączność na wejście (EVIOCGRAB) — inne procesy nie widzą klawiszy.
            # Fallback: bez grab (apka działa dalej) — reguła SDL2-apek RG40XX V.
            try:
                import fcntl
                fcntl.ioctl(self.gp_fd, 0x40044590, 1)   # EVIOCGRAB=1
                self.log.write('gamepad grab OK\n'); self.log.flush()
            except Exception as e:
                self.log.write(f'gamepad grab FAIL (dziala bez grab): {e}\n'); self.log.flush()
        except Exception as e:
            self.log.write(f'gamepad FAIL: {e}\n'); self.log.flush()

        self._tex = None

        # stan aplikacji
        self.screen = 'menu'    # menu / point / table / plot / invert / norms
        # indeks jednostki ciśnienia OSOBNO dla każdego ekranu (cykl R1)
        self.p_unit = {'point': 0, 'table': 0, 'plot': 0, 'invert': 0}
        self.menu_idx = 0
        self.norms_scroll = 0

        # diagnostyka — kod ostatnio naciśniętego przycisku
        self.last_btn = '—'

        # PUNKT
        self.point_h = 11000.0
        self.point_dT_idx = 0
        self.point_unit_idx = 0
        self.point_field = 0    # 0=h, 1=dT, 2=jednostka
        self.step_mode_idx = 3  # STEP_MODES: 0=×0.001 … 3=×1 (domyślny) … (L1−/L2+, Y)
        self.point_scroll = 0   # offset wierszy output gdy nie mieszczą się

        # TABELA
        self.tab_h0 = 0.0
        self.tab_h1 = 20000.0
        self.tab_step = 1000.0
        self.tab_dT = 0.0
        self.tab_field = 0      # 0=h0, 1=h1, 2=step, 3=dT
        self.tab_scroll = 0
        self.tab_rows = []
        self.tab_status = ''
        self.tab_save_path = None

        # WYKRES
        self.plot_h0 = 0.0
        self.plot_h1 = 30000.0
        self.plot_n = 150
        self.plot_field = 0
        self.plot_path = None
        self.plot_status = ''

        # INWERSJA
        self.inv_mode = 0       # 0=p->h_p, 1=rho->h_rho, 2=p,T->h_rho, 3=h,T->h_rho
        self.inv_p = 50000.0
        self.inv_rho = 0.5
        self.inv_dT = 0.0
        self.inv_T_C = 15.0     # temperatura [°C] dla trybów p,T i h,T
        self.inv_h = 1000.0     # wysokość [m] dla trybu h,T->h_rho
        self.inv_field = 0      # 0=mode, 1=value(p/rho/h), 2=ΔT lub T[°C]
        self.export_msg = ''    # komunikat eksportu raportu PDF (INWERSJA)
        self.inv_result = None
        self.inv_status = ''    # komunikat "poza zakresem ISA" / błąd (zamiast cichego NIC)
        self.inv_rho_calc = None  # ρ wyliczona w trybach 2/3 (NIE nadpisuje inv_rho usera)
        self.inv_snap = None    # migawka wejść z chwili obliczenia (A) — spójny raport PDF
        self._b_down_ts = None  # timestamp wciśnięcia B (długie B = czyść)

        # Lewy analog — stan auto-repeat (wzorzec z anbercc/main.py)
        self.analog_y = 0
        self.analog_next = 0.0

        self._load_prefs()      # nadpisz domyślne jednostki/tryb/krok zapamiętanymi

    # ── preferencje (przeżywają restart) ─────────────────────────────────────
    def _load_prefs(self):
        try:
            import json
            d = json.loads(PREF.read_text(encoding='utf-8'))
            for k, v in (d.get('p_unit') or {}).items():
                if k in self.p_unit and isinstance(v, int) and 0 <= v < len(P_UNITS):
                    self.p_unit[k] = v
            for attr, n in (('point_unit_idx', len(UNITS)),
                            ('step_mode_idx', len(STEP_MODES)),
                            ('inv_mode', 4)):
                v = d.get(attr)
                if isinstance(v, int) and 0 <= v < n:
                    setattr(self, attr, v)
        except Exception:
            pass

    def _save_prefs(self):
        try:
            import json
            PREF.write_text(json.dumps({
                'p_unit': self.p_unit,
                'point_unit_idx': self.point_unit_idx,
                'step_mode_idx': self.step_mode_idx,
                'inv_mode': self.inv_mode,
            }), encoding='utf-8')
        except Exception as e:
            self.log.write(f'prefs save ERR: {e}\n'); self.log.flush()

    # ── input ───────────────────────────────────────────────────────────────
    def _poll_gamepad(self):
        if self.gp_fd is None:
            return []
        out = []
        try:
            while True:
                buf = os.read(self.gp_fd, EV_SIZE)
                if not buf or len(buf) < EV_SIZE:
                    break
                _s, _us, etype, code, value = _EV.unpack(buf)
                out.append((etype, code, value))
        except BlockingIOError:
            pass
        except Exception as e:
            self.log.write(f'gamepad read ERR: {e}\n'); self.log.flush()
        return out

    # ── pomocnicze tekst/grafika ───────────────────────────────────────────
    def _text(self, x, y, txt, font=None, color=FG):
        self.draw.text((x, y), txt, font=font or self.fsm, fill=color)

    def _hline(self, y, color=SEP):
        self.draw.line([(0, y), (W, y)], fill=color, width=1)

    def _box(self, x, y, w, h, color=SEP):
        self.draw.rectangle([(x, y), (x+w, y+h)], outline=color)

    # ── render: nagłówek + stopka wspólne ──────────────────────────────────
    def _header(self, title):
        self._text(8, 6, '⬡ AnberISA', self.fmd, ACC)
        tw = self.fmd.getlength(title)
        self._text(W//2 - tw//2, 6, title, self.fmd, FG)
        ts = time.strftime('%H:%M')
        self._text(W - 50, 6, ts, self.fmd, DIM)
        # pasek diagnostyki — zawsze pokazuje ostatni kod EV_KEY
        self._text(W - 160, 22, f'btn:{self.last_btn}', self.fsm, DIM)
        self._hline(28)

    def _footer(self, hints):
        self._hline(H - 22)
        self._text(8, H - 16, hints, self.fsm, DIM)

    # ── jednostka ciśnienia (per ekran) ─────────────────────────────────────
    def _p_unit(self):
        return P_UNITS[self.p_unit.get(self.screen, 0)]

    def _pconv(self, p_Pa):
        """Zwraca (sformatowana_wartość, etykieta) w jednostce bieżącego ekranu.
        Format PL: spacja = separator tysięcy, przecinek = część dziesiętna
        (kropka nie występuje → brak pomyłki 500,000 vs 500 000)."""
        lab, fac, dec = self._p_unit()
        s = f'{p_Pa / fac:,.{dec}f}'.replace(',', ' ').replace('.', ',')
        return s, lab

    # ── EKRAN: MENU ─────────────────────────────────────────────────────────
    def render_menu(self):
        self.draw.rectangle([(0, 0), (W, H)], fill=BG)
        self._header('MENU')

        items = [
            ('PUNKT',    'wartości na zadanej wysokości'),
            ('TABELA',   'profil h0..h1 z krokiem'),
            ('WYKRES',   'profil T, p, rho, a -> PNG'),
            ('INWERSJA', 'wysokość z p lub rho'),
            ('NORMY',    'opis zmiennych + odniesienia'),
        ]
        y = 56
        for i, (name, desc) in enumerate(items):
            sel = (i == self.menu_idx)
            col = SEL if sel else FG
            mark = '►' if sel else ' '
            self._text(60, y, f'{mark}  {name}', self.flg, col)
            self._text(220, y + 6, desc, self.fsm, DIM if not sel else FG)
            y += 42

        sl = isa(0.0)
        info = (f'ISA SL: T0={sl["T_K"]:.2f} K  p0={sl["p_Pa"]:.0f} Pa  '
                f'rho0={sl["rho_kg_m3"]:.4f} kg/m³  a0={sl["a_m_s"]:.2f} m/s')
        self._text(8, H - 50, info, self.fsm, DIM)

        self._footer('A=wybierz   D-pad ↑↓ / L-stick=nawigacja   B/MENU=wyjście')

    # ── EKRAN: PUNKT ───────────────────────────────────────────────────────
    def render_point(self):
        self.draw.rectangle([(0, 0), (W, H)], fill=BG)
        self._header('PUNKT — wartości ISA')

        unit = UNITS[self.point_unit_idx]
        dT = DT_CYCLE[self.point_dT_idx]

        # Info nagłówkowe: jednostki + ΔT + krok (cykl Y)
        step_factor = STEP_MODES[self.step_mode_idx]
        self._text(20, 36, f'h:{unit}   ΔT:{dT:+g}   krok:×{step_factor}', self.fsm, DIM)

        rows = [
            ('Wysokość:', f'{self.point_h:.1f} {unit}'),
            ('ΔT [K]:  ', f'{dT:+.0f}  (ISA{dT:+g})' if dT else '0  (ISA standard)'),
            ('Jedn.:   ', unit),
        ]
        # Krótkie wyjaśnienie ΔT — zawsze widoczne pod nagłówkiem
        self._text(420, 36, 'ΔT = odchyłka od ISA', self.fsm, DIM)
        self._text(420, 50, 'T(h) = T_ISA(h) + ΔT', self.fsm, DIM)
        self._text(420, 64, 'np. ISA+15 = gorący dzień', self.fsm, DIM)
        self._text(420, 78, '    ISA-15 = zimny dzień', self.fsm, DIM)
        y = 50
        for i, (lab, val) in enumerate(rows):
            sel = (i == self.point_field)
            col = SEL if sel else FG
            mark = '►' if sel else ' '
            self._text(20, y, f'{mark} {lab}', self.fmd, col)
            self._text(200, y, val, self.fmd, col)
            y += 26

        self._hline(y + 4)
        y += 12

        try:
            r = isa(self.point_h, dT=dT, unit_h=unit)
        except ValueError as e:
            self._text(20, y, f'BŁĄD: {e}', self.fmd, RED)
            self._footer('↑↓=pole  ←→=±wart  L1/L2=krok  R1=jedn.p  X=ΔT  B=menu')
            return

        labels = [
            ('h geopot.',     f'{r["h_geo_m"]:.2f} m', f'{r["h_geo_m"]/0.3048:.1f} ft'),
            ('h geom.',       f'{r["h_geom_m"]:.2f} m', f'{r["h_geom_m"]/0.3048:.1f} ft'),
            ('warstwa',       f'{r["layer"]}', ''),
            ('T',             f'{r["T_K"]:.3f} K', f'{r["T_K"]-273.15:+.2f} °C'),
            ('p',             '%s %s' % self._pconv(r["p_Pa"]), 'R1=jedn.'),
            ('rho',           f'{r["rho_kg_m3"]:.5f} kg/m³', ''),
            ('a',             f'{r["a_m_s"]:.3f} m/s', f'{r["a_m_s"]*3.6:.2f} km/h'),
            ('mu',            f'{r["mu_Pa_s"]:.3e} Pa·s', ''),
            ('sigma=rho/rho0',f'{r["sigma"]:.5f}', ''),
            ('delta=p/p0',    f'{r["delta"]:.5f}', ''),
            ('theta=T/T0',    f'{r["theta"]:.5f}', ''),
        ]
        # Scroll: ogranicz wiersze do tego co zmieści się przed footerem
        avail_px = (H - 50) - y
        max_rows = max(4, avail_px // 16)
        total = len(labels)
        self.point_scroll = max(0, min(max(0, total - max_rows), self.point_scroll))
        shown = labels[self.point_scroll : self.point_scroll + max_rows]
        for lab, v1, v2 in shown:
            self._text(20, y, lab, self.fsm, ACC)
            self._text(170, y, v1, self.fsm, FG)
            if v2:
                self._text(360, y, v2, self.fsm, DIM)
            y += 16
        # wskaźnik ile ukryto
        if total > max_rows:
            self._text(W - 100, H - 50,
                       f'  ▲{self.point_scroll}  ▼{total - self.point_scroll - max_rows}',
                       self.fsm, DIM)

        # legenda — tylko gdy zostało miejsce
        if y < H - 38:
            self._text(20, y + 2, 'σ=ρ/ρ0 δ=p/p0 θ=T/T0   ISO 2533 / ICAO 7488/3', self.fsm, DIM)
        self._footer('↑↓=pole  ←→=±wart  L1/L2=krok  R1=jedn.p  R2=jedn.h  X=ΔT  B=menu')

    # ── EKRAN: TABELA ──────────────────────────────────────────────────────
    def _recompute_table(self):
        h0, h1, step, dT = self.tab_h0, self.tab_h1, self.tab_step, self.tab_dT
        if step <= 0 or h1 <= h0:
            self.tab_rows = []
            self.tab_status = 'BŁĄD: wymagane h1 > h0 i krok > 0'
            return
        rows = []
        h = h0
        truncated = range_cut = False
        while h <= h1 + 1e-6:
            if len(rows) >= 200:
                truncated = True          # N6: limit — NIE po cichu
                break
            try:
                rows.append(isa(h, dT=dT))
            except ValueError:
                range_cut = True          # h poza modelem ISA (0-86 km)
                break
            h += step
        self.tab_rows = rows
        if truncated:
            self.tab_status = (f'UWAGA: limit 200 wierszy — ucięto na '
                               f'{rows[-1]["h_geo_m"]:.0f} m (zwiększ krok)')
        elif range_cut:
            self.tab_status = f'UWAGA: ucięto na {h:.0f} m — poza zakresem modelu ISA'
        elif rows:
            self.tab_status = f'OK: {len(rows)} wierszy'
        else:
            self.tab_status = 'BŁĄD: zakres poza modelem ISA'

    def render_table(self):
        self.draw.rectangle([(0, 0), (W, H)], fill=BG)
        self._header('TABELA — profil ISA')

        rows = [
            ('h0:  ', f'{self.tab_h0:.0f} m'),
            ('h1:  ', f'{self.tab_h1:.0f} m'),
            ('krok:', f'{self.tab_step:.0f} m'),
            ('ΔT:  ', f'{self.tab_dT:+.0f} K'),
        ]
        for i, (lab, val) in enumerate(rows):
            sel = (i == self.tab_field)
            col = SEL if sel else FG
            mark = '►' if sel else ' '
            x = 10 + i*155
            self._text(x, 36, f'{mark}{lab}', self.fsm, col)
            self._text(x + 50, 36, val, self.fsm, col)
        self._hline(58)

        cols = ('h[m]', 'T[K]', 'T[°C]', f'p[{self._p_unit()[0]}]', 'rho[kg/m³]', 'a[m/s]', 'sigma')
        xs = (10, 95, 170, 240, 340, 460, 540)
        y = 64
        for i, c in enumerate(cols):
            self._text(xs[i], y, c, self.fsm, ACC)
        self._hline(y + 14)
        y += 18

        if not self.tab_rows:
            self._text(20, y + 10, 'Brak danych. Naciśnij A by obliczyć.', self.fsm, DIM)
            if self.tab_status:
                col = GRN if 'OK' in self.tab_status else (RED if 'BŁĄD' in self.tab_status else YEL)
                self._text(20, H - 40, self.tab_status, self.fsm, col)
            self._footer('↑↓=pole  ←→=±wart  L1/L2=krok  R1=jedn.p  A=oblicz  R2=CSV  B=menu')
            return

        max_rows = (H - y - 40) // 14
        rows_v = self.tab_rows[self.tab_scroll:self.tab_scroll + max_rows]
        for r in rows_v:
            vals = (
                f'{r["h_geo_m"]:.0f}',
                f'{r["T_K"]:.2f}',
                f'{r["T_K"]-273.15:+.2f}',
                self._pconv(r["p_Pa"])[0],
                f'{r["rho_kg_m3"]:.5f}',
                f'{r["a_m_s"]:.2f}',
                f'{r["sigma"]:.4f}',
            )
            for i, v in enumerate(vals):
                self._text(xs[i], y, v, self.fsm, FG)
            y += 14

        n = len(self.tab_rows)
        self._text(W - 130, H - 38,
                   f'pozycja {self.tab_scroll+1}-{min(self.tab_scroll+max_rows, n)}/{n}',
                   self.fsm, DIM)

        if self.tab_status:
            col = GRN if 'OK' in self.tab_status else (RED if 'BŁĄD' in self.tab_status else YEL)
            self._text(8, H - 38, self.tab_status, self.fsm, col)

        self._footer('↑↓=pole  ←→/L-stk=scroll  Y=cykl kroku  A=oblicz  R2=CSV  B(przytrzym.)=czyść  B=menu')

    # ── EKRAN: WYKRES ──────────────────────────────────────────────────────
    def render_plot(self):
        self.draw.rectangle([(0, 0), (W, H)], fill=BG)
        self._header('WYKRES — profil ISA')

        rows = [
            ('h0:', f'{self.plot_h0:.0f} m'),
            ('h1:', f'{self.plot_h1:.0f} m'),
            ('n: ', f'{self.plot_n}'),
        ]
        for i, (lab, val) in enumerate(rows):
            sel = (i == self.plot_field)
            col = SEL if sel else FG
            mark = '►' if sel else ' '
            x = 10 + i*200
            self._text(x, 36, f'{mark}{lab} {val}', self.fmd, col)
        self._hline(64)

        if self.plot_path and Path(self.plot_path).exists():
            try:
                img = Image.open(self.plot_path).convert('RGBA')
                maxw, maxh = W - 20, H - 120
                img.thumbnail((maxw, maxh))
                ix = (W - img.width) // 2
                iy = 72
                self.img.paste(img, (ix, iy))
            except Exception as e:
                self._text(20, 80, f'Błąd odczytu PNG: {e}', self.fsm, RED)
        else:
            self._text(20, 80, 'Naciśnij A aby wygenerować wykres.', self.fmd, DIM)
            self._text(20, 100, 'Wynik zostanie zapisany w:', self.fsm, DIM)
            self._text(20, 116, str(WYK_DIR) + '/', self.fsm, ACC)

        if self.plot_status:
            col = GRN if 'OK' in self.plot_status else (RED if 'BŁĄD' in self.plot_status else YEL)
            self._text(20, H - 40, self.plot_status, self.fsm, col)

        self._footer('↑↓=pole  ←→=±wart  L1/L2=krok  R1=jedn.p  A=generuj  B(przytrzym.)=czyść  B=menu')

    def _generate_plot(self):
        try:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
        except Exception as e:
            self.plot_status = f'BŁĄD: brak matplotlib ({e})'
            return
        try:
            n = max(2, int(self.plot_n))
            h0, h1 = self.plot_h0, self.plot_h1
            if h1 <= h0:
                self.plot_status = 'BŁĄD: h1 musi być > h0'
                return
            hs = [h0 + (h1 - h0) * i / (n - 1) for i in range(n)]
            T, p, rho, a = [], [], [], []
            for h in hs:
                r = isa(h)
                T.append(r['T_K']); p.append(r['p_Pa'])
                rho.append(r['rho_kg_m3']); a.append(r['a_m_s'])
            _plab, _pfac, _ = P_UNITS[self.p_unit['plot']]
            p_disp = [pp / _pfac for pp in p]
            fig, axes = plt.subplots(2, 2, figsize=(8, 6), dpi=100)
            (ax1, ax2), (ax3, ax4) = axes
            for ax, y, lab, c in (
                (ax1, T,   'T [K]',          'tab:red'),
                (ax2, p_disp, f'p [{_plab}]', 'tab:blue'),
                (ax3, rho, 'rho [kg/m^3]',   'tab:green'),
                (ax4, a,   'a [m/s]',        'tab:orange'),
            ):
                ax.plot(y, hs, color=c, lw=1.5)
                ax.set_ylabel('h [m]')
                ax.set_xlabel(lab)
                ax.grid(True, alpha=0.3)
            fig.suptitle(f'Profil ISA: h={h0:.0f}..{h1:.0f} m, n={n}')
            fig.tight_layout()
            out = WYK_DIR / f'isa_{int(h0)}_{int(h1)}_{n}.png'
            fig.savefig(out)
            plt.close(fig)
            self.plot_path = str(out)
            self.plot_status = f'OK: {out.name}'
            self.log.write(f'wykres zapisany: {out}\n'); self.log.flush()
        except Exception as e:
            self.plot_status = f'BŁĄD: {e}'

    def _save_table_csv(self):
        if not self.tab_rows:
            self.tab_status = 'BŁĄD: brak danych do zapisu (najpierw A=oblicz)'
            return
        try:
            ts = time.strftime('%Y%m%d_%H%M%S')
            out = TAB_DIR / f'isa_tab_{int(self.tab_h0)}_{int(self.tab_h1)}_dT{int(self.tab_dT):+d}_{ts}.csv'
            with out.open('w', encoding='utf-8') as f:
                f.write(f'# AnberISA tabela ISO 2533:1975 / ICAO Doc 7488/3\n')
                f.write(f'# h0={self.tab_h0} m  h1={self.tab_h1} m  step={self.tab_step} m  dT={self.tab_dT:+g} K\n')
                f.write('h_geo_m;T_K;T_C;p_Pa;rho_kg_m3;a_m_s;sigma;delta;theta\n')
                for r in self.tab_rows:
                    f.write(
                        f'{r["h_geo_m"]:.2f};{r["T_K"]:.4f};{r["T_K"]-273.15:+.4f};'
                        f'{r["p_Pa"]:.4f};{r["rho_kg_m3"]:.6f};{r["a_m_s"]:.4f};'
                        f'{r["sigma"]:.6f};{r["delta"]:.6f};{r["theta"]:.6f}\n'
                    )
            self.tab_save_path = str(out)
            self.tab_status = f'OK: zapisano {out.name} ({len(self.tab_rows)} wierszy)'
            self.log.write(f'tabela zapisana: {out}\n'); self.log.flush()
        except Exception as e:
            self.tab_status = f'BŁĄD: {e}'

    def _clear_data(self):
        """Czyszczenie wyników bieżącego ekranu — przytrzymanie B >= 0,6 s."""
        if self.screen == 'table':
            self.tab_rows = []
            self.tab_scroll = 0
            self.tab_status = 'wyczyszczono'
            self.tab_save_path = None
        elif self.screen == 'plot':
            self.plot_path = None
            self.plot_status = 'wyczyszczono'
        elif self.screen == 'invert':
            self.inv_result = None
            self.inv_status = ''
            self.export_msg = ''
            self.inv_snap = None
            self.inv_rho_calc = None

    # ── EKRAN: INWERSJA ────────────────────────────────────────────────────
    # ── RAPORT PDF (INWERSJA) ───────────────────────────────────────────────
    def _inv_meta(self):
        """Buduje meta dla raport.generuj_pdf z MIGAWKI wejść (inv_snap) zapisanej
        w chwili obliczenia (A) — raport pozostaje spójny z wynikiem nawet gdy
        użytkownik pozmieniał pola po obliczeniu."""
        import datetime
        s = self.inv_snap
        R, p0, T0, L, g0 = C.R_air, C.p0_SL, 288.15, -0.0065, 9.80665
        rho0 = p0 / (R * T0)
        n = -g0 / (L * R) - 1.0
        h = s['result']
        m = s['mode']
        meta = {'autor': 'Karol Furtak', 'tel': '664-770-734',
                'data': datetime.date.today().strftime('%d.%m.%Y'), 'diagram': None}
        if m == 0:
            p = s['p']; pv, pl = self._pconv(p)
            meta['tytul'] = 'INWERSJA — wysokość ciśnieniowa h_p z ciśnienia p'
            meta['zmienne'] = [
                ('p', 'Ciśnienie statyczne', pv, pl),
                ('p0', 'Ciśnienie wzorcowe SL', '101325', 'Pa'),
                ('T0', 'Temperatura wzorcowa SL', '288.15', 'K'),
                ('L', 'Gradient temp. troposfery', '-0.0065', 'K/m'),
                ('R', 'Stała gazowa powietrza', f'{R:.3f}', 'J/(kg·K)'),
                ('g0', 'Przyspieszenie wzorcowe', '9.80665', 'm/s²')]
            meta['wzory_tex'] = [
                (r'$h_p$ — wysokość ciśnieniowa: wysokość w ISA o tym samym ciśnieniu (odwrócenie formuły barometrycznej troposfery)',
                 r'h_p = \dfrac{T_0}{L}\left[\left(\dfrac{p}{p_0}\right)^{-LR/g_0} - 1\right] = %.1f\ \mathrm{m}' % h)]
            meta['warunki'] = [('Zakres troposfery: h_p < 11000 m', h < 11000)]
            meta['wnioski'] = r'Wysokość ciśnieniowa $h_p = %.1f$ m — wysokość w atmosferze wzorcowej o tym samym ciśnieniu (baza altimetrii QNE/QNH/QFE).' % h
        elif m == 1:
            rho = s['rho']
            meta['tytul'] = 'INWERSJA — wysokość gęstościowa h_ρ z gęstości ρ'
            meta['zmienne'] = [
                ('ρ', 'Gęstość powietrza', f'{rho:.5f}', 'kg/m³'),
                ('ΔT', 'Odchyłka od ISA', f'{s["dT"]:+.0f}', 'K')]
            meta['wzory_tex'] = [
                (r'$h_\rho$ — wysokość gęstościowa: rozwiązanie $\rho_{ISA}(h+\Delta T)=\rho$ (iteracyjnie, bisekcja)',
                 r'\rho_{ISA}(h_\rho) = %.5f\ \mathrm{kg/m^3} \;\Rightarrow\; h_\rho = %.1f\ \mathrm{m}' % (rho, h))]
            meta['warunki'] = [('Zakres modelu ISA: 0–86 km', 0 <= h <= 86000)]
            meta['wnioski'] = r'Wysokość gęstościowa $h_\rho = %.1f$ m — wys. w ISA(+ΔT) o gęstości %.5f kg/m³.' % (h, rho)
        else:
            TK = s['T_C'] + 273.15
            rho = s['rho_calc']
            Tx = T0 * (rho / rho0) ** (1.0 / n)
            h_analit = (Tx - T0) / L   # wynik wzoru troposferycznego (jak w handle)
            if m == 2:
                p = s['p']; pv, pl = self._pconv(p)
                meta['tytul'] = 'INWERSJA — wysokość gęstościowa h_ρ z ciśnienia p i temperatury T'
                meta['zmienne'] = [
                    ('p', 'Ciśnienie', pv, pl),
                    ('T', 'Temperatura', f'{s["T_C"]:.2f}', '°C'),
                    ('R', 'Stała gazowa powietrza', f'{R:.3f}', 'J/(kg·K)')]
                first = (r'$\rho$ — gęstość rzeczywista z równania stanu gazu',
                         r'\rho = \dfrac{p}{R\,T} = \dfrac{%.0f}{%.3f\cdot%.2f} = %.5f\ \mathrm{kg/m^3}' % (p, R, TK, rho))
            else:
                p = isa(s['h'])['p_Pa']
                meta['tytul'] = 'INWERSJA — wysokość gęstościowa h_ρ z wysokości h i temperatury T'
                meta['zmienne'] = [
                    ('h', 'Wysokość (pressure alt.)', f'{s["h"]:.1f}', 'm'),
                    ('T', 'Temperatura', f'{s["T_C"]:.2f}', '°C'),
                    ('R', 'Stała gazowa powietrza', f'{R:.3f}', 'J/(kg·K)')]
                first = (r'$\rho$ — gęstość: ciśnienie ISA na wysokości h, potem równanie gazu',
                         r'\rho = \dfrac{p_{ISA}(h)}{R\,T} = \dfrac{%.0f}{%.3f\cdot%.2f} = %.5f\ \mathrm{kg/m^3}' % (p, R, TK, rho))
            meta['zmienne'].append(('ρ', 'Gęstość rzeczywista (wynik pośredni)', f'{rho:.5f}', 'kg/m³'))
            if h_analit > 11000.0:
                # S6: FAKTYCZNIE użyto modelu warstwowego (bisekcja, jak w trybie 1)
                # — wzór troposferyczny nie obowiązuje, więc NIE drukujemy go z liczbami.
                meta['wzory_tex'] = [
                    first,
                    (r'$\rho_0$ — gęstość wzorcowa na poziomie morza',
                     r'\rho_0 = \dfrac{p_0}{R\,T_0} = %.5f\ \mathrm{kg/m^3}' % rho0),
                    (r'$h_\rho$ — powyżej troposfery (wzór analityczny dałby h>11 km): '
                     r'rozwiązano $\rho_{ISA}(h_\rho)=\rho$ iteracyjnie (bisekcja, model warstwowy)',
                     r'\rho_{ISA}(h_\rho) = %.5f\ \mathrm{kg/m^3} \;\Rightarrow\; h_\rho = %.1f\ \mathrm{m}' % (rho, h))]
                meta['warunki'] = [('Zakres modelu ISA: 0–86 km', 0 <= h <= 86000)]
            else:
                meta['wzory_tex'] = [
                    first,
                    (r'$\rho_0$ — gęstość wzorcowa na poziomie morza',
                     r'\rho_0 = \dfrac{p_0}{R\,T_0} = %.5f\ \mathrm{kg/m^3}' % rho0),
                    (r'$T_x$ — temperatura ISA o tej samej gęstości ($n = -g_0/LR - 1 = %.4f$)' % n,
                     r'T_x = T_0\left(\dfrac{\rho}{\rho_0}\right)^{1/n} = %.2f\ \mathrm{K}' % Tx),
                    (r'$h_\rho$ — wysokość gęstościowa (równoważna wys. w ISA; może być ujemna)',
                     r'h_\rho = \dfrac{T_x - T_0}{L} = \dfrac{%.2f - 288.15}{-0.0065} = %.1f\ \mathrm{m}' % (Tx, h))]
                meta['warunki'] = [('Zakres troposfery (wzór analityczny): h_ρ < 11000 m', h < 11000)]
            znak = 'UJEMNA (powietrze gęstsze niż ISA na SL)' if h < 0 else 'dodatnia'
            meta['wnioski'] = (r'Wysokość gęstościowa $h_\rho = %.1f$ m (%s) — wielkość osiągowa, '
                               r'równoważna wys. w ISA o gęstości %.5f kg/m³; NIE fizyczna wysokość.' % (h, znak, rho))
        return meta

    def _export_inv_report(self):
        if self.inv_snap is None or self.inv_snap.get('result') is None:
            self.export_msg = '⚠ Najpierw oblicz (A)!'
            return
        self.export_msg = 'Generuję raport (chwila)...'
        self.render()
        try:
            import raport, time, os
            rdir = '/mnt/data/sprawozdania/raporty/AnberISA'
            os.makedirs(rdir, exist_ok=True)
            out = f"{rdir}/inwersja_tryb{self.inv_snap['mode']}_{time.strftime('%Y%m%d_%H%M%S')}.pdf"
            raport.generuj_pdf(out, self._inv_meta())
            self.export_msg = f'✔ Zapisano: {os.path.basename(out)}'
        except Exception as e:
            self.log.write(f'export ERR: {e}\n'); self.log.flush()
            self.export_msg = f'✘ Błąd: {str(e)[:42]}'

    def render_invert(self):
        self.draw.rectangle([(0, 0), (W, H)], fill=BG)
        self._header('INWERSJA — wysokość z p lub rho')
        self._text(W - 150, 8, f'krok ×{STEP_MODES[self.step_mode_idx]:g}', self.fsm, DIM)

        MODE_NAMES = ['p → h_p (wys. ciśnieniowa)',
                      'ρ → h_ρ (wys. gęstościowa)',
                      'p, T → h_ρ (z gęstości ρ=p/R·T)',
                      'h, T → h_ρ (gęstościowa z wys. i T)']
        mode_name = MODE_NAMES[self.inv_mode]
        if self.inv_mode in (0, 2):
            val_lab = f'p [{self._p_unit()[0]}]'
            val_str = self._pconv(self.inv_p)[0]
        elif self.inv_mode == 3:
            val_lab = 'h [m]'
            val_str = f'{self.inv_h:.1f}'
        else:
            val_lab = 'ρ [kg/m³]'
            val_str = f'{self.inv_rho:.4f}'
        if self.inv_mode in (2, 3):
            third = ('T [°C]:', f'{self.inv_T_C:+.2f}')
        else:
            third = ('ΔT:', f'{self.inv_dT:+.0f} K  (tylko ρ→h)')

        rows = [
            ('Tryb:', mode_name),
            (val_lab + ':', val_str),
            third,
        ]
        for i, (lab, val) in enumerate(rows):
            sel = (i == self.inv_field)
            col = SEL if sel else FG
            mark = '►' if sel else ' '
            self._text(20, 40 + i*24, f'{mark} {lab}', self.fmd, col)
            self._text(160, 40 + i*24, val, self.fmd, col)

        self._hline(118)

        if self.inv_result is not None:
            h = self.inv_result
            self._text(20, 128, 'Wynik:', self.fmd, ACC)
            self._text(20, 154, f'h_geo  = {h:.2f} m', self.fmd, FG)
            try:
                from isa_lib import geometric
                hgm = geometric(h)
                self._text(20, 178, f'h_geom = {hgm:.2f} m   ({hgm/0.3048:.1f} ft)', self.fmd, FG)
                if self.inv_mode in (2, 3):
                    # poniżej SL model warstwowy nie liczy isa() — pokazujemy WEJŚCIE
                    self._text(20, 208, f'T   = {self.inv_T_C:+.2f} °C   (wejście)', self.fsm, DIM)
                    if self.inv_mode == 2:
                        self._text(20, 224, 'p   = %s %s   (wejście)' % self._pconv(self.inv_p), self.fsm, DIM)
                    else:
                        self._text(20, 224, f'h   = {self.inv_h:.1f} m   (wejście, p z ISA)', self.fsm, DIM)
                    _rc = self.inv_rho_calc if self.inv_rho_calc is not None else self.inv_rho
                    self._text(20, 240, f'ρ   = {_rc:.5f} kg/m³', self.fsm, DIM)
                    if h < 0:
                        self._text(20, 256, '(h<0 = powietrze gęstsze niż ISA na SL — OK)', self.fsm, DIM)
                else:
                    r = isa(h, dT=(self.inv_dT if self.inv_mode == 1 else 0.0))
                    self._text(20, 208, f'T   = {r["T_K"]:.2f} K   ({r["T_K"]-273.15:+.2f} °C)', self.fsm, DIM)
                    self._text(20, 224, 'p   = %s %s' % self._pconv(r["p_Pa"]), self.fsm, DIM)
                    self._text(20, 240, f'rho = {r["rho_kg_m3"]:.5f} kg/m³', self.fsm, DIM)
                    self._text(20, 256, f'a   = {r["a_m_s"]:.2f} m/s', self.fsm, DIM)
            except Exception as e:
                self._text(20, 178, f'(błąd: {e})', self.fmd, RED)
        elif self.inv_status:
            # S1/S2/S5: zamiast cichego NIC — jasna informacja, że stan jest
            # poza zakresem atmosfery wzorcowej (albo jaki błąd wystąpił).
            col = RED if self.inv_status.startswith('BŁĄD') else YEL
            for i, ln in enumerate(self.inv_status.split('\n')):
                self._text(20, 132 + i * 18, ln, self.fsm, col)
        else:
            self._text(20, 138, 'Naciśnij A aby obliczyć.', self.fmd, DIM)

        if self.export_msg:
            col = GRN if self.export_msg.startswith('✔') else (RED if self.export_msg.startswith('✘') else YEL)
            self._text(20, H - 96, self.export_msg, self.fsm, col)

        # legenda norm — odseparowana sekcja na dole
        self._hline(H - 78)
        self._text(20, H - 72, 'h_p = wys. ciśnieniowa: h w ISA o tym samym p (QNE/QNH/QFE).', self.fsm, DIM)
        self._text(20, H - 58, 'h_ρ = wys. GĘSTOŚCIOWA: h w ISA o tej samej ρ — wielkość', self.fsm, DIM)
        self._text(20, H - 44, '      osiągowa (NIE fizyczna); h_ρ<0 = powietrze gęstsze niż ISA-SL.', self.fsm, DIM)

        self._footer('↑↓=pole ←→=±wart L1/L2=krok R1=jedn.p X=ΔT A=oblicz R2=PDF B=menu')

    # ── EKRAN: NORMY ───────────────────────────────────────────────────────
    NORMS_LINES = [
        ('NORMY I ŹRÓDŁA', ACC, FONT_MD),
        ('', FG, FONT_SM),
        ('• ISO 2533:1975  — Standard Atmosphere.', FG, FONT_SM),
        ('  Międzynarodowa norma definiująca atmosferę wzorcową do 80 km', DIM, FONT_SM),
        ('  geopotencjalnych. Wraz z Add.1:1985 i Add.2:1997.', DIM, FONT_SM),
        ('• ICAO Doc 7488/3 (1993) — Manual of the ICAO Std Atmosphere', FG, FONT_SM),
        ('  rozszerzony do 80 km geopot.; podstawa certyfikacji lotniczej', DIM, FONT_SM),
        ('  (CS-25, FAR Part 25, Annex 8 do Konwencji Chicagowskiej).', DIM, FONT_SM),
        ('• U.S. Standard Atmosphere, 1976 — NOAA/NASA/USAF;', FG, FONT_SM),
        ('  identyczny z ICAO do 32 km, rozszerzony do 86 km h_geom', DIM, FONT_SM),
        ('  (≈ 84 852 m h_geo — koniec naszego modelu).', DIM, FONT_SM),
        ('• PN-83/L-01551 — Atmosfera wzorcowa (norma polska, wycofana', FG, FONT_SM),
        ('  na rzecz ISO; spotykana w literaturze PWN i opracowaniach', DIM, FONT_SM),
        ('  PŁ / PW dla lotnictwa).', DIM, FONT_SM),
        ('• NACA Report 1235 (1955) — historyczne korzenie ICAO ISA.', FG, FONT_SM),
        ('', FG, FONT_SM),
        ('ZMIENNE I JEDNOSTKI (SI; ISO 2533 §2)', ACC, FONT_MD),
        ('', FG, FONT_SM),
        ('h_geo  [m]    — wysokość geopotencjalna.', FG, FONT_SM),
        ('               Wysokość mierzona tak jakby g=g0=const wszędzie;', DIM, FONT_SM),
        ('               niezależna od szerokości i wysokości terenu.', DIM, FONT_SM),
        ('               h = (r·Z)/(r+Z), r = 6 356 766 m (ICAO §2.3).', DIM, FONT_SM),
        ('h_geom [m]    — wysokość geometryczna Z (od MSL, ICAO §2.2).', FG, FONT_SM),
        ('               Z = (r·h)/(r-h)  — odwrócenie powyższego.', DIM, FONT_SM),
        ('T      [K]    — temperatura termodynamiczna powietrza suchego.', FG, FONT_SM),
        ('               T(h) = T_b + L_b·(h − h_b) w danej warstwie b.', DIM, FONT_SM),
        ('               (ISO 2533 §3.1; ICAO Doc 7488/3 rozdz. 2.7).', DIM, FONT_SM),
        ('p      [Pa]   — ciśnienie statyczne (ISO 2533 §3.2).', FG, FONT_SM),
        ('               L≠0: p = p_b·(T_b/T)^(g0·M/(R*·L))', DIM, FONT_SM),
        ('               L=0: p = p_b·exp(−g0·M·(h−h_b)/(R*·T_b))', DIM, FONT_SM),
        ('rho    [kg/m³]— gęstość: ρ = p·M/(R*·T)  (równanie stanu).', FG, FONT_SM),
        ('               Równoważnie: ρ = p/(R_air·T), R_air=287,05 J/(kg·K).', DIM, FONT_SM),
        ('a      [m/s]  — prędkość dźwięku: a = √(γ·R*·T/M).', FG, FONT_SM),
        ('               Równoważnie: a = √(γ·R_air·T); zależy tylko od T.', DIM, FONT_SM),
        ('mu     [Pa·s] — lepkość dynamiczna powietrza (Sutherland).', FG, FONT_SM),
        ('               μ = β·T^(3/2)/(T+S), β=1,458e-6, S=110,4 K', DIM, FONT_SM),
        ('               (ISO 2533 §3.7; ważne dla 100–1000 K).', DIM, FONT_SM),
        ('ΔT     [K]    — odchyłka temperatury od ISA na danej h.', FG, FONT_SM),
        ('               T_real(h) = T_ISA(h) + ΔT  (gradient L_b bez', DIM, FONT_SM),
        ('               zmian — atmosfera "non-standard day" ICAO §4.2).', DIM, FONT_SM),
        ('               ISA+15 = "gorący dzień", używane w certyfikacji', DIM, FONT_SM),
        ('               osiągów startowych (CS-25.105, hot-and-high).', DIM, FONT_SM),
        ('σ = ρ/ρ0      — gęstość względna (do EAS, IAS — CAS).', FG, FONT_SM),
        ('δ = p/p0      — ciśnienie względne (do FL, mocy turbiny).', FG, FONT_SM),
        ('θ = T/T0      — temperatura względna; związek: δ = σ·θ.', FG, FONT_SM),
        ('h_p    [m]    — wysokość ciśnieniowa: h taka, że p_ISA(h)=p.', FG, FONT_SM),
        ('               Standardowy QNE/QNH dla altimetrii lotniczej.', DIM, FONT_SM),
        ('h_ρ    [m]    — wysokość gęstościowa: h w ISA, na której gęstość', FG, FONT_SM),
        ('               ρ_ISA(h) = ρ rzeczywiste (z p i T). Wielkość ZASTĘPCZA,', DIM, FONT_SM),
        ('               osiągowa — NIE fizyczna wysokość nad terenem.', DIM, FONT_SM),
        ('               Decyduje o osiągach startowych (ρ → ciąg, siła nośna).', DIM, FONT_SM),
        ('               h_ρ < 0 = powietrze GĘSTSZE niż ISA na SL (zimno / wyż).', DIM, FONT_SM),
        ('', FG, FONT_SM),
        ('STAŁE (ICAO Doc 7488/3 Tab.A; ISO 2533 Tab.1)', ACC, FONT_MD),
        ('', FG, FONT_SM),
        ('g0  = 9,80665 m/s²       — przyspieszenie ziemskie wzorcowe', FG, FONT_SM),
        ('R*  = 8 314,32 J/(kmol·K)— uniwersalna stała gazowa', FG, FONT_SM),
        ('M   = 28,9644 kg/kmol    — masa molowa powietrza suchego', FG, FONT_SM),
        ('R_air=287,05287 J/(kg·K) — indywidualna stała gazowa (=R*/M)', FG, FONT_SM),
        ('γ   = 1,4                — wykł. adiabaty (5/7 powietrza dwuat.)', FG, FONT_SM),
        ('r   = 6 356 766 m        — promień Ziemi wzorcowy (h_geom↔h_geo)', FG, FONT_SM),
        ('β   = 1,458e-6 kg/(m·s·√K)— stała Sutherlanda', FG, FONT_SM),
        ('S   = 110,4 K            — temp. Sutherlanda', FG, FONT_SM),
        ('', FG, FONT_SM),
        ('WARUNKI NA POZIOMIE MORZA (MSL, h=0)', ACC, FONT_MD),
        ('', FG, FONT_SM),
        ('T0  = 288,15 K           = 15,00 °C', FG, FONT_SM),
        ('p0  = 101 325 Pa = 1013,25 hPa = 760,0 mmHg = 29,9213 inHg', FG, FONT_SM),
        ('ρ0  = 1,225 kg/m³', FG, FONT_SM),
        ('a0  = 340,294 m/s        ≈ Mach 1 na MSL ISA', FG, FONT_SM),
        ('', FG, FONT_SM),
        ('WARSTWY (h_geo, L = dT/dh; ICAO §2.7 Tab.2)', ACC, FONT_MD),
        ('', FG, FONT_SM),
        ('  0–11 000 m   troposfera        L = −6,5 K/km', FG, FONT_SM),
        ('11–20 000 m   tropopauza        L =  0       (T = 216,65 K)', FG, FONT_SM),
        ('20–32 000 m   stratosfera 1     L = +1,0 K/km', FG, FONT_SM),
        ('32–47 000 m   stratosfera 2     L = +2,8 K/km', FG, FONT_SM),
        ('47–51 000 m   stratopauza       L =  0       (T = 270,65 K)', FG, FONT_SM),
        ('51–71 000 m   mezosfera 1       L = −2,8 K/km', FG, FONT_SM),
        ('71–84 852 m   mezosfera 2       L = −2,0 K/km', FG, FONT_SM),
        ('', FG, FONT_SM),
        ('LITERATURA UZUPEŁNIAJĄCA', ACC, FONT_MD),
        ('', FG, FONT_SM),
        ('• Anderson J.D. "Introduction to Flight" (rozdz. 3 — ISA).', FG, FONT_SM),
        ('• Houghton/Carpenter "Aerodynamics for Eng. Students".', FG, FONT_SM),
        ('• Fiszdon W. "Mechanika lotu" (PWN, PL).', FG, FONT_SM),
        ('• Goraj Z. "Dynamika i aerodynamika samolotów" (PWN, PL).', FG, FONT_SM),
    ]

    def render_norms(self):
        self.draw.rectangle([(0, 0), (W, H)], fill=BG)
        self._header('NORMY — opis i odniesienia')

        view_h = H - 60   # od y=32 do y=H-28
        y0 = 34
        line_h = 14
        max_lines = view_h // line_h

        total = len(self.NORMS_LINES)
        self.norms_scroll = max(0, min(max(0, total - max_lines), self.norms_scroll))
        end = min(total, self.norms_scroll + max_lines)

        y = y0
        for txt, col, fsz in self.NORMS_LINES[self.norms_scroll:end]:
            font = self.fmd if fsz == FONT_MD else self.fsm
            self._text(12, y, txt, font, col)
            y += line_h

        if total > max_lines:
            self._text(W - 110, H - 38,
                       f'{self.norms_scroll+1}-{end}/{total}', self.fsm, DIM)

        self._footer('D-pad ↑↓=±1  L-stick=ciągły  L1=−5  R1=+5  L2/R2=+20 (strona w dół)  X=−20 (w górę)  B=menu')

    # ── render: dispatch ────────────────────────────────────────────────────
    def render(self):
        if self.screen == 'menu':    self.render_menu()
        elif self.screen == 'point': self.render_point()
        elif self.screen == 'table': self.render_table()
        elif self.screen == 'plot':  self.render_plot()
        elif self.screen == 'invert': self.render_invert()
        elif self.screen == 'norms': self.render_norms()
        raw = self.img.tobytes()
        surf = sdl2.SDL_CreateRGBSurfaceWithFormatFrom(
            raw, W, H, 32, W*4, sdl2.SDL_PIXELFORMAT_RGBA32)
        if self._tex:
            sdl2.SDL_DestroyTexture(self._tex)
        self._tex = sdl2.SDL_CreateTextureFromSurface(self.ren, surf)
        sdl2.SDL_FreeSurface(surf)
        sdl2.SDL_RenderClear(self.ren)
        sdl2.SDL_RenderCopy(self.ren, self._tex, None, None)
        sdl2.SDL_RenderPresent(self.ren)

    # ── nawigacja kursora (zmiana aktywnego pola) ───────────────────────────
    def nav(self, dy):
        if self.screen == 'point':    self.point_field = (self.point_field + dy) % 3
        elif self.screen == 'table':  self.tab_field   = (self.tab_field   + dy) % 4
        elif self.screen == 'plot':   self.plot_field  = (self.plot_field  + dy) % 3
        elif self.screen == 'invert': self.inv_field   = (self.inv_field   + dy) % 3

    # ── helper: zacisnij wysokosc do zakresu jednostki ──────────────────────
    def _clamp_h(self, h, unit):
        if unit == 'ft':   return max(0.0, min(C.H_MAX_GEO/0.3048, h))
        if unit == 'km':   return max(0.0, min(C.H_MAX_GEO/1000.0, h))
        return max(0.0, min(C.H_MAX_GEO, h))

    # ── helper: zmiana jednostki wysokości = KONWERSJA wartości ─────────────
    def _set_point_unit(self, new_idx):
        """PUNKT: przełącz jednostkę h przeliczając wartość (11000 m -> 36089 ft),
        a nie reinterpretując liczbę (11000 m -> '11000 ft')."""
        _TO_M = {'m': 1.0, 'ft': 0.3048, 'km': 1000.0}
        old_u = UNITS[self.point_unit_idx]
        new_u = UNITS[new_idx]
        self.point_h = self._clamp_h(self.point_h * _TO_M[old_u] / _TO_M[new_u], new_u)
        self.point_unit_idx = new_idx

    # ── zmiana wartości aktywnego pola (dy = ±1, big = ±duży krok) ──────────
    def adjust(self, dy, big):
        if self.screen == 'point':
            f = self.point_field
            if f == 0:
                unit = UNITS[self.point_unit_idx]
                factor = STEP_MODES[self.step_mode_idx]
                if unit == 'm':    base = 1.0      # 1 m × factor
                elif unit == 'ft': base = 1.0      # 1 ft × factor
                else:              base = 0.001    # 0.001 km × factor
                self.point_h = self._clamp_h(self.point_h + dy * base * factor, unit)
            elif f == 1:
                self.point_dT_idx = (self.point_dT_idx + dy) % len(DT_CYCLE)
            elif f == 2:
                self._set_point_unit((self.point_unit_idx + dy) % len(UNITS))

        elif self.screen == 'table':
            f = self.tab_field
            factor = STEP_MODES[self.step_mode_idx]
            if f == 0:    # h0 — wysokość początkowa (0 m = poziom morza)
                self.tab_h0 = max(0.0, self.tab_h0 + dy * 1.0 * factor)
                if self.tab_h1 <= self.tab_h0:
                    self.tab_h1 = self.tab_h0 + self.tab_step
            elif f == 1:  # h1 — wysokość końcowa
                self.tab_h1 = max(self.tab_h0 + self.tab_step, self.tab_h1 + dy * 1.0 * factor)
            elif f == 2:  # krok h
                self.tab_step = max(1.0, self.tab_step + dy * 1.0 * factor)
            elif f == 3:  # ΔT
                self.tab_dT = max(-50.0, min(50.0, self.tab_dT + dy * 1.0 * factor))

        elif self.screen == 'plot':
            f = self.plot_field
            factor = STEP_MODES[self.step_mode_idx]
            if f == 0:    # h0
                self.plot_h0 = max(0.0, self.plot_h0 + dy * 1.0 * factor)
                if self.plot_h1 <= self.plot_h0:
                    self.plot_h1 = self.plot_h0 + 100
            elif f == 1:  # h1
                self.plot_h1 = max(self.plot_h0 + 100, self.plot_h1 + dy * 1.0 * factor)
            elif f == 2:  # n
                self.plot_n = max(10, min(500, self.plot_n + dy * 1 * factor))

        elif self.screen == 'invert':
            f = self.inv_field
            factor = STEP_MODES[self.step_mode_idx]
            if f == 0:    # tryb: p / ρ / p,T / h,T
                self.inv_mode = (self.inv_mode + dy) % 4
                self._save_prefs()
            elif f == 1:
                if self.inv_mode in (0, 2):   # p — krok liczony w WYBRANEJ jednostce
                    base_pa = P_UNITS[self.p_unit['invert']][1]   # Pa / jednostkę
                    # S2: bez cichego clampa do p0 — wartości > p0 są dozwolone;
                    # tryb 2 policzy h_ρ<0, tryb 0 pokaże komunikat "poza zakresem ISA".
                    self.inv_p = max(1.0, min(P_INPUT_MAX, self.inv_p + dy * factor * base_pa))
                elif self.inv_mode == 3:      # h [m]
                    self.inv_h = max(0.0, min(C.H_MAX_GEO, self.inv_h + dy * 1.0 * factor))
                else:                          # ρ [kg/m³]
                    self.inv_rho = max(1e-5, self.inv_rho + dy * 0.001 * factor)
            elif f == 2:
                if self.inv_mode in (2, 3):   # T [°C]
                    self.inv_T_C = max(-90.0, min(60.0, self.inv_T_C + dy * 1.0 * factor))
                else:                          # ΔT
                    self.inv_dT = max(-50.0, min(50.0, self.inv_dT + dy * 1.0 * factor))

    # ── analog: docelowy scroll w zależności od ekranu ──────────────────────
    def _analog_scroll(self, sign):
        """sign=+1 (gałka w dół) przewija w przód; sign=-1 w tył."""
        if self.screen == 'norms':
            view_h = H - 60
            max_lines = view_h // 14
            total = len(self.NORMS_LINES)
            cap = max(0, total - max_lines)
            self.norms_scroll = max(0, min(cap, self.norms_scroll + sign * 3))
        elif self.screen == 'table' and self.tab_rows:
            n = len(self.tab_rows)
            self.tab_scroll = max(0, min(max(0, n - 1), self.tab_scroll + sign * 3))
        elif self.screen == 'point':
            self.point_scroll = max(0, min(20, self.point_scroll + sign * 3))
        elif self.screen == 'menu':
            self.menu_idx = (self.menu_idx + sign) % 5

    # ── obsługa wejść ───────────────────────────────────────────────────────
    def handle(self, etype, code, val):
        # diagnostyka — pasek btn:<kod> w nagłówku (bez logowania per-klawisz;
        # mapa przycisków jest już rozpoznana, log rósł bez ograniczeń)
        if etype == EV_KEY and val == 1:
            self.last_btn = str(code)

        # Lewy analog Y — tylko zapamiętujemy wartość; auto-repeat w pętli run().
        if etype == EV_ABS and code == ABS_LY_CODE:
            self.analog_y = val
            return None

        # EXIT
        if etype == EV_KEY and val == 1 and code in EXIT_KEYS:
            return 'quit'
        # B → wstecz / quit z menu; PRZYTRZYMANE B (>=0,6 s) → czyść wyniki.
        # Akcja przy ZWOLNIENIU (val==0), żeby odróżnić krótkie od długiego.
        if etype == EV_KEY and code == BTN_B:
            if val == 1:
                self._b_down_ts = time.monotonic()
                return None
            if val == 0:
                if self._b_down_ts is None:
                    # zwolnienie bez zarejestrowanego wciśnięcia (start z wciśniętym
                    # B / guard / budzenie) — ignoruj, żeby nie robić "wstecz" znikąd
                    return None
                held = time.monotonic() - self._b_down_ts
                self._b_down_ts = None
                if held >= B_HOLD_CLEAR_S and self.screen in ('table', 'plot', 'invert'):
                    self._clear_data()
                    return 'render'
                if self.screen == 'menu':
                    return 'quit'
                self.screen = 'menu'
                return 'render'
            return None

        # MENU
        if self.screen == 'menu':
            if etype == EV_KEY and val == 1:
                if code == BTN_A:
                    self.screen = ('point', 'table', 'plot', 'invert', 'norms')[self.menu_idx]
                    if self.screen == 'norms':
                        self.norms_scroll = 0
                    return 'render'
            if etype == EV_ABS and code == 17 and val != 0:
                self.menu_idx = (self.menu_idx + (1 if val > 0 else -1)) % 5
                return 'render'
            return None

        # EKRANY ROBOCZE
        if etype == EV_KEY and val == 1:
            if code == BTN_A:
                if self.screen == 'table':
                    self._recompute_table()
                    self.tab_scroll = 0
                elif self.screen == 'plot':
                    self.plot_status = 'Generuję...'
                    self._generate_plot()
                elif self.screen == 'invert':
                    self.export_msg = ''   # nowy wynik → skasuj stary komunikat eksportu
                    self.inv_status = ''
                    try:
                        if self.inv_mode == 0:
                            if self.inv_p > C.p0_SL:
                                # S5: p>p0 → h_p<0; zamiast maskowanego ValueError
                                # jasny komunikat, że to poza atmosferą wzorcową.
                                self.inv_result = None
                                self.inv_status = (
                                    'POZA ZAKRESEM ISA: p > p0 = 101 325 Pa.\n'
                                    'Ujemna wysokość ciśnieniowa nie wchodzi w zakres\n'
                                    'atmosfery wzorcowej (model: 0–86 km).\n'
                                    'Dla p > p0 (wyż) użyj trybu 2: p,T → h_ρ (liczy h_ρ<0).')
                            else:
                                self.inv_result = pressure_altitude(self.inv_p)
                        elif self.inv_mode == 1:
                            try:
                                self.inv_result = density_altitude(self.inv_rho, dT=self.inv_dT)
                            except ValueError:
                                # S1: ρ poza zakresem → dotąd ciche NIC; teraz komunikat.
                                rho_max = isa(0.0, dT=self.inv_dT)['rho_kg_m3']
                                rho_min = isa(C.H_MAX_GEO, dT=self.inv_dT)['rho_kg_m3']
                                self.inv_result = None
                                self.inv_status = (
                                    f'POZA ZAKRESEM ISA: ρ = {self.inv_rho:.5f} kg/m³\n'
                                    f'poza zakresem modelu {rho_min:.3e} … {rho_max:.5f} kg/m³\n'
                                    '(atmosfera wzorcowa 0–86 km, ΔT jak ustawiono).\n'
                                    'Dla ρ > ρ(SL) użyj trybu 2/3 (p,T / h,T — liczą h_ρ<0).')
                        else:  # 2: p,T  /  3: h,T  → ρ → h_ρ (analitycznie; OBSŁUGUJE h<0)
                            R = C.R_air
                            TK = self.inv_T_C + 273.15
                            if self.inv_mode == 2:
                                rho = self.inv_p / (R * TK)
                            else:  # tryb 3: ciśnienie wzięte z ISA na zadanej wysokości
                                rho = isa(self.inv_h)['p_Pa'] / (R * TK)
                            self.inv_rho_calc = rho   # N8: NIE nadpisuj inv_rho (wejścia trybu 1)
                            T0, L, g0 = 288.15, -0.0065, 9.80665   # troposfera ISA
                            rho0 = C.p0_SL / (R * T0)               # ρ SL ≈ 1.225
                            n = -g0 / (L * R) - 1.0
                            Tx = T0 * (rho / rho0) ** (1.0 / n)
                            h = (Tx - T0) / L
                            # h<0 (zimne/gęste) = poprawna ujemna wys. gęstościowa; >11 km → model warstwowy
                            self.inv_result = density_altitude(rho) if h > 11000.0 else h
                    except Exception as e:
                        self.inv_result = None
                        self.inv_status = f'BŁĄD: {str(e)[:70]}'
                        self.log.write(f'invert ERR: {e}\n'); self.log.flush()
                    if self.inv_result is not None:
                        # N9: migawka wejść z chwili obliczenia — raport PDF (R2)
                        # zawsze opisuje TEN wynik, nawet po zmianie pól.
                        self.inv_snap = {
                            'mode': self.inv_mode, 'p': self.inv_p,
                            'rho': self.inv_rho, 'rho_calc': self.inv_rho_calc,
                            'dT': self.inv_dT, 'T_C': self.inv_T_C,
                            'h': self.inv_h, 'result': self.inv_result,
                        }
                return 'render'

            if code == BTN_X:                 # 307 = cykl ΔT / NORMY: strona w górę
                if self.screen == 'point':
                    self.point_dT_idx = (self.point_dT_idx + 1) % len(DT_CYCLE)
                elif self.screen == 'table':
                    self.tab_dT = ((self.tab_dT + 5 + 50) % 100) - 50
                elif self.screen == 'invert':
                    self.inv_dT = ((self.inv_dT + 5 + 50) % 100) - 50
                elif self.screen == 'norms':
                    # N1: „strona w górę" — na tym egzemplarzu kody 314/315 to
                    # fizyczne L2/R2 (nietykalne), więc page-up dostał wolny X.
                    self.norms_scroll = max(0, self.norms_scroll - 20)
                return 'render'

            # ── Przyciski wg REALNEJ mapy egzemplarza (konfiguracja.md / AnberNet) ──
            #   R1=309 · L2=314 · R2=315 · Y=306 ; L1/SELECT/START = pula {308,310,311,312,313}
            if code == 306:                   # Y = cykl kroku (dodatek)
                if self.screen in ('point', 'table', 'plot', 'invert'):
                    self.step_mode_idx = (self.step_mode_idx + 1) % len(STEP_MODES)
                    self._save_prefs()
                return 'render'

            if code == 309:                   # R1 = JEDNOSTKA CIŚNIENIA (per ekran)
                if self.screen in self.p_unit:
                    self.p_unit[self.screen] = (self.p_unit[self.screen] + 1) % len(P_UNITS)
                    self._save_prefs()
                elif self.screen == 'norms':
                    self.norms_scroll = max(0, self.norms_scroll + 5)
                return 'render'

            if code == 314:                   # L2 = KROK +
                if self.screen == 'norms':
                    self.norms_scroll = max(0, self.norms_scroll + 20)
                else:
                    self.step_mode_idx = min(len(STEP_MODES) - 1, self.step_mode_idx + 1)
                    self._save_prefs()
                return 'render'

            if code == 315:                   # R2 = JEDN.h (PUNKT) / CSV (TABELA) / RAPORT PDF (INWERSJA)
                if self.screen == 'point':
                    # N5: zmiana jednostki KONWERTUJE wartość (akcja R2 bez zmian)
                    self._set_point_unit((self.point_unit_idx + 1) % len(UNITS))
                    self._save_prefs()
                elif self.screen == 'table':
                    self._save_table_csv()
                elif self.screen == 'norms':
                    self.norms_scroll = max(0, self.norms_scroll + 20)
                elif self.screen == 'invert':
                    self._export_inv_report()
                else:
                    try:
                        self.adjust(1, False)
                    except Exception as e:
                        self.log.write(f'adjust ERR: {e}\n'); self.log.flush()
                return 'render'

            if code in (308, 310, 311, 312, 313):   # L1 (+SELECT/START) = KROK −
                if self.screen == 'norms':
                    self.norms_scroll = max(0, self.norms_scroll - 5)
                else:
                    self.step_mode_idx = max(0, self.step_mode_idx - 1)
                    self._save_prefs()
                return 'render'

        # D-pad (EV_ABS)
        if etype == EV_ABS and val != 0 and code in (16, 17):
            sign = 1 if val > 0 else -1
            if code == 17:
                # góra / dół — nawigacja po polach (lub scroll w NORMACH)
                if self.screen == 'norms':
                    self.norms_scroll = max(0, self.norms_scroll + sign)
                    return 'render'
                self.nav(sign)
                return 'render'
            else:
                # ←/→ — w TABELI (gdy są wyniki) scroll, inaczej adjust(krok mały)
                if self.screen == 'table' and self.tab_rows:
                    self.tab_scroll = max(0, min(max(0, len(self.tab_rows)-1), self.tab_scroll + sign))
                    return 'render'
                if self.screen in ('point', 'plot', 'invert', 'table'):
                    try:
                        self.adjust(sign, big=False)
                    except Exception as e:
                        self.log.write(f'adjust(D-pad) ERR: {e}\n'); self.log.flush()
                    return 'render'
                return None

        return None

    # ── pętla główna ────────────────────────────────────────────────────────
    def run(self):
        self._pwrscr = ScreenPowerToggle()
        ev = sdl2.SDL_Event()
        while sdl2.SDL_PollEvent(ctypes.byref(ev)):
            pass
        start_ms = sdl2.SDL_GetTicks()
        GUARD_MS = 1500
        self.render()
        last_periodic = 0

        was_off = False
        while True:
            self._pwrscr.poll()
            # S3: realny zegar ms (spójny z _last_write w power_screen) — dzięki
            # temu fb0/blank=4 jest faktycznie ponawiane co 200 ms przy OFF.
            self._pwrscr.tick(int(time.monotonic() * 1000))
            if self._pwrscr.is_off:
                self._poll_gamepad()   # S8: odrzucaj klawisze przy zgaszonym ekranie
                was_off = True
                sdl2.SDL_Delay(120)
                continue
            if was_off:
                was_off = False
                self._poll_gamepad()   # S8: odrzuć resztę bufora z chwili budzenia
                self._b_down_ts = None
                self.render()          # odśwież obraz zaraz po włączeniu ekranu
            now = sdl2.SDL_GetTicks()
            guard = (now - start_ms) < GUARD_MS

            evs = self._poll_gamepad()
            for etype, code, val in evs:
                if guard:
                    continue
                r = self.handle(etype, code, val)
                if r == 'quit':
                    self.quit(); return
                if r == 'render':
                    self.render()

            while sdl2.SDL_PollEvent(ctypes.byref(ev)):
                if guard:
                    continue
                if ev.type == sdl2.SDL_KEYDOWN:
                    if ev.key.keysym.sym == sdl2.SDLK_ESCAPE:
                        self.quit(); return

            # Lewy analog — auto-repeat scroll z proporcjonalną prędkością.
            # Skill rg40xx-buttons: zakres ±4096, deadzone 400. Wzór anbercc/filepicker:
            # lekkie wychylenie → 200ms/krok (precyzja), max → 20ms/krok (szybkie scroll).
            ay = abs(self.analog_y)
            if not guard and ay > ANALOG_DEADZONE:
                tnow = time.monotonic()
                if tnow >= self.analog_next:
                    sign = 1 if self.analog_y > 0 else -1
                    self._analog_scroll(sign)
                    self.render()
                    deflect = min(1.0, (ay - ANALOG_DEADZONE) / max(1, ANALOG_MAX - ANALOG_DEADZONE))
                    repeat_ms = ANALOG_SLOW_MS - deflect * (ANALOG_SLOW_MS - ANALOG_FAST_MS)
                    self.analog_next = tnow + repeat_ms / 1000.0

            if now - last_periodic >= 10000:
                self.render()
                last_periodic = now

            sdl2.SDL_Delay(40)

    def quit(self):
        try:
            self._pwrscr.restore()
        except Exception:
            pass
        self.log.write(f'[{time.strftime("%H:%M:%S")}] exit\n'); self.log.flush()
        if self.gp_fd is not None:
            try:
                import fcntl
                fcntl.ioctl(self.gp_fd, 0x40044590, 0)   # EVIOCGRAB=0 (zwolnij)
            except Exception:
                pass
            try: os.close(self.gp_fd)
            except Exception: pass
        if self._tex:
            sdl2.SDL_DestroyTexture(self._tex)
        sdl2.SDL_DestroyRenderer(self.ren)
        sdl2.SDL_DestroyWindow(self.win)
        sdl2.SDL_Quit()


if __name__ == '__main__':
    AnberISA().run()
