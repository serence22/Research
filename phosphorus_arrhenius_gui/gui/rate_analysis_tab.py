from __future__ import annotations

import pandas as pd
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from core.constants import CONDITIONS


def fill_table(table: QTableWidget, df: pd.DataFrame) -> None:
    table.setRowCount(len(df))
    table.setColumnCount(len(df.columns))
    table.setHorizontalHeaderLabels([str(c) for c in df.columns])
    for r, (_, row) in enumerate(df.iterrows()):
        for c, col in enumerate(df.columns):
            table.setItem(r, c, QTableWidgetItem("" if pd.isna(row[col]) else str(row[col])))
    table.resizeColumnsToContents()


class RateAnalysisTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.condition_combo = QComboBox()
        self.condition_combo.addItems(CONDITIONS)
        self.interval_table = QTableWidget()
        self.summary_table = QTableWidget()
        self.interval_table.setAlternatingRowColors(True)
        self.summary_table.setAlternatingRowColors(True)
        top = QHBoxLayout()
        top.addWidget(QLabel("공정 조건"))
        top.addWidget(self.condition_combo)
        top.addStretch()
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(QLabel("Interval 데이터"))
        layout.addWidget(self.interval_table, 2)
        layout.addWidget(QLabel("온도별 대표 소모속도"))
        layout.addWidget(self.summary_table, 1)
        self.bundle = None
        self.condition_combo.currentTextChanged.connect(self.refresh)

    def set_bundle(self, bundle) -> None:
        self.bundle = bundle
        self.refresh()

    def refresh(self) -> None:
        if self.bundle is None:
            return
        condition = self.condition_combo.currentText()
        cols = [
            "parsed_temperature_C", "series_id", "t1_min", "t2_min", "duration_min",
            "interval_loss_mg", "rate_mg_per_min", "rate_mg_per_hour", "source_sheet",
            "merged_interval", "direct_interval", "fitting_included", "notes",
        ]
        interval_df = self.bundle.intervals[self.bundle.intervals["condition"] == condition]
        fill_table(self.interval_table, interval_df[[c for c in cols if c in interval_df.columns]])
        fill_table(self.summary_table, self.bundle.summaries.get(condition, pd.DataFrame()))
