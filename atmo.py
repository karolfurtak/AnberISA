#!/usr/bin/env python3
"""
atmo.py — frontend CLI dla biblioteki isa_lib.

Tryby:
  point   — pojedyncza wysokość
  table   — tabela na zakresie wysokości
  plot    — wykres T(h), p(h), rho(h), a(h)
  invert  — wysokość ciśnieniowa/gęstościowa z p lub rho

Przykłady:
  python3 atmo.py point  -H 11000
  python3 atmo.py point  -H 35000 --unit ft --dT 15
  python3 atmo.py table  --h0 0 --h1 20000 --step 1000
  python3 atmo.py table  --h0 0 --h1 50000 --step 2500 --csv tabela.csv
  python3 atmo.py plot   --h0 0 --h1 30000 --n 200 --out wykresy/profil.png
  python3 atmo.py invert --p 26500
  python3 atmo.py invert --rho 0.9
"""
from __future__ import annotations
import argparse
import csv
import sys
from pathlib import Path

# Dodaj katalog skryptu do sys.path, by import isa_lib działał także spoza katalogu.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from isa_lib import (
    isa,
    pressure_altitude,
    density_altitude,
    constants as C,
)


# ---------------------------------------------------------------------------
# Formatowanie
# ---------------------------------------------------------------------------
def _fmt_point(r: dict) -> str:
    lines = [
        f"--- Atmosfera wzorcowa ISA ({'+%g' % r['dT_K'] if r['dT_K'] else 'standard'}) ---",
        f"  wysokość geopot.    h_geo  = {r['h_geo_m']:10.2f} m   ({r['h_geo_m']/0.3048:10.1f} ft)",
        f"  wysokość geom.      h_geom = {r['h_geom_m']:10.2f} m   ({r['h_geom_m']/0.3048:10.1f} ft)",
        f"  warstwa             nr     = {r['layer']}",
        "",
        f"  temperatura         T      = {r['T_K']:10.3f} K     ({r['T_K']-273.15:+8.2f} °C)",
        f"  ciśnienie           p      = {r['p_Pa']:10.2f} Pa    ({r['p_Pa']/100:8.3f} hPa)",
        f"  gęstość             rho    = {r['rho_kg_m3']:10.5f} kg/m^3",
        f"  prędkość dźwięku    a      = {r['a_m_s']:10.3f} m/s   ({r['a_m_s']*3.6:7.2f} km/h)",
        f"  lepkość dynam.      mu     = {r['mu_Pa_s']:.4e} Pa·s",
        f"  lepkość kinemat.    nu     = {r['nu_m2_s']:.4e} m^2/s",
        "",
        f"  sigma (rho/rho0)           = {r['sigma']:10.6f}",
        f"  delta (p/p0)               = {r['delta']:10.6f}",
        f"  theta (T/T0)               = {r['theta']:10.6f}",
    ]
    return "\n".join(lines)


def _print_table(rows: list[dict]) -> None:
    hdr = ("h[m]", "T[K]", "p[Pa]", "rho[kg/m3]", "a[m/s]", "sigma")
    print(f"{hdr[0]:>8} {hdr[1]:>9} {hdr[2]:>11} {hdr[3]:>12} {hdr[4]:>9} {hdr[5]:>10}")
    print("-" * 64)
    for r in rows:
        print(
            f"{r['h_geo_m']:8.0f} "
            f"{r['T_K']:9.3f} "
            f"{r['p_Pa']:11.2f} "
            f"{r['rho_kg_m3']:12.6f} "
            f"{r['a_m_s']:9.3f} "
            f"{r['sigma']:10.6f}"
        )


def _save_csv(rows: list[dict], path: Path) -> None:
    fields = list(rows[0].keys())
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)


# ---------------------------------------------------------------------------
# Komendy
# ---------------------------------------------------------------------------
def cmd_point(args) -> int:
    r = isa(args.H, dT=args.dT, unit_h=args.unit)
    print(_fmt_point(r))
    return 0


def cmd_table(args) -> int:
    import numpy as np
    hs = np.arange(args.h0, args.h1 + args.step * 0.5, args.step)
    rows = [isa(float(h), dT=args.dT, unit_h=args.unit) for h in hs]
    _print_table(rows)
    if args.csv:
        out = Path(args.csv)
        _save_csv(rows, out)
        print(f"\n[zapisano CSV: {out}]")
    return 0


def cmd_plot(args) -> int:
    import numpy as np
    import matplotlib
    matplotlib.use("Agg")  # konieczne: brak X-serwera na konsoli
    import matplotlib.pyplot as plt

    hs = np.linspace(args.h0, args.h1, args.n)
    rows = [isa(float(h), dT=args.dT, unit_h=args.unit) for h in hs]
    T = np.array([r["T_K"] for r in rows])
    p = np.array([r["p_Pa"] for r in rows])
    rho = np.array([r["rho_kg_m3"] for r in rows])
    a = np.array([r["a_m_s"] for r in rows])
    h_km = hs / 1000.0

    fig, axes = plt.subplots(2, 2, figsize=(10, 8))
    titlebase = "ISA" if args.dT == 0 else f"ISA{args.dT:+g}"

    axes[0, 0].plot(T, h_km, "r-")
    axes[0, 0].set_xlabel("Temperatura T [K]")
    axes[0, 0].set_ylabel("Wysokość h [km]")
    axes[0, 0].set_title(f"{titlebase}: T(h)")
    axes[0, 0].grid(True, alpha=0.3)

    axes[0, 1].plot(p / 100.0, h_km, "b-")
    axes[0, 1].set_xlabel("Ciśnienie p [hPa]")
    axes[0, 1].set_ylabel("Wysokość h [km]")
    axes[0, 1].set_title(f"{titlebase}: p(h)")
    axes[0, 1].set_xscale("log")
    axes[0, 1].grid(True, which="both", alpha=0.3)

    axes[1, 0].plot(rho, h_km, "g-")
    axes[1, 0].set_xlabel("Gęstość ρ [kg/m³]")
    axes[1, 0].set_ylabel("Wysokość h [km]")
    axes[1, 0].set_title(f"{titlebase}: ρ(h)")
    axes[1, 0].grid(True, alpha=0.3)

    axes[1, 1].plot(a, h_km, "m-")
    axes[1, 1].set_xlabel("Prędkość dźwięku a [m/s]")
    axes[1, 1].set_ylabel("Wysokość h [km]")
    axes[1, 1].set_title(f"{titlebase}: a(h)")
    axes[1, 1].grid(True, alpha=0.3)

    fig.suptitle(f"Profil atmosfery wzorcowej — {titlebase}", fontsize=13)
    fig.tight_layout()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=120)
    plt.close(fig)
    print(f"[zapisano wykres: {out}]")
    return 0


def cmd_invert(args) -> int:
    if args.p is not None:
        h = pressure_altitude(args.p)
        print(f"Wysokość ciśnieniowa dla p = {args.p} Pa: h_p = {h:.2f} m geopot. "
              f"({h/0.3048:.0f} ft)")
    if args.rho is not None:
        h = density_altitude(args.rho, dT=args.dT)
        print(f"Wysokość gęstościowa dla rho = {args.rho} kg/m^3 (dT={args.dT:+g}): "
              f"h_rho = {h:.2f} m geopot. ({h/0.3048:.0f} ft)")
    if args.p is None and args.rho is None:
        print("Podaj --p lub --rho.", file=sys.stderr)
        return 2
    return 0


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="atmo",
        description="Międzynarodowa Atmosfera Wzorcowa ICAO/ISO 2533 — kalkulator i wykresy.",
    )
    sp = p.add_subparsers(dest="cmd", required=True)

    # point
    p1 = sp.add_parser("point", help="Parametry na jednej wysokości")
    p1.add_argument("-H", type=float, required=True, help="Wysokość (jednostka --unit)")
    p1.add_argument("--unit", default="m",
                    choices=["m", "km", "ft", "m_geom", "ft_geom"],
                    help="Jednostka wysokości (domyśl. m geopot.)")
    p1.add_argument("--dT", type=float, default=0.0, help="Offset ISA+dT [K]")
    p1.set_defaults(func=cmd_point)

    # table
    p2 = sp.add_parser("table", help="Tabela na zakresie wysokości")
    p2.add_argument("--h0", type=float, default=0.0)
    p2.add_argument("--h1", type=float, default=20000.0)
    p2.add_argument("--step", type=float, default=1000.0)
    p2.add_argument("--unit", default="m",
                    choices=["m", "km", "ft", "m_geom", "ft_geom"])
    p2.add_argument("--dT", type=float, default=0.0)
    p2.add_argument("--csv", default=None, help="Ścieżka do zapisu CSV")
    p2.set_defaults(func=cmd_table)

    # plot
    p3 = sp.add_parser("plot", help="Wykresy T(h), p(h), rho(h), a(h)")
    p3.add_argument("--h0", type=float, default=0.0)
    p3.add_argument("--h1", type=float, default=30000.0)
    p3.add_argument("--n", type=int, default=200, help="Liczba punktów")
    p3.add_argument("--unit", default="m", choices=["m"])
    p3.add_argument("--dT", type=float, default=0.0)
    p3.add_argument("--out", default="wykresy/atmo_profil.png")
    p3.set_defaults(func=cmd_plot)

    # invert
    p4 = sp.add_parser("invert", help="Wysokość ciśnieniowa / gęstościowa")
    p4.add_argument("--p", type=float, default=None, help="Ciśnienie [Pa]")
    p4.add_argument("--rho", type=float, default=None, help="Gęstość [kg/m^3]")
    p4.add_argument("--dT", type=float, default=0.0)
    p4.set_defaults(func=cmd_invert)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
