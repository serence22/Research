from __future__ import annotations

from dataclasses import dataclass
import math

from .arrhenius_model import ArrheniusFit, rate_from_fit


@dataclass
class PredictionResult:
    condition: str
    model_type: str
    temperature_c: float
    process_time_min: float
    initial_mass_mg: float
    reference_mass_mg: float
    mass_scaling_factor: float
    surface_area_factor: float
    k_per_min: float
    q_mg_per_min: float
    q_mg_per_hour: float
    initial_rate_mg_per_hour: float
    predicted_loss_mg: float
    remaining_mass_mg: float
    consumed_fraction_percent: float
    range_status: str
    warning: str


@dataclass
class CompositePredictionSegment:
    model: str
    start_min: float
    end_min: float
    k_per_min: float
    p_before_mg: float
    loss_mg: float
    remaining_mg: float


@dataclass
class CompositePredictionResult:
    condition: str
    model_type: str
    temperature_c: float
    process_time_min: float
    initial_mass_mg: float
    k1_per_min: float | None
    k2_per_min: float | None
    q_mg_per_min: float
    q_mg_per_hour: float
    initial_rate_mg_per_hour: float
    predicted_loss_mg: float
    remaining_mass_mg: float
    consumed_fraction_percent: float
    range_status: str
    warning: str
    segments: list[CompositePredictionSegment]


def predict_loss(
    fit: ArrheniusFit,
    initial_mass_mg: float,
    temperature_c: float,
    process_time: float,
    time_unit: str = "min",
    surface_area_factor: float = 1.0,
    reference_mass_mg: float = 200.0,
) -> PredictionResult:
    if initial_mass_mg <= 0:
        raise ValueError("초기 P 질량은 0보다 커야 합니다.")
    if process_time <= 0:
        raise ValueError("공정 시간은 0보다 커야 합니다.")
    if surface_area_factor <= 0:
        raise ValueError("surface-area factor는 0보다 커야 합니다.")
    if reference_mass_mg <= 0:
        raise ValueError("기준 질량은 0보다 커야 합니다.")

    time_min = process_time * 60 if time_unit == "hour" else process_time
    k = rate_from_fit(fit, temperature_c, surface_area_factor)
    remaining = initial_mass_mg * math.exp(-k * time_min)
    loss = initial_mass_mg - remaining
    average_rate_min = loss / time_min
    in_range = fit.min_temperature_c <= temperature_c <= fit.max_temperature_c
    warning = (
        "1차 반응식 적용: M(t)=M0*exp(-k*t), loss=M0*(1-exp(-k*t)). "
        "따라서 같은 온도/시간/압력에서는 초기 질량이 n배이면 소모량도 n배입니다."
    )
    return PredictionResult(
        condition=fit.condition,
        model_type=fit.model_type,
        temperature_c=temperature_c,
        process_time_min=time_min,
        initial_mass_mg=initial_mass_mg,
        reference_mass_mg=reference_mass_mg,
        mass_scaling_factor=initial_mass_mg / reference_mass_mg,
        surface_area_factor=surface_area_factor,
        k_per_min=k,
        q_mg_per_min=average_rate_min,
        q_mg_per_hour=average_rate_min * 60,
        initial_rate_mg_per_hour=k * initial_mass_mg * 60,
        predicted_loss_mg=loss,
        remaining_mass_mg=remaining,
        consumed_fraction_percent=loss / initial_mass_mg * 100,
        range_status="interpolation" if in_range else "extrapolation",
        warning=warning,
    )


def predict_loss_composite(
    fit_0_120: ArrheniusFit,
    fit_after_120: ArrheniusFit,
    initial_mass_mg: float,
    temperature_c: float,
    process_time: float,
    time_unit: str = "min",
    surface_area_factor: float = 1.0,
    switch_time_min: float = 120.0,
) -> CompositePredictionResult:
    if initial_mass_mg <= 0:
        raise ValueError("initial P mass must be greater than zero.")
    if process_time <= 0:
        raise ValueError("process time must be greater than zero.")
    if surface_area_factor <= 0:
        raise ValueError("surface-area factor must be greater than zero.")
    if not fit_0_120.is_valid:
        raise ValueError("k1 Arrhenius model (0-120 min) is not valid.")

    time_min = process_time * 60 if time_unit == "hour" else process_time
    needs_k2 = time_min > switch_time_min + 1e-12
    if needs_k2 and not fit_after_120.is_valid:
        raise ValueError("k2 Arrhenius model (After 120 min) is not valid.")

    k1 = rate_from_fit(fit_0_120, temperature_c, surface_area_factor)
    k2 = rate_from_fit(fit_after_120, temperature_c, surface_area_factor) if needs_k2 else None
    segments: list[CompositePredictionSegment] = []
    remaining = float(initial_mass_mg)

    first_end = min(time_min, switch_time_min)
    if first_end > 0:
        loss = remaining * (1 - math.exp(-k1 * first_end))
        remaining -= loss
        segments.append(
            CompositePredictionSegment(
                model="k1 (0-120 min)",
                start_min=0.0,
                end_min=first_end,
                k_per_min=k1,
                p_before_mg=initial_mass_mg,
                loss_mg=loss,
                remaining_mg=remaining,
            )
        )

    if needs_k2 and k2 is not None:
        duration = time_min - switch_time_min
        p_before = remaining
        loss = remaining * (1 - math.exp(-k2 * duration))
        remaining -= loss
        segments.append(
            CompositePredictionSegment(
                model="k2 (After 120 min)",
                start_min=switch_time_min,
                end_min=time_min,
                k_per_min=k2,
                p_before_mg=p_before,
                loss_mg=loss,
                remaining_mg=remaining,
            )
        )

    total_loss = initial_mass_mg - remaining
    average_rate_min = total_loss / time_min
    ranges = [fit_0_120.min_temperature_c <= temperature_c <= fit_0_120.max_temperature_c]
    if needs_k2:
        ranges.append(fit_after_120.min_temperature_c <= temperature_c <= fit_after_120.max_temperature_c)
    in_range = all(ranges)
    return CompositePredictionResult(
        condition="0.15 Torr / Ar 20 sccm",
        model_type="Composite first-order Arrhenius: k1 until 120 min, k2 after 120 min",
        temperature_c=temperature_c,
        process_time_min=time_min,
        initial_mass_mg=initial_mass_mg,
        k1_per_min=k1,
        k2_per_min=k2,
        q_mg_per_min=average_rate_min,
        q_mg_per_hour=average_rate_min * 60,
        initial_rate_mg_per_hour=k1 * initial_mass_mg * 60,
        predicted_loss_mg=total_loss,
        remaining_mass_mg=remaining,
        consumed_fraction_percent=total_loss / initial_mass_mg * 100,
        range_status="interpolation" if in_range else "extrapolation",
        warning="Uses k1 for 0-120 min and automatically switches to k2 after 120 min.",
        segments=segments,
    )
