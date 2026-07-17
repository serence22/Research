from __future__ import annotations

import math
import re
from typing import Any

import pandas as pd

from .constants import (
    AR_TOLERANCE,
    BASE_CONDITION_015,
    CONDITION_002,
    PRESSURE_TOLERANCE_002,
    PRESSURE_TOLERANCE_0029,
    PRESSURE_TOLERANCE_015,
    TEMPERATURE_OVERRIDES,
)


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value).strip())


def clean_column_name(value: Any) -> str:
    return clean_text(value)


def is_missing(value: Any) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value)) or pd.isna(value)


def parse_first_number(value: Any) -> float | None:
    if is_missing(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"[-+]?\d+(?:\.\d+)?", str(value))
    return float(match.group(0)) if match else None


def parse_pressure(value: Any) -> float | None:
    return parse_first_number(value)


def canonical_pressure(raw_pressure: float | None) -> tuple[float | None, str | None, str]:
    if raw_pressure is None:
        return None, None, "pressure parsing failed"
    if abs(raw_pressure - 0.029) <= PRESSURE_TOLERANCE_0029:
        return 0.02, CONDITION_002, "raw 0.029 Torr pooled as canonical 0.02 Torr"
    if abs(raw_pressure - 0.02) <= PRESSURE_TOLERANCE_002:
        return 0.02, CONDITION_002, "raw 0.02 Torr kept as canonical 0.02 Torr"
    if abs(raw_pressure - 0.15) <= PRESSURE_TOLERANCE_015:
        return 0.15, BASE_CONDITION_015, "raw 0.15 Torr kept as canonical 0.15 Torr"
    return None, None, f"unsupported pressure: {raw_pressure:g} Torr"


def expected_ar_for_pressure(canonical: float | None) -> float | None:
    if canonical == 0.15:
        return 20.0
    if canonical == 0.02:
        return 0.0
    return None


def validate_or_infer_ar(raw_ar: Any, canonical: float | None) -> tuple[float | None, bool, str | None]:
    expected = expected_ar_for_pressure(canonical)
    if expected is None:
        return None, False, "Ar cannot be inferred without canonical pressure"
    parsed = parse_first_number(raw_ar)
    if parsed is None:
        return expected, True, None
    if abs(parsed - expected) <= AR_TOLERANCE:
        return parsed, False, None
    return parsed, False, f"Ar flow {parsed:g} sccm does not match expected {expected:g} sccm"


def parse_temperature(value: Any, previous_calibrated: bool = False) -> tuple[float | None, str, bool, str]:
    if is_missing(value):
        return None, "missing", False, "temperature is missing"
    text = clean_text(value)
    if text in TEMPERATURE_OVERRIDES:
        corrected = TEMPERATURE_OVERRIDES[text]
        return (
            corrected,
            "user_override",
            True,
            f"{text} was corrected to {corrected:g}°C by user-defined calibration.",
        )
    if isinstance(value, (int, float)):
        return float(value), "numeric", False, ""
    if "=" in text:
        parsed = parse_first_number(text.split("=", 1)[1])
        if parsed is not None:
            return parsed, "equals_rhs", False, ""
    if text == "365(MFC)" and previous_calibrated:
        return (
            373.5,
            "forward_fill_from_previous_row",
            True,
            "Temperature inherited as 373.5°C from the preceding calibrated MFC row.",
        )
    return None, "manual_review_required", False, "temperature check required"


def normalize_equipment(cvd_name: Any) -> str:
    text = clean_text(cvd_name).upper().replace(" ", "")
    if "CVD1" in text:
        return "CVD1"
    if "CVD2" in text:
        return "CVD2"
    return clean_text(cvd_name) or "UNKNOWN"


def infer_loading_class(cvd_name: Any, initial_mass: Any = None) -> int | None:
    text = clean_text(cvd_name).lower().replace(" ", "")
    if "400mg" in text or "(400" in text:
        return 400
    if "200mg" in text or "(200" in text:
        return 200
    mass = parse_first_number(initial_mass)
    if mass is None:
        return None
    if 150 <= mass <= 250:
        return 200
    if 330 <= mass <= 470:
        return 400
    return int(round(mass))
