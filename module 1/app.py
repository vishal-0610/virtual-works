from __future__ import annotations

import csv
import io
import os
import uuid
from typing import Any

import pandas as pd
from flask import Flask, jsonify, render_template, request, send_file
from werkzeug.utils import secure_filename


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

# Demo-sized uploads stay in memory; every cleaning operation works on a copy.
DATASETS: dict[str, dict[str, Any]] = {}
MISSING_MARKERS = {"", "na", "n/a", "null", "none", "nan", "<na>"}
NUMERIC_HINTS = ("age", "amount", "price", "score", "income", "salary", "quantity", "count", "year", "weight", "height", "rate")
DATE_HINTS = ("date", "time", "birth", "joined", "created", "updated")


def is_missing(value: Any) -> bool:
    return str(value).strip().casefold() in MISSING_MARKERS


def missing_mask(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.apply(lambda column: column.map(is_missing))


def parse_csv(stream: Any) -> pd.DataFrame:
    if hasattr(stream, "read"):
        raw = stream.read()
    else:
        with open(stream, "rb") as source:
            raw = source.read()
    source_headers = next(csv.reader(io.StringIO(raw.decode("utf-8-sig"))), [])
    frame = pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False, na_filter=False)
    frame.columns = [str(column) for column in frame.columns]
    frame.attrs["source_headers"] = [str(column) for column in source_headers]
    return frame


def column_kinds(frame: pd.DataFrame) -> dict[str, str]:
    kinds: dict[str, str] = {}
    for column in frame.columns:
        values = frame.loc[~missing_mask(frame)[column], column].astype(str)
        lowered = column.casefold()
        if values.empty:
            kinds[column] = "empty"
            continue
        numeric = pd.to_numeric(values.str.replace(",", "", regex=False), errors="coerce")
        numeric_ratio = float(numeric.notna().mean())
        dates = pd.to_datetime(values, errors="coerce", format="mixed")
        date_ratio = float(dates.notna().mean())
        if any(hint in lowered for hint in NUMERIC_HINTS) or numeric_ratio >= 0.65:
            kinds[column] = "number"
        elif any(hint in lowered for hint in DATE_HINTS) or date_ratio >= 0.65:
            kinds[column] = "date"
        else:
            kinds[column] = "text"
    return kinds


def analyze_frame(frame: pd.DataFrame, config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or {}
    mask = missing_mask(frame)
    missing_by_column = {str(column): int(mask[column].sum()) for column in frame.columns}
    missing_total = int(mask.to_numpy().sum())
    empty_rows = mask.all(axis=1) if len(frame.columns) else pd.Series(False, index=frame.index)
    duplicate_rows = frame.duplicated(keep="first")
    kinds = column_kinds(frame)
    profiles: list[dict[str, Any]] = []
    invalid_cells = 0
    whitespace_cells = 0
    capitalization_cells = 0
    duplicate_id_count = 0
    invalid_numeric_by_column: dict[str, int] = {}
    invalid_date_by_column: dict[str, int] = {}
    mixed_columns: list[str] = []

    id_column = config.get("idColumn") or next(
        (
            column for column in frame.columns
            if column.casefold().replace("_", " ").replace("-", " ").split()[-1:] == ["id"]
            or str(column).endswith("ID")
        ),
        None,
    )
    for column in frame.columns:
        present = frame.loc[~mask[column], column].astype(str)
        kind = kinds[column]
        numeric_invalid = 0
        date_invalid = 0
        if kind == "number":
            numeric_invalid = int(pd.to_numeric(present.str.replace(",", "", regex=False), errors="coerce").isna().sum())
            invalid_numeric_by_column[str(column)] = numeric_invalid
        elif kind == "date":
            date_invalid = int(pd.to_datetime(present, errors="coerce", format="mixed").isna().sum())
            invalid_date_by_column[str(column)] = date_invalid
        if numeric_invalid or date_invalid:
            mixed_columns.append(str(column))
            invalid_cells += numeric_invalid + date_invalid
        whitespace_cells += int((present != present.str.strip()).sum())
        if kind == "text" and len(present):
            groups = present.groupby(present.str.casefold())
            for _, group in groups:
                if group.nunique() > 1:
                    capitalization_cells += len(group) - int(group.value_counts().max())
        profiles.append({
            "name": str(column),
            "kind": kind,
            "missing": missing_by_column[str(column)],
            "invalidNumeric": numeric_invalid,
            "invalidDate": date_invalid,
            "mixed": bool(numeric_invalid or date_invalid),
        })

    if id_column in frame.columns:
        ids = frame.loc[~mask[id_column], id_column].astype(str).str.strip()
        duplicate_id_count = int(ids.duplicated(keep=False).sum())

    required_fields = config.get("requiredFields") or []
    if isinstance(required_fields, str):
        required_fields = [required_fields]
    validations: list[dict[str, str]] = []
    if not len(frame.columns):
        validations.append({"status": "invalid", "label": "Column structure", "detail": "The dataset has no columns."})
    else:
        source_headers = frame.attrs.get("source_headers", [str(column) for column in frame.columns])
        blank_headers = [str(column) for column in source_headers if not str(column).strip()]
        normalized_headers = [str(column).strip().casefold() for column in source_headers]
        duplicate_headers = sorted({name for name in normalized_headers if normalized_headers.count(name) > 1 and name})
        if blank_headers:
            validations.append({"status": "invalid", "label": "Column names", "detail": f"{len(blank_headers)} source column name(s) are blank."})
        elif duplicate_headers:
            validations.append({"status": "invalid", "label": "Column names", "detail": "Duplicate source names: " + ", ".join(duplicate_headers) + "."})
        elif any(str(column) != str(column).strip() for column in source_headers):
            validations.append({"status": "warning", "label": "Column names", "detail": "Some names contain leading or trailing spaces."})
        else:
            validations.append({"status": "valid", "label": "Column names", "detail": f"{len(frame.columns)} named columns found."})

    if required_fields:
        absent = [name for name in required_fields if name not in frame.columns]
        empty_required = [name for name in required_fields if name in frame.columns and mask[name].any()]
        if absent or empty_required:
            detail = []
            if absent:
                detail.append("Not found: " + ", ".join(absent))
            if empty_required:
                detail.append("Empty values: " + ", ".join(empty_required))
            validations.append({"status": "invalid", "label": "Required fields", "detail": "; ".join(detail)})
        else:
            validations.append({"status": "valid", "label": "Required fields", "detail": f"{len(required_fields)} required field(s) are populated."})
    else:
        validations.append({"status": "warning", "label": "Required fields", "detail": "No required fields selected."})

    if id_column in frame.columns:
        status = "invalid" if duplicate_id_count else "valid"
        detail = f"{duplicate_id_count} duplicate ID value(s) found." if duplicate_id_count else "ID values are unique."
        validations.append({"status": status, "label": "Unique ID", "detail": detail})
    else:
        validations.append({"status": "warning", "label": "Unique ID", "detail": "No ID column selected or detected."})

    range_column = config.get("rangeColumn")
    if range_column in frame.columns:
        numbers = pd.to_numeric(frame.loc[~mask[range_column], range_column].str.replace(",", "", regex=False), errors="coerce")
        minimum = config.get("rangeMin")
        maximum = config.get("rangeMax")
        violations = 0
        if minimum not in (None, ""):
            violations += int((numbers < float(minimum)).sum())
        if maximum not in (None, ""):
            violations += int((numbers > float(maximum)).sum())
        validations.append({"status": "invalid" if violations else "valid", "label": "Numerical range", "detail": f"{violations} value(s) outside the selected range." if violations else "Values are within the selected range."})
    else:
        validations.append({"status": "warning", "label": "Numerical range", "detail": "No numerical range selected."})

    invalid_rows = int((duplicate_rows | mask.any(axis=1)).sum())
    quality_score = max(0, round(100 * (1 - (missing_total + int(duplicate_rows.sum()) + invalid_cells) / max(1, frame.size))))
    return {
        "rows": int(len(frame)),
        "columns": int(len(frame.columns)),
        "missingTotal": missing_total,
        "missingByColumn": missing_by_column,
        "duplicateRows": int(duplicate_rows.sum()),
        "emptyRows": int(empty_rows.sum()),
        "invalidCells": invalid_cells,
        "invalidRecords": invalid_rows,
        "invalidNumeric": sum(invalid_numeric_by_column.values()),
        "invalidDates": sum(invalid_date_by_column.values()),
        "whitespaceCells": whitespace_cells,
        "capitalizationCells": capitalization_cells,
        "duplicateIds": duplicate_id_count,
        "mixedColumns": mixed_columns,
        "profiles": profiles,
        "validations": validations,
        "qualityScore": quality_score,
        "idColumn": id_column if id_column in frame.columns else "",
    }


def preview(frame: pd.DataFrame, limit: int = 8) -> dict[str, Any]:
    safe = frame.head(limit).where(pd.notna(frame.head(limit)), "")
    return {"columns": [str(column) for column in frame.columns], "rows": safe.astype(str).values.tolist(), "total": int(len(frame))}


def store_frame(frame: pd.DataFrame, filename: str) -> str:
    token = uuid.uuid4().hex
    DATASETS[token] = {"original": frame.copy(deep=True), "cleaned": None, "filename": filename, "stats": None}
    return token


def dataset_for(token: str) -> dict[str, Any] | None:
    return DATASETS.get(token)


@app.get("/")
def home():
    return render_template("index.html")


@app.post("/api/upload")
def upload():
    uploaded = request.files.get("file")
    if not uploaded or not uploaded.filename:
        return jsonify({"error": "Choose a CSV file to upload."}), 400
    if not uploaded.filename.casefold().endswith(".csv"):
        return jsonify({"error": "Only CSV files are supported."}), 400
    try:
        frame = parse_csv(uploaded.stream)
    except Exception as error:
        return jsonify({"error": f"Could not read this CSV: {error}"}), 400
    if frame.empty and len(frame.columns) == 0:
        return jsonify({"error": "The CSV must include a header row."}), 400
    token = store_frame(frame, secure_filename(uploaded.filename) or "dataset.csv")
    return jsonify({"token": token, "filename": DATASETS[token]["filename"], "preview": preview(frame), "analysis": analyze_frame(frame)})


@app.post("/api/sample")
def sample():
    sample_path = os.path.join(app.root_path, "sample_data", "messy_customers.csv")
    try:
        frame = parse_csv(sample_path)
    except Exception as error:
        return jsonify({"error": f"Could not load sample dataset: {error}"}), 500
    token = store_frame(frame, "messy_customers.csv")
    return jsonify({"token": token, "filename": "messy_customers.csv", "preview": preview(frame), "analysis": analyze_frame(frame)})


@app.post("/api/analyze")
def analyze():
    payload = request.get_json(silent=True) or {}
    dataset = dataset_for(str(payload.get("token", "")))
    if not dataset:
        return jsonify({"error": "Dataset session not found. Upload or load the sample again."}), 404
    return jsonify({"analysis": analyze_frame(dataset["original"], payload)})


@app.post("/api/clean")
def clean():
    payload = request.get_json(silent=True) or {}
    dataset = dataset_for(str(payload.get("token", "")))
    if not dataset:
        return jsonify({"error": "Dataset session not found. Upload or load the sample again."}), 404
    options = payload.get("options", {})
    original = dataset["original"]
    cleaned = original.copy(deep=True)
    original_analysis = analyze_frame(original)
    log: list[str] = []
    formatting_corrections = 0
    start_rows = len(cleaned)

    if options.get("removeEmptyRows"):
        mask = missing_mask(cleaned)
        before = len(cleaned)
        cleaned = cleaned.loc[~mask.all(axis=1)].copy()
        log.append(f"Removed {before - len(cleaned)} completely empty row(s).")
    if options.get("removeDuplicates"):
        before = len(cleaned)
        cleaned = cleaned.drop_duplicates(keep="first").copy()
        log.append(f"Removed {before - len(cleaned)} duplicate row(s); first copies were preserved.")
    if options.get("trimSpaces"):
        changed = 0
        for column in cleaned.columns:
            values = cleaned[column].astype(str)
            changed += int((values != values.str.strip()).sum())
            cleaned[column] = values.str.strip()
        formatting_corrections += changed
        log.append(f"Trimmed spaces in {changed} cell(s).")
    if options.get("standardizeCapitalization"):
        changed = 0
        for column in cleaned.columns:
            if any(hint in column.casefold() for hint in ("email", "url", "website", "id", "code")):
                continue
            values = cleaned[column].astype(str)
            text_mask = values.str.contains(r"[A-Za-z]", regex=True, na=False)
            replacements = values.loc[text_mask].str.title()
            changed += int((values.loc[text_mask] != replacements).sum())
            cleaned.loc[text_mask, column] = replacements
        formatting_corrections += changed
        log.append(f"Standardized capitalization in {changed} cell(s) using title case.")

    original_kinds = column_kinds(original)
    if options.get("convertTypes") or options.get("handleInvalid"):
        for column, kind in original_kinds.items():
            if kind == "number":
                converted = pd.to_numeric(cleaned[column].astype(str).str.replace(",", "", regex=False), errors="coerce")
                changed = int((converted.isna() & ~missing_mask(cleaned)[column]).sum())
                cleaned[column] = converted
                if options.get("handleInvalid") and changed:
                    log.append(f"Converted {changed} invalid value(s) in '{column}' to missing.")
                elif options.get("convertTypes"):
                    log.append(f"Converted '{column}' to a numeric type.")
            elif kind == "date" and options.get("convertTypes"):
                original_values = cleaned[column].astype(str)
                values = pd.to_datetime(original_values, errors="coerce", format="mixed")
                standardized = values.dt.strftime("%Y-%m-%d")
                formatting_corrections += int((values.notna() & (original_values != standardized)).sum())
                cleaned[column] = standardized.where(values.notna(), original_values)
                log.append(f"Standardized valid dates in '{column}' to YYYY-MM-DD.")

    strategy = payload.get("missingStrategy", "leave")
    missing_before = int(missing_mask(cleaned).to_numpy().sum())
    if strategy == "drop_rows":
        before = len(cleaned)
        cleaned = cleaned.loc[~missing_mask(cleaned).any(axis=1)].copy()
        log.append(f"Removed {before - len(cleaned)} row(s) containing missing values.")
    elif strategy in {"mean", "median", "mode", "custom"}:
        fill_value = payload.get("customValue", "") if strategy == "custom" else None
        kinds = column_kinds(original)
        for column in cleaned.columns:
            missing = missing_mask(cleaned)[column]
            if not missing.any():
                continue
            if strategy in {"mean", "median"} and kinds.get(column) == "number":
                numeric = pd.to_numeric(cleaned[column], errors="coerce")
                value = numeric.mean() if strategy == "mean" else numeric.median()
                if pd.notna(value):
                    cleaned.loc[missing, column] = value
            elif strategy == "mode" and kinds.get(column) == "text":
                values = cleaned.loc[~missing, column]
                if not values.empty:
                    cleaned.loc[missing, column] = values.mode().iloc[0]
            elif strategy == "custom":
                cleaned[column] = cleaned[column].astype(object)
                cleaned.loc[missing, column] = fill_value
        log.append(f"Handled missing values using {strategy.replace('_', ' ')}." )

    # Keep a fresh object for every session; the source frame is never mutated.
    dataset["cleaned"] = cleaned.copy(deep=True)
    cleaned_analysis = analyze_frame(cleaned)
    final_missing = int(missing_mask(cleaned).to_numpy().sum())
    stats = {
        "originalRows": int(start_rows),
        "cleanedRows": int(len(cleaned)),
        "duplicatesRemoved": max(0, original_analysis["duplicateRows"] - cleaned_analysis["duplicateRows"]),
        "missingDetected": original_analysis["missingTotal"],
        "missingHandled": max(0, original_analysis["missingTotal"] - final_missing),
        "invalidRecords": original_analysis["invalidRecords"],
        "formattingCorrections": formatting_corrections,
        "cleanedQualityScore": cleaned_analysis["qualityScore"],
        "operations": log,
    }
    dataset["stats"] = stats
    return jsonify({"preview": preview(cleaned), "analysis": cleaned_analysis, "stats": stats, "originalAnalysis": original_analysis})


@app.get("/api/download/<token>")
def download(token: str):
    dataset = dataset_for(token)
    if not dataset:
        return jsonify({"error": "Dataset session not found."}), 404
    frame = dataset.get("cleaned")
    if frame is None:
        return jsonify({"error": "Apply cleaning before downloading the cleaned dataset."}), 400
    output = io.BytesIO(frame.to_csv(index=False).encode("utf-8-sig"))
    return send_file(output, mimetype="text/csv", as_attachment=True, download_name="cleaned_" + dataset["filename"])


@app.errorhandler(413)
def too_large(_error):
    return jsonify({"error": "File is larger than the 16 MB upload limit."}), 413


if __name__ == "__main__":
    app.run(debug=False, use_reloader=False, port=int(os.environ.get("PORT", "5000")))
