# P Sublimation Analyzer

Tkinter GUI for phosphorus sublimation Arrhenius fitting, prediction, and constant-rate temperature scheduling.

## What It Does

- Loads experiment data from a local workbook or a public Google Sheets URL.
- Uses only the `Codex` sheet when available.
- Fits first-order Arrhenius models with:
  - `k1`: 0-120 min
  - `k2`: after 120 min
- Prediction automatically uses `k1` up to 120 min and `k2` after 120 min.
- Constant Rate Schedule automatically marks each stage as `k1`, `k2`, or `k1+k2`.

## Run On Another PC

Install Python 3.10 or newer, then run:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements_tkinter.txt
python phosphorus_sublimation_gui.py
```

Or double-click:

```bat
run_app.bat
```

## Run Online With Streamlit Cloud

1. Push this repository to GitHub.
2. Open https://share.streamlit.io
3. Sign in with GitHub.
4. Create a new app from this repository.
5. Set the main file path to:

```text
streamlit_app.py
```

6. Deploy.

After deployment, Streamlit creates a browser link like:

```text
https://your-app-name.streamlit.app
```

Open that link from any laptop without downloading the project.

## Run Directly With GitHub Pages

This repository also includes a static mobile web app:

```text
index.html
style.css
app.js
```

To publish it with GitHub Pages:

1. Open the repository on GitHub.
2. Go to `Settings` -> `Pages`.
3. Under `Build and deployment`, choose:
   - Source: `Deploy from a branch`
   - Branch: `main`
   - Folder: `/root`
4. Save.

The app URL will look like:

```text
https://serence22.github.io/Research/
```

Use this GitHub Pages link when you want to open the app directly from a phone browser.

## Google Sheets

Paste a Google Sheets URL into `Workbook / Google Sheet URL`, then press `Analyze`.

The sheet must be accessible by link. If it is private, export will fail unless the file is downloaded locally as `.xlsx`.

## Notes

- Excel files are intentionally excluded from GitHub by `.gitignore`.
- Use Google Sheets as the shared data source when running from multiple computers.
