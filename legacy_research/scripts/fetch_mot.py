#!/usr/bin/env python3
"""
fetch_mot.py
────────────
Download UK MOT anonymised test data, filter to VW Golf, produce:
  data/raw/mot_vw_golf_tests.csv   — one row per MOT test (pass/fail + mileage)
  data/raw/mot_vw_golf_failures.csv — one row per failure/advisory item
  data/raw/mot_failure_rate.csv    — failure rate summary by engine spec + year

Data source: DVSA anonymised MOT results (data.gov.uk), no registration needed.
File sizes: ~1-3 GB per year uncompressed — script processes in chunks.

Usage:
    python scripts/fetch_mot.py
    python scripts/fetch_mot.py --years 2023         # single year
    python scripts/fetch_mot.py --years 2021 2022 2023
"""

import argparse
import gzip
import io
import logging
import time
import zipfile

import pyzipper
from pathlib import Path

import pandas as pd
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"

# DVSA URL patterns (data.dft.gov.uk, no auth needed)
# 2005-2016: gzip-compressed pipe-delimited txt
# 2017-2023: ZIP containing pipe-delimited txt
DFT_BASE = "https://data.dft.gov.uk/anonymised-mot-test/test_data"
LOOKUP_URL = "https://data.dft.gov.uk/anonymised-mot-test/lookup.zip"

# cylinder_capacity → engine_spec mapping for VW Golf engines (cc values)
# Combined with fuel_type to distinguish diesel/petrol
CC_TO_DISP = {
    999: "1.0_TSI",
    1197: "1.2_TSI",
    1198: "1.2_TSI",
    1390: "1.4_TSI",
    1395: "1.4_TSI",
    1498: "1.5_TSI",
    1499: "1.5_TSI",
    1595: "1.6_TDI",
    1598: "1.6_TDI",
    1781: "1.8_TSI",
    1798: "1.8_TSI",
    1896: "1.9_TDI",
    1968: "2.0_TDI",
    1984: "2.0_TSI",
    1994: "2.0_TSI",
    3189: "3.2_VR6",
}

# DVSA fuel_type codes (from lookup.zip)
PETROL_CODES = {"P", "PE"}
DIESEL_CODES = {"D", "DI"}


# New S3 URLs for 2023+ (from data.gov.uk)
S3_BASE = "https://edh-dvsa-data-gov-uk-files-prod.s3.eu-west-1.amazonaws.com"


def resolve_url(year: int, kind: str) -> str:
    prefix = "test_result" if kind == "result" else "test_item"
    if year <= 2016:
        return f"{DFT_BASE}/{prefix}_{year}.txt.gz"
    elif year == 2023:
        if kind == "result":
            return f"{S3_BASE}/dft_test_result_2023.zip"
        else:
            return f"{S3_BASE}/dft_test_item_2023.zip"
    elif year == 2024:
        if kind == "result":
            return f"{S3_BASE}/MOT+testing+data+results+(2024).zip"
        else:
            return f"{S3_BASE}/MOT+Testing+data+failure+item+(2024).zip"
    else:
        return f"{DFT_BASE}/dft_{prefix}_{year}.zip"


def download_zip_stream(url: str, max_retries: int = 3) -> bytes:
    """Download with retry logic for large files."""
    for attempt in range(1, max_retries + 1):
        try:
            log.info("Downloading %s ... (attempt %d/%d)", url, attempt, max_retries)
            resp = requests.get(
                url, stream=True, timeout=1200, headers={"Accept-Encoding": "identity"}
            )
            if resp.status_code == 404:
                log.warning("404 — URL not found: %s", url)
                return b""
            resp.raise_for_status()

            total = int(resp.headers.get("content-length", 0))
            chunks = []
            downloaded = 0
            for chunk in resp.iter_content(chunk_size=2 * 1024 * 1024):  # 2 MB chunks
                if chunk:
                    chunks.append(chunk)
                    downloaded += len(chunk)
                    mb = downloaded // (1024 * 1024)
                    if total and mb % 50 == 0 and mb > 0:
                        log.info(
                            "  %d MB / %d MB (%.0f%%)",
                            mb,
                            total // (1024 * 1024),
                            downloaded / total * 100,
                        )
            log.info("  Complete: %d MB", downloaded // (1024 * 1024))
            return b"".join(chunks)
        except (
            requests.exceptions.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
            requests.exceptions.ContentDecodingError,
        ) as e:
            log.warning("Download failed (attempt %d): %s", attempt, e)
            if attempt < max_retries:
                time.sleep(5 * attempt)
            continue
        except Exception as e:
            log.error("Unexpected error: %s", e)
            break
    return b""


def open_mot_file(raw_bytes: bytes, url: str):
    """Return a file-like object for the MOT data, handling .gz and .zip (including LZMA)."""
    if url.endswith(".gz"):
        return gzip.open(io.BytesIO(raw_bytes), "rt", encoding="latin-1")
    elif url.endswith(".zip"):
        # Use pyzipper for LZMA compression (type 9)
        try:
            zf = pyzipper.AESZipFile(io.BytesIO(raw_bytes), "r")
        except Exception:
            # Fallback to standard zipfile for regular ZIPs
            zf = zipfile.ZipFile(io.BytesIO(raw_bytes))
        names = zf.namelist()
        data_file = next(
            (n for n in names if n.lower().endswith((".csv", ".txt"))), names[0]
        )
        log.info("  Reading %s from ZIP ...", data_file)
        return io.TextIOWrapper(zf.open(data_file), encoding="latin-1")
    else:
        return io.StringIO(raw_bytes.decode("latin-1"))


def read_mot_filtered(
    raw_bytes: bytes, url: str, make_filter: str, model_filter: str
) -> pd.DataFrame:
    """Read MOT file in chunks, keeping only rows matching make+model."""
    fh = open_mot_file(raw_bytes, url)

    # Peek at first line to detect separator
    first_line = fh.readline()
    sep = "|" if first_line.count("|") > first_line.count(",") else ","
    fh.seek(0) if hasattr(fh, "seek") else None

    # Re-open since we consumed the first line (gz/zip don't support seek)
    fh = open_mot_file(raw_bytes, url)

    chunks = []
    total = 0
    for chunk in pd.read_csv(
        fh, sep=sep, dtype=str, low_memory=False, chunksize=200_000, on_bad_lines="skip"
    ):
        chunk.columns = [c.strip().lower() for c in chunk.columns]
        total += len(chunk)
        if "make" in chunk.columns and "model" in chunk.columns:
            mask = chunk["make"].str.upper().str.contains(
                make_filter, na=False
            ) & chunk["model"].str.upper().str.contains(model_filter, na=False)
            filtered = chunk[mask]
            if len(filtered) > 0:
                chunks.append(filtered)
    log.info("  Scanned %d rows total", total)

    if not chunks:
        return pd.DataFrame()
    df = pd.concat(chunks, ignore_index=True)
    log.info(
        "  Filtered to %s %s: %d rows, columns: %s",
        make_filter,
        model_filter,
        len(df),
        list(df.columns),
    )
    return df


def read_items_filtered(raw_bytes: bytes, url: str, test_ids: set) -> pd.DataFrame:
    """Read item (failure) file in chunks, keeping only rows with matching test_ids."""
    fh = open_mot_file(raw_bytes, url)
    first_line = fh.readline()
    sep = "|" if first_line.count("|") > first_line.count(",") else ","
    fh = open_mot_file(raw_bytes, url)
    chunks = []
    total = 0
    for chunk in pd.read_csv(
        fh, sep=sep, dtype=str, low_memory=False, chunksize=200_000, on_bad_lines="skip"
    ):
        chunk.columns = [c.strip().lower() for c in chunk.columns]
        total += len(chunk)
        if "test_id" in chunk.columns and test_ids:
            chunk = chunk[chunk["test_id"].astype(str).isin(test_ids)]
        if len(chunk) > 0:
            chunks.append(chunk)
    log.info(
        "  Scanned %d item rows, kept %d for Golf", total, sum(len(c) for c in chunks)
    )
    return pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()


def filter_golf_tests(df: pd.DataFrame) -> pd.DataFrame:
    """Filter MOT test results to VW Golf."""
    if "make" not in df.columns or "model" not in df.columns:
        log.warning(
            "Expected 'make' and 'model' columns not found. Columns: %s",
            list(df.columns),
        )
        return df.iloc[0:0]

    make_mask = df["make"].str.upper().str.contains("VOLKSWAGEN", na=False)
    model_mask = df["model"].str.upper().str.contains("GOLF", na=False)
    result = df[make_mask & model_mask].copy()
    log.info("  VW Golf: %d / %d rows", len(result), len(df))
    return result


def infer_engine_spec(row) -> str:
    """Map cylinder_capacity + fuel_type to engine spec string."""
    cc_raw = row.get("cylinder_capacity", None)
    fuel = str(row.get("fuel_type", "")).strip().upper()

    try:
        cc = int(float(str(cc_raw).strip()))
    except (ValueError, TypeError):
        return "unknown"

    base = CC_TO_DISP.get(cc)
    if base is None:
        return f"unknown_{cc}cc"

    # Override fuel type suffix if we can determine petrol vs diesel
    if fuel in DIESEL_CODES and "TSI" in base:
        return base.replace("TSI", "TDI")
    if fuel in PETROL_CODES and "TDI" in base:
        return base.replace("TDI", "TSI")

    return base


def load_rfr_lookup(lookup_bytes: bytes) -> dict:
    """Parse RfR lookup table → {rfr_id: description}."""
    with zipfile.ZipFile(io.BytesIO(lookup_bytes)) as zf:
        names = zf.namelist()
        log.info("Lookup ZIP contents: %s", names)
        # Try item_detail.csv first, then first available
        target = next(
            (n for n in names if "item" in n.lower() or "rfr" in n.lower()), names[0]
        )
        raw = zf.read(target).decode("latin-1")

    df = pd.read_csv(io.StringIO(raw), sep="|", dtype=str, low_memory=False)
    df.columns = [c.strip().lower() for c in df.columns]
    log.info("RfR lookup: %d rows, columns: %s", len(df), list(df.columns))

    # Try to find id and description columns
    id_col = next((c for c in df.columns if "id" in c or "code" in c), df.columns[0])
    desc_col = next(
        (c for c in df.columns if "desc" in c or "text" in c or "name" in c),
        df.columns[1] if len(df.columns) > 1 else df.columns[0],
    )

    return dict(zip(df[id_col].str.strip(), df[desc_col].str.strip()))


def compute_failure_rate_summary(
    tests_df: pd.DataFrame, failures_df: pd.DataFrame
) -> pd.DataFrame:
    """Compute failure rates by engine_spec and registration year."""
    tests_df = tests_df.copy()
    tests_df["reg_year"] = pd.to_datetime(
        tests_df["first_use_date"], errors="coerce"
    ).dt.year
    tests_df["passed"] = tests_df["test_result"].str.upper().str.startswith("P")

    # Merge failure counts per test
    fail_counts = (
        failures_df.groupby("test_id").size().reset_index(name="failure_count")
    )
    merged = tests_df.merge(fail_counts, on="test_id", how="left")
    merged["failure_count"] = merged["failure_count"].fillna(0)

    # Group by engine_spec + reg_year
    summary = (
        merged.groupby(["engine_spec", "reg_year"])
        .agg(
            total_tests=("test_id", "count"),
            pass_count=("passed", "sum"),
            avg_failures=("failure_count", "mean"),
            avg_mileage=(
                "test_mileage",
                lambda x: pd.to_numeric(x, errors="coerce").mean(),
            ),
        )
        .reset_index()
    )
    summary["fail_rate_pct"] = (
        (1 - summary["pass_count"] / summary["total_tests"]) * 100
    ).round(1)
    summary = summary.sort_values(["engine_spec", "reg_year"])
    return summary


def main():
    parser = argparse.ArgumentParser(description="Download UK MOT data for VW Golf")
    parser.add_argument(
        "--years",
        nargs="+",
        type=int,
        default=[2023],
        help="Years to download (default: 2023)",
    )
    args = parser.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)

    # Download RfR lookup
    log.info("=== Downloading RfR lookup table ===")
    lookup_bytes = download_zip_stream(LOOKUP_URL)
    rfr_map = {}
    if lookup_bytes:
        rfr_map = load_rfr_lookup(lookup_bytes)
        log.info("Loaded %d RfR codes", len(rfr_map))

    all_tests = []
    all_failures = []

    for year in args.years:
        log.info("=== Processing year %d ===", year)

        # Test results
        result_url = resolve_url(year, "result")
        result_bytes = download_zip_stream(result_url)
        if not result_bytes:
            log.warning("Skipping year %d test results — download failed", year)
            continue

        tests_golf = read_mot_filtered(result_bytes, result_url, "VOLKSWAGEN", "GOLF")
        tests_golf["year"] = year

        # Add engine_spec
        tests_golf["engine_spec"] = tests_golf.apply(infer_engine_spec, axis=1)

        # Keep useful columns
        keep_test = [
            c
            for c in [
                "test_id",
                "vehicle_id",
                "test_date",
                "test_result",
                "test_mileage",
                "make",
                "model",
                "fuel_type",
                "cylinder_capacity",
                "first_use_date",
                "postcode_area",
                "engine_spec",
                "year",
            ]
            if c in tests_golf.columns
        ]
        all_tests.append(tests_golf[keep_test])

        # Failure items
        item_url = resolve_url(year, "item")
        item_bytes = download_zip_stream(item_url)
        if not item_bytes:
            log.warning("Skipping year %d failure items — download failed", year)
            continue

        golf_test_ids = (
            set(tests_golf["test_id"].astype(str))
            if "test_id" in tests_golf.columns
            else set()
        )
        items_raw = read_items_filtered(item_bytes, item_url, golf_test_ids)

        # Decode RfR codes
        if "rfr_id" in items_raw.columns and rfr_map:
            items_raw["rfr_description"] = (
                items_raw["rfr_id"].astype(str).str.strip().map(rfr_map)
            )

        items_raw["year"] = year
        all_failures.append(items_raw)

    if not all_tests:
        log.error("No data downloaded. Exiting.")
        return

    # Combine and save
    tests_df = pd.concat(all_tests, ignore_index=True)
    tests_path = RAW_DIR / "mot_vw_golf_tests.csv"
    tests_df.to_csv(tests_path, index=False)
    log.info("Saved %d test rows to %s", len(tests_df), tests_path)

    if all_failures:
        failures_df = pd.concat(all_failures, ignore_index=True)
        failures_path = RAW_DIR / "mot_vw_golf_failures.csv"
        failures_df.to_csv(failures_path, index=False)
        log.info("Saved %d failure item rows to %s", len(failures_df), failures_path)
    else:
        failures_df = pd.DataFrame()

    # Failure rate summary
    if len(failures_df) > 0 and "test_id" in failures_df.columns:
        summary = compute_failure_rate_summary(tests_df, failures_df)
        summary_path = RAW_DIR / "mot_failure_rate.csv"
        summary.to_csv(summary_path, index=False)
        log.info("Saved failure rate summary to %s", summary_path)

        log.info("\n=== FAILURE RATE BY ENGINE SPEC (top 20 rows) ===")
        log.info(
            "\n%s",
            summary.sort_values("fail_rate_pct", ascending=False).head(20).to_string(),
        )

    log.info("\n=== ENGINE SPEC DISTRIBUTION IN TESTS ===")
    log.info("\n%s", tests_df["engine_spec"].value_counts().to_string())

    log.info("\n=== REGISTRATION YEAR DISTRIBUTION ===")
    reg_years = pd.to_datetime(tests_df["first_use_date"], errors="coerce").dt.year
    log.info("\n%s", reg_years.value_counts().sort_index().to_string())


if __name__ == "__main__":
    main()
