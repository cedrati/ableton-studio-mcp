"""Setting a parameter from a musical value ("800 Hz", "5 ms", "-6 dB", "Bell").

Live's API sets parameters in their internal range (often 0–1) but can show
any value the way its UI does (``str_for_value``). So a musical value is
found by searching the internal range until Live's own display matches it:
no per-device table, and it works for every native device.
"""
from __future__ import absolute_import, print_function, unicode_literals

import math
import re

# unit -> (family, factor to the family's base unit)
UNITS = {
    "hz": ("hz", 1.0), "khz": ("hz", 1000.0),
    "ms": ("s", 0.001), "s": ("s", 1.0), "sec": ("s", 1.0),
    "db": ("db", 1.0),
    "%": ("%", 1.0),
    "st": ("st", 1.0), "semitones": ("st", 1.0),
    "ct": ("ct", 1.0), "cents": ("ct", 1.0),
    "bpm": ("bpm", 1.0),
    "": ("", 1.0),
}
_NUMBER = re.compile(r"^\s*([+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+|inf))\s*([a-z%]*)\s*$", re.I)
SAMPLES = 64        # coarse scan of the range
BISECTIONS = 40     # refinement inside the bracket


_RATIO = re.compile(r"^\s*(\d+(?:[.,]\d*)?|[.,]\d+|inf|∞)\s*:\s*1(?:[.,]0*)?\s*$", re.I)


def parse_quantity(text):
    """'2.2 kHz' -> (2200.0, 'hz'); '-inf dB' -> (-inf, 'db'); '8.00 : 1' ->
    (8.0, 'ratio'); 'Bell' -> None."""
    ratio = _RATIO.match(text)
    if ratio:
        number = ratio.group(1).replace(",", ".").lower()
        return (float("inf") if number in ("inf", "∞") else float(number)), "ratio"
    match = _NUMBER.match(text.replace("−", "-"))
    if not match:
        return None
    number, unit = match.group(1).replace(",", "."), match.group(2).lower()
    if unit not in UNITS:
        return None
    family, factor = UNITS[unit]
    value = float("-inf" if number.lstrip("+-").lower() == "inf" and number.startswith("-")
                  else "inf" if number.lstrip("+").lower() == "inf" else number)
    return value * factor, family


def _value_items(param):
    """A quantized parameter's named settings; [] otherwise. (Live raises
    RuntimeError when a continuous parameter is asked for them.)"""
    try:
        if not getattr(param, "is_quantized", False):
            return []
        return [str(i) for i in (param.value_items or [])]
    except Exception:
        return []


def _display(param, value):
    try:
        return str(param.str_for_value(value))
    except Exception:
        return None


def _numeric_display(param, value, family):
    shown = _display(param, value)
    parsed = parse_quantity(shown) if shown is not None else None
    if parsed is None or (family and parsed[1] and parsed[1] != family):
        return None
    return parsed[0]


def resolve_value(param, wanted):
    """The internal value to give ``param`` so that it means ``wanted``.

    ``wanted`` is a number in the parameter's own range, or text: one of its
    named values ("Bell", "Alg. 11"), or a quantity with a unit ("800 Hz",
    "-6 dB", "30 %"). Raises ValueError when no setting matches.
    """
    low, high = float(param.min), float(param.max)
    if isinstance(wanted, bool):
        wanted = 1.0 if wanted else 0.0
    if isinstance(wanted, (int, float)):
        if not low <= float(wanted) <= high:
            # "Ratio": 8 means 8 : 1 on a parameter Live shows as a ratio.
            if _numeric_display(param, (low + high) / 2, "ratio") is not None:
                return _search(param, float(wanted), "ratio", low, high, "%s : 1" % wanted)
            raise ValueError("%s takes %s to %s, not %s" % (param.name, low, high, wanted))
        return float(wanted)

    text = str(wanted).strip()
    items = _value_items(param)
    for i, item in enumerate(items):
        if item.lower() == text.lower():
            return low + i
    if getattr(param, "is_quantized", False) or items:
        for step in range(int(round(high - low)) + 1):
            if (_display(param, low + step) or "").lower() == text.lower():
                return low + step
        raise ValueError("%s has no setting '%s'%s" % (
            param.name, text, (" (it has: %s)" % ", ".join(items)) if items else ""))

    target = parse_quantity(text)
    if target is None:
        # A textual display on a continuous parameter ("1/16", "Off"): scan.
        for k in range(SAMPLES * 4 + 1):
            value = low + (high - low) * k / (SAMPLES * 4)
            if (_display(param, value) or "").lower() == text.lower():
                return value
        raise ValueError("%s never shows '%s'" % (param.name, text))
    goal, family = target
    try:
        return _search(param, goal, family, low, high, text)
    except ValueError:
        # "35 %" on a parameter shown as a plain 0–1 number means 0.35.
        if family == "%" and _numeric_display(param, high, "") is not None:
            return _search(param, goal / 100.0, "", low, high, text)
        raise


def _search(param, goal, family, low, high, text):
    points = []
    for k in range(SAMPLES + 1):
        value = low + (high - low) * k / SAMPLES
        shown = _numeric_display(param, value, family)
        if shown is not None:
            points.append((value, shown))
    if not points:
        raise ValueError("%s is not shown in %s (it shows e.g. '%s')"
                         % (param.name, family or "plain numbers", _display(param, (low + high) / 2)))
    if math.isinf(goal):
        return min(points, key=lambda p: p[1])[0] if goal < 0 else max(points, key=lambda p: p[1])[0]
    shown_values = [s for _v, s in points if not math.isinf(s)]
    if shown_values and not min(shown_values) - 1e-9 <= goal <= max(shown_values) + 1e-9:
        raise ValueError("%s goes from %s to %s, so it can't be %s" % (
            param.name, _display(param, low), _display(param, high), text))
    best = min(points, key=lambda p: abs(p[1] - goal))
    for (v1, s1), (v2, s2) in zip(points, points[1:]):
        if (s1 - goal) * (s2 - goal) <= 0 and not (math.isinf(s1) or math.isinf(s2)):
            a, b, sa = v1, v2, s1
            for _ in range(BISECTIONS):
                mid = (a + b) / 2
                sm = _numeric_display(param, mid, family)
                if sm is None:
                    break
                if abs(sm - goal) < abs(best[1] - goal):
                    best = (mid, sm)
                if (sa - goal) * (sm - goal) <= 0:
                    b = mid
                else:
                    a, sa = mid, sm
            break
    return best[0]
