from __future__ import annotations

import numpy as np
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QTextEdit, QVBoxLayout, QWidget

from core.arrhenius_model import rate_from_fit
from core.constants import CONDITIONS

try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.figure import Figure
except Exception:  # pragma: no cover
    FigureCanvas = None
    Figure = None


class ArrheniusTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.condition_combo = QComboBox()
        self.condition_combo.addItems(CONDITIONS)
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        self.figure = Figure(figsize=(8, 5)) if Figure else None
        self.canvas = FigureCanvas(self.figure) if FigureCanvas else QLabel("matplotlib 설치 후 그래프가 표시됩니다.")
        top = QHBoxLayout()
        top.addWidget(QLabel("모델 조건"))
        top.addWidget(self.condition_combo)
        top.addStretch()
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.details)
        layout.addWidget(self.canvas, 1)
        self.bundle = None
        self.condition_combo.currentTextChanged.connect(self.refresh)

    def set_bundle(self, bundle) -> None:
        self.bundle = bundle
        self.refresh()

    def refresh(self) -> None:
        if self.bundle is None:
            return
        condition = self.condition_combo.currentText()
        fit = self.bundle.fits[condition]
        summary = self.bundle.summaries[condition]
        self.details.setPlainText(str(fit))
        if not self.figure or summary.empty:
            return
        self.figure.clear()
        ax1 = self.figure.add_subplot(221)
        ax2 = self.figure.add_subplot(222)
        ax3 = self.figure.add_subplot(223)
        ax4 = self.figure.add_subplot(224)
        intervals = self.bundle.intervals[(self.bundle.intervals["condition"] == condition) & (self.bundle.intervals["fitting_included"] == True)]
        ax1.scatter(intervals["parsed_temperature_C"], intervals["rate_mg_per_hour"], color="#2563eb")
        ax1.set_title("Temperature vs individual rate")
        ax1.set_xlabel("℃")
        ax1.set_ylabel("mg/hour")
        ax2.errorbar(
            summary["temperature_C"],
            summary["representative_rate_mg_per_hour"],
            yerr=summary["std_rate_mg_per_min"] * 60,
            fmt="o",
            color="#e11d48",
        )
        ax2.set_title("Representative rate")
        ax2.set_xlabel("℃")
        x = 1000 / summary["temperature_K"]
        y = np.log(summary["representative_rate_mg_per_min"])
        ax3.scatter(x, y, color="#2563eb")
        if fit.is_valid:
            xx = np.linspace(x.min(), x.max(), 50)
            ax3.plot(xx, fit.slope * (xx / 1000 * 1000) + fit.intercept, color="#e11d48")
        ax3.set_title("Arrhenius plot")
        ax3.set_xlabel("1000/T")
        ax3.set_ylabel("ln(q)")
        if fit.is_valid:
            temps = np.linspace(fit.min_temperature_c - 15, fit.max_temperature_c + 15, 120)
            rates = [rate_from_fit(fit, t) * 60 for t in temps]
            ax4.plot(temps, rates, color="#e11d48")
            ax4.scatter(summary["temperature_C"], summary["representative_rate_mg_per_hour"], color="#2563eb")
        ax4.set_title("Predicted q vs temperature")
        ax4.set_xlabel("℃")
        ax4.set_ylabel("mg/hour")
        self.figure.tight_layout()
        self.canvas.draw()
