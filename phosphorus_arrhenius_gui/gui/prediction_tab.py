from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QFormLayout, QPushButton, QTextEdit, QVBoxLayout, QWidget

from core.constants import CONDITIONS
from core.predictor import predict_loss


class PredictionTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.condition = QComboBox()
        self.condition.addItems(CONDITIONS)
        self.initial_mass = QDoubleSpinBox(maximum=1_000_000, value=200.0)
        self.temperature = QDoubleSpinBox(minimum=-273, maximum=1000, value=375.0)
        self.time = QDoubleSpinBox(maximum=1_000_000, value=120.0)
        self.time_unit = QComboBox()
        self.time_unit.addItems(["min", "hour"])
        self.surface = QDoubleSpinBox(maximum=1000, value=1.0, decimals=3)
        self.result = QTextEdit()
        self.result.setReadOnly(True)
        self.run_button = QPushButton("예측 계산")
        form = QFormLayout()
        form.addRow("Process condition", self.condition)
        form.addRow("Initial P mass, mg", self.initial_mass)
        form.addRow("Temperature, ℃", self.temperature)
        form.addRow("Process time", self.time)
        form.addRow("Time unit", self.time_unit)
        form.addRow("Surface-area scaling factor", self.surface)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.run_button)
        layout.addWidget(self.result, 1)
        self.bundle = None
        self.run_button.clicked.connect(self.calculate)

    def set_bundle(self, bundle) -> None:
        self.bundle = bundle

    def calculate(self) -> None:
        if self.bundle is None:
            return
        fit = self.bundle.fits[self.condition.currentText()]
        try:
            pred = predict_loss(
                fit,
                self.initial_mass.value(),
                self.temperature.value(),
                self.time.value(),
                self.time_unit.currentText(),
                self.surface.value(),
            )
        except Exception as exc:
            self.result.setPlainText(str(exc))
            return
        self.result.setPlainText(
            f"condition: {pred.condition}\n"
            f"model type: {pred.model_type}\n"
            f"q: {pred.q_mg_per_min:.6g} mg/min ({pred.q_mg_per_hour:.6g} mg/hour)\n"
            f"expected loss: {pred.predicted_loss_mg:.6g} mg\n"
            f"remaining mass: {pred.remaining_mass_mg:.6g} mg\n"
            f"consumed fraction: {pred.consumed_fraction_percent:.3g}%\n"
            f"range: {pred.range_status}\n"
            f"surface-area factor: {pred.surface_area_factor:g}\n\n"
            f"{pred.warning}\n"
            "0.02 condition: raw 0.029 and 0.02 Torr are pooled."
        )
