from __future__ import annotations

from pathlib import Path

import pandas as pd


def export_analysis_xlsx(
    output_path: str | Path,
    raw_formula: pd.DataFrame,
    raw_full: pd.DataFrame,
    intervals: pd.DataFrame,
    summaries: dict[str, pd.DataFrame],
    fits: dict,
    log_lines: list[str],
    predictions: pd.DataFrame | None = None,
    schedule: pd.DataFrame | None = None,
) -> Path:
    path = Path(output_path)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        raw_formula.to_excel(writer, sheet_name="Raw Formula Rows 91-106", index=False)
        raw_full.to_excel(writer, sheet_name="Raw Full Record Selected Rows", index=False)
        intervals.to_excel(writer, sheet_name="Processed Intervals", index=False)
        intervals[["source_sheet", "excel_row", "original_pressure", "effective_pressure", "canonical_pressure", "pressure_note"]].to_excel(
            writer, sheet_name="Pressure Normalization", index=False
        )
        intervals[[
            "source_sheet",
            "excel_row",
            "original_temperature",
            "parsed_temperature_C",
            "temperature_override_applied",
            "temperature_parse_method",
            "temperature_correction_note",
        ]].to_excel(writer, sheet_name="Temperature Corrections", index=False)
        for condition, summary in summaries.items():
            sheet = "Condition 0.15 Summary" if "0.15" in condition else "Condition 0.02 Summary"
            summary.to_excel(writer, sheet_name=sheet, index=False)
        fit_rows = [vars(fit) for fit in fits.values()]
        pd.DataFrame(fit_rows).to_excel(writer, sheet_name="Arrhenius Fits", index=False)
        if predictions is not None:
            predictions.to_excel(writer, sheet_name="Predictions", index=False)
        if schedule is not None:
            schedule.to_excel(writer, sheet_name="Constant Rate Schedule", index=False)
        pd.DataFrame({"log": log_lines}).to_excel(writer, sheet_name="Analysis Log", index=False)
    return path


def export_csv(df: pd.DataFrame, output_path: str | Path) -> Path:
    path = Path(output_path)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path
