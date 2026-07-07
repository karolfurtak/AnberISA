"""
isa_lib — Międzynarodowa Atmosfera Wzorcowa (ICAO/ISO 2533:1975).

Publiczne API:
    isa(h, dT=0.0, unit_h='m')        -> dict | list[dict]
    geopotential(h_geom)              -> h_geo  [m]
    geometric(h_geo)                  -> h_geom [m]
    speed_of_sound(T)                 -> a [m/s]
    density(p, T)                     -> rho [kg/m^3]
    dynamic_viscosity(T)              -> mu [Pa·s]
    kinematic_viscosity(mu, rho)      -> nu [m^2/s]
    pressure_altitude(p)              -> h_p [m]
    density_altitude(rho, dT=0.0)     -> h_rho [m]

Stałe ICAO (warstwy 0..86 km, w jednostkach SI) — patrz `constants.py`.
"""
from .core import (
    isa,
    geopotential,
    geometric,
    speed_of_sound,
    density,
    dynamic_viscosity,
    kinematic_viscosity,
    pressure_altitude,
    density_altitude,
)
from . import constants

__all__ = [
    "isa",
    "geopotential",
    "geometric",
    "speed_of_sound",
    "density",
    "dynamic_viscosity",
    "kinematic_viscosity",
    "pressure_altitude",
    "density_altitude",
    "constants",
]

__version__ = "1.0.0"
