from __future__ import annotations

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget


class DataReviewTab(QWidget):
    COLUMNS = [
        "use", "source_sheet", "excel_row", "source_priority", "original_CVD_name",
        "normalized_equipment", "loading_class", "series_id", "original_pressure",
        "effective_pressure", "canonical_pressure", "condition", "ar_sccm", "inferred_ar",
        "original_temperature", "parsed_temperature_C", "temperature_parse_method",
        "temperature_override_applied", "temperature_correction_note", "t1_min", "t2_min",
        "initial_p_mg", "remaining_p_mg", "p1_mg", "p2_mg", "cumulative_loss_mg",
        "interval_loss_mg", "duration_min", "rate_mg_per_min", "rate_mg_per_hour",
        "startup_interval", "merged_interval", "direct_interval", "source_rows",
        "duplicate_status", "fitting_included", "exclusion_reason", "notes",
    ]

    def __init__(self) -> None:
        super().__init__()
        self.table = QTableWidget()
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        layout = QVBoxLayout(self)
        layout.addWidget(self.table)

    def set_data(self, df: pd.DataFrame) -> None:
        columns = [c for c in self.COLUMNS if c in df.columns]
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(df))
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels(columns)
        for r, (_, row) in enumerate(df[columns].iterrows()):
            for c, col in enumerate(columns):
                item = QTableWidgetItem("" if pd.isna(row[col]) else str(row[col]))
                if col == "use":
                    item.setCheckState(Qt.Checked if bool(row[col]) else Qt.Unchecked)
                self.table.setItem(r, c, item)
        self.table.resizeColumnsToContents()
        self.table.setSortingEnabled(True)
