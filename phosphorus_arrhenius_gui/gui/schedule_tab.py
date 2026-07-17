from __future__ import annotations

import pandas as pd
from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QFormLayout, QPushButton, QTableWidget, QTextEdit, QVBoxLayout, QWidget

from core.constants import CONDITIONS, DEFAULT_MIN_RATE_MG_HOUR, DEFAULT_TARGET_RATE_MG_HOUR
from core.schedule_optimizer import calculate_schedule
from gui.rate_analysis_tab import fill_table


class ScheduleTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.condition = QComboBox()
        self.condition.addItems(CONDITIONS)
        self.initial = QDoubleSpinBox(maximum=1_000_000, value=2000.0)
        self.minimum_remaining = QDoubleSpinBox(maximum=1_000_000, value=200.0)
        self.hours = QDoubleSpinBox(maximum=10_000, value=8.0)
        self.target = QDoubleSpinBox(maximum=100_000, value=DEFAULT_TARGET_RATE_MG_HOUR)
        self.minimum_rate = QDoubleSpinBox(maximum=100_000, value=DEFAULT_MIN_RATE_MG_HOUR)
        self.start_temp = QDoubleSpinBox(minimum=-273, maximum=1000, value=360.0)
        self.end_temp = QDoubleSpinBox(minimum=-273, maximum=1000, value=410.0)
        self.increment = QDoubleSpinBox(maximum=100, value=5.0)
        self.min_stage = QDoubleSpinBox(maximum=1000, value=0.5)
        self.max_stage = QDoubleSpinBox(maximum=30, value=8.0)
        self.tolerance = QDoubleSpinBox(maximum=100, value=2.0)
        self.surface = QDoubleSpinBox(maximum=1000, value=1.0, decimals=3)
        self.mode = QComboBox()
        self.mode.addItems(["Constant temperature", "Two-stage", "Multi-stage optimized"])
        self.button = QPushButton("Schedule 계산")
        self.summary = QTextEdit()
        self.summary.setReadOnly(True)
        self.table = QTableWidget()
        form = QFormLayout()
        for label, widget in [
            ("Process condition", self.condition),
            ("Initial P mass, mg", self.initial),
            ("Minimum remaining P mass, mg", self.minimum_remaining),
            ("Total process time, hour", self.hours),
            ("Target average rate, mg/hour", self.target),
            ("Minimum instantaneous rate, mg/hour", self.minimum_rate),
            ("Starting temperature, ℃", self.start_temp),
            ("Ending temperature, ℃", self.end_temp),
            ("Temperature increment, ℃", self.increment),
            ("Minimum stage duration, hour", self.min_stage),
            ("Maximum stage count", self.max_stage),
            ("Average-rate tolerance, %", self.tolerance),
            ("Surface-area scaling factor", self.surface),
            ("Schedule mode", self.mode),
        ]:
            form.addRow(label, widget)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.button)
        layout.addWidget(self.summary)
        layout.addWidget(self.table, 1)
        self.bundle = None
        self.latest_schedule = pd.DataFrame()
        self.button.clicked.connect(self.calculate)

    def set_bundle(self, bundle) -> None:
        self.bundle = bundle

    def calculate(self) -> None:
        if self.bundle is None:
            return
        result = calculate_schedule(
            self.bundle.fits[self.condition.currentText()],
            self.initial.value(),
            self.minimum_remaining.value(),
            self.hours.value(),
            self.target.value(),
            self.minimum_rate.value(),
            self.start_temp.value(),
            self.end_temp.value(),
            self.increment.value(),
            self.min_stage.value(),
            int(self.max_stage.value()),
            self.tolerance.value(),
            self.surface.value(),
            self.mode.currentText(),
        )
        self.latest_schedule = result.stages
        self.summary.setPlainText(result.message + "\n" + "\n".join(f"{k}: {v}" for k, v in result.summary.items()))
        fill_table(self.table, result.stages)
