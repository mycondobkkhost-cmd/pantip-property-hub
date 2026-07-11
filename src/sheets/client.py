"""Google Sheets client for fetching property listings."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import gspread
import pandas as pd
from google.oauth2.service_account import Credentials
from loguru import logger

from config.settings import settings

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

REQUIRED_COLUMNS = {"title", "caption", "image_urls", "status"}


def _get_gspread_client(credentials_path: Path) -> gspread.Client:
    if not credentials_path.exists():
        raise FileNotFoundError(
            f"Google credentials not found at {credentials_path}. "
            "Download your Service Account JSON and place it there."
        )

    creds = Credentials.from_service_account_file(str(credentials_path), scopes=SCOPES)
    return gspread.authorize(creds)


def fetch_properties_from_sheets(
    spreadsheet_id: str | None = None,
    sheet_name: str | None = None,
    credentials_path: Path | None = None,
    only_pending: bool = True,
) -> list[dict[str, Any]]:
    """
    Connect to Google Sheets and fetch property rows as dicts.

    Expected columns (case-insensitive):
      - title: Property name / location headline
      - caption: Post text (Below Market Value, Yield %, etc.)
      - image_urls: Comma-separated image URLs or local paths
      - status: 'pending' | 'posted' | 'failed'
      - row_id (optional): Stable identifier for tracking
      - group_url (optional): Override default Facebook group
    """
    spreadsheet_id = spreadsheet_id or settings.GOOGLE_SHEETS_ID
    sheet_name = sheet_name or settings.GOOGLE_SHEET_NAME
    credentials_path = credentials_path or settings.GOOGLE_CREDENTIALS_PATH

    if not spreadsheet_id:
        raise ValueError("GOOGLE_SHEETS_ID is not set in .env")

    logger.info("Connecting to Google Sheets: {}", spreadsheet_id)
    client = _get_gspread_client(credentials_path)
    worksheet = client.open_by_key(spreadsheet_id).worksheet(sheet_name)

    records = worksheet.get_all_records()
    if not records:
        logger.warning("Sheet '{}' is empty", sheet_name)
        return []

    df = pd.DataFrame(records)
    df.columns = [str(col).strip().lower() for col in df.columns]

    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(
            f"Sheet is missing required columns: {', '.join(sorted(missing))}"
        )

    if only_pending:
        df = df[df["status"].astype(str).str.lower() == "pending"]

    properties: list[dict[str, Any]] = []
    for idx, row in df.iterrows():
        image_raw = str(row.get("image_urls", "")).strip()
        image_urls = [u.strip() for u in image_raw.split(",") if u.strip()]

        properties.append(
            {
                "row_index": idx + 2,  # +2: header row + 1-based sheet rows
                "row_id": str(row.get("row_id", idx + 2)),
                "title": str(row.get("title", "")).strip(),
                "caption": str(row.get("caption", "")).strip(),
                "image_urls": image_urls,
                "group_url": str(row.get("group_url", "")).strip() or None,
                "status": str(row.get("status", "pending")).lower(),
            }
        )

    logger.info("Fetched {} pending properties", len(properties))
    return properties


def mark_property_status(
    row_index: int,
    status: str,
    spreadsheet_id: str | None = None,
    sheet_name: str | None = None,
    credentials_path: Path | None = None,
) -> None:
    """Update the status column for a given row after posting."""
    spreadsheet_id = spreadsheet_id or settings.GOOGLE_SHEETS_ID
    sheet_name = sheet_name or settings.GOOGLE_SHEET_NAME
    credentials_path = credentials_path or settings.GOOGLE_CREDENTIALS_PATH

    client = _get_gspread_client(credentials_path)
    worksheet = client.open_by_key(spreadsheet_id).worksheet(sheet_name)

    headers = [h.strip().lower() for h in worksheet.row_values(1)]
    if "status" not in headers:
        raise ValueError("Cannot update status: 'status' column not found")

    status_col = headers.index("status") + 1
    worksheet.update_cell(row_index, status_col, status)
    logger.info("Updated row {} status -> {}", row_index, status)
