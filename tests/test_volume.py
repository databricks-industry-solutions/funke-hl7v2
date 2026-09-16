"""Tests for the time-of-day / weekly volume shaping (funke.demo.volume)."""

import random
from datetime import datetime, timedelta

from funke.demo.volume import (
    admit_discharge_bias,
    build_backfill_timestamps,
    volume_multiplier,
    volume_multiplier_noisy,
)

# 2024-01-01 is a Monday (weekday); 2024-01-06 is a Saturday (weekend).
_MON = datetime(2024, 1, 1)
_SAT = datetime(2024, 1, 6)


def _at(day: datetime, hour: int) -> datetime:
    return day.replace(hour=hour)


def test_peaks_exceed_overnight_trough():
    trough = volume_multiplier(_at(_MON, 3))
    assert volume_multiplier(_at(_MON, 9)) > trough
    assert volume_multiplier(_at(_MON, 17)) > trough


def test_double_hump_midday_dip():
    midday = volume_multiplier(_at(_MON, 13))
    assert midday < volume_multiplier(_at(_MON, 9))
    assert midday < volume_multiplier(_at(_MON, 17))
    assert midday > volume_multiplier(_at(_MON, 3))


def test_weekend_lower_than_weekday_same_hour():
    for hour in (3, 9, 13, 17, 22):
        assert volume_multiplier(_at(_SAT, hour)) < volume_multiplier(_at(_MON, hour))


def test_multiplier_positive_and_bounded():
    for day in (_MON, _SAT):
        for hour in range(24):
            m = volume_multiplier(_at(day, hour))
            assert 0.0 < m <= 1.0


def test_determinism():
    ts = _at(_MON, 10)
    assert volume_multiplier(ts) == volume_multiplier(ts)
    # Fresh RNGs seeded identically must produce identical noise.
    assert volume_multiplier_noisy(ts, random.Random(42)) == volume_multiplier_noisy(
        ts, random.Random(42)
    )


def test_admit_discharge_bias_sign_and_bounds():
    assert admit_discharge_bias(_at(_MON, 9)) > 0.5  # strong morning admit skew
    assert admit_discharge_bias(_at(_MON, 17)) < -0.5  # strong evening discharge skew
    assert abs(admit_discharge_bias(_at(_MON, 0))) < 0.05  # ~neutral overnight
    for hour in range(24):
        assert -1.0 <= admit_discharge_bias(_at(_MON, hour)) <= 1.0


def test_backfill_timestamps_monotonic_and_sized():
    rng = random.Random(7)
    hours = 168
    peak = 400.0
    start = _MON
    ts = build_backfill_timestamps(hours, peak, rng, start)

    # Monotonic non-decreasing so downstream per-visit event_ts ordering stays valid.
    assert all(ts[i] <= ts[i + 1] for i in range(len(ts) - 1))
    # All timestamps fall within the requested window.
    assert ts[0] >= start
    assert ts[-1] < start + timedelta(hours=hours)
    # A week at peak 400 lands around ~30k events (loose band absorbs the noise).
    assert 20_000 < len(ts) < 40_000
