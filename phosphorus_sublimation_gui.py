from __future__ import annotations

from pathlib import Path
import math
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import pandas as pd

from phosphorus_arrhenius_gui.core.analysis_pipeline import AnalysisBundle, refit_bundle_from_selection, run_analysis
from phosphorus_arrhenius_gui.core.arrhenius_model import rate_from_fit, temperature_for_rate
from phosphorus_arrhenius_gui.core.constants import CONDITION_015, CONDITION_015_AFTER_120, CONDITION_015_0_120, CONDITIONS
from phosphorus_arrhenius_gui.core.predictor import predict_loss_composite
from phosphorus_arrhenius_gui.core.schedule_optimizer import calculate_composite_schedule


COLORS = {
    "bg": "#f5f7fb",
    "surface": "#ffffff",
    "surface2": "#eef3f8",
    "line": "#d7dee8",
    "text": "#17202a",
    "muted": "#667085",
    "blue": "#2563eb",
    "blue_dark": "#1d4ed8",
    "red": "#e11d48",
    "green": "#059669",
    "grid": "#e8edf3",
}


def fmt(value: object, digits: int = 5) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    if isinstance(value, float):
        return f"{value:.{digits}g}"
    return str(value)


class PlotCanvas(tk.Canvas):
    def __init__(self, master: tk.Misc, **kwargs) -> None:
        super().__init__(
            master,
            bg=COLORS["surface"],
            highlightthickness=1,
            highlightbackground=COLORS["line"],
            **kwargs,
        )

    def clear(self) -> None:
        self.delete("all")

    def axes(self, title: str, x_label: str, y_label: str, xs: list[float], ys: list[float]):
        self.clear()
        width = max(self.winfo_width(), 760)
        height = max(self.winfo_height(), 420)
        left, top, right, bottom = 82, 58, width - 34, height - 64
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)
        if x0 == x1:
            x0 -= 1
            x1 += 1
        if y0 == y1:
            span = abs(y0) or 1
            y0 -= span * 0.1
            y1 += span * 0.1
        xp = (x1 - x0) * 0.08
        yp = (y1 - y0) * 0.14
        x0, x1, y0, y1 = x0 - xp, x1 + xp, y0 - yp, y1 + yp

        def sx(x: float) -> float:
            return left + (x - x0) / (x1 - x0) * (right - left)

        def sy(y: float) -> float:
            return bottom - (y - y0) / (y1 - y0) * (bottom - top)

        self.create_text(left, 26, text=title, anchor="w", font=("Segoe UI", 15, "bold"), fill=COLORS["text"])
        self.create_text(left, 47, text=y_label, anchor="w", font=("Segoe UI", 9), fill=COLORS["muted"])
        self.create_text((left + right) / 2, height - 24, text=x_label, font=("Segoe UI", 9), fill=COLORS["muted"])
        for i in range(6):
            x = x0 + (x1 - x0) * i / 5
            y = y0 + (y1 - y0) * i / 5
            self.create_line(sx(x), top, sx(x), bottom, fill=COLORS["grid"])
            self.create_line(left, sy(y), right, sy(y), fill=COLORS["grid"])
            self.create_text(sx(x), bottom + 18, text=f"{x:.4g}", font=("Segoe UI", 8), fill=COLORS["muted"])
            self.create_text(left - 10, sy(y), text=f"{y:.4g}", anchor="e", font=("Segoe UI", 8), fill=COLORS["muted"])
        self.create_line(left, bottom, right, bottom, fill="#98a2b3")
        self.create_line(left, top, left, bottom, fill="#98a2b3")
        return sx, sy

    def point(self, sx, sy, x: float, y: float, color: str, radius: int = 5) -> None:
        px, py = sx(x), sy(y)
        self.create_oval(px - radius, py - radius, px + radius, py + radius, fill=color, outline="white", width=1)


class DataTable(ttk.Frame):
    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master)
        self.tree = ttk.Treeview(self, show="headings")
        ybar = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        xbar = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

    def set_dataframe(self, df: pd.DataFrame, columns: list[str] | None = None) -> None:
        self.tree.delete(*self.tree.get_children())
        if df is None or df.empty:
            self.tree["columns"] = []
            return
        columns = columns or list(df.columns)
        columns = [c for c in columns if c in df.columns]
        self.tree["columns"] = columns
        for col in columns:
            self.tree.heading(col, text=col)
            width = {
                "Stage": 70,
                "Time range (h)": 120,
                "Model used": 100,
                "P before mg": 120,
                "Temperature C": 120,
                "k min^-1": 110,
                "Initial rate mg/hour": 160,
                "Effective rate mg/hour": 170,
                "Stage P loss mg": 150,
                "Cumulative P loss mg": 180,
                "Remaining P mg": 140,
                "Minimum rate satisfied": 170,
                "Target rate satisfied": 170,
                "Within measured range": 170,
                "비고": 280,
            }.get(col, 128)
            if col == "Final rate mg/hour":
                width = 160
            elif col == "Effective rate satisfied":
                width = 180
            elif col == "비고":
                width = 300
            self.tree.column(col, width=width, anchor="center", stretch=True)
        for idx, (row_index, row) in enumerate(df[columns].iterrows()):
            tags = ("odd",) if idx % 2 else ("even",)
            if "fitting_included" in row and not bool(row["fitting_included"]):
                tags = ("excluded",)
            self.tree.insert("", "end", iid=str(row_index), values=[fmt(row[col]) for col in columns], tags=tags)
        self.tree.tag_configure("even", background=COLORS["surface"])
        self.tree.tag_configure("odd", background="#f8fafc")
        self.tree.tag_configure("excluded", background="#fff1f2", foreground="#9f1239")

    def selected_indices(self) -> list[int]:
        indices: list[int] = []
        for iid in self.tree.selection():
            try:
                indices.append(int(iid))
            except ValueError:
                pass
        return indices


class PhosphorusTkApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Phosphorus Sublimation Arrhenius Analyzer")
        self.geometry("1380x900")
        self.minsize(1120, 760)
        self.configure(bg=COLORS["bg"])

        self.bundle: AnalysisBundle | None = None
        self.file_path = tk.StringVar(value=self.default_workbook())
        self.condition = tk.StringVar(value=CONDITION_015)
        self.pred_temp = tk.DoubleVar(value=390.0)
        self.pred_mass = tk.DoubleVar(value=2000.0)
        self.pred_reference_mass = tk.DoubleVar(value=200.0)
        self.pred_time = tk.DoubleVar(value=2.0)
        self.pred_unit = tk.StringVar(value="hour")
        self.surface_factor = tk.DoubleVar(value=1.0)
        self.schedule_initial_mass = tk.StringVar(value="2000")
        self.schedule_target = tk.StringVar(value="120")
        self.schedule_min_rate = tk.StringVar(value="80")
        self.schedule_hours = tk.StringVar(value="8")
        self.schedule_min_remaining = tk.StringVar(value="200")
        self.schedule_start_temp = tk.StringVar(value="330")
        self.schedule_end_temp = tk.StringVar(value="410")
        self.schedule_step = tk.StringVar(value="1")
        self.schedule_mode = tk.StringVar(value="Time-step optimized")

        self.metric_vars = {
            "fit_0_120": tk.StringVar(value="-"),
            "fit_after_120": tk.StringVar(value="-"),
            "assumption": tk.StringVar(value="질량비례: initial/reference"),
            "rows": tk.StringVar(value="-"),
        }
        self.setup_style()
        self.build_ui()
        if self.file_path.get():
            self.load_file()

    def default_workbook(self) -> str:
        files = [p for p in Path.cwd().glob("*.xlsx") if not p.name.startswith("~$")]
        ver7 = [p for p in files if "ver.7" in p.name]
        if ver7:
            return str(ver7[0])
        exp4 = [p for p in files if "실험4" in p.name or "4" in p.stem]
        if exp4:
            return str(exp4[0])
        ver3 = [p for p in files if "ver.3" in p.name]
        if ver3:
            return str(ver3[0])
        ver2 = [p for p in files if "ver.2" in p.name]
        if ver2:
            return str(ver2[0])
        return str(files[0]) if files else ""

    def setup_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", font=("Segoe UI", 10), background=COLORS["bg"], foreground=COLORS["text"])
        style.configure("App.TFrame", background=COLORS["bg"])
        style.configure("Surface.TFrame", background=COLORS["surface"])
        style.configure("Title.TLabel", font=("Segoe UI", 21, "bold"), background=COLORS["bg"], foreground=COLORS["text"])
        style.configure("Subtitle.TLabel", font=("Segoe UI", 10), background=COLORS["bg"], foreground=COLORS["muted"])
        style.configure("CardTitle.TLabel", font=("Segoe UI", 9), background=COLORS["surface"], foreground=COLORS["muted"])
        style.configure("CardValue.TLabel", font=("Segoe UI", 14, "bold"), background=COLORS["surface"], foreground=COLORS["text"])
        style.configure("Primary.TButton", background=COLORS["blue"], foreground="white", padding=(14, 8), borderwidth=0)
        style.map("Primary.TButton", background=[("active", COLORS["blue_dark"])])
        style.configure("Quiet.TButton", background=COLORS["surface2"], foreground=COLORS["text"], padding=(14, 8), borderwidth=0)
        style.configure("TNotebook", background=COLORS["bg"], borderwidth=0)
        style.configure("TNotebook.Tab", background=COLORS["surface2"], foreground=COLORS["muted"], padding=(16, 9))
        style.map("TNotebook.Tab", background=[("selected", COLORS["surface"])], foreground=[("selected", COLORS["text"])])
        style.configure("Treeview", rowheight=29, background=COLORS["surface"], fieldbackground=COLORS["surface"])
        style.configure("Treeview.Heading", background=COLORS["surface2"], foreground=COLORS["muted"], font=("Segoe UI", 9, "bold"))

    def build_ui(self) -> None:
        shell = ttk.Frame(self, style="App.TFrame", padding=18)
        shell.pack(fill="both", expand=True)
        header = ttk.Frame(shell, style="App.TFrame")
        header.pack(fill="x", pady=(0, 12))
        title_box = ttk.Frame(header, style="App.TFrame")
        title_box.pack(side="left", fill="x", expand=True)
        ttk.Label(title_box, text="P Sublimation Analyzer", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            title_box,
            text="Tkinter | 수식 + 전체 기록 | 0.15 Torr / canonical 0.02 Torr | 초기질량 비례 예측",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(3, 0))
        ttk.Button(header, text="Open XLSX", style="Quiet.TButton", command=self.choose_file).pack(side="right", padx=(8, 0))
        ttk.Button(header, text="Analyze", style="Primary.TButton", command=self.load_file).pack(side="right")

        toolbar = ttk.Frame(shell, style="Surface.TFrame", padding=12)
        toolbar.pack(fill="x", pady=(0, 12))
        ttk.Label(toolbar, text="Workbook / Google Sheet URL", background=COLORS["surface"], foreground=COLORS["muted"]).pack(side="left")
        ttk.Entry(toolbar, textvariable=self.file_path).pack(side="left", fill="x", expand=True, padx=(8, 16))
        ttk.Label(toolbar, text="Condition", background=COLORS["surface"], foreground=COLORS["muted"]).pack(side="left")
        condition_box = ttk.Combobox(toolbar, textvariable=self.condition, values=CONDITIONS, width=26, state="readonly")
        condition_box.pack(side="left", padx=(8, 0))
        condition_box.bind("<<ComboboxSelected>>", lambda _e: self.refresh_condition_views())

        cards = ttk.Frame(shell, style="App.TFrame")
        cards.pack(fill="x", pady=(0, 12))
        self.metric_card(cards, "0.15 Torr 0-120 min", self.metric_vars["fit_0_120"], 0)
        self.metric_card(cards, "0.15 Torr After 120 min", self.metric_vars["fit_after_120"], 1)
        self.metric_card(cards, "예측 가정", self.metric_vars["assumption"], 2)
        self.metric_card(cards, "분석 interval", self.metric_vars["rows"], 3)
        for col in range(4):
            cards.columnconfigure(col, weight=1, uniform="metric")

        self.tabs = ttk.Notebook(shell)
        self.tabs.pack(fill="both", expand=True)
        self.overview_tab = ttk.Frame(self.tabs, style="App.TFrame", padding=12)
        self.rate_tab = ttk.Frame(self.tabs, style="App.TFrame", padding=12)
        self.fit_tab = ttk.Frame(self.tabs, style="App.TFrame", padding=12)
        self.prediction_tab = ttk.Frame(self.tabs, style="App.TFrame", padding=12)
        self.schedule_tab = ttk.Frame(self.tabs, style="App.TFrame", padding=12)
        self.review_tab = ttk.Frame(self.tabs, style="App.TFrame", padding=12)
        self.log_tab = ttk.Frame(self.tabs, style="App.TFrame", padding=12)
        for tab, name in [
            (self.overview_tab, "Overview"),
            (self.rate_tab, "Rate Analysis"),
            (self.fit_tab, "Arrhenius"),
            (self.prediction_tab, "Prediction"),
            (self.schedule_tab, "Constant Rate Schedule"),
            (self.review_tab, "Data Review"),
            (self.log_tab, "Log"),
        ]:
            self.tabs.add(tab, text=name)

        self.build_overview_tab()
        self.build_rate_tab()
        self.build_fit_tab()
        self.build_prediction_tab()
        self.build_schedule_tab()
        self.build_review_tab()
        self.build_log_tab()

    def metric_card(self, parent: ttk.Frame, title: str, value: tk.StringVar, column: int) -> None:
        frame = ttk.Frame(parent, style="Surface.TFrame", padding=14)
        frame.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 8, 0 if column == 3 else 8))
        ttk.Label(frame, text=title, style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(frame, textvariable=value, style="CardValue.TLabel").pack(anchor="w", pady=(4, 0))

    def build_overview_tab(self) -> None:
        self.overview_table = DataTable(self.overview_tab)
        self.overview_table.pack(fill="both", expand=True)

    def build_rate_tab(self) -> None:
        pane = ttk.PanedWindow(self.rate_tab, orient="vertical")
        pane.pack(fill="both", expand=True)
        top = ttk.Frame(pane, style="Surface.TFrame", padding=10)
        bottom = ttk.Frame(pane, style="Surface.TFrame", padding=10)
        pane.add(top, weight=2)
        pane.add(bottom, weight=1)
        ttk.Label(top, text="Interval 데이터", background=COLORS["surface"], font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 6))
        self.rate_interval_table = DataTable(top)
        self.rate_interval_table.pack(fill="both", expand=True)
        ttk.Label(bottom, text="온도별 대표 소모속도", background=COLORS["surface"], font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 6))
        self.rate_summary_table = DataTable(bottom)
        self.rate_summary_table.pack(fill="both", expand=True)

    def build_fit_tab(self) -> None:
        self.fit_plot = PlotCanvas(self.fit_tab)
        self.fit_plot.pack(fill="both", expand=True)

    def build_prediction_tab(self) -> None:
        controls = ttk.Frame(self.prediction_tab, style="Surface.TFrame", padding=12)
        controls.pack(fill="x", pady=(0, 10))
        fields = [
            ("온도 ℃", self.pred_temp),
            ("초기 P mg", self.pred_mass),
            ("시간", self.pred_time),
        ]
        for label, var in fields:
            ttk.Label(controls, text=label, background=COLORS["surface"], foreground=COLORS["muted"]).pack(side="left", padx=(0, 5))
            ttk.Entry(controls, textvariable=var, width=9).pack(side="left", padx=(0, 12))
        ttk.Combobox(controls, textvariable=self.pred_unit, values=["min", "hour"], width=7, state="readonly").pack(side="left", padx=(0, 12))
        ttk.Button(controls, text="Predict", style="Primary.TButton", command=self.calculate_prediction).pack(side="left")
        self.prediction_text = tk.Text(self.prediction_tab, height=7, bg=COLORS["surface"], relief="flat", padx=12, pady=10, font=("Segoe UI", 11))
        self.prediction_text.tag_configure("remaining", foreground=COLORS["blue"], font=("Segoe UI", 11, "bold"))
        self.prediction_text.pack(fill="x", pady=(0, 10))
        self.prediction_plot = PlotCanvas(self.prediction_tab)
        self.prediction_plot.pack(fill="both", expand=True)

    def build_schedule_tab(self) -> None:
        controls = ttk.Frame(self.schedule_tab, style="Surface.TFrame", padding=12)
        controls.pack(fill="x", pady=(0, 10))
        fields = [
            ("초기 P mg", self.schedule_initial_mass),
            ("공정 h", self.schedule_hours),
            ("목표 mg/h", self.schedule_target),
            ("최소 mg/h", self.schedule_min_rate),
            ("최소 잔류 mg", self.schedule_min_remaining),
            ("시작 ℃", self.schedule_start_temp),
            ("종료 ℃", self.schedule_end_temp),
            ("시간간격 h", self.schedule_step),
        ]
        for label, var in fields:
            ttk.Label(controls, text=label, background=COLORS["surface"], foreground=COLORS["muted"]).pack(side="left", padx=(0, 4))
            ttk.Entry(controls, textvariable=var, width=8).pack(side="left", padx=(0, 8))
        ttk.Combobox(
            controls,
            textvariable=self.schedule_mode,
            values=["Time-step optimized"],
            width=22,
            state="readonly",
        ).pack(side="left", padx=(0, 10))
        ttk.Button(controls, text="Calculate", style="Primary.TButton", command=self.calculate_schedule).pack(side="left")
        self.schedule_text = tk.Text(self.schedule_tab, height=6, bg=COLORS["surface"], relief="flat", padx=12, pady=10)
        self.schedule_text.pack(fill="x", pady=(0, 10))
        self.schedule_table = DataTable(self.schedule_tab)
        self.schedule_table.pack(fill="both", expand=True)

    def build_review_tab(self) -> None:
        controls = ttk.Frame(self.review_tab, style="Surface.TFrame", padding=10)
        controls.pack(fill="x", pady=(0, 8))
        ttk.Button(controls, text="Toggle selected", style="Quiet.TButton", command=self.toggle_review_selection).pack(side="left", padx=(0, 8))
        ttk.Button(controls, text="Include selected", style="Quiet.TButton", command=lambda: self.set_review_selection(True)).pack(side="left", padx=(0, 8))
        ttk.Button(controls, text="Exclude selected", style="Quiet.TButton", command=lambda: self.set_review_selection(False)).pack(side="left", padx=(0, 8))
        ttk.Button(controls, text="Include all valid", style="Quiet.TButton", command=self.include_all_valid_review_rows).pack(side="left", padx=(0, 8))
        ttk.Label(
            controls,
            text="선택을 바꾸면 Arrhenius fit이 즉시 재계산됩니다.",
            background=COLORS["surface"],
            foreground=COLORS["muted"],
        ).pack(side="left", padx=(8, 0))
        self.review_table = DataTable(self.review_tab)
        self.review_table.pack(fill="both", expand=True)
        self.review_table.tree.bind("<Double-1>", lambda _event: self.toggle_review_selection())

    def build_log_tab(self) -> None:
        self.log_text = tk.Text(self.log_tab, bg=COLORS["surface"], relief="flat", padx=14, pady=12, font=("Segoe UI", 10))
        self.log_text.pack(fill="both", expand=True)

    def choose_file(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Excel files", "*.xlsx")])
        if path:
            self.file_path.set(path)
            self.load_file()

    def load_file(self) -> None:
        try:
            self.bundle = run_analysis(self.file_path.get())
        except Exception as exc:
            messagebox.showerror("분석 오류", str(exc))
            return
        self.refresh_all()

    def refresh_all(self) -> None:
        if not self.bundle:
            return
        self.update_metrics()
        self.populate_overview()
        self.refresh_condition_views()
        self.populate_review()
        self.populate_log()
        self.calculate_prediction()

    def update_metrics(self) -> None:
        for condition, key in [(CONDITION_015_0_120, "fit_0_120"), (CONDITION_015_AFTER_120, "fit_after_120")]:
            fit = self.bundle.fits[condition]
            if fit.is_valid:
                self.metric_vars[key].set(f"Ea {fit.ea_kj_per_mol:.3g} kJ/mol, R² {fit.r_squared:.3f}")
            else:
                self.metric_vars[key].set("fit 불가")
        self.metric_vars["rows"].set(str(int(self.bundle.intervals["fitting_included"].sum())))
        self.metric_vars["assumption"].set("소모량 ∝ 초기질량/기준질량")

    def populate_overview(self) -> None:
        rows = []
        for condition in (CONDITION_015_0_120, CONDITION_015_AFTER_120):
            fit = self.bundle.fits[condition]
            summary = self.bundle.summaries[condition]
            rows.append(
                {
                    "condition": condition,
                    "status": fit.status,
                    "A min^-1": fit.a_mg_per_min,
                    "Ea kJ/mol": fit.ea_kj_per_mol,
                    "R squared": fit.r_squared,
                    "temperature count": fit.temperature_count,
                    "interval count": fit.interval_count,
                    "temperature range": f"{fmt(fit.min_temperature_c)}-{fmt(fit.max_temperature_c)}",
                    "summary rows": len(summary),
                }
            )
        self.overview_table.set_dataframe(pd.DataFrame(rows))

    def refresh_condition_views(self) -> None:
        if not self.bundle:
            return
        fit_conditions = [CONDITION_015_0_120, CONDITION_015_AFTER_120]
        intervals = self.bundle.intervals[self.bundle.intervals["condition"].isin(fit_conditions)].copy()
        interval_cols = [
            "source_sheet",
            "source_rows",
            "parsed_temperature_C",
            "series_id",
            "t1_min",
            "t2_min",
            "duration_min",
            "interval_loss_mg",
            "rate_mg_per_min",
            "rate_mg_per_hour",
            "merged_interval",
            "startup_interval",
            "fitting_included",
            "duplicate_status",
            "exclusion_reason",
        ]
        self.rate_interval_table.set_dataframe(intervals, interval_cols)
        summaries = []
        for fit_condition in fit_conditions:
            summary = self.bundle.summaries[fit_condition].copy()
            if not summary.empty:
                summary.insert(0, "model", "k1" if fit_condition == CONDITION_015_0_120 else "k2")
                summaries.append(summary)
        self.rate_summary_table.set_dataframe(pd.concat(summaries, ignore_index=True) if summaries else pd.DataFrame())
        self.draw_fit_plot()

    def populate_review(self) -> None:
        review_cols = [
            "fitting_included",
            "time_group",
            "condition",
            "t1_min",
            "t2_min",
            "parsed_temperature_C",
            "p1_mg",
            "p2_mg",
            "interval_loss_mg",
            "duration_min",
            "rate_mg_per_hour",
            "exclusion_reason",
            "use",
            "original_CVD_name",
            "original_pressure",
            "ar_sccm",
            "inferred_ar",
            "original_temperature",
            "temperature_parse_method",
            "temperature_override_applied",
            "temperature_correction_note",
            "source_sheet",
            "excel_row",
            "source_priority",
            "normalized_equipment",
            "loading_class",
            "series_id",
            "effective_pressure",
            "canonical_pressure",
            "base_condition",
            "cumulative_loss_mg",
            "rate_mg_per_min",
            "startup_interval",
            "merged_interval",
            "source_rows",
            "duplicate_status",
            "notes",
        ]
        visible = self.bundle.intervals[self.bundle.intervals["base_condition"].eq("0.15 Torr / Ar 20 sccm")].copy()
        self.review_table.set_dataframe(visible, review_cols)

    def _can_toggle_review_row(self, idx: int) -> bool:
        if not self.bundle or idx not in self.bundle.intervals.index:
            return False
        row = self.bundle.intervals.loc[idx]
        return bool(row.get("use", False)) and pd.notna(row.get("condition"))

    def _refresh_after_review_selection(self) -> None:
        if not self.bundle:
            return
        refit_bundle_from_selection(self.bundle)
        self.update_metrics()
        self.populate_overview()
        self.refresh_condition_views()
        self.populate_review()
        self.populate_log()
        self.calculate_prediction()

    def toggle_review_selection(self) -> None:
        if not self.bundle:
            return
        selected = self.review_table.selected_indices()
        if not selected:
            return
        changed = False
        for idx in selected:
            if self._can_toggle_review_row(idx):
                current = bool(self.bundle.intervals.at[idx, "fitting_included"])
                self.bundle.intervals.at[idx, "fitting_included"] = not current
                changed = True
        if changed:
            self._refresh_after_review_selection()

    def set_review_selection(self, included: bool) -> None:
        if not self.bundle:
            return
        selected = self.review_table.selected_indices()
        if not selected:
            return
        changed = False
        for idx in selected:
            if self._can_toggle_review_row(idx):
                self.bundle.intervals.at[idx, "fitting_included"] = included
                changed = True
        if changed:
            self._refresh_after_review_selection()

    def include_all_valid_review_rows(self) -> None:
        if not self.bundle:
            return
        valid = self.bundle.intervals["use"].fillna(False).astype(bool) & self.bundle.intervals["condition"].notna()
        self.bundle.intervals.loc[valid, "fitting_included"] = True
        self._refresh_after_review_selection()

    def populate_log(self) -> None:
        self.log_text.delete("1.0", "end")
        self.log_text.insert(
            "end",
            "\n".join(
                self.bundle.logs
                + [
                    "",
                    "새 예측 가정:",
                    "같은 온도, 시간, 압력에서 초기 질량이 n배이면 소모속도와 소모량도 n배로 계산합니다.",
                    "mass scaling factor = initial P mass / reference mass",
                ]
            ),
        )

    def draw_fit_plot(self) -> None:
        series = [
            ("k1: 0-120 min", CONDITION_015_0_120, COLORS["blue"]),
            ("k2: After 120 min", CONDITION_015_AFTER_120, COLORS["red"]),
        ]
        plot_items = []
        xs_all: list[float] = []
        ys_all: list[float] = []
        for label_text, fit_condition, color in series:
            summary = self.bundle.summaries[fit_condition]
            fit = self.bundle.fits[fit_condition]
            if summary.empty or not fit.is_valid:
                continue
            x_summary = [1 / float(tk) for tk in summary["temperature_K"]]
            k_col = "representative_k_per_min" if "representative_k_per_min" in summary.columns else "representative_rate_mg_per_min"
            y_summary = [math.log(float(rate)) for rate in summary[k_col]]
            x_min, x_max = min(x_summary), max(x_summary)
            x_line = [x_min + (x_max - x_min) * i / 80 for i in range(81)]
            y_line = [fit.slope * x + fit.intercept for x in x_line]
            plot_items.append((label_text, fit, x_summary, y_summary, x_line, y_line, color))
            xs_all.extend(x_summary + x_line)
            ys_all.extend(y_summary + y_line)
        if not plot_items:
            self.fit_plot.clear()
            return
        sx, sy = self.fit_plot.axes("Arrhenius fitting: ln(k) vs 1/T", "1/T, K^-1", "ln(k), k in min^-1", xs_all, ys_all)
        label_y = 82
        for label_text, fit, x_summary, y_summary, x_line, y_line, color in plot_items:
            for x, y in zip(x_summary, y_summary):
                self.fit_plot.point(sx, sy, x, y, color, 6)
            self.fit_plot.create_line(
                *(coord for x, y in zip(x_line, y_line) for coord in (sx(x), sy(y))),
                fill=color,
                width=3,
            )
            fit_label = (
                f"{label_text} | slope {fit.slope:.4g} | intercept {fit.intercept:.4g} | "
                f"Ea {fit.ea_kj_per_mol:.3g} kJ/mol | R² {fit.r_squared:.4f}"
            )
            self.fit_plot.create_text(94, label_y, anchor="w", text=fit_label, font=("Segoe UI", 10, "bold"), fill=color)
            label_y += 22
        return
        condition = self.condition.get()
        summary = self.bundle.summaries[condition]
        fit = self.bundle.fits[condition]
        if summary.empty or not fit.is_valid:
            self.fit_plot.clear()
            return
        x_summary = [1 / float(tk) for tk in summary["temperature_K"]]
        k_col = "representative_k_per_min" if "representative_k_per_min" in summary.columns else "representative_rate_mg_per_min"
        y_summary = [math.log(float(rate)) for rate in summary[k_col]]
        x_min, x_max = min(x_summary), max(x_summary)
        x_line = [x_min + (x_max - x_min) * i / 80 for i in range(81)]
        y_line = [fit.slope * x + fit.intercept for x in x_line]
        sx, sy = self.fit_plot.axes("Arrhenius fitting: ln(k) vs 1/T", "1/T, K^-1", "ln(k), k in min^-1", x_summary + x_line, y_summary + y_line)
        for x, y in zip(x_summary, y_summary):
            self.fit_plot.point(sx, sy, x, y, COLORS["blue"], 6)
        self.fit_plot.create_line(*(coord for x, y in zip(x_line, y_line) for coord in (sx(x), sy(y))), fill=COLORS["red"], width=3)
        label = (
            f"{condition} | slope {fit.slope:.4g} | intercept {fit.intercept:.4g} | "
            f"Ea {fit.ea_kj_per_mol:.3g} kJ/mol | R² {fit.r_squared:.4f}"
        )
        self.fit_plot.create_text(94, 82, anchor="w", text=label, font=("Segoe UI", 10, "bold"), fill=COLORS["text"])

    def calculate_prediction(self) -> None:
        if not self.bundle:
            return
        fit_0_120 = self.bundle.fits[CONDITION_015_0_120]
        fit_after_120 = self.bundle.fits[CONDITION_015_AFTER_120]
        try:
            pred = predict_loss_composite(
                fit_0_120,
                fit_after_120,
                initial_mass_mg=self.pred_mass.get(),
                temperature_c=self.pred_temp.get(),
                process_time=self.pred_time.get(),
                time_unit=self.pred_unit.get(),
                surface_area_factor=1.0,
            )
        except Exception as exc:
            self.prediction_text.delete("1.0", "end")
            self.prediction_text.insert("end", str(exc))
            return
        self.prediction_text.delete("1.0", "end")
        self.prediction_text.insert("end", f"Condition: {pred.condition}\n")
        self.prediction_text.insert("end", f"Base model: {pred.model_type}\n")
        self.prediction_text.insert("end", f"k1 (0-120 min): {pred.k1_per_min:.6g} min^-1\n")
        if pred.k2_per_min is not None:
            self.prediction_text.insert("end", f"k2 (After 120 min): {pred.k2_per_min:.6g} min^-1\n")
        self.prediction_text.insert("end", "Model used by time: " + " / ".join(f"{s.model} {s.start_min:g}-{s.end_min:g} min" for s in pred.segments) + "\n")
        self.prediction_text.insert("end", f"Initial rate: {pred.initial_rate_mg_per_hour:.6g} mg/hour\n")
        self.prediction_text.insert("end", f"Average rate over input time: {pred.q_mg_per_min:.6g} mg/min ({pred.q_mg_per_hour:.6g} mg/hour)\n")
        self.prediction_text.insert("end", f"Expected loss: {pred.predicted_loss_mg:.6g} mg\n")
        self.prediction_text.insert("end", f"Remaining P: {pred.remaining_mass_mg:.6g} mg\n", "remaining")
        self.prediction_text.insert("end", f"Consumed fraction: {pred.consumed_fraction_percent:.4g}% | {pred.range_status}\n")
        self.prediction_text.insert("end", pred.warning)
        minutes = pred.process_time_min
        times = [minutes * i / 100 for i in range(101)]
        losses = []
        for t in times:
            remaining_at_t = pred.initial_mass_mg
            for segment in pred.segments:
                if t <= segment.start_min:
                    break
                duration = min(t, segment.end_min) - segment.start_min
                if duration > 0:
                    remaining_at_t *= math.exp(-segment.k_per_min * duration)
            losses.append(pred.initial_mass_mg - remaining_at_t)
        remaining = [pred.initial_mass_mg - loss for loss in losses]
        sx, sy = self.prediction_plot.axes("Composite k1/k2 prediction", "Time, min", "P mass, mg", times, losses + remaining)
        self.prediction_plot.create_line(*(coord for t, y in zip(times, losses) for coord in (sx(t), sy(y))), fill=COLORS["red"], width=3)
        self.prediction_plot.create_line(*(coord for t, y in zip(times, remaining) for coord in (sx(t), sy(y))), fill=COLORS["blue"], width=3)
        self.prediction_plot.create_text(94, 82, anchor="w", text="red: cumulative loss | blue: remaining P | switch at 120 min", fill=COLORS["text"])
        return
        fit = self.bundle.fits[self.condition.get()]
        try:
            pred = predict_loss(
                fit,
                initial_mass_mg=self.pred_mass.get(),
                temperature_c=self.pred_temp.get(),
                process_time=self.pred_time.get(),
                time_unit=self.pred_unit.get(),
                surface_area_factor=1.0,
                reference_mass_mg=self.pred_mass.get(),
            )
        except Exception as exc:
            self.prediction_text.delete("1.0", "end")
            self.prediction_text.insert("end", str(exc))
            return
        self.prediction_text.delete("1.0", "end")
        self.prediction_text.insert("end", f"Condition: {pred.condition}\n")
        self.prediction_text.insert("end", f"Base model: {pred.model_type}\n")
        self.prediction_text.insert("end", f"First-order k: {pred.k_per_min:.6g} min^-1\n")
        self.prediction_text.insert("end", f"Initial rate: {pred.initial_rate_mg_per_hour:.6g} mg/hour\n")
        self.prediction_text.insert("end", f"Average rate over input time: {pred.q_mg_per_min:.6g} mg/min ({pred.q_mg_per_hour:.6g} mg/hour)\n")
        self.prediction_text.insert("end", f"Expected loss: {pred.predicted_loss_mg:.6g} mg\n")
        self.prediction_text.insert("end", f"Remaining P: {pred.remaining_mass_mg:.6g} mg\n", "remaining")
        self.prediction_text.insert("end", f"Consumed fraction: {pred.consumed_fraction_percent:.4g}% | {pred.range_status}\n")
        self.prediction_text.insert("end", pred.warning)
        minutes = pred.process_time_min
        times = [minutes * i / 100 for i in range(101)]
        losses = [pred.initial_mass_mg * (1 - math.exp(-pred.k_per_min * t)) for t in times]
        remaining = [pred.initial_mass_mg - loss for loss in losses]
        sx, sy = self.prediction_plot.axes("질량비례 예측", "Time, min", "P mass, mg", times, losses + remaining)
        self.prediction_plot.create_line(*(coord for t, y in zip(times, losses) for coord in (sx(t), sy(y))), fill=COLORS["red"], width=3)
        self.prediction_plot.create_line(*(coord for t, y in zip(times, remaining) for coord in (sx(t), sy(y))), fill=COLORS["blue"], width=3)
        self.prediction_plot.create_text(94, 82, anchor="w", text="red: cumulative loss | blue: remaining P", fill=COLORS["text"])

    def calculate_schedule(self) -> None:
        if not self.bundle:
            return
        fit_0_120 = self.bundle.fits[CONDITION_015_0_120]
        fit_after_120 = self.bundle.fits[CONDITION_015_AFTER_120]
        fit = fit_0_120
        notes: list[str] = []
        def optional_float(var: tk.StringVar) -> float | None:
            text = str(var.get()).strip()
            return None if text == "" else float(text)

        initial = optional_float(self.schedule_initial_mass)
        min_remaining = optional_float(self.schedule_min_remaining)
        hours = optional_float(self.schedule_hours)
        target = optional_float(self.schedule_target)
        min_rate = optional_float(self.schedule_min_rate)
        start_temp = optional_float(self.schedule_start_temp)
        end_temp = optional_float(self.schedule_end_temp)
        time_step = optional_float(self.schedule_step)

        if min_rate is None:
            min_rate = 80.0
            notes.append("최소 순간속도 자동 보정: 80 mg/h")
        missing_mass_balance = [initial is None, min_remaining is None, hours is None, target is None].count(True)
        if missing_mass_balance == 1:
            if target is None and None not in (initial, min_remaining, hours):
                target = (initial - min_remaining) / hours
                notes.append(f"목표 평균 자동 보정: {target:.5g} mg/h = (초기질량-최소잔류)/공정시간")
            elif hours is None and None not in (initial, min_remaining, target):
                hours = (initial - min_remaining) / target
                notes.append(f"공정시간 자동 보정: {hours:.5g} h = (초기질량-최소잔류)/목표평균")
            elif initial is None and None not in (min_remaining, target, hours):
                initial = min_remaining + target * hours
                notes.append(f"초기질량 자동 보정: {initial:.5g} mg = 최소잔류+목표평균*공정시간")
            elif min_remaining is None and None not in (initial, target, hours):
                min_remaining = initial - target * hours
                notes.append(f"최소잔류 자동 보정: {min_remaining:.5g} mg = 초기질량-목표평균*공정시간")
        else:
            if initial is None:
                initial = self.pred_mass.get()
                notes.append(f"초기질량 자동 보정: {initial:.5g} mg (Prediction 입력값 사용)")
            if hours is None:
                hours = 8.0
                notes.append("공정시간 자동 보정: 8 h")
            if min_remaining is None:
                min_remaining = max(50.0, initial * 0.1)
                notes.append(f"최소잔류 자동 보정: {min_remaining:.5g} mg")
            if target is None:
                target = (initial - min_remaining) / hours
                notes.append(f"목표 평균 자동 보정: {target:.5g} mg/h = (초기질량-최소잔류)/공정시간")
        if time_step is None:
            time_step = max(0.25, min(2.0, hours / 8))
            notes.append(f"시간간격 자동 보정: {time_step:.5g} h")
        if start_temp is None or end_temp is None:
            try:
                required = temperature_for_rate(fit, target, initial, self.surface_factor.get())
                if start_temp is None:
                    start_temp = required - 10
                    notes.append(f"시작온도 자동 보정: {start_temp:.5g} ℃")
                if end_temp is None:
                    end_temp = required + 10
                    notes.append(f"종료온도 자동 보정: {end_temp:.5g} ℃")
            except Exception:
                if start_temp is None:
                    start_temp = 330.0
                    notes.append("시작온도 자동 보정: 330 ℃")
                if end_temp is None:
                    end_temp = 410.0
                    notes.append("종료온도 자동 보정: 410 ℃")

        result = calculate_composite_schedule(
            fit_0_120,
            fit_after_120,
            initial_mass_mg=initial,
            minimum_remaining_mg=min_remaining,
            total_hours=hours,
            target_average_mg_hour=target,
            minimum_instant_mg_hour=min_rate,
            start_temperature_c=start_temp,
            end_temperature_c=end_temp,
            time_step_hours=time_step,
            surface_area_factor=self.surface_factor.get(),
            mode=self.schedule_mode.get(),
            reference_mass_mg=initial,
        )
        self.schedule_text.delete("1.0", "end")
        prefix = "\n".join(notes)
        if prefix:
            prefix += "\n"
        self.schedule_text.insert(
            "end",
            prefix
            + result.message,
        )
        self.schedule_table.set_dataframe(result.stages)


if __name__ == "__main__":
    PhosphorusTkApp().mainloop()
