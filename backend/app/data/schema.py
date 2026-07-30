"""Canonical data-schema definitions shared across ingestion and analytics.

Keeping column names, table names, and PII columns in one place means the whole
codebase has a single source of truth for "what the data looks like".
"""
from __future__ import annotations

# Table names inside DuckDB (lowercase, code-friendly).
TABLE_RD26 = "rd26"          # current academic year (AY2026)
TABLE_RD25 = "rd25"          # last academic year (AY2025) — retention source
TABLE_FINANCE = "finance_dump"  # payment detail — 2nd-EMI base
TABLE_TARGETS = "targets"    # per center/region targets

# RD26_DUMP / RD25_DUMP columns, in sheet order.
RD_COLUMNS = [
    "region", "regno", "student_name", "class_course", "batch", "center",
    "enrolled_years", "joining_date", "source_name", "fees_amt", "pct_discount",
    "fees_paid", "pct_paid", "newpayment_checks", "eligibility_status", "status",
    "free_admission", "ep_status", "form_status", "arpu", "arpu_check",
]

# Columns stored as numbers (everything else is VARCHAR to preserve raw text).
RD_NUMERIC_COLUMNS = {
    "enrolled_years", "fees_amt", "pct_discount", "fees_paid", "pct_paid", "arpu",
}

# PII columns — masked in any user-facing output.
PII_COLUMNS = {"student_name", "regno"}

# Reference lists for the synthetic sample generator.
REGIONS_CENTERS = {
    "AP & TS": ["Vijayawada Vidyapeeth", "Vizag Vidyapeeth"],
    "Maharashtra": [
        "Mumbai - Thane Vidyapeeth", "Pune - JP Nagar Vidyapeeth",
        "Nagpur Vidyapeeth", "Nashik Vidyapeeth", "Latur Vidyapeeth",
    ],
    "South": ["Bengaluru - Vidyapeeth", "Chennai - Vidyapeeth", "Mysore Vidyapeeth"],
    "TC": ["Dombivali TC", "Pimple Saudagar TC", "Wardhman Nagar TC"],
}

CLASSES = ["8th", "9th", "10th", "11th JEE", "11th NEET", "12th JEE", "12th NEET",
           "Dropper JEE", "Dropper NEET"]

PAYMENT_MILESTONES = ["Token Only", "1st EMI Paid", "2nd EMI Paid", "3rd EMI Paid",
                      "4th EMI Paid", "Total Paid"]
