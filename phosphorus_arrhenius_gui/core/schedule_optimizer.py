from __future__ import annotations

from dataclasses import dataclass
import math

import pandas as pd

from .arrhenius_model import ArrheniusFit, rate_from_fit, temperature_for_k


@dataclass
class ScheduleResult:
    feasible: bool
    message: str
    stages: pd.DataFrame
    summary: dict


def _format_hour(value: float) -> str:
    text = f"{value:.10g}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def scaled_rate_mg_hour(
    fit: ArrheniusFit,
    temperature_c: float,
    current_mass_mg: float,
    reference_mass_mg: float,
    surface_area_factor: float,
) -> float:
    _ = reference_mass_mg
    k = rate_from_fit(fit, temperature_c, surface_area_factor)
    return k * current_mass_mg * 60


def _stage_loss_mg(k_per_min: float, current_mass_mg: float, duration_h: float) -> float:
    return current_mass_mg * (1 - math.exp(-k_per_min * duration_h * 60))


def _stage_model_parts(
    fit_0_120: ArrheniusFit,
    fit_after_120: ArrheniusFit,
    start_h: float,
    end_h: float,
    switch_h: float = 2.0,
) -> list[tuple[str, ArrheniusFit, float]]:
    parts: list[tuple[str, ArrheniusFit, float]] = []
    if start_h < switch_h and end_h > start_h:
        first_end = min(end_h, switch_h)
        if first_end > start_h:
            parts.append(("k1", fit_0_120, first_end - start_h))
    if end_h > switch_h:
        second_start = max(start_h, switch_h)
        if end_h > second_start:
            parts.append(("k2", fit_after_120, end_h - second_start))
    return parts


def _model_used(parts: list[tuple[str, ArrheniusFit, float]]) -> str:
    names = []
    for name, _fit, duration in parts:
        if duration > 1e-12 and name not in names:
            names.append(name)
    return "+".join(names)


def _composite_stage_loss(
    parts: list[tuple[str, ArrheniusFit, float]],
    temperature_c: float,
    current_mass_mg: float,
    surface_area_factor: float,
    minimum_remaining_mg: float | None = None,
) -> tuple[float, float, float, float]:
    remaining = float(current_mass_mg)
    initial_rate: float | None = None
    final_rate = 0.0
    representative_k = 0.0
    weighted_minutes = 0.0
    for _name, fit, duration_h in parts:
        if duration_h <= 0:
            continue
        k_per_min = rate_from_fit(fit, temperature_c, surface_area_factor)
        minutes = duration_h * 60
        if initial_rate is None:
            initial_rate = k_per_min * remaining * 60
        loss = remaining * (1 - math.exp(-k_per_min * minutes))
        if minimum_remaining_mg is not None and remaining - loss < minimum_remaining_mg:
            loss = max(0.0, remaining - minimum_remaining_mg)
        remaining -= loss
        representative_k += k_per_min * minutes
        weighted_minutes += minutes
        final_rate = k_per_min * remaining * 60
        if minimum_remaining_mg is not None and remaining <= minimum_remaining_mg + 1e-9:
            break
    if initial_rate is None:
        initial_rate = 0.0
    average_k = representative_k / weighted_minutes if weighted_minutes else 0.0
    return current_mass_mg - remaining, initial_rate, final_rate, average_k


def _temperature_for_composite_stage_loss(
    parts: list[tuple[str, ArrheniusFit, float]],
    target_loss_mg: float,
    current_mass_mg: float,
    start_temperature_c: float,
    end_temperature_c: float,
    surface_area_factor: float,
) -> tuple[float, bool, str]:
    if target_loss_mg <= 0:
        return start_temperature_c, False, ""
    low = float(start_temperature_c)
    high = float(end_temperature_c)
    low_loss, *_ = _composite_stage_loss(parts, low, current_mass_mg, surface_area_factor)
    high_loss, *_ = _composite_stage_loss(parts, high, current_mass_mg, surface_area_factor)
    if target_loss_mg <= low_loss:
        return low, True, f"Required temperature is below start range; applied {low:g} C"
    if target_loss_mg >= high_loss:
        return high, True, f"Required temperature is above end range; applied {high:g} C"
    for _ in range(80):
        mid = (low + high) / 2
        mid_loss, *_ = _composite_stage_loss(parts, mid, current_mass_mg, surface_area_factor)
        if mid_loss < target_loss_mg:
            low = mid
        else:
            high = mid
    return high, False, ""


def _durations_from_time_step(total_hours: float, time_step_hours: float) -> list[float]:
    durations: list[float] = []
    elapsed = 0.0
    while elapsed < total_hours - 1e-12:
        duration = min(time_step_hours, total_hours - elapsed)
        durations.append(duration)
        elapsed += duration
    return durations


def _required_temperature_for_average_rate(
    fit: ArrheniusFit,
    target_rate_mg_hour: float,
    current_mass_mg: float,
    duration_h: float,
    surface_area_factor: float,
) -> float:
    target_loss = target_rate_mg_hour * duration_h
    if target_loss >= current_mass_mg:
        target_loss = current_mass_mg * (1 - 1e-12)
    fraction = target_loss / current_mass_mg
    k_per_min = -math.log(1 - fraction) / (duration_h * 60)
    return temperature_for_k(fit, k_per_min, surface_area_factor)


def _integer_temperature(required_temp_c: float, start_temp_c: float, end_temp_c: float) -> tuple[int, bool, str]:
    integer_temp = math.ceil(required_temp_c)
    if integer_temp < start_temp_c:
        return int(math.ceil(start_temp_c)), True, f"필요온도 {required_temp_c:.2f} C가 시작온도보다 낮아 시작온도 적용"
    if integer_temp > end_temp_c:
        return int(math.floor(end_temp_c)), True, f"필요온도 {required_temp_c:.2f} C가 종료온도보다 높아 종료온도 적용"
    if abs(integer_temp - required_temp_c) > 1e-9:
        return int(integer_temp), False, f"정수 올림: {required_temp_c:.2f} C -> {integer_temp:d} C"
    return int(integer_temp), False, ""


def calculate_schedule(
    fit: ArrheniusFit,
    initial_mass_mg: float = 2000.0,
    minimum_remaining_mg: float = 200.0,
    total_hours: float = 8.0,
    target_average_mg_hour: float = 120.0,
    minimum_instant_mg_hour: float = 80.0,
    start_temperature_c: float = 360.0,
    end_temperature_c: float = 410.0,
    temperature_increment_c: float = 5.0,
    minimum_stage_duration_h: float = 0.5,
    max_stage_count: int = 8,
    average_tolerance_percent: float = 2.0,
    surface_area_factor: float = 1.0,
    mode: str = "Time-step optimized",
    reference_mass_mg: float = 200.0,
    time_step_hours: float | None = None,
) -> ScheduleResult:
    _ = (temperature_increment_c, max_stage_count, mode, reference_mass_mg)

    if not fit.is_valid:
        return ScheduleResult(False, "선택한 Arrhenius 모델이 유효하지 않습니다.", pd.DataFrame(), {})
    if initial_mass_mg <= 0 or surface_area_factor <= 0:
        return ScheduleResult(False, "초기 질량과 surface factor는 0보다 커야 합니다.", pd.DataFrame(), {})
    if minimum_remaining_mg < 0 or minimum_remaining_mg >= initial_mass_mg:
        return ScheduleResult(False, "최소 잔류량은 0 이상, 초기 질량보다 작아야 합니다.", pd.DataFrame(), {})
    if total_hours <= 0 or target_average_mg_hour <= 0 or minimum_instant_mg_hour <= 0:
        return ScheduleResult(False, "공정 시간과 소모율 조건은 0보다 커야 합니다.", pd.DataFrame(), {})
    if start_temperature_c > end_temperature_c:
        return ScheduleResult(False, "시작 온도는 종료 온도보다 작거나 같아야 합니다.", pd.DataFrame(), {})
    if time_step_hours is None:
        time_step_hours = minimum_stage_duration_h
    if time_step_hours <= 0:
        return ScheduleResult(False, "시간 간격은 0보다 커야 합니다.", pd.DataFrame(), {})

    durations = _durations_from_time_step(total_hours, time_step_hours)
    remaining = float(initial_mass_mg)
    cumulative_loss = 0.0
    elapsed = 0.0
    rows: list[dict] = []
    out_of_user_range = False
    out_of_measured_range = False
    min_rate_failed = False
    effective_rate_failed = False
    minimum_remaining_limited = False

    for stage, duration_h in enumerate(durations, start=1):
        start_h = elapsed
        end_h = elapsed + duration_h
        p_before = remaining
        remaining_allowed = max(0.0, p_before - minimum_remaining_mg)
        remaining_time = max(total_hours - elapsed, duration_h)
        required_total_loss_left = max(0.0, target_average_mg_hour * total_hours - cumulative_loss)
        stage_target_rate = required_total_loss_left / remaining_time if remaining_time else 0.0

        if stage_target_rate < minimum_instant_mg_hour and remaining_allowed > 0:
            stage_target_rate = minimum_instant_mg_hour

        max_stage_rate_without_crossing_min = remaining_allowed / duration_h if duration_h else 0.0
        remark_parts: list[str] = []
        if stage_target_rate > max_stage_rate_without_crossing_min:
            stage_target_rate = max_stage_rate_without_crossing_min
            minimum_remaining_limited = True
            remark_parts.append("최소 잔류량 보호로 목표 소모율 낮춤")

        if stage_target_rate <= 0 or remaining_allowed <= 0:
            required_temp = float("nan")
            applied_temp = int(math.ceil(start_temperature_c))
            k_per_min = 0.0
            initial_rate = 0.0
            final_rate = 0.0
            stage_loss = 0.0
            temp_outside_user_range = False
            remark_parts.append("최소 잔류량 도달")
        else:
            required_temp = _required_temperature_for_average_rate(
                fit,
                stage_target_rate,
                p_before,
                duration_h,
                surface_area_factor,
            )
            applied_temp, temp_outside_user_range, temp_remark = _integer_temperature(
                required_temp,
                start_temperature_c,
                end_temperature_c,
            )
            if temp_remark:
                remark_parts.append(temp_remark)
            out_of_user_range = out_of_user_range or temp_outside_user_range
            k_per_min = rate_from_fit(fit, applied_temp, surface_area_factor)
            initial_rate = k_per_min * p_before * 60
            predicted_loss = _stage_loss_mg(k_per_min, p_before, duration_h)
            stage_loss = min(predicted_loss, remaining_allowed)
            if stage_loss < predicted_loss - 1e-9:
                minimum_remaining_limited = True
                remark_parts.append("최소 잔류량 보호로 구간 소모량 제한")
            final_rate = k_per_min * max(p_before - stage_loss, minimum_remaining_mg) * 60

        cumulative_loss += stage_loss
        remaining = max(minimum_remaining_mg, initial_mass_mg - cumulative_loss)
        effective_rate = stage_loss / duration_h if duration_h else 0.0
        minimum_rate_satisfied = effective_rate >= minimum_instant_mg_hour - 1e-9
        lower_target = target_average_mg_hour * 0.95
        upper_target = target_average_mg_hour * 1.05
        effective_rate_satisfied = lower_target - 1e-9 <= effective_rate <= upper_target + 1e-9
        min_rate_failed = min_rate_failed or not minimum_rate_satisfied
        effective_rate_failed = effective_rate_failed or not effective_rate_satisfied
        within_measured_range = bool(fit.min_temperature_c <= applied_temp <= fit.max_temperature_c)
        out_of_measured_range = out_of_measured_range or not within_measured_range
        if not within_measured_range:
            remark_parts.append("실험 범위 밖 외삽")

        rows.append(
            {
                "Stage": stage,
                "Time range (h)": f"{_format_hour(start_h)}-{_format_hour(end_h)}",
                "Temperature C": applied_temp,
                "Stage P loss mg": stage_loss,
                "P before mg": p_before,
                "Remaining P mg": remaining,
                "Cumulative P loss mg": cumulative_loss,
                "Effective rate mg/hour": effective_rate,
                "Initial rate mg/hour": initial_rate,
                "Final rate mg/hour": final_rate,
                "Minimum rate satisfied": bool(minimum_rate_satisfied),
                "Effective rate satisfied": bool(effective_rate_satisfied),
                "비고": " / ".join(dict.fromkeys(part for part in remark_parts if part)),
            }
        )
        elapsed = end_h

    table = pd.DataFrame(rows)
    total_loss = float(table["Stage P loss mg"].sum()) if not table.empty else 0.0
    average_rate = total_loss / total_hours if total_hours else 0.0
    min_effective = float(table["Effective rate mg/hour"].min()) if not table.empty else 0.0
    max_effective = float(table["Effective rate mg/hour"].max()) if not table.empty else 0.0
    target_error_percent = (
        abs(average_rate - target_average_mg_hour) / target_average_mg_hour * 100
        if target_average_mg_hour
        else 0.0
    )
    target_satisfied = target_error_percent <= average_tolerance_percent
    feasible = target_satisfied and not min_rate_failed and not out_of_user_range
    measured_range_message = (
        "실험 온도 범위를 벗어난 외삽 구간이 포함되어 있습니다."
        if out_of_measured_range
        else "모든 구간이 실험 온도 범위 내에서 계산되었습니다."
    )

    summary = {
        "first_order_model": True,
        "average_rate_mg_hour": average_rate,
        "final_remaining_p_mg": initial_mass_mg - total_loss,
        "measured_range_message": measured_range_message,
        "stage_count": len(table),
        "total_process_time_h": total_hours,
        "initial_mass_mg": initial_mass_mg,
        "minimum_effective_rate_mg_hour": min_effective,
        "maximum_effective_rate_mg_hour": max_effective,
        "target_satisfied": target_satisfied,
        "minimum_rate_satisfied": not min_rate_failed,
        "effective_rate_satisfied_all_stages": not effective_rate_failed,
        "minimum_remaining_limited": minimum_remaining_limited,
        "extrapolation_status": out_of_measured_range,
        "model_condition": fit.condition,
    }

    message = (
        "1차 반응식 적용\n"
        f"전체 평균 소모속도: {average_rate:.2f} mg/h\n"
        f"최종 잔류량: {initial_mass_mg - total_loss:.2f} mg\n"
        f"{measured_range_message}\n"
        f"사용된 stage 수: {len(table)}\n"
        f"총 공정시간: {total_hours:g} h\n"
        f"초기 P 질량: {initial_mass_mg:g} mg"
    )
    return ScheduleResult(feasible, message, table, summary)


def calculate_composite_schedule(
    fit_0_120: ArrheniusFit,
    fit_after_120: ArrheniusFit,
    initial_mass_mg: float = 2000.0,
    minimum_remaining_mg: float = 200.0,
    total_hours: float = 8.0,
    target_average_mg_hour: float = 120.0,
    minimum_instant_mg_hour: float = 80.0,
    start_temperature_c: float = 360.0,
    end_temperature_c: float = 410.0,
    temperature_increment_c: float = 5.0,
    minimum_stage_duration_h: float = 0.5,
    max_stage_count: int = 8,
    average_tolerance_percent: float = 2.0,
    surface_area_factor: float = 1.0,
    mode: str = "Time-step optimized",
    reference_mass_mg: float = 200.0,
    time_step_hours: float | None = None,
) -> ScheduleResult:
    _ = (temperature_increment_c, max_stage_count, mode, reference_mass_mg)

    if not fit_0_120.is_valid:
        return ScheduleResult(False, "k1 Arrhenius model (0-120 min) is not valid.", pd.DataFrame(), {})
    if total_hours > 2.0 and not fit_after_120.is_valid:
        return ScheduleResult(False, "k2 Arrhenius model (After 120 min) is not valid.", pd.DataFrame(), {})
    if initial_mass_mg <= 0 or surface_area_factor <= 0:
        return ScheduleResult(False, "Initial mass and surface factor must be greater than zero.", pd.DataFrame(), {})
    if minimum_remaining_mg < 0 or minimum_remaining_mg >= initial_mass_mg:
        return ScheduleResult(False, "Minimum remaining mass must be >= 0 and smaller than initial mass.", pd.DataFrame(), {})
    if total_hours <= 0 or target_average_mg_hour <= 0 or minimum_instant_mg_hour <= 0:
        return ScheduleResult(False, "Process time and rate targets must be greater than zero.", pd.DataFrame(), {})
    if start_temperature_c > end_temperature_c:
        return ScheduleResult(False, "Start temperature must be lower than or equal to end temperature.", pd.DataFrame(), {})
    if time_step_hours is None:
        time_step_hours = minimum_stage_duration_h
    if time_step_hours <= 0:
        return ScheduleResult(False, "Time step must be greater than zero.", pd.DataFrame(), {})

    durations = _durations_from_time_step(total_hours, time_step_hours)
    remaining = float(initial_mass_mg)
    cumulative_loss = 0.0
    elapsed = 0.0
    rows: list[dict] = []
    out_of_user_range = False
    out_of_measured_range = False
    min_rate_failed = False
    effective_rate_failed = False
    minimum_remaining_limited = False

    for stage, duration_h in enumerate(durations, start=1):
        start_h = elapsed
        end_h = elapsed + duration_h
        p_before = remaining
        parts = _stage_model_parts(fit_0_120, fit_after_120, start_h, end_h)
        model_used = _model_used(parts)
        remaining_allowed = max(0.0, p_before - minimum_remaining_mg)
        remaining_time = max(total_hours - elapsed, duration_h)
        required_total_loss_left = max(0.0, target_average_mg_hour * total_hours - cumulative_loss)
        stage_target_rate = required_total_loss_left / remaining_time if remaining_time else 0.0

        if stage_target_rate < minimum_instant_mg_hour and remaining_allowed > 0:
            stage_target_rate = minimum_instant_mg_hour

        max_stage_rate_without_crossing_min = remaining_allowed / duration_h if duration_h else 0.0
        remark_parts: list[str] = []
        if stage_target_rate > max_stage_rate_without_crossing_min:
            stage_target_rate = max_stage_rate_without_crossing_min
            minimum_remaining_limited = True
            remark_parts.append("minimum remaining limit applied")

        if stage_target_rate <= 0 or remaining_allowed <= 0:
            applied_temp = int(math.ceil(start_temperature_c))
            k_per_min = 0.0
            initial_rate = 0.0
            final_rate = 0.0
            stage_loss = 0.0
            temp_outside_user_range = False
            remark_parts.append("minimum remaining reached")
        else:
            target_loss = min(stage_target_rate * duration_h, remaining_allowed)
            required_temp, temp_outside_user_range, temp_remark = _temperature_for_composite_stage_loss(
                parts,
                target_loss,
                p_before,
                start_temperature_c,
                end_temperature_c,
                surface_area_factor,
            )
            applied_temp, integer_outside, integer_remark = _integer_temperature(
                required_temp,
                start_temperature_c,
                end_temperature_c,
            )
            temp_outside_user_range = temp_outside_user_range or integer_outside
            for remark in (temp_remark, integer_remark):
                if remark:
                    remark_parts.append(remark)
            out_of_user_range = out_of_user_range or temp_outside_user_range
            stage_loss, initial_rate, final_rate, k_per_min = _composite_stage_loss(
                parts,
                applied_temp,
                p_before,
                surface_area_factor,
                minimum_remaining_mg,
            )
            if stage_loss >= remaining_allowed - 1e-9 and p_before - stage_loss <= minimum_remaining_mg + 1e-9:
                minimum_remaining_limited = True
                remark_parts.append("minimum remaining protected")

        cumulative_loss += stage_loss
        remaining = max(minimum_remaining_mg, initial_mass_mg - cumulative_loss)
        effective_rate = stage_loss / duration_h if duration_h else 0.0
        minimum_rate_satisfied = effective_rate >= minimum_instant_mg_hour - 1e-9
        lower_target = target_average_mg_hour * 0.95
        upper_target = target_average_mg_hour * 1.05
        effective_rate_satisfied = lower_target - 1e-9 <= effective_rate <= upper_target + 1e-9
        min_rate_failed = min_rate_failed or not minimum_rate_satisfied
        effective_rate_failed = effective_rate_failed or not effective_rate_satisfied

        measured_checks = []
        for _name, fit, duration_part in parts:
            if duration_part <= 1e-12:
                continue
            measured_checks.append(fit.min_temperature_c <= applied_temp <= fit.max_temperature_c)
        within_measured_range = all(measured_checks) if measured_checks else True
        out_of_measured_range = out_of_measured_range or not within_measured_range
        if not within_measured_range:
            remark_parts.append("실험 범위 밖 외삽")

        rows.append(
            {
                "Stage": stage,
                "Time range (h)": f"{_format_hour(start_h)}-{_format_hour(end_h)}",
                "Model used": model_used,
                "Temperature C": applied_temp,
                "Stage P loss mg": stage_loss,
                "P before mg": p_before,
                "Remaining P mg": remaining,
                "Cumulative P loss mg": cumulative_loss,
                "Effective rate mg/hour": effective_rate,
                "Initial rate mg/hour": initial_rate,
                "Final rate mg/hour": final_rate,
                "k min^-1": k_per_min,
                "Minimum rate satisfied": str(bool(minimum_rate_satisfied)),
                "Effective rate satisfied": str(bool(effective_rate_satisfied)),
                "Within measured range": str(bool(within_measured_range)),
                "비고": " / ".join(dict.fromkeys(part for part in remark_parts if part)),
            }
        )
        elapsed = end_h

    table = pd.DataFrame(rows)
    total_loss = float(table["Stage P loss mg"].sum()) if not table.empty else 0.0
    average_rate = total_loss / total_hours if total_hours else 0.0
    min_effective = float(table["Effective rate mg/hour"].min()) if not table.empty else 0.0
    max_effective = float(table["Effective rate mg/hour"].max()) if not table.empty else 0.0
    target_error_percent = (
        abs(average_rate - target_average_mg_hour) / target_average_mg_hour * 100
        if target_average_mg_hour
        else 0.0
    )
    target_satisfied = target_error_percent <= average_tolerance_percent
    feasible = target_satisfied and not min_rate_failed and not out_of_user_range
    measured_range_message = (
        "실험 온도 범위를 벗어난 외삽 구간이 포함되어 있습니다."
        if out_of_measured_range
        else "모든 구간이 실험 온도 범위 내에서 계산되었습니다."
    )

    summary = {
        "first_order_model": True,
        "average_rate_mg_hour": average_rate,
        "final_remaining_p_mg": initial_mass_mg - total_loss,
        "measured_range_message": measured_range_message,
        "stage_count": len(table),
        "total_process_time_h": total_hours,
        "initial_mass_mg": initial_mass_mg,
        "minimum_effective_rate_mg_hour": min_effective,
        "maximum_effective_rate_mg_hour": max_effective,
        "target_satisfied": target_satisfied,
        "minimum_rate_satisfied": not min_rate_failed,
        "effective_rate_satisfied_all_stages": not effective_rate_failed,
        "minimum_remaining_limited": minimum_remaining_limited,
        "extrapolation_status": out_of_measured_range,
        "model_condition": "0.15 Torr / Ar 20 sccm composite k1/k2",
    }

    message = (
        "1차 반응식 적용: k1은 0-120 min, k2는 120 min 이후 자동 적용\n"
        f"전체 평균 소모속도: {average_rate:.2f} mg/h\n"
        f"최종 잔류량: {initial_mass_mg - total_loss:.2f} mg\n"
        f"{measured_range_message}\n"
        f"사용된 stage 수: {len(table)}\n"
        f"총 공정시간: {total_hours:g} h\n"
        f"초기 P 질량: {initial_mass_mg:g} mg"
    )
    return ScheduleResult(feasible, message, table, summary)
