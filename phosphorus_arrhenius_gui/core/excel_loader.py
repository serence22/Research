from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .constants import (
    FORMULA_HEADER_ROW,
    FORMULA_NROWS,
    FORMULA_SHEET,
    FORMULA_USECOLS,
    FULL_RECORD_SHEET,
    SELECTED_FULL_RECORD_ROWS,
)
from .parsing import clean_column_name


def _ensure_xlsx(file_path: str | Path) -> Path:
    path = Path(file_path)
    if path.suffix.lower() != ".xlsx":
        raise ValueError("xlsx 파일만 열 수 있습니다.")
    if not path.exists():
        raise FileNotFoundError(path)
    return path


def read_formula_sheet(file_path: str | Path) -> pd.DataFrame:
    path = _ensure_xlsx(file_path)
    df = pd.read_excel(
        path,
        sheet_name=FORMULA_SHEET,
        header=FORMULA_HEADER_ROW - 1,
        nrows=FORMULA_NROWS,
        usecols=FORMULA_USECOLS,
        engine="openpyxl",
    )
    df.columns = [clean_column_name(c) for c in df.columns]
    df["excel_row"] = range(91, 107)
    df["source_sheet"] = FORMULA_SHEET
    df["source_priority"] = 1
    return df


def read_full_record_selected(file_path: str | Path) -> tuple[pd.DataFrame, list[int]]:
    path = _ensure_xlsx(file_path)
    df = pd.read_excel(path, sheet_name=FULL_RECORD_SHEET, header=0, engine="openpyxl")
    df.columns = [clean_column_name(c) for c in df.columns]
    df["excel_row"] = np.arange(2, 2 + len(df))
    selected = df[df["excel_row"].isin(SELECTED_FULL_RECORD_ROWS)].copy()
    selected["source_sheet"] = FULL_RECORD_SHEET
    selected["source_priority"] = 2
    missing = sorted(set(SELECTED_FULL_RECORD_ROWS) - set(selected["excel_row"].dropna().astype(int)))
    return selected, missing


def load_raw_sheets(file_path: str | Path) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    logs: list[str] = []
    formula = read_formula_sheet(file_path)
    full, missing = read_full_record_selected(file_path)
    if missing:
        logs.append(f"전체 기록 지정 행 누락: {missing}")
    logs.append("Data sources: 수식 rows 91-106; 전체 기록 selected rows only")
    return formula, full, logs
