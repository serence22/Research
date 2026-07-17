from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
import pandas as pd

from .constants import R_GAS


@dataclass
class ArrheniusFit:
    condition: str
    status: str
    model_type: str
    a_mg_per_min: float | None = None
    ln_a: float | None = None
    ea_j_per_mol: float | None = None
    ea_kj_per_mol: float | None = None
    slope: float | None = None
    intercept: float | None = None
    r_squared: float | None = None
    rmse: float | None = None
    temperature_count: int = 0
    series_count: int = 0
    interval_count: int = 0
    min_temperature_c: float | None = None
    max_temperature_c: float | None = None
    warning: str = ""

    @property
    def is_valid(self) -> bool:
        return self.status == "valid" and self.a_mg_per_min is not None and self.ea_j_per_mol is not None


def _first_order_k_per_min(row: pd.Series) -> float:
    p1 = float(row["p1_mg"])
    p2 = float(row["p2_mg"])
    duration = float(row["duration_min"])
    if p1 <= 0 or p2 <= 0 or duration <= 0 or p2 >= p1:
        raise ValueError("invalid first-order interval")
    return -math.log(p2 / p1) / duration


def summarize_temperature_rates(intervals: pd.DataFrame, condition: str) -> pd.DataFrame:
    df = intervals[(intervals["condition"] == condition) & (intervals["fitting_included"] == True)].copy()
    if df.empty:
        return pd.DataFrame()
    df["k_per_min"] = df.apply(_first_order_k_per_min, axis=1)
    rows = []
    for temp, group in df.groupby("parsed_temperature_C"):
        durations = group["duration_min"].astype(float)
        k_values = group["k_per_min"].astype(float)
        losses = group["interval_loss_mg"].astype(float)
        representative_k = float((k_values * durations).sum() / durations.sum())
        rows.append(
            {
                "condition": condition,
                "temperature_C": float(temp),
                "temperature_K": float(temp) + 273.15,
                "representative_k_per_min": representative_k,
                "representative_rate_mg_per_min": representative_k,
                "representative_rate_mg_per_hour": representative_k * 60,
                "mean_k_per_min": float(k_values.mean()),
                "median_k_per_min": float(k_values.median()),
                "std_k_per_min": float(k_values.std(ddof=1)) if len(k_values) > 1 else 0.0,
                "min_k_per_min": float(k_values.min()),
                "max_k_per_min": float(k_values.max()),
                "mean_loss_mg_per_min": float((losses / durations).mean()),
                "series_count": group["series_id"].nunique(),
                "interval_count": len(group),
                "total_duration_min": float(durations.sum()),
            }
        )
    return pd.DataFrame(rows).sort_values("temperature_C")


def fit_arrhenius(summary: pd.DataFrame, condition: str, model_type: str = "First-order Arrhenius") -> ArrheniusFit:
    if summary.empty or summary["temperature_C"].nunique() < 3:
        return ArrheniusFit(condition=condition, status="invalid", model_type=model_type, warning="unique temperatures < 3")
    k_col = "representative_k_per_min" if "representative_k_per_min" in summary.columns else "representative_rate_mg_per_min"
    x = 1.0 / summary["temperature_K"].astype(float).to_numpy()
    y = np.log(summary[k_col].astype(float).to_numpy())
    slope, intercept = np.polyfit(x, y, 1)
    predicted = slope * x + intercept
    ss_res = float(np.sum((y - predicted) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2 = 1 - ss_res / ss_tot if ss_tot else 0.0
    rmse = float(np.sqrt(np.mean((y - predicted) ** 2)))
    ea = -float(slope) * R_GAS
    return ArrheniusFit(
        condition=condition,
        status="valid",
        model_type=model_type,
        a_mg_per_min=float(math.exp(intercept)),
        ln_a=float(intercept),
        ea_j_per_mol=ea,
        ea_kj_per_mol=ea / 1000,
        slope=float(slope),
        intercept=float(intercept),
        r_squared=float(r2),
        rmse=rmse,
        temperature_count=int(summary["temperature_C"].nunique()),
        series_count=int(summary["series_count"].sum()),
        interval_count=int(summary["interval_count"].sum()),
        min_temperature_c=float(summary["temperature_C"].min()),
        max_temperature_c=float(summary["temperature_C"].max()),
    )


def rate_from_fit(fit: ArrheniusFit, temperature_c: float, surface_area_factor: float = 1.0) -> float:
    """Return first-order k in min^-1."""
    if not fit.is_valid:
        raise ValueError("Arrhenius model is not valid.")
    tk = temperature_c + 273.15
    if tk <= 0:
        raise ValueError("temperature must be above absolute zero.")
    return fit.a_mg_per_min * math.exp(-fit.ea_j_per_mol / (R_GAS * tk)) * surface_area_factor


def temperature_for_k(fit: ArrheniusFit, k_per_min: float, surface_area_factor: float = 1.0) -> float:
    if not fit.is_valid:
        raise ValueError("Arrhenius model is not valid.")
    if k_per_min <= 0 or surface_area_factor <= 0:
        raise ValueError("k and surface-area factor must be greater than zero.")
    adjusted_k = k_per_min / surface_area_factor
    denom = fit.ln_a - math.log(adjusted_k)
    if denom <= 0:
        raise ValueError("temperature cannot be calculated from this k.")
    return fit.ea_j_per_mol / (R_GAS * denom) - 273.15


def temperature_for_rate(
    fit: ArrheniusFit,
    rate_mg_per_hour: float,
    current_mass_mg: float = 1.0,
    surface_area_factor: float = 1.0,
) -> float:
    if current_mass_mg <= 0:
        raise ValueError("current mass must be greater than zero.")
    k_per_min = rate_mg_per_hour / (60 * current_mass_mg)
    return temperature_for_k(fit, k_per_min, surface_area_factor)
