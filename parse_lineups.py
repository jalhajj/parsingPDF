"""Utilities for parsing lineup PDF exports into a pandas DataFrame.

The expected PDF format contains two pages, one for the home team and one for
 the opponent. Each page holds a single table with the following top-level
 headers: "Line-up", "MIN", "Score +/-", "Field Goals" (with sub-headers
 "M/A" and "%"), "Rebounds" (with sub-headers "OR", "DR", and "TOT"), plus
 assist/turnover/steal columns ("AS", "TO", "ST").

The :func:`parse_lineup_pdf` function reads this table from each page, expands
 nested headers, splits score and field-goal figures, and returns a normalized
 DataFrame with a consistent set of columns for both teams.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

import pandas as pd
import pdfplumber


def _combine_headers(rows: Sequence[Sequence[str]]) -> Tuple[List[str], List[List[str]]]:
    """Combine two header rows into a single list of column names.

    The first two rows of the extracted table hold the main headers and their
    sub-headers. This helper merges the values into single labels such as
    ``"Field Goals M/A"`` or ``"Rebounds OR"`` while leaving standalone headers
    untouched. Remaining rows are returned as data rows.
    """

    if len(rows) < 2:
        raise ValueError("Expected at least two rows to build headers")

    main, sub, *rest = rows
    combined: List[str] = []
    for primary, secondary in zip(main, sub):
        primary = (primary or "").strip()
        secondary = (secondary or "").strip()
        if primary and secondary:
            combined.append(f"{primary} {secondary}".strip())
        else:
            combined.append(primary or secondary)
    return combined, [list(r) for r in rest]


def _normalize_column(name: str) -> str:
    """Normalize a raw column name into a canonical label."""

    cleaned = re.sub(r"\s+", " ", name or "").strip().lower()
    mapping = {
        "line-up": "Lineup",
        "line up": "Lineup",
        "min": "Min",
        "score+/-": "Score",
        "score +/-": "Score",
        "field goals m/a": "M/A",
        "field goals %": "FG%",
        "rebounds or": "OR",
        "rebounds dr": "DR",
        "rebounds tot": "TOT",
        "as": "AS",
        "to": "TO",
        "st": "ST",
    }
    return mapping.get(cleaned, name.strip())


def _split_score(score: str) -> Tuple[int | None, int | None]:
    """Split a score string like ``"20-15"`` into integers."""

    if not score:
        return None, None
    parts = re.split(r"\s*-\s*", str(score))
    if len(parts) != 2:
        return None, None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None, None


def _split_field_goals(value: str) -> Tuple[int | None, int | None]:
    """Split a made/attempted string like ``"5/11"`` into integers."""

    if not value:
        return None, None
    parts = str(value).split("/")
    if len(parts) != 2:
        return None, None
    try:
        made = int(parts[0])
        attempted = int(parts[1])
    except ValueError:
        return None, None
    return made, attempted


def _infer_teams_from_filename(pdf_path: Path) -> Tuple[str, str] | None:
    """Infer the team codes from the PDF filename, if possible."""

    tokens = pdf_path.stem.split("_")
    candidates = [t for t in tokens if t.isupper() and len(t) == 3]
    if len(candidates) >= 2:
        return candidates[0], candidates[1]
    return None


def _extract_table(page: pdfplumber.page.Page) -> List[List[str]]:
    """Extract the first non-empty table from a page."""

    for table in page.extract_tables():
        if table and any(any(cell for cell in row) for row in table):
            return table
    raise ValueError("No table data found on page")


def parse_lineup_pdf(pdf_path: str | Path, teams: Iterable[str] | None = None) -> pd.DataFrame:
    """Parse the lineup PDF into a normalized :class:`pandas.DataFrame`.

    Parameters
    ----------
    pdf_path:
        Path to the lineup PDF containing two pages (home and away).
    teams:
        Optional iterable specifying the team names for page 1 and page 2. If
        omitted, the function attempts to infer three-letter team codes from the
        filename (e.g., ``lineup-analysis_D1_QAT_LBN_20251127.pdf`` ->
        ``("QAT", "LBN")``). When inference fails, generic placeholders are
        used.

    Returns
    -------
    pandas.DataFrame
        A DataFrame with columns: ``Team``, ``Opponent``, ``Lineup``, ``Min``,
        ``Team Score``, ``Opponent Score``, ``FGA``, ``FGM``, ``OR``, ``DR``,
        ``AS``, ``TO``, and ``ST``.
    """

    pdf_path = Path(pdf_path)
    inferred = _infer_teams_from_filename(pdf_path)
    if teams is None and inferred:
        teams = inferred
    elif teams is None:
        teams = ("Team 1", "Team 2")

    team_list = list(teams)
    if len(team_list) < 2:
        raise ValueError("Two team names are required to map pages to teams")

    frames: List[pd.DataFrame] = []
    with pdfplumber.open(pdf_path) as pdf:
        for idx, page in enumerate(pdf.pages):
            raw_table = _extract_table(page)
            headers, data_rows = _combine_headers(raw_table)
            normalized_headers = [_normalize_column(h) for h in headers]
            df = pd.DataFrame(data_rows, columns=normalized_headers)

            # Drop completely empty rows that sometimes appear at the bottom.
            df = df.dropna(how="all").reset_index(drop=True)

            # Identify the relevant columns.
            score_col = next((c for c in df.columns if c.lower().startswith("score")), None)
            ma_col = next((c for c in df.columns if c.lower().endswith("m/a")), None)
            or_col = next((c for c in df.columns if c.lower() == "or"), None)
            dr_col = next((c for c in df.columns if c.lower() == "dr"), None)
            as_col = next((c for c in df.columns if c.lower() == "as"), None)
            to_col = next((c for c in df.columns if c.lower() == "to"), None)
            st_col = next((c for c in df.columns if c.lower() == "st"), None)
            min_col = next((c for c in df.columns if c.lower() == "min"), None)

            if score_col is None or ma_col is None:
                raise ValueError("Could not locate required columns in table")

            df[["Team Score", "Opponent Score"]] = df[score_col].apply(
                lambda x: pd.Series(_split_score(x))
            )
            df[["FGM", "FGA"]] = df[ma_col].apply(
                lambda x: pd.Series(_split_field_goals(x))
            )

            df["Team"] = team_list[idx if idx < len(team_list) else -1]
            df["Opponent"] = team_list[1 - idx if idx < 2 else 0]

            result = df[[
                "Team",
                "Opponent",
                "Lineup",
                min_col or "Min",
                "Team Score",
                "Opponent Score",
                "FGA",
                "FGM",
                or_col or "OR",
                dr_col or "DR",
                as_col or "AS",
                to_col or "TO",
                st_col or "ST",
            ]].rename(columns={
                min_col or "Min": "Min",
                or_col or "OR": "OR",
                dr_col or "DR": "DR",
                as_col or "AS": "AS",
                to_col or "TO": "TO",
                st_col or "ST": "ST",
            })
            frames.append(result)

    return pd.concat(frames, ignore_index=True)
