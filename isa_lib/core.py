"""
Rdzeń obliczeń ISA — formuły barometryczne warstwa po warstwie.

Założenia ICAO/ISO 2533:
- atmosfera w równowadze hydrostatycznej,
- powietrze suche jako gaz doskonały (p = rho*R*T),
- gradient temperatury L stały w obrębie warstwy,
- p_base ustalone tak, by łańcuch warstw był spójny przy g0 i R_air.
"""
from __future__ import annotations
import math
from typing import Iterable, Union, List, Dict, Sequence

from . import constants as C

Number = Union[int, float]
HInput = Union[Number, Sequence[Number]]


# ---------------------------------------------------------------------------
# Konwersje wysokości
# ---------------------------------------------------------------------------
def geopotential(h_geom: Number) -> float:
    """Wysokość geometryczna -> geopotencjalna [m]."""
    return C.r_earth * h_geom / (C.r_earth + h_geom)


def geometric(h_geo: Number) -> float:
    """Wysokość geopotencjalna -> geometryczna [m]."""
    return C.r_earth * h_geo / (C.r_earth - h_geo)


# ---------------------------------------------------------------------------
# Pomocnicze
# ---------------------------------------------------------------------------
def _layer_index(h_geo: float) -> int:
    """Indeks warstwy, do której należy wysokość geopotencjalna h_geo [m]."""
    if h_geo < C.LAYERS[0][0] - 1e-6:
        raise ValueError(f"Wysokość poniżej SL nieobsługiwana: {h_geo} m")
    if h_geo > C.H_MAX_GEO + 1e-6:
        raise ValueError(
            f"Wysokość {h_geo:.0f} m (geopot.) przekracza zakres modelu "
            f"(do {C.H_MAX_GEO:.0f} m geopot. ≈ 86 km geom.)"
        )
    for i in range(len(C.LAYERS) - 1):
        if h_geo < C.LAYERS[i + 1][0]:
            return i
    return len(C.LAYERS) - 1


def _T_p_in_layer(h_geo: float, dT: float = 0.0) -> tuple[float, float]:
    """Zwraca (T, p) na zadanej wysokości geopotencjalnej [m]."""
    i = _layer_index(h_geo)
    h_b, T_b, L, p_b = C.LAYERS[i]
    dh = h_geo - h_b
    T = T_b + L * dh
    if abs(L) < 1e-12:
        # warstwa izotermiczna
        p = p_b * math.exp(-C.g0 * dh / (C.R_air * T_b))
    else:
        exponent = -C.g0 / (C.R_air * L)
        p = p_b * (T / T_b) ** exponent
    # Odchylenie temperatury (offset) — wpływa na rho/a, nie na p (ICAO PA jest po p).
    T_eff = T + dT
    return T_eff, p


# ---------------------------------------------------------------------------
# Wielkości pochodne
# ---------------------------------------------------------------------------
def density(p: float, T: float) -> float:
    """rho z równania stanu gazu doskonałego [kg/m^3]."""
    return p / (C.R_air * T)


def speed_of_sound(T: float) -> float:
    """Prędkość dźwięku a = sqrt(gamma R T) [m/s]."""
    return math.sqrt(C.gamma * C.R_air * T)


def dynamic_viscosity(T: float) -> float:
    """mu wg formuły Sutherlanda [Pa·s]."""
    return (
        C.mu_ref
        * (T / C.T_ref_sutherland) ** 1.5
        * (C.T_ref_sutherland + C.T_sutherland)
        / (T + C.T_sutherland)
    )


def kinematic_viscosity(mu: float, rho: float) -> float:
    """nu = mu / rho [m^2/s]."""
    return mu / rho


# ---------------------------------------------------------------------------
# Główna funkcja API
# ---------------------------------------------------------------------------
def isa(h: HInput, dT: float = 0.0, unit_h: str = "m") -> Union[Dict, List[Dict]]:
    """
    Oblicza parametry atmosfery na zadanej wysokości.

    Parametry
    ---------
    h : float | iterable
        Wysokość. Domyślnie geopotencjalna w metrach.
    dT : float
        Odchylenie temperatury od ISA [K]. (ISA+dT, np. +15 dla "ISA+15").
        Wpływa na T, rho, a. Nie wpływa na p (zgodnie z definicją PA).
    unit_h : str
        'm'       — metry geopotencjalne (domyślnie),
        'm_geom'  — metry geometryczne (konwersja na geopot.),
        'ft'      — stopy geopotencjalne,
        'ft_geom' — stopy geometryczne,
        'km'      — kilometry geopotencjalne.

    Zwraca
    ------
    dict z kluczami: h_geo_m, h_geom_m, T_K, p_Pa, rho_kg_m3, a_m_s,
                     mu_Pa_s, nu_m2_s, sigma, delta, theta, layer
    lub lista dictów jeśli h było iterowalne.
    """
    if isinstance(h, (list, tuple)) or (hasattr(h, "__iter__") and not isinstance(h, str)):
        return [isa(float(x), dT=dT, unit_h=unit_h) for x in h]

    h = float(h)

    # 1) Sprowadź h do metrów geopotencjalnych
    if unit_h == "m":
        h_geo = h
    elif unit_h == "km":
        h_geo = h * 1000.0
    elif unit_h == "ft":
        h_geo = h * 0.3048
    elif unit_h == "m_geom":
        h_geo = geopotential(h)
    elif unit_h == "ft_geom":
        h_geo = geopotential(h * 0.3048)
    else:
        raise ValueError(f"Nieznana jednostka wysokości: {unit_h!r}")

    h_geom = geometric(h_geo)

    # 2) T, p
    T, p = _T_p_in_layer(h_geo, dT=dT)
    rho = density(p, T)
    a = speed_of_sound(T)
    mu = dynamic_viscosity(T)
    nu = kinematic_viscosity(mu, rho)

    # 3) Bezwymiarowe (ratio do SL)
    sigma = rho / C.rho0_SL
    delta = p / C.p0_SL
    theta = T / C.T0_SL

    return {
        "h_geo_m": h_geo,
        "h_geom_m": h_geom,
        "T_K": T,
        "p_Pa": p,
        "rho_kg_m3": rho,
        "a_m_s": a,
        "mu_Pa_s": mu,
        "nu_m2_s": nu,
        "sigma": sigma,
        "delta": delta,
        "theta": theta,
        "layer": _layer_index(h_geo),
        "dT_K": dT,
    }


# ---------------------------------------------------------------------------
# Odwrotności: wysokość ciśnieniowa i gęstościowa
# ---------------------------------------------------------------------------
def pressure_altitude(p: float) -> float:
    """
    Wysokość ciśnieniowa h_p [m geopot.] — wysokość w ISA, na której panuje p.
    Rozwiązuje równania warstwa po warstwie analitycznie.
    """
    if p > C.p0_SL + 1e-6:
        raise ValueError(f"p={p} Pa > p0 — wysokość ciśnieniowa < 0 nieobsługiwana.")
    for i, (h_b, T_b, L, p_b) in enumerate(C.LAYERS):
        # górna granica warstwy
        if i < len(C.LAYERS) - 1:
            p_top = C.LAYERS[i + 1][3]
        else:
            p_top = 0.0
        if p >= p_top - 1e-12:
            # w tej warstwie
            if abs(L) < 1e-12:
                dh = -C.R_air * T_b / C.g0 * math.log(p / p_b)
            else:
                T = T_b * (p / p_b) ** (-C.R_air * L / C.g0)
                dh = (T - T_b) / L
            return h_b + dh
    raise ValueError(f"Ciśnienie {p} Pa poniżej zakresu modelu.")


def density_altitude(rho: float, dT: float = 0.0) -> float:
    """
    Wysokość gęstościowa h_rho [m geopot.] — wysokość w ISA(+dT), na której panuje rho.
    Rozwiązanie iteracyjne (bisekcja) — gęstość jest monotoniczna względem h.
    """
    f = lambda h: isa(h, dT=dT)["rho_kg_m3"] - rho
    lo, hi = 0.0, C.H_MAX_GEO
    f_lo, f_hi = f(lo), f(hi)
    # Brzegi zakresu: jeśli rho zgadza się idealnie z gęstością na SL lub szczycie,
    # zwróć je natychmiast (zabezpiecza bisekcję przed dryfem przy f_lo == 0).
    if abs(f_lo) < 1e-12:
        return lo
    if abs(f_hi) < 1e-12:
        return hi
    if f_lo * f_hi > 0:
        raise ValueError(
            f"Gęstość {rho} kg/m^3 poza zakresem modelu "
            f"({isa(hi, dT=dT)['rho_kg_m3']:.3e}..{isa(lo, dT=dT)['rho_kg_m3']:.3e})."
        )
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        f_mid = f(mid)
        if abs(f_mid) < 1e-10 or (hi - lo) < 1e-4:
            return mid
        # Bisekcja: znak zmienia się między lo a mid → przedział węższy = (lo, mid)
        if f_lo * f_mid <= 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return 0.5 * (lo + hi)
