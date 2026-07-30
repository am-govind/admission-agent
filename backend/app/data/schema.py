"""Canonical typed schema shared by ingestion and analytics.

Column names, target SQL types, PII columns and required columns live here so the
whole codebase has a single source of truth for "what the data looks like".

Types matter: the source workbook hands us real Python `datetime`, `bool` and
`float` values, and an earlier version flattened everything to VARCHAR. That forced
every query to re-parse dates and cast numbers, which is both slow and a source of
silent wrong answers. Each column is now cast once, at load time, to the type
declared here.
"""
from __future__ import annotations

import re

# ---------- table names inside DuckDB (lowercase, code-friendly) ----------
TABLE_RD26 = "rd26"            # current academic year (AY2026)
TABLE_RD25 = "rd25"            # last academic year (AY2025) — retention source
TABLE_FINANCE = "finance_dump"  # payment detail — 2nd-EMI base
TABLE_TARGETS = "targets"      # per center/region targets

ANALYTICS_TABLES = (TABLE_RD26, TABLE_RD25, TABLE_FINANCE, TABLE_TARGETS)

TABLE_LABELS = {
    TABLE_RD26: "AY2026 admissions dump",
    TABLE_RD25: "AY2025 admissions dump",
    TABLE_FINANCE: "Finance dump",
    TABLE_TARGETS: "Targets",
}

# Which config setting names the source tab for each table.
TABLE_TAB_SETTING = {
    TABLE_RD26: "tab_rd26",
    TABLE_RD25: "tab_rd25",
    TABLE_FINANCE: "tab_finance",
    TABLE_TARGETS: "tab_targets",
}

# ---------- column types ----------
# VARCHAR    — text, kept verbatim
# IDENTIFIER — numeric-looking code that must stay text (no 2.35e7, no lost zeros)
# INTEGER / DOUBLE / DATE / BOOLEAN — cast, so queries never re-parse
VARCHAR = "VARCHAR"
IDENTIFIER = "IDENTIFIER"
INTEGER = "INTEGER"
DOUBLE = "DOUBLE"
DATE = "DATE"
BOOLEAN = "BOOLEAN"

# RD26_DUMP / RD25_DUMP, in sheet order (columns A..U in the workbook).
RD_COLUMN_TYPES: dict[str, str] = {
    "region": VARCHAR,             # A
    "regno": IDENTIFIER,           # B — arrives as a float, must not become 2.35e7
    "student_name": VARCHAR,       # C — PII
    "class_course": VARCHAR,       # D
    "batch": VARCHAR,              # E
    "center": VARCHAR,             # F
    "enrolled_years": INTEGER,     # G
    "joining_date": DATE,          # H
    "source_name": VARCHAR,        # I
    "fees_amt": DOUBLE,            # J
    "pct_discount": DOUBLE,        # K
    "fees_paid": DOUBLE,           # L — the 3498 threshold column
    "pct_paid": DOUBLE,            # M
    "newpayment_checks": VARCHAR,  # N
    "eligibility_status": VARCHAR,  # O
    "status": VARCHAR,             # P
    "free_admission": BOOLEAN,     # Q
    "ep_status": VARCHAR,          # R
    "form_status": VARCHAR,        # S
    "arpu": DOUBLE,                # T
    "arpu_check": VARCHAR,         # U
}

RD_COLUMNS = list(RD_COLUMN_TYPES)

# Finance Dump uses different column positions to the RD dumps, so it is matched by
# header name. Only the columns the 2nd-EMI base formula needs are typed here; any
# other columns present in the tab are loaded as VARCHAR.
FINANCE_COLUMN_TYPES: dict[str, str] = {
    "region": VARCHAR,                  # A
    "batch": VARCHAR,                   # D
    "status": VARCHAR,                  # I
    "center": VARCHAR,                  # J
    "newpayment_checks": VARCHAR,       # P
    "vp_ps_regular_schemes": BOOLEAN,   # T
}

TARGETS_COLUMN_TYPES: dict[str, str] = {
    "region": VARCHAR,
    "center": VARCHAR,
    "class_course": VARCHAR,
    "reg_target": INTEGER,
    "retention_target": INTEGER,
    "monthly_target": INTEGER,
    "arpu_target": DOUBLE,
}

TABLE_COLUMN_TYPES: dict[str, dict[str, str]] = {
    TABLE_RD26: RD_COLUMN_TYPES,
    TABLE_RD25: RD_COLUMN_TYPES,
    TABLE_FINANCE: FINANCE_COLUMN_TYPES,
    TABLE_TARGETS: TARGETS_COLUMN_TYPES,
}

# Columns the analytics functions cannot work without. A table missing any of these
# is reported unavailable rather than silently producing wrong numbers.
REQUIRED_COLUMNS: dict[str, tuple[str, ...]] = {
    TABLE_RD26: (
        "region", "center", "class_course", "joining_date", "fees_paid",
        "newpayment_checks", "eligibility_status", "status", "free_admission",
        "ep_status", "form_status", "arpu", "arpu_check",
    ),
    TABLE_RD25: (
        "region", "center", "enrolled_years", "newpayment_checks", "status",
        "free_admission", "form_status",
    ),
    TABLE_FINANCE: (
        "region", "center", "batch", "status", "newpayment_checks",
        "vp_ps_regular_schemes",
    ),
    TABLE_TARGETS: ("region", "center"),
}

# PII columns — masked in any user-facing output and never projectable by the explorer.
PII_COLUMNS = {"student_name", "regno"}

# ---------- reference values (observed in the AY2026 dump) ----------
REGIONS_CENTERS: dict[str, list[str]] = {
    "AP & TS": [
        "Hyderabad - AS RAO NAGAR Vidyapeeth", "Hyderabad - Chanda Nagar Vidyapeeth",
        "Hyderabad - Habsiguda Vidyapeeth", "Hyderabad - Kothapet Vidyapeeth",
        "Hyderabad - Kukatpally Vidyapeeth", "Hyderabad - Madhapur Vidyapeeth",
        "Hyderabad - Manikonda Vidyapeeth", "Hyderabad - Nallagandla Vidyapeeth",
        "Hyderabad - Shaikpet Vidyapeeth", "Hyderabad - Suchitra Vidyapeeth",
        "Vijayawada Vidyapeeth", "Vizag Vidyapeeth", "Warangal Vidyapeeth",
    ],
    "Maharashtra": [
        "Akola Vidyapeeth", "Chhatrapati Sambhajinagar Vidyapeeth",
        "Dombivali Kalyan Tuition Center", "Goa - Madgaon Vidyapeeth",
        "Goa - Panjim Vidyapeeth", "Latur Vidyapeeth", "Mumbai - Andheri Vidyapeeth",
        "Mumbai - Borivali Vidyapeeth", "Mumbai - Chembur Vidyapeeth",
        "Mumbai - Ghatkopar Vidyapeeth", "Mumbai - Kalyan Vidyapeeth",
        "Mumbai - Kharghar Vidyapeeth", "Mumbai - Nerul Vidyapeeth",
        "Mumbai - Panvel Vidyapeeth", "Mumbai - Thane Vidyapeeth",
        "Mumbai - Virar Vidyapeeth", "Nagpur - Wardhman Nagar Tuition Center",
        "Nagpur Vidyapeeth", "Nagpur Vidyapeeth (Residential Program)",
        "Nanded Vidyapeeth", "Nashik Vidyapeeth", "Pune - FC Road Vidyapeeth",
        "Pune - Hadapsar Vidyapeeth", "Pune - NalStop Vidyapeeth",
        "Pune - Pimple Saudagar Tuition Center", "Pune - Pimpri Vidyapeeth",
        "Pune - Viman Nagar Vidyapeeth",
    ],
    "South": [
        "Bengaluru - Banaswadi Vidyapeeth", "Bengaluru - HSR layout Vidyapeeth",
        "Bengaluru - JP Nagar Vidyapeeth", "Bengaluru - RR Nagar Vidyapeeth",
        "Bengaluru - RajajiNagar Vidyapeeth", "Bengaluru - Whitefield Vidyapeeth",
        "Bengaluru - Yelahanka Vidyapeeth", "Chennai - Adyar Gandhi Nagar Vidyapeeth",
        "Chennai - Annanagar Vidyapeeth", "Chennai - Ashok Nagar Vidyapeeth",
        "Chennai - Medavakkam Vidyapeeth", "Coimbatore Vidyapeeth", "Mysore Vidyapeeth",
    ],
}

CLASSES = ["8th", "9th", "10th", "11th JEE", "11th NEET", "12th JEE", "12th NEET",
           "Dropper JEE", "Dropper NEET", "NEET Crash Course"]

# The nine class columns of the workbook's class-wise breakdown, with the wildcard
# each one matches. Courses outside this list (e.g. "NEET Crash Course") are not in
# the breakdown, so it does not sum to the registration total — same as the sheet.
CLASSWISE_TOKENS: tuple[tuple[str, str], ...] = (
    ("8th", "8th"),
    ("9th", "9th"),
    ("10th", "10th"),
    ("11th JEE", "11th jee"),
    ("11th NEET", "11th neet"),
    ("12th JEE", "12th jee"),
    ("12th NEET", "12th neet"),
    ("Dropper JEE", "dropper jee"),
    ("Dropper NEET", "dropper neet"),
)

# Observed newpayment_checks values. Three of these contain "token", which is why
# the token exclusion is a substring match and not equality with "Token Only".
PAYMENT_MILESTONES = ["Less than Token", "Token Only", "Paid btw Token & 1st EMI",
                      "1st EMI Paid", "2nd EMI Paid", "3rd EMI Paid", "4th EMI Paid",
                      "Total Paid"]

EP_STATUSES = ["", "LOAN", "ENACH", "FlexiPay_Completed", "FlexiPay_Cancelled",
               "READY_FOR_DISBURSAL", "Loan_Cancelled"]

ELIGIBILITY_STATUSES = ["Eligible", "Not Eligible: Fee Pending",
                        "Not Eligible: Both Fee & Form Incomplete",
                        "Not Eligible:       Incomplete Form"]

FORM_STATUSES = ["Completed", "Stage 1", "Stage 2", "Admission Cancelled"]

_NON_WORD = re.compile(r"[^a-z0-9]+")


def normalize_header(raw: object) -> str:
    """Map a sheet header cell to a snake_case SQL-safe column name.

    "Fees Paid" -> fees_paid, "VP/PS Regular Schemes" -> vp_ps_regular_schemes.
    """
    text = "" if raw is None else str(raw)
    slug = _NON_WORD.sub("_", text.strip().lower()).strip("_")
    if not slug:
        return ""
    if slug[0].isdigit():
        slug = f"c_{slug}"
    return slug


def column_type(table: str, column: str) -> str:
    """Declared type for a column, defaulting to VARCHAR for unknown extras."""
    return TABLE_COLUMN_TYPES.get(table, {}).get(column, VARCHAR)
