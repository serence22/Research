from __future__ import annotations

from typing import Any

import pandas as pd


def _complete_formula_interval(row: pd.Series) -> dict[str, Any]:
    duration = row["t2_min"] - row["t1_min"]
    loss = row["p1_mg"] - row["p2_mg"]
    rate = loss / duration
    data = row.to_dict()
    data.update(
        {
            "duration_min": duration,
            "interval_loss_mg": loss,
            "rate_mg_per_min": rate,
            "rate_mg_per_hour": rate * 60,
            "fitting_included": bool(row["use"]),
        }
    )
    return data


def build_formula_intervals(formula_rows: pd.DataFrame) -> pd.DataFrame:
    intervals = []
    for _, row in formula_rows.iterrows():
        if row["use"]:
            intervals.append(_complete_formula_interval(row))
        else:
            data = row.to_dict()
            data["fitting_included"] = False
            intervals.append(data)
    df = pd.DataFrame(intervals)
    merged_rows = []
    used_short_indices: set[int] = set()
    for idx, first in df.iterrows():
        if not first.get("fitting_included"):
            continue
        if abs(first["t1_min"] - 30) > 1e-9 or abs(first["t2_min"] - 40) > 1e-9:
            continue
        candidates = df[
            (df["series_id"] == first["series_id"])
            & (df["fitting_included"] == True)
            & (abs(df["t1_min"] - 40) < 1e-9)
            & (abs(df["t2_min"] - 60) < 1e-9)
        ]
        if candidates.empty:
            continue
        second_idx = candidates.index[0]
        second = df.loc[second_idx]
        if abs(first["p2_mg"] - second["p1_mg"]) > 0.5:
            continue
        merged = first.to_dict()
        merged.update(
            {
                "t1_min": 30.0,
                "t2_min": 60.0,
                "p1_mg": first["p1_mg"],
                "p2_mg": second["p2_mg"],
                "duration_min": 30.0,
                "interval_loss_mg": first["p1_mg"] - second["p2_mg"],
                "rate_mg_per_min": (first["p1_mg"] - second["p2_mg"]) / 30.0,
                "rate_mg_per_hour": (first["p1_mg"] - second["p2_mg"]) / 30.0 * 60,
                "merged_interval": True,
                "direct_interval": False,
                "source_rows": f"{int(first['excel_row'])},{int(second['excel_row'])}",
                "notes": "Merged 30-40 + 40-60 min interval",
            }
        )
        merged_rows.append(merged)
        used_short_indices.update({idx, second_idx})
    if used_short_indices:
        df.loc[list(used_short_indices), "fitting_included"] = False
        df.loc[list(used_short_indices), "exclusion_reason"] = "Merged into 30-60 min interval"
    if merged_rows:
        df = pd.concat([df, pd.DataFrame(merged_rows)], ignore_index=True)
    return df


def build_full_record_intervals(full_rows: pd.DataFrame) -> pd.DataFrame:
    valid = full_rows[full_rows["use"] == True].copy()
    intervals: list[dict[str, Any]] = []
    group_cols = ["condition", "series_id", "parsed_temperature_C"]
    for _, group in valid.groupby(group_cols, dropna=False):
        group = group.sort_values("time_min")
        times = list(group["time_min"].astype(float))
        if len(group) == 1:
            row = group.iloc[0].to_dict()
            duration = float(row["time_min"])
            loss = float(row["cumulative_loss_mg"])
            rate = loss / duration
            row.update(
                {
                    "t1_min": 0.0,
                    "t2_min": duration,
                    "p1_mg": row["initial_p_mg"],
                    "p2_mg": row["remaining_p_mg"],
                    "duration_min": duration,
                    "interval_loss_mg": loss,
                    "rate_mg_per_min": rate,
                    "rate_mg_per_hour": rate * 60,
                    "startup_interval": True,
                    "direct_interval": False,
                    "fitting_included": True,
                    "notes": (row.get("notes") or "") + "; 0→t cumulative interval may contain startup effects.",
                }
            )
            intervals.append(row)
            continue
        time_map = {float(r["time_min"]): r for _, r in group.iterrows()}
        if 10.0 in time_map and 30.0 in time_map:
            r10, r30 = time_map[10.0], time_map[30.0]
            loss = r30["cumulative_loss_mg"] - r10["cumulative_loss_mg"]
            if loss > 0:
                row = r30.to_dict()
                row.update(
                    {
                        "t1_min": 10.0,
                        "t2_min": 30.0,
                        "duration_min": 20.0,
                        "interval_loss_mg": loss,
                        "rate_mg_per_min": loss / 20.0,
                        "rate_mg_per_hour": loss / 20.0 * 60,
                        "source_rows": f"{int(r10['excel_row'])},{int(r30['excel_row'])}",
                        "direct_interval": False,
                        "fitting_included": True,
                    }
                )
                intervals.append(row)
        if 30.0 in time_map and 60.0 in time_map:
            r30, r60 = time_map[30.0], time_map[60.0]
            loss = r60["cumulative_loss_mg"] - r30["cumulative_loss_mg"]
            if loss > 0:
                row = r60.to_dict()
                row.update(
                    {
                        "t1_min": 30.0,
                        "t2_min": 60.0,
                        "duration_min": 30.0,
                        "interval_loss_mg": loss,
                        "rate_mg_per_min": loss / 30.0,
                        "rate_mg_per_hour": loss / 30.0 * 60,
                        "source_rows": f"{int(r30['excel_row'])},{int(r60['excel_row'])}",
                        "merged_interval": True,
                        "direct_interval": False,
                        "fitting_included": True,
                    }
                )
                intervals.append(row)
        if not intervals:
            for (_, prev), (_, cur) in zip(group.iloc[:-1].iterrows(), group.iloc[1:].iterrows()):
                duration = cur["time_min"] - prev["time_min"]
                loss = cur["cumulative_loss_mg"] - prev["cumulative_loss_mg"]
                if duration <= 0 or loss <= 0:
                    continue
                row = cur.to_dict()
                row.update(
                    {
                        "t1_min": prev["time_min"],
                        "t2_min": cur["time_min"],
                        "duration_min": duration,
                        "interval_loss_mg": loss,
                        "rate_mg_per_min": loss / duration,
                        "rate_mg_per_hour": loss / duration * 60,
                        "source_rows": f"{int(prev['excel_row'])},{int(cur['excel_row'])}",
                        "direct_interval": False,
                        "fitting_included": True,
                    }
                )
                intervals.append(row)
    return pd.DataFrame(intervals)
