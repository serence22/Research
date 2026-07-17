from pathlib import Path

import pandas as pd

from phosphorus_arrhenius_gui.core.analysis_pipeline import refit_bundle_from_selection, run_analysis
from phosphorus_arrhenius_gui.core.constants import CONDITION_015_AFTER_120, CONDITION_015_0_120, FIT_CONDITIONS
from phosphorus_arrhenius_gui.core.predictor import predict_loss
from phosphorus_arrhenius_gui.core.schedule_optimizer import calculate_schedule
from phosphorus_arrhenius_gui.core.summary_sheet_loader import build_summary_intervals, read_summary_sheet


ROOT = Path(__file__).resolve().parents[2]
SOURCE = next(p for p in ROOT.glob("*ver.7.xlsx") if not p.name.startswith("~$"))


def test_codex_loader_falls_back_to_current_sheet_when_codex_absent():
    df = read_summary_sheet(SOURCE)
    assert len(df) == 12
    assert set(df["source_sheet"]) == {"정리본"}


def test_analysis_uses_only_015_split_conditions():
    bundle = run_analysis(SOURCE)
    assert set(bundle.fits) == set(FIT_CONDITIONS)
    assert set(bundle.intervals["condition"].dropna().unique()) == {CONDITION_015_0_120}
    assert CONDITION_015_0_120 in bundle.fits
    assert CONDITION_015_AFTER_120 in bundle.fits


def test_002_rows_are_excluded_from_fitting_menu_conditions():
    bundle = run_analysis(SOURCE)
    excluded = bundle.intervals[bundle.intervals["original_pressure"].astype(str).str.contains("0.02", na=False)]
    assert not excluded.empty
    assert excluded["condition"].isna().all()
    assert not excluded["fitting_included"].any()


def test_0_120_fit_expected_values_are_stable():
    fit = run_analysis(SOURCE).fits[CONDITION_015_0_120]
    assert fit.is_valid
    assert round(fit.ea_kj_per_mol, 3) == 208.154
    assert round(fit.r_squared, 3) == 0.988


def test_after_120_condition_exists_even_when_no_rows_are_present():
    fit = run_analysis(SOURCE).fits[CONDITION_015_AFTER_120]
    assert not fit.is_valid


def test_time_group_classification_rules():
    data = pd.DataFrame(
        [
            {"CVD 종류": "CVD1", "공정 압력": "0.15 torr", "온도": 350, "T1(min.)": 30, "T2(min.)": 40, "p1 (mg)": 200, "p2(mg)": 190},
            {"CVD 종류": "CVD1", "공정 압력": "0.15 torr", "온도": 360, "T1(min.)": 60, "T2(min.)": 120, "p1 (mg)": 200, "p2(mg)": 180},
            {"CVD 종류": "CVD1", "공정 압력": "0.15 torr", "온도": 370, "T1(min.)": 120, "T2(min.)": 480, "p1 (mg)": 200, "p2(mg)": 150},
            {"CVD 종류": "CVD1", "공정 압력": "0.15 torr", "온도": 380, "T1(min.)": 60, "T2(min.)": 480, "p1 (mg)": 200, "p2(mg)": 120},
        ]
    )
    data["excel_row"] = range(2, 6)
    intervals = build_summary_intervals(data)
    assert intervals.loc[0, "time_group"] == "0-120 min"
    assert intervals.loc[1, "time_group"] == "0-120 min"
    assert intervals.loc[2, "time_group"] == "After 120 min"
    assert intervals.loc[3, "time_group"] == "120분 경계 교차"
    assert not intervals.loc[3, "fitting_included"]


def test_refit_uses_data_review_selection_state():
    bundle = run_analysis(SOURCE)
    original_ea = bundle.fits[CONDITION_015_0_120].ea_kj_per_mol
    idx = bundle.intervals[bundle.intervals["condition"] == CONDITION_015_0_120].index[0]
    bundle.intervals.at[idx, "fitting_included"] = False
    refit_bundle_from_selection(bundle)
    assert bundle.fits[CONDITION_015_0_120].is_valid
    assert bundle.fits[CONDITION_015_0_120].ea_kj_per_mol != original_ea


def test_first_order_prediction_is_linear_with_initial_mass():
    fit = run_analysis(SOURCE).fits[CONDITION_015_0_120]
    small = predict_loss(fit, 200, 370, 30, reference_mass_mg=200)
    large = predict_loss(fit, 2000, 370, 30, reference_mass_mg=200)
    assert round(large.predicted_loss_mg / small.predicted_loss_mg, 6) == 10


def test_schedule_generates_requested_columns_and_effective_band():
    fit = run_analysis(SOURCE).fits[CONDITION_015_0_120]
    result = calculate_schedule(
        fit,
        initial_mass_mg=2000,
        minimum_remaining_mg=50,
        total_hours=17,
        target_average_mg_hour=110,
        minimum_instant_mg_hour=80,
        start_temperature_c=330,
        end_temperature_c=410,
        time_step_hours=1,
        reference_mass_mg=2000,
    )
    assert list(result.stages.columns) == [
        "Stage",
        "Time range (h)",
        "Temperature C",
        "Stage P loss mg",
        "P before mg",
        "Remaining P mg",
        "Cumulative P loss mg",
        "Effective rate mg/hour",
        "Initial rate mg/hour",
        "Final rate mg/hour",
        "Minimum rate satisfied",
        "Effective rate satisfied",
        "비고",
    ]
    lower = 110 * 0.95
    upper = 110 * 1.05
    expected = result.stages["Effective rate mg/hour"].between(lower, upper, inclusive="both")
    assert result.stages["Effective rate satisfied"].tolist() == expected.tolist()
    outside = result.stages[result.stages["Effective rate mg/hour"] < lower]
    assert not outside.empty
    assert outside["Minimum rate satisfied"].all()
    assert not outside["Effective rate satisfied"].any()
