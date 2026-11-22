"""Structured humanization: quasi-periodic rhythms and micro-variations.

Random humanization adds noise: every note moves independently, so nothing
in the variation is remembered. Musicians are not like that: their timing
and dynamics drift with a long memory. This module uses *irrational
rotations* instead of random numbers, n -> {n * theta + phase}:

- the values never repeat (theta is irrational), yet they are spread as
  evenly as possible (three-distance theorem): variation with structure;
- coding a rotation with a window gives *quasi-periodic rhythms*, the
  infinite relatives of Euclidean rhythms: hits spread as evenly as possible,
  a loop that seems to repeat but slowly slides (Sturmian words);
- a loop of a *near-period* length (a continued fraction denominator of
  theta) closes almost seamlessly.

The default rotation comes from the Cedra constant
C = sqrt(3) + (3/2) sqrt(2) - 2, theta = ln C ~ 0.617, which starts like the
golden ratio and then drifts away from it (https://github.com/cedrati/cedra).
Timing, velocity and duration are driven by the logarithms of three Galois
conjugates of C. These are linearly independent over Q together with 1
(proved in the cedra notes, Theorem D), so the three variations are jointly
equidistributed: no hidden correlation between them.

Pure functions, no Live connection: the tools in tools/drums.py and the
`humanize_structured` operation of transform_clip use them.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Union

_SQRT2, _SQRT3 = math.sqrt(2.0), math.sqrt(3.0)

CEDRA = _SQRT3 + 1.5 * _SQRT2 - 2.0                      # ~ 1.853371
CEDRA_CONJUGATES = (
    CEDRA,                                               # sqrt(3) + (3/2) sqrt(2) - 2
    _SQRT3 - 1.5 * _SQRT2 - 2.0,                         # sqrt(2) -> -sqrt(2)
    -_SQRT3 + 1.5 * _SQRT2 - 2.0,                        # sqrt(3) -> -sqrt(3)
)

ROTATIONS: Dict[str, float] = {
    "cedra": math.log(CEDRA),                            # ~ 0.617006
    "golden": (math.sqrt(5.0) - 1.0) / 2.0,              # ~ 0.618034, the most even of all
    "silver": _SQRT2 - 1.0,                              # ~ 0.414214
}

# One rotation per humanized dimension: timing, velocity, duration
HUMANIZE_ROTATIONS = tuple(math.log(abs(c)) % 1.0 for c in CEDRA_CONJUGATES)


class QuasiPeriodicError(ValueError):
    pass


def resolve_rotation(rotation: Union[str, float, None]) -> float:
    """A rotation number in (0, 1): a name from ROTATIONS or a number."""
    if rotation is None:
        return ROTATIONS["cedra"]
    if isinstance(rotation, str):
        key = rotation.strip().lower()
        if key in ROTATIONS:
            return ROTATIONS[key]
        try:
            rotation = float(key)
        except ValueError:
            raise QuasiPeriodicError("Unknown rotation '%s'. Known: %s, or a number between 0 and 1"
                                     % (rotation, ", ".join(ROTATIONS)))
    value = float(rotation) % 1.0
    if not 0.0 < value < 1.0:
        raise QuasiPeriodicError("A rotation must not be a whole number")
    return value


def rotate(n: int, theta: float, phase: float = 0.0) -> float:
    """{n * theta + phase}, in [0, 1)."""
    return (n * theta + phase) % 1.0


def continued_fraction(x: float, terms: int = 12) -> List[int]:
    """First partial quotients of x (float precision: a dozen terms are reliable)."""
    out = []
    for _ in range(terms):
        q = math.floor(x)
        out.append(int(q))
        x -= q
        if x < 1e-12:
            break
        x = 1.0 / x
    return out


def near_periods(rotation: Union[str, float, None] = None, max_steps: int = 10000) -> List[int]:
    """Loop lengths that close almost seamlessly: the continued fraction
    denominators of the rotation number (for Cedra: 2, 3, 5, 8, 13, 47, 1376...)."""
    theta = resolve_rotation(rotation)
    q_prev, q = 0, 1
    out = []
    for a in continued_fraction(theta)[1:]:
        q_prev, q = q, a * q + q_prev
        if q > max_steps:
            break
        if q > 1 and q not in out:
            out.append(q)
    return out


def word(steps: int, density: Optional[float] = None, rotation: Union[str, float, None] = None,
         phase: float = 0.0) -> List[int]:
    """Quasi-periodic rhythm: 1 when {n theta + phase} < density, n = 1..steps.

    With density equal to the rotation number (the default) this is a
    Sturmian word: hits spread as evenly as possible, gaps of only two sizes.
    Another density keeps at most three gap sizes (three-gap theorem)."""
    theta = resolve_rotation(rotation)
    tau = theta if density is None else float(density)
    if not 0.0 < tau < 1.0:
        raise QuasiPeriodicError("density must be between 0 and 1 (exclusive)")
    return [1 if rotate(n, theta, phase) < tau else 0 for n in range(1, steps + 1)]


def seam_mismatch(steps: int, density: Optional[float] = None,
                  rotation: Union[str, float, None] = None) -> float:
    """Share of steps that change when the pattern is shifted by its own
    length: how audible the loop point is (exact value 2 min(||steps theta||, tau, 1 - tau))."""
    theta = resolve_rotation(rotation)
    tau = theta if density is None else float(density)
    d = abs(steps * theta - round(steps * theta))
    return 2.0 * min(d, tau, 1.0 - tau)


def rhythm_notes(steps: int, pitch: int, grid: float = 0.25, density: Optional[float] = None,
                 rotation: Union[str, float, None] = None, phase: float = 0.0,
                 velocity_low: int = 50, velocity_high: int = 95, gate: float = 0.8,
                 accent_pitch: Optional[int] = None, accent_near_period: int = 13,
                 accent_velocity: int = 88) -> Dict:
    """Notes of a quasi-periodic rhythm on one pitch.

    - hits follow `word`; each hit's velocity follows {n theta + phase}
      between velocity_low and velocity_high (dynamics that never repeat);
    - with `accent_pitch`, a second voice plays where the rhythm slips
      against its near-period `accent_near_period` (w(n) != w(n + q)):
      sparse accents at musically meaningful places."""
    if steps <= 0:
        raise QuasiPeriodicError("steps must be positive")
    theta = resolve_rotation(rotation)
    q = max(1, int(accent_near_period))
    w = word(steps + q, density, theta, phase)
    lo, hi = sorted((int(velocity_low), int(velocity_high)))
    notes, hits, accents = [], [], []
    for i in range(steps):
        start = round(i * grid, 6)
        if w[i]:
            v = lo + (hi - lo) * rotate(i + 1, theta, phase)
            notes.append({"pitch": int(pitch), "start_time": start, "duration": grid * gate,
                          "velocity": int(round(v)), "mute": False})
            hits.append(i)
        if accent_pitch is not None and w[i] != w[i + q]:
            notes.append({"pitch": int(accent_pitch), "start_time": start, "duration": grid * gate,
                          "velocity": int(accent_velocity), "mute": False})
            accents.append(i)
    gaps = sorted({b - a for a, b in zip(hits, hits[1:])})
    return {"notes": notes, "hits": len(hits), "accents": len(accents),
            "density": len(hits) / steps, "gap_sizes": gaps,
            "seam_mismatch": seam_mismatch(steps, density, theta)}


def _drift(t: float, period: float, shift: float) -> float:
    """Smooth quasi-periodic curve in [-1, 1]: two sines whose periods have
    an irrational ratio (1 : C), so the curve never comes back to itself."""
    x = t / period + shift
    return 0.5 * (math.sin(2 * math.pi * x) + math.sin(2 * math.pi * x / CEDRA))


def humanize_structured(notes: Sequence[Dict], timing: float = 0.01, velocity: float = 8,
                        duration: float = 0.0, drift: float = 0.3, drift_bars: float = 8,
                        phase: float = 0.0) -> List[Dict]:
    """Move notes by quasi-periodic amounts instead of random ones.

    Each value mixes a fast part (an irrational rotation, different at every
    onset, never repeating) and, with `drift`, a slow quasi-periodic curve
    over about `drift_bars` bars (the groove pushes and lays back, gets
    louder and softer). Timing, velocity and duration use three rotations
    that are independent over Q, so they don't move together.

    - timing: largest shift in beats (0.01 ~ 5 ms at 120 BPM)
    - velocity: largest velocity change
    - duration: largest relative length change (0.1 = +-10 %)
    - drift: 0-1, share of the slow curve (0 = only the fast part)
    - drift_bars: length of the slow curve, in 4/4 bars
    - phase: shifts every sequence: another take with the same character
    Notes starting together (a chord) keep the same timing shift."""
    if not 0.0 <= drift <= 1.0:
        raise QuasiPeriodicError("drift must be between 0 and 1")
    period = 4.0 * max(float(drift_bars), 0.25)
    th_t, th_v, th_d = HUMANIZE_ROTATIONS
    order = sorted(range(len(notes)), key=lambda i: (notes[i]["start_time"], notes[i].get("pitch", 0)))
    onset_index: Dict[float, int] = {}
    out: List[Optional[Dict]] = [None] * len(notes)
    for k, i in enumerate(order, start=1):
        n = dict(notes[i])
        t = float(n["start_time"])
        key = round(t, 6)
        if key not in onset_index:
            onset_index[key] = len(onset_index) + 1
        j = onset_index[key]
        u_t = (1 - drift) * (2 * rotate(j, th_t, phase) - 1) + drift * _drift(t, period, phase)
        u_v = (1 - drift) * (2 * rotate(k, th_v, phase) - 1) + drift * _drift(t, period, phase + 0.25)
        u_d = 2 * rotate(k, th_d, phase) - 1
        n["start_time"] = max(0.0, t + timing * u_t)
        n["velocity"] = int(max(1, min(127, round(n.get("velocity", 100) + velocity * u_v))))
        if duration:
            n["duration"] = max(0.01, float(n["duration"]) * (1 + duration * u_d))
        out[i] = n
    return [n for n in out if n is not None]
