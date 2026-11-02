"""
services/gas_pattern_service.py — Fire Sentinel Prototype 2

INTERIM, rule-based version of the "which gas is building up" feature.

Honest framing for the report/viva: MQ-series sensors are broad-spectrum and
NOT gas-specific — they have overlapping response curves. This module does
NOT claim precise multi-gas identification. It compares the RELATIVE
deviation across MQ-2 / MQ-7 / MQ-135 and returns the single most-elevated
channel as a labeled hint, e.g. "MQ-7 (CO) shows the largest deviation —
consistent with incomplete combustion or an electrical/smouldering source."

This gets replaced in the ML phase by a trained pattern classifier (an
"electronic nose" approach) once you have labeled trial sessions for
different gas sources (LPG leak, overheating wire, burning wood, etc.) — the
function signature below is designed to stay the same so routes/services
calling it don't need to change when that swap happens.
"""

from dataclasses import dataclass


@dataclass
class GasSourceHint:
    label: str
    dominant_sensor: str
    confidence_note: str


# Deviation percentages below this are treated as noise, not a real signal.
NOISE_FLOOR_PCT = 15.0


def infer_gas_source_hint(mq2_deviation_pct: float, mq7_deviation_pct: float, mq135_deviation_pct: float) -> GasSourceHint:
    deviations = {
        "MQ-2": mq2_deviation_pct,
        "MQ-7": mq7_deviation_pct,
        "MQ-135": mq135_deviation_pct,
    }
    dominant_sensor = max(deviations, key=deviations.get)
    dominant_value = deviations[dominant_sensor]

    if dominant_value < NOISE_FLOOR_PCT:
        return GasSourceHint(
            label="No significant gas deviation",
            dominant_sensor="none",
            confidence_note="All channels within normal fluctuation range.",
        )

    labels = {
        "MQ-2": "Possible LPG / combustible gas / smoke source",
        "MQ-7": "Possible carbon monoxide buildup (incomplete combustion or smouldering source)",
        "MQ-135": "General air quality degradation (smoke, VOCs, or broad combustion byproducts)",
    }

    return GasSourceHint(
        label=labels[dominant_sensor],
        dominant_sensor=dominant_sensor,
        confidence_note=(
            f"Heuristic hint based on relative sensor deviation ({dominant_value:.0f}% above baseline "
            f"on {dominant_sensor}), not a calibrated multi-gas identification."
        ),
    )
