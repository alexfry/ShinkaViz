"""Map projection shared by the data builders and the page (index.html has the same formulas).

Lambert conformal conic on a sphere, set up for Japan: standard parallels 33°N and 41°N, origin 37°N 137°E.
It keeps shapes right everywhere from Kagoshima to Hokkaido, with distances within about 1% across the
Shinkansen network. Coordinates are metres: x east, z south (the page's three.js convention).
"""
import math

PROJ = 'lcc-jp-1'
R = 6371008.8
P1, P2, PHI0, LAM0 = map(math.radians, (33.0, 41.0, 37.0, 137.0))
_t = lambda p: math.tan(math.pi / 4 + p / 2)
N = math.log(math.cos(P1) / math.cos(P2)) / math.log(_t(P2) / _t(P1))
F = math.cos(P1) * _t(P1) ** N / N
RHO0 = R * F / _t(PHI0) ** N


def to_xz(lon, lat):
    rho = R * F / _t(math.radians(lat)) ** N
    th = N * (math.radians(lon) - LAM0)
    return (rho * math.sin(th), -(RHO0 - rho * math.cos(th)))


def to_ll(x, z):
    y = -z
    rho = math.copysign(math.hypot(x, RHO0 - y), N)
    th = math.atan2(x, RHO0 - y)
    lat = 2 * math.atan((R * F / rho) ** (1 / N)) - math.pi / 2
    return (math.degrees(LAM0 + th / N), math.degrees(lat))
