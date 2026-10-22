import io
import os

import pandas as pd

ALLOWED = {".xlsx", ".xls", ".csv"}
MAX_BYTES = 15 * 1024 * 1024


def clean(v):
    """Normalize empty and whitespace-only values."""
    if v is None:
        return ""

    try:
        if pd.isna(v):
            return ""
    except (TypeError, ValueError):
        pass

    s = str(v).strip()
    return "" if s.lower() in {"nan", "nat", "none"} else s


def is_blank_row(row):
    """True if every value in the row is empty or whitespace."""
    if row is None:
        return True

    values = row.values if isinstance(row, dict) else row

    return all(clean(value) == "" for value in values)


def read_table(filename, content):
    ext = os.path.splitext(filename.lower())[1]

    if ext not in ALLOWED:
        raise ValueError("For comparison, upload .xlsx, .xls, or .csv files.")

    if len(content) > MAX_BYTES:
        raise ValueError("Each file must be 15 MB or smaller.")

    if ext == ".csv":
        df = pd.read_csv(
            io.BytesIO(content),
            dtype=object,
            keep_default_na=False,
        )
    else:
        df = pd.read_excel(
            io.BytesIO(content),
            dtype=object,
            keep_default_na=False,
        )

    df.columns = [str(c).strip() for c in df.columns]

    if not len(df.columns):
        raise ValueError(f"{filename} has no columns.")

    # Remove completely empty rows before comparison.
    # Reset the index so subsequent row matching remains consistent.
    df = df.loc[~df.apply(is_blank_row, axis=1)].reset_index(drop=True)

    return df


def compare_tables(ref, new, key=None):
    # Also filter blank rows here so callers that pass DataFrames
    # directly receive the same behavior as read_table().
    ref = ref.loc[~ref.apply(is_blank_row, axis=1)].reset_index(drop=True)

    new = new.loc[~new.apply(is_blank_row, axis=1)].reset_index(drop=True)

    issues = []
    rc = list(ref.columns)
    nc = list(new.columns)

    # Missing and extra columns.
    for c in rc:
        if c not in nc:
            issues.append(
                {
                    "issue_type": "Missing column",
                    "record_key": "—",
                    "column": c,
                    "reference_value": "Column exists",
                    "comparison_value": "Column missing",
                }
            )

    for c in nc:
        if c not in rc:
            issues.append(
                {
                    "issue_type": "Extra column",
                    "record_key": "—",
                    "column": c,
                    "reference_value": "Column missing",
                    "comparison_value": "Column exists",
                }
            )

    common = [c for c in rc if c in nc]

    if key and key in common:
        rk = ref[key].map(clean)
        nk = new[key].map(clean)

        # Duplicate keys.
        for label, series in (("Reference", rk), ("Comparison", nk)):
            dup = series[series.duplicated(keep=False) & (series != "")]

            for k in sorted(set(dup.tolist())):
                issues.append(
                    {
                        "issue_type": f"Duplicate key in {label}",
                        "record_key": k,
                        "column": key,
                        "reference_value": "Unique key expected",
                        "comparison_value": (
                            f"Key appears {(series == k).sum()} times"
                        ),
                    }
                )

        rm, nm = {}, {}

        for i, k in enumerate(rk):
            if k and k not in rm:
                rm[k] = i

        for i, k in enumerate(nk):
            if k and k not in nm:
                nm[k] = i

        # Missing and extra records.
        for k in sorted(set(rm) - set(nm)):
            issues.append(
                {
                    "issue_type": "Missing record",
                    "record_key": k,
                    "column": key,
                    "reference_value": "Record exists",
                    "comparison_value": "Record missing",
                }
            )

        for k in sorted(set(nm) - set(rm)):
            issues.append(
                {
                    "issue_type": "Extra record",
                    "record_key": k,
                    "column": key,
                    "reference_value": "Record missing",
                    "comparison_value": "Record exists",
                }
            )

        # Compare matching records.
        for k in sorted(set(rm) & set(nm)):
            i, j = rm[k], nm[k]

            for c in common:
                if c == key:
                    continue

                a = clean(ref.iloc[i][c])
                b = clean(new.iloc[j][c])

                if a != b:
                    issues.append(
                        {
                            "issue_type": "Value mismatch",
                            "record_key": k,
                            "column": c,
                            "reference_value": a,
                            "comparison_value": b,
                            "reference_row": i + 2,
                            "comparison_row": j + 2,
                        }
                    )

    else:
        if key:
            issues.append(
                {
                    "issue_type": "Matching key unavailable",
                    "record_key": "—",
                    "column": key,
                    "reference_value": "Key required in both files",
                    "comparison_value": "Compared by row position",
                }
            )

        # Compare by row position.
        for i in range(max(len(ref), len(new))):
            if i >= len(ref):
                issues.append(
                    {
                        "issue_type": "Extra record",
                        "record_key": str(i + 1),
                        "column": "—",
                        "reference_value": "No row",
                        "comparison_value": f"Row {i + 2} exists",
                    }
                )
                continue

            if i >= len(new):
                issues.append(
                    {
                        "issue_type": "Missing record",
                        "record_key": str(i + 1),
                        "column": "—",
                        "reference_value": f"Row {i + 2} exists",
                        "comparison_value": "No row",
                    }
                )
                continue

            for c in common:
                a = clean(ref.iloc[i][c])
                b = clean(new.iloc[i][c])

                if a != b:
                    issues.append(
                        {
                            "issue_type": "Value mismatch",
                            "record_key": str(i + 1),
                            "column": c,
                            "reference_value": a,
                            "comparison_value": b,
                            "reference_row": i + 2,
                            "comparison_row": i + 2,
                        }
                    )

    # Intentionally do not create separate blank-cell issues.
    # A blank-versus-filled difference is still a Value mismatch.

    counts = {}
    for issue in issues:
        issue_type = issue["issue_type"]
        counts[issue_type] = counts.get(issue_type, 0) + 1

    summary = {
        "reference_rows": len(ref),
        "comparison_rows": len(new),
        "reference_columns": len(rc),
        "comparison_columns": len(nc),
        "matching_key": key or "Row position",
        "total_issues": len(issues),
        "issue_counts": counts,
        "status": "No issues found" if not issues else "Issues found",
    }

    return summary, issues
