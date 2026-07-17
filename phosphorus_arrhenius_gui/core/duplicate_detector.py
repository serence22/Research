from __future__ import annotations

import pandas as pd


def mark_duplicates(intervals: pd.DataFrame) -> pd.DataFrame:
    if intervals.empty:
        return intervals
    df = intervals.copy()
    df["duplicate_status"] = df.get("duplicate_status", "")
    key_cols = ["condition", "normalized_equipment", "loading_class", "t1_min", "t2_min"]
    df["_dup_temp"] = df["parsed_temperature_C"].round(1)
    df["_dup_loss"] = df["interval_loss_mg"].round(0)
    df["_dup_rate"] = df["rate_mg_per_min"].round(2)
    sort_cols = ["source_priority", "merged_interval"]
    df = df.sort_values(sort_cols, ascending=[True, False]).reset_index(drop=True)
    seen: set[tuple] = set()
    for idx, row in df.iterrows():
        key = tuple(row.get(c) for c in key_cols) + (row["_dup_temp"], row["_dup_loss"], row["_dup_rate"])
        if key in seen and bool(row.get("fitting_included")):
            df.at[idx, "fitting_included"] = False
            df.at[idx, "duplicate_status"] = "duplicate_qc_only"
            df.at[idx, "exclusion_reason"] = "Duplicate of higher-priority interval"
        else:
            seen.add(key)
            if bool(row.get("fitting_included")):
                df.at[idx, "duplicate_status"] = "unique"
    return df.drop(columns=["_dup_temp", "_dup_loss", "_dup_rate"])
