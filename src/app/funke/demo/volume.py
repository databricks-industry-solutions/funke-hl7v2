"""Time-of-day / weekly volume shaping for the synthetic ADT generator.

Pure math with no dependency on the HL7 engine, so it can be imported by both the engine
(:mod:`funke.demo.adt`, to tilt the admit/discharge mix) and the generator runner
(``resources/demo/adt_generator.py``, to shape message density and realtime pacing). All tuning
knobs are module-level constants.

The volume curve is two Gaussian humps (a morning admit surge and a late-afternoon discharge
surge) over an overnight baseline, scaled down on weekends, with optional multiplicative noise.
"""

import math
import random
from datetime import datetime, timedelta

# --- diurnal volume shape ---
_BUMP_CENTERS = (9.0, 17.0)  # morning + late-afternoon peaks (hours)
_BUMP_WIDTH = 2.0  # Gaussian sigma in hours (controls hump breadth)
_BASELINE = 0.15  # overnight floor as a fraction of peak
_WEEKEND_FACTOR = 0.6  # Sat/Sun overall scaling
_NOISE = 0.15  # +/- fractional jitter for the noisy variant

# --- admit/discharge tilt ---
_BIAS_CENTERS = (9.0, 17.0)  # admit peak, discharge peak (hours)
_BIAS_WIDTH = 3.0  # Gaussian sigma for the tilt


def volume_multiplier(ts: datetime) -> float:
    """Return the deterministic diurnal/weekly volume shape in ``(0, 1]``.

    Two Gaussian humps centered at ~09:00 and ~17:00 sit over an overnight baseline; the whole
    curve is scaled down on weekends. Peaks reach ~1.0 at the hump centers and fall to
    ~``_BASELINE`` overnight.

    Args:
        ts: The timestamp whose hour-of-day and weekday drive the shape.

    Returns:
        A multiplier in ``(0, 1]`` (weekend peak is capped by ``_WEEKEND_FACTOR``).
    """
    hour = ts.hour + ts.minute / 60.0
    bumps = sum(math.exp(-0.5 * ((hour - c) / _BUMP_WIDTH) ** 2) for c in _BUMP_CENTERS)
    bumps = min(1.0, bumps)  # cap the small overlap between the two humps
    shape = _BASELINE + (1.0 - _BASELINE) * bumps  # in [_BASELINE, 1.0]
    if ts.weekday() >= 5:  # 5=Sat, 6=Sun
        shape *= _WEEKEND_FACTOR
    return shape


def volume_multiplier_noisy(ts: datetime, rng: random.Random) -> float:
    """:func:`volume_multiplier` with +/- ``_NOISE`` multiplicative jitter.

    Args:
        ts: The timestamp whose shape to perturb.
        rng: Random source for the jitter (inject a seeded one for deterministic tests).

    Returns:
        A multiplier in ``(0, ~1.15]``; never zero, so callers can safely divide by it.
    """
    return volume_multiplier(ts) * (1.0 + rng.uniform(-_NOISE, _NOISE))


def admit_discharge_bias(ts: datetime) -> float:
    """Return the admit-vs-discharge tilt in ``[-1, 1]`` for the given time.

    ``+1`` is a strong morning admit skew, ``-1`` a strong late-afternoon discharge skew, and
    ~0 midday/overnight. This is pure (no RNG) so a seeded engine stays deterministic.

    Args:
        ts: The timestamp whose hour-of-day drives the tilt.

    Returns:
        The tilt in ``[-1, 1]`` (admit bump minus discharge bump).
    """
    hour = ts.hour + ts.minute / 60.0
    admit_bump = math.exp(-0.5 * ((hour - _BIAS_CENTERS[0]) / _BIAS_WIDTH) ** 2)
    discharge_bump = math.exp(-0.5 * ((hour - _BIAS_CENTERS[1]) / _BIAS_WIDTH) ** 2)
    return admit_bump - discharge_bump


def build_backfill_timestamps(
    hours: float, peak_rate_per_hour: float, rng: random.Random, start: datetime
) -> list[datetime]:
    """Build a shaped, globally-sorted list of backfill event timestamps.

    For each whole hour in ``[start, start + hours)`` the target event count is
    ``round(peak_rate_per_hour * volume_multiplier_noisy(hour_start))``; that many timestamps are
    scattered uniformly within the hour. The combined list is sorted ascending so the engine can
    be driven strictly in time order (keeping per-visit ``event_ts`` monotonic downstream).

    Args:
        hours: Length of the backfill window in hours.
        peak_rate_per_hour: Events per hour at the diurnal peak; scaled by the volume curve.
        rng: Random source for per-hour noise and within-hour jitter.
        start: Timestamp of the start of the window (typically ``now - hours``).

    Returns:
        Ascending-sorted event timestamps spanning the window.
    """
    timestamps: list[datetime] = []
    for h in range(math.ceil(hours)):
        hour_start = start + timedelta(hours=h)
        count = max(
            0, round(peak_rate_per_hour * volume_multiplier_noisy(hour_start, rng))
        )
        for _ in range(count):
            timestamps.append(hour_start + timedelta(seconds=rng.uniform(0, 3600)))
    timestamps.sort()
    return timestamps
