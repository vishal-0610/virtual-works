# Data Cleaning & Structural Validation

**Virtual Works Internship Project - Task 1**  
**Project ID:** `task1`

A web-based CSV quality workbench. Upload a file or load the included messy customer sample, inspect detected issues, choose cleaning operations, validate the result, compare before and after, and download a cleaned CSV.

## Features

- CSV upload (16 MB limit), sample data, record counts, and raw preview.
- Detection of missing/empty values, duplicate rows and IDs, invalid numbers and dates, mixed types, surrounding spaces, and capitalization variants.
- Independent cleaned copy. The uploaded source is retained unchanged for comparison during the app session.
- Selectable duplicate/empty-row removal, whitespace trimming, title-case normalization, type/date conversion, invalid-number handling, and missing-value strategies (drop rows, mean, median, mode, custom value, or leave unchanged).
- Structural checks for required fields, a unique ID column, and a configurable numeric range.
- Before/after metrics, visual issue comparison, data-quality score, operation log, and CSV download.

## Requirements

- Python 3.10 or newer
- pip

## Install and run

Open a terminal in this folder and run:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

Then open [http://127.0.0.1:5000](http://127.0.0.1:5000). On Windows, if PowerShell blocks activation, run `Set-ExecutionPolicy -Scope Process Bypass` in that terminal and activate again, or use `.venv\Scripts\python.exe -m pip install -r requirements.txt` followed by `.venv\Scripts\python.exe app.py`.

## Walkthrough

1. Select **Load Sample Dataset** or upload a `.csv` file.
2. Inspect the raw preview and quality indicators.
3. Choose required fields, an ID column, and optional numeric range in Validation Results.
4. Select cleaning operations and a missing-value strategy, then apply cleaning.
5. Review the cleaned preview, validation status, before/after comparison, and operation log.
6. Download the result as a CSV.

## Modules

- `app.py`: Flask routes, CSV parsing, quality profiling, structural validation, isolated cleaning transformations, and CSV export.
- `templates/index.html`: dashboard sections and user controls.
- `static/css/styles.css`: responsive dashboard styling.
- `static/js/app.js`: upload/sample flow, analysis rendering, validation controls, cleaning requests, charts, and download state.
- `sample_data/messy_customers.csv`: test data with missing fields, duplicate records and IDs, malformed dates/numbers, whitespace, and inconsistent capitalization.

## Data integrity and scope

The original frame is held separately from the cleaned frame and is not mutated by cleaning. The operation log describes applied actions; row-removal counts are shown before export. This demonstration keeps datasets in process memory, so uploads and results are cleared when the server restarts and are not shared between server processes. Do not expose the development server to untrusted networks; add authentication, persistent storage, and production WSGI configuration before deployment.
