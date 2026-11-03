"""
services/hazard_service.py — Fire Sentinel

Combines the CNN class, the YOLO flame boxes and the growth since the previous snapshot into one
hazard level for a snapshot. Pure logic: no Flask, no model code, easy to test and to retune.

Levels
  HAZARDOUS   any of: CNN says HAZARDOUS_FIRE | flame area >= HAZARD_AREA_RATIO | flame area grew
              >= HAZARD_GROWTH_RATIO times since the previous snapshot (and is >= HAZARD_GROWTH_MIN_AREA)
  CONTROLLED  flame evidence (CNN says CONTROLLED_FLAME, or the detector sees a flame) but small and not growing
  NONE        the CNN says NO_FLAME and the detector found nothing
  UNKNOWN     no usable evidence (CNN not loaded and the detector found nothing / was off)

Escalation is deliberately one-way: any single hazardous signal wins. "Detector found nothing" is never
treated as proof of no fire (its box recall is only about 57%).

KNOWN WEAKNESS: a close-up of a small, harmless flame (stove) can fill a big part of the frame and trip
the area rule. Growth, the CNN class and the sensors are the counterweights, and the thresholds in
config.py are uncalibrated placeholders until tuned on real OV3660 footage.
"""
from dataclasses import dataclass, field

import config


@dataclass
class HazardAssessment:
    level: str
    reasons: list = field(default_factory=list)
    growth: float = None        # area now / area in previous snapshot, None when not comparable


def previous_flame_area(conn, device_id):
    """Flame area of this device's most recent snapshot inside the growth window, or None.
    Only rows where the detector actually ran (flame_area_ratio not NULL) count."""
    row = conn.execute(
        """SELECT flame_area_ratio FROM snapshots
           WHERE device_id = ? AND flame_area_ratio IS NOT NULL
             AND created_at >= datetime('now', ?)
           ORDER BY id DESC LIMIT 1""",
        (device_id, f"-{int(config.HAZARD_GROWTH_WINDOW_S)} seconds"),
    ).fetchone()
    return None if row is None else row[0]


def assess(cnn_label, detection, previous_area=None):
    reasons = []
    det_ok = detection is not None and detection.status == "ok"
    flame_seen = det_ok and detection.n_flames > 0
    area = detection.area_ratio if flame_seen else 0.0

    growth = None
    if flame_seen and previous_area is not None and previous_area > 0:
        growth = area / previous_area

    hazardous = False
    if cnn_label == "HAZARDOUS_FIRE":
        hazardous = True; reasons.append("CNN classified the image as hazardous fire")
    if flame_seen and area >= config.HAZARD_AREA_RATIO:
        hazardous = True; reasons.append(f"flame covers {area:.0%} of the frame (limit {config.HAZARD_AREA_RATIO:.0%})")
    if growth is not None and growth >= config.HAZARD_GROWTH_RATIO and area >= config.HAZARD_GROWTH_MIN_AREA:
        hazardous = True; reasons.append(f"flame area grew {growth:.1f}x since the previous snapshot")
    if hazardous:
        return HazardAssessment("HAZARDOUS", reasons, growth)

    if cnn_label == "CONTROLLED_FLAME":
        reasons.append("CNN classified the image as a controlled flame")
    if flame_seen:
        reasons.append(f"detector sees {detection.n_flames} flame(s) covering {area:.1%} of the frame, not growing")
    if cnn_label == "NO_FLAME" and flame_seen:
        reasons.append("CNN and detector disagree (CNN says no flame)")
    if cnn_label == "CONTROLLED_FLAME" or flame_seen:
        return HazardAssessment("CONTROLLED", reasons, growth)

    if cnn_label == "NO_FLAME":
        reasons.append("CNN found no flame and the detector found none" if det_ok
                       else "CNN found no flame (detector not available)")
        return HazardAssessment("NONE", reasons, growth)

    reasons.append("no usable classifier result and no flame detected")
    if not det_ok:
        reasons.append("flame detector not available")
    return HazardAssessment("UNKNOWN", reasons, growth)
