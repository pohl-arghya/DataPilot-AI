# DataPilot AI

Turn raw data into better decisions. A local analytics app: upload a CSV or Excel file and get KPIs, charts, data-quality checks, insights and rule-based Q&A. Built with Flask, pandas, NumPy, OpenPyXL, vanilla JavaScript and Chart.js (bundled, so it works offline).

## Run it on Windows

1. **Install Python 3.10 or newer** from https://www.python.org/downloads/. On the first installer screen, tick **"Add python.exe to PATH"**.
2. Open **PowerShell** and go to the project folder, for example:
   ```
   cd C:\Users\YOU\Downloads\DataPilot_AI
   ```
3. Create and activate a virtual environment:
   ```
   python -m venv venv
   venv\Scripts\activate
   ```
   If PowerShell blocks activation, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, then try again. (In Command Prompt use `venv\Scripts\activate.bat`.)
4. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
5. Start the app:
   ```
   python app.py
   ```
6. Open **http://127.0.0.1:5000** in your browser. Stop the app with `Ctrl+C`.

## Try it

- Click **Try sample dataset** (a generated sample with a few missing values and duplicate rows added on purpose so the quality checks have something to show).
- Click **Upload dataset** or drag a `.csv`, `.xlsx` or `.xls` file onto the dashed area. Max 16 MB.
- **Data Explorer**: column types, missing values, numeric summary, searchable, sortable, paged records.
- **Insights**: data-quality findings (separate) and observations, each with the calculation behind it.
- **Ask DataPilot**: try the suggested questions. Answers are rule-based pandas calculations, not an AI model.
- **Settings**: dark mode and manual column mapping if auto-detection is wrong. A column named only `Total` is never assumed to be revenue.

## Test

```
python tests.py
```
Runs 31 checks (sample data, KPI maths, CSV/XLSX upload, bad files, missing/duplicate detection, mapping, Q&A) against Flask's test client. Browser appearance, dark mode and mobile layout need a manual check: open the site, toggle the theme, narrow the window below 820 px, and watch the browser console (F12) for errors.

## Project layout

```
app.py              Flask routes, analysis, insights, rule-based Q&A
templates/index.html  static/style.css  static/script.js  static/vendor/chart.umd.js
data/sample_sales.csv
tests.py
```
Endpoints: `GET /`, `POST /api/sample`, `POST /api/upload`, `POST /api/ask`, plus `POST /api/mapping`, `GET /api/rows`, `GET /api/state`.

## Privacy and limits

Files are read into memory only and never saved or sent elsewhere; the active dataset is forgotten when you stop the app. The app holds one dataset for one local user. It is not hardened for public hosting. Adding an AI model later: replace `answer_question()` in `app.py` and keep the API key in an environment variable on the server.

## Common problems

| Problem | Fix |
|---|---|
| `'python' is not recognized` | Reinstall Python with "Add to PATH" ticked, or try `py` instead of `python`. |
| `No module named flask` | Activate the venv (`venv\Scripts\activate`), then `pip install -r requirements.txt`. |
| `Address already in use` | Another program uses port 5000. Change `port=5000` at the bottom of `app.py`. |
| `.xls` file fails | Make sure `xlrd` installed; or re-save the file as `.xlsx`. |
| Charts empty | The file needs date + sales columns for trends. See the notes under the dashboard and Settings. |
