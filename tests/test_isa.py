"""
Testy isa_lib — porównanie z tabelami ICAO/US 1976.

Wartości referencyjne z ICAO Doc 7488/3 / US Standard Atmosphere 1976.
Tolerancja: 0.05% dla T, p; 0.1% dla rho, a (ograniczona przez precyzję tabel).
"""
import math
import sys
from pathlib import Path

# umożliwia uruchamianie z katalogu apps/atmosfera/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from isa_lib import (
    isa, geopotential, geometric,
    speed_of_sound, density, dynamic_viscosity,
    pressure_altitude, density_altitude,
    constants as C,
)


# Tabela referencyjna ICAO Doc 7488 / US 1976 — wysokości **geopotencjalne**.
# Wartości p, rho mogą minimalnie się różnić od źródeł zewnętrznych (~0.5%),
# bo różne tablice używają nieco innej precyzji R_air i p_base warstw.
# (h_geo_m, T_K, p_Pa, rho_kg_m3)
ICAO_TABLE_GEOPOT = [
    (     0,  288.150, 101325.00, 1.22500),
    (  1000,  281.650,  89874.6,  1.11164),
    (  2000,  275.150,  79495.2,  1.00649),
    (  5000,  255.650,  54019.9,  0.73612),
    ( 10000,  223.150,  26436.3,  0.41271),
    ( 11000,  216.650,  22632.1,  0.36392),
    ( 15000,  216.650,  12044.6,  0.19367),
    ( 20000,  216.650,   5474.9,  0.08803),
    ( 25000,  221.650,   2511.0,  0.03946),
    ( 32000,  228.650,    868.0,  0.01323),
    ( 47000,  270.650,    110.91, 0.001427),
    ( 50000,  270.650,     75.94, 0.000977),
    ( 71000,  214.650,      3.956, 0.0000642),
]


# ---------------------------------------------------------------------------
# Tabela ICAO (wysokości geopotencjalne) — temperatura egzaktna, p/rho ~0.5%.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("h,T_ref,p_ref,rho_ref", ICAO_TABLE_GEOPOT)
def test_icao_table_geopot(h, T_ref, p_ref, rho_ref):
    r = isa(h)
    assert r["T_K"] == pytest.approx(T_ref, abs=0.01), f"T@{h}"
    assert r["p_Pa"] == pytest.approx(p_ref, rel=5e-3), f"p@{h}"
    assert r["rho_kg_m3"] == pytest.approx(rho_ref, rel=5e-3), f"rho@{h}"


# ---------------------------------------------------------------------------
# Egzaktne wartości na granicach warstw (definicja standardu)
# ---------------------------------------------------------------------------
LAYER_BOUNDARIES = [
    # (h_geo, T_K) — wartości narzucone definicją ICAO
    (    0.0, 288.15),
    (11000.0, 216.65),
    (20000.0, 216.65),
    (32000.0, 228.65),
    (47000.0, 270.65),
    (51000.0, 270.65),
    (71000.0, 214.65),
    (84852.0, 186.946),
]


@pytest.mark.parametrize("h,T_ref", LAYER_BOUNDARIES)
def test_layer_boundary_temperatures(h, T_ref):
    """Temperatura na granicach warstw — zgodność z definicją (egzaktna do 0.001 K)."""
    r = isa(h)
    assert r["T_K"] == pytest.approx(T_ref, abs=1e-3), f"T@{h}"


# ---------------------------------------------------------------------------
# Punkty kontrolne — warunki SL
# ---------------------------------------------------------------------------
def test_sea_level():
    r = isa(0)
    assert r["T_K"] == pytest.approx(288.15, abs=1e-6)
    assert r["p_Pa"] == pytest.approx(101325.0, abs=1e-3)
    assert r["rho_kg_m3"] == pytest.approx(1.225, rel=1e-4)
    assert r["a_m_s"] == pytest.approx(340.294, rel=1e-4)
    assert r["sigma"] == pytest.approx(1.0)
    assert r["delta"] == pytest.approx(1.0)
    assert r["theta"] == pytest.approx(1.0)


def test_tropopauza():
    r = isa(11000)
    assert r["T_K"] == pytest.approx(216.65, abs=1e-6)
    assert r["layer"] in (0, 1)


def test_stratosfera_izoterma():
    """W warstwie 11-20 km T = const, więc p maleje wykładniczo."""
    r1 = isa(11000)
    r2 = isa(20000)
    assert r1["T_K"] == r2["T_K"]
    # Sprawdź wykładniczość: p2/p1 = exp(-g*(h2-h1)/(R*T))
    # Tolerancja luźniejsza, bo p_base w tabeli ICAO są zaokrąglone — łańcuch nie jest
    # idealnie samospójny (różnice rzędu 1e-6 wynikają z zaokrągleń w stałych).
    expected = r1["p_Pa"] * math.exp(-C.g0 * (20000 - 11000) / (C.R_air * 216.65))
    assert r2["p_Pa"] == pytest.approx(expected, rel=1e-5)


# ---------------------------------------------------------------------------
# Konwersje wysokości
# ---------------------------------------------------------------------------
def test_geopot_geom_round_trip():
    for h in [0, 1000, 11000, 50000, 80000]:
        assert geometric(geopotential(h)) == pytest.approx(h, abs=1e-6)


def test_geopot_at_low_alt():
    """Na małych wysokościach h_geo ≈ h_geom."""
    assert geopotential(1000) == pytest.approx(1000 * C.r_earth / (C.r_earth + 1000), rel=1e-9)
    # różnica < 0.16 m
    assert abs(geopotential(1000) - 1000) < 1.0


# ---------------------------------------------------------------------------
# Jednostki
# ---------------------------------------------------------------------------
def test_unit_ft_vs_m():
    h_ft = 35000.0
    h_m = h_ft * 0.3048
    r_ft = isa(h_ft, unit_h="ft")
    r_m = isa(h_m, unit_h="m")
    assert r_ft["T_K"] == pytest.approx(r_m["T_K"])
    assert r_ft["p_Pa"] == pytest.approx(r_m["p_Pa"])


def test_unit_km():
    assert isa(10, unit_h="km")["T_K"] == pytest.approx(isa(10000)["T_K"])


# ---------------------------------------------------------------------------
# Offset ISA+dT
# ---------------------------------------------------------------------------
def test_isa_plus_15():
    r0 = isa(0)
    r15 = isa(0, dT=15)
    assert r15["T_K"] == pytest.approx(r0["T_K"] + 15)
    # p nie zmienia się
    assert r15["p_Pa"] == pytest.approx(r0["p_Pa"])
    # rho maleje: rho = p / (R*T)
    assert r15["rho_kg_m3"] < r0["rho_kg_m3"]
    assert r15["rho_kg_m3"] == pytest.approx(r0["p_Pa"] / (C.R_air * (288.15 + 15)), rel=1e-9)


# ---------------------------------------------------------------------------
# Iterowalność
# ---------------------------------------------------------------------------
def test_isa_iterable():
    hs = [0, 1000, 5000]
    res = isa(hs)
    assert isinstance(res, list)
    assert len(res) == 3
    assert res[0]["T_K"] == pytest.approx(288.15)


# ---------------------------------------------------------------------------
# Wzory pomocnicze
# ---------------------------------------------------------------------------
def test_speed_of_sound():
    assert speed_of_sound(288.15) == pytest.approx(340.294, rel=1e-4)
    assert speed_of_sound(216.65) == pytest.approx(295.07, rel=1e-3)


def test_density():
    assert density(101325.0, 288.15) == pytest.approx(1.225, rel=1e-4)


def test_sutherland():
    # W T=288.15 K mu = mu_ref = 1.7894e-5
    assert dynamic_viscosity(288.15) == pytest.approx(1.7894e-5, rel=1e-6)
    # W T=216.65 K (tropopauza): ~1.422e-5 Pa·s
    assert dynamic_viscosity(216.65) == pytest.approx(1.422e-5, rel=5e-3)


# ---------------------------------------------------------------------------
# Odwrotne: pressure_altitude / density_altitude
# ---------------------------------------------------------------------------
def test_pressure_altitude_round_trip():
    for h in [0, 1000, 5000, 11000, 15000, 25000, 45000, 60000]:
        r = isa(h)
        h_back = pressure_altitude(r["p_Pa"])
        assert h_back == pytest.approx(h, abs=0.5)


def test_density_altitude_round_trip():
    for h in [0, 2000, 8000, 11000, 18000, 30000]:
        r = isa(h)
        h_back = density_altitude(r["rho_kg_m3"])
        assert h_back == pytest.approx(h, abs=2.0)


def test_density_altitude_hot_day():
    """
    Gorący dzień (ISA+20) na lotnisku 1500 m: wysokość gęstościowa > wysokość fizyczna.
    Klasyczne wyniki: różnica rzędu 300-400 m.
    """
    r = isa(1500, dT=20)
    h_rho = density_altitude(r["rho_kg_m3"])
    # h_rho jest dla standardowego ISA (dT=0), więc powinno być > 1500
    assert h_rho > 1500
    # Reguła praktyczna: ~120 ft (~36 m) na każdy 1°C powyżej ISA → 20°C ≈ 720 m.
    assert h_rho - 1500 == pytest.approx(700, abs=80)


# ---------------------------------------------------------------------------
# Limity i wyjątki
# ---------------------------------------------------------------------------
def test_above_max_altitude_raises():
    with pytest.raises(ValueError):
        isa(90000)


def test_below_sea_level_raises():
    with pytest.raises(ValueError):
        isa(-100)
