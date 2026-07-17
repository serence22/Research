from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.analysis_pipeline import run_analysis
from core.constants import CONDITION_015
from core.exporter import export_analysis_xlsx
from gui.arrhenius_tab import ArrheniusTab
from gui.data_review_tab import DataReviewTab
from gui.log_tab import LogTab
from gui.prediction_tab import PredictionTab
from gui.rate_analysis_tab import RateAnalysisTab
from gui.schedule_tab import ScheduleTab


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Phosphorus Sublimation Arrhenius Analyzer")
        self.resize(1400, 900)
        self.bundle = None
        self.file_path = QLineEdit()
        self.file_path.setPlaceholderText("xlsx 파일을 선택하세요")
        default = next(Path.cwd().glob("*.xlsx"), None)
        if default:
            self.file_path.setText(str(default))

        self.status_label = QLabel("대기")
        self.condition_label = QLabel(CONDITION_015)
        self.review_tab = DataReviewTab()
        self.rate_tab = RateAnalysisTab()
        self.arrhenius_tab = ArrheniusTab()
        self.prediction_tab = PredictionTab()
        self.schedule_tab = ScheduleTab()
        self.log_tab = LogTab()

        self._build_ui()
        if default:
            self.process_file()

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)

        title = QLabel("Phosphorus Sublimation Arrhenius Analyzer")
        title.setObjectName("TitleLabel")
        title.setAlignment(Qt.AlignLeft)
        subtitle = QLabel("수식 rows 91-106 + 전체 기록 selected rows, 0.15 Torr와 canonical 0.02 Torr 독립 모델")
        subtitle.setObjectName("SubtitleLabel")
        root.addWidget(title)
        root.addWidget(subtitle)

        toolbar = QHBoxLayout()
        for text, slot in [
            ("Open XLSX", self.open_file),
            ("Reload", self.process_file),
            ("Reprocess", self.process_file),
            ("Refit", self.process_file),
            ("Export Results", self.export_results),
            ("Save Graphs", self.save_graphs),
        ]:
            button = QPushButton(text)
            button.clicked.connect(slot)
            toolbar.addWidget(button)
        toolbar.addWidget(self.file_path, 1)
        toolbar.addWidget(QLabel("상태:"))
        toolbar.addWidget(self.status_label)
        toolbar.addWidget(QLabel("현재 condition:"))
        toolbar.addWidget(self.condition_label)
        root.addLayout(toolbar)

        source_note = QLabel(
            "Data sources: 수식 Excel rows 91-106 | 전체 기록 Excel rows 2-6, 8, 23, 28-31, 41-43, 50, 64"
        )
        source_note.setObjectName("SourceNote")
        root.addWidget(source_note)

        self.tabs = QTabWidget()
        self.tabs.addTab(self.review_tab, "Data Review")
        self.tabs.addTab(self.rate_tab, "Rate Analysis")
        self.tabs.addTab(self.arrhenius_tab, "Arrhenius Fit")
        self.tabs.addTab(self.prediction_tab, "Prediction")
        self.tabs.addTab(self.schedule_tab, "Constant Rate Schedule")
        self.tabs.addTab(self.log_tab, "Log")
        root.addWidget(self.tabs, 1)
        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #f5f7fb; color: #17202a; font-family: Segoe UI; font-size: 10pt; }
            #TitleLabel { font-size: 22pt; font-weight: 700; }
            #SubtitleLabel, #SourceNote { color: #667085; }
            QPushButton { background: #2563eb; color: white; border: none; padding: 8px 12px; border-radius: 4px; }
            QPushButton:hover { background: #1d4ed8; }
            QLineEdit, QComboBox, QDoubleSpinBox, QTextEdit, QTableWidget {
                background: white; border: 1px solid #d9e1ea; border-radius: 4px; padding: 4px;
            }
            QTabWidget::pane { border: 1px solid #d9e1ea; background: white; }
            QTabBar::tab { background: #eef3f8; padding: 9px 16px; margin-right: 2px; }
            QTabBar::tab:selected { background: white; color: #17202a; }
            QHeaderView::section { background: #eef3f8; padding: 6px; border: 1px solid #d9e1ea; }
            """
        )

    def open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Excel 파일 열기", str(Path.cwd()), "Excel Files (*.xlsx)")
        if path:
            self.file_path.setText(path)
            self.process_file()

    def process_file(self) -> None:
        try:
            self.status_label.setText("분석 중")
            self.bundle = run_analysis(self.file_path.text())
            self.review_tab.set_data(self.bundle.intervals)
            self.rate_tab.set_bundle(self.bundle)
            self.arrhenius_tab.set_bundle(self.bundle)
            self.prediction_tab.set_bundle(self.bundle)
            self.schedule_tab.set_bundle(self.bundle)
            self.log_tab.set_logs(self.bundle.logs)
            self.status_label.setText("완료")
            self.statusBar().showMessage("분석 완료", 5000)
        except Exception as exc:
            self.status_label.setText("오류")
            QMessageBox.critical(self, "분석 오류", str(exc))

    def export_results(self) -> None:
        if self.bundle is None:
            QMessageBox.information(self, "Export", "먼저 분석을 실행하세요.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "결과 저장", "phosphorus_arrhenius_results.xlsx", "Excel Files (*.xlsx)")
        if not path:
            return
        export_analysis_xlsx(
            path,
            self.bundle.raw_formula,
            self.bundle.raw_full,
            self.bundle.intervals,
            self.bundle.summaries,
            self.bundle.fits,
            self.bundle.logs,
            schedule=self.schedule_tab.latest_schedule,
        )
        QMessageBox.information(self, "Export", f"저장 완료:\n{path}")

    def save_graphs(self) -> None:
        QMessageBox.information(
            self,
            "Save Graphs",
            "Arrhenius Fit 탭의 matplotlib toolbar 저장 버튼으로 현재 그래프를 PNG로 저장할 수 있습니다.",
        )
