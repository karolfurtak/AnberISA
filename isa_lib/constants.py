"""
Stałe Międzynarodowej Atmosfery Wzorcowej (ICAO/ISO 2533:1975, US 1976).

Wszystkie wartości w jednostkach SI. Źródło: ICAO Doc 7488/3 (1993),
US Standard Atmosphere 1976.
"""

# --- Stałe fizyczne ---
g0 = 9.80665              # przyspieszenie ziemskie wzorcowe [m/s^2]
R_air = 287.05287         # indywidualna stała gazowa powietrza suchego [J/(kg·K)]
gamma = 1.4               # wykładnik adiabaty powietrza []
M_air = 0.0289644         # masa molowa powietrza suchego [kg/mol]
R_univ = 8.31446          # uniwersalna stała gazowa [J/(mol·K)]
r_earth = 6_356_766.0     # promień ziemi wzorcowy [m] (do konwersji h_geom <-> h_geo)

# --- Sutherland (lepkość dynamiczna) ---
mu_ref = 1.7894e-5        # [Pa·s] w T_ref = 288.15 K
T_sutherland = 110.4      # [K]
T_ref_sutherland = 288.15 # [K]

# --- Warunki na poziomie morza (SL) ---
T0_SL = 288.15            # [K]
p0_SL = 101_325.0         # [Pa]
rho0_SL = 1.225           # [kg/m^3]
a0_SL = 340.294           # [m/s] (z T0_SL)

# --- Warstwy atmosfery (h_geo w m, T_base w K, lapse L w K/m, p_base w Pa) ---
# (h_base, T_base, L, p_base)
# p_base są wartościami wzorcowymi ICAO — łańcuch jest wewnętrznie spójny.
LAYERS = [
    # h_base [m_geo],  T_base [K],   L [K/m],     p_base [Pa]
    (    0.0,         288.15,       -0.0065,     101_325.000),   # troposfera
    ( 11_000.0,       216.65,        0.0,         22_632.0640),  # tropopauza
    ( 20_000.0,       216.65,        0.0010,       5_474.8889),  # stratosfera dolna
    ( 32_000.0,       228.65,        0.0028,         868.0187),  # stratosfera górna
    ( 47_000.0,       270.65,        0.0,            110.9063),  # stratopauza
    ( 51_000.0,       270.65,       -0.0028,          66.9389),  # mezosfera dolna
    ( 71_000.0,       214.65,       -0.0020,           3.9564),  # mezosfera górna
    ( 84_852.0,       186.946,       0.0,             0.37338),  # górna granica modelu (~86 km h_geom); T spójna z łańcuchem: 214.65 − 0.0020·13852
]

# Maksymalna wysokość modelu (geopotencjalna) w metrach.
H_MAX_GEO = LAYERS[-1][0]   # 84 852 m
