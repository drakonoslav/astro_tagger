"""Body and frame naming, in one place so records cannot drift.

Conventions used in records:
  BCRS         origin = solar-system barycenter (SSB), ICRS axes, TDB time scale
  ITRS         Earth-fixed frame; geodetic coordinates are on the WGS84 datum
  IAU_<BODY>   SPICE name of a body-fixed frame (e.g. IAU_MARS)
  Local_ENU    east-north-up frame at a site

Bodies are named canonically without a prefix ("MARS"). Legacy "IAU_MARS" input is accepted.
"""
from .errors import ConfigError

# canonical body -> (ephemeris key, kernel has the body *center*?)
# Outer planets, Mars and Pluto are barycenter-only in the DE planetary kernels.
BODIES = {
    "SUN":     ("sun", True),
    "MERCURY": ("mercury", True),
    "VENUS":   ("venus", True),
    "EARTH":   ("earth", True),
    "MOON":    ("moon", True),
    "MARS":    ("mars barycenter", False),
    "JUPITER": ("jupiter barycenter", False),
    "SATURN":  ("saturn barycenter", False),
    "URANUS":  ("uranus barycenter", False),
    "NEPTUNE": ("neptune barycenter", False),
    "PLUTO":   ("pluto barycenter", False),
}


def canonical_body(name) -> str:
    n = str(name).strip().upper()
    if n.startswith("IAU_"):
        n = n[4:]
    if n not in BODIES:
        raise ConfigError(f"Unknown body '{name}'. Known: {', '.join(BODIES)}")
    return n


def ephemeris_key(body: str) -> str:
    return BODIES[body][0]


def has_body_center(body: str) -> bool:
    return BODIES[body][1]


def body_fixed_frame(body: str) -> str:
    return "ITRS" if body == "EARTH" else f"IAU_{body}"
