"""
patterns.py — Shared Regex Patterns for Ocean Freight Contract Extraction
=======================================================================
"""

from __future__ import annotations

import re


CONTRACT_ID_RX = re.compile(r"\b([A-Z]{2,5}\d{3,4}[A-Z]\d{2})\b")
CARRIER_PRIMARY_RX = re.compile(r'hereinafter\s+called\s+"([^"]+)"', re.I)
CARRIER_SECONDARY_RX = re.compile(r"between\s+([\w][\w\s,\.&\-]+?)\s+\(hereinafter", re.I)

# Section Transitions
ORIGIN_ARBIT_RX = re.compile(r"6-3\.?\s+ORIGIN\s+ARBIT", re.I)
DEST_ARBIT_RX = re.compile(r"6-4\.?\s+DEST(?:INATION)?\s+ARBIT", re.I)

# Context Labels
ORIGIN_VIA_SPLIT_RX = re.compile(r"\bORIGIN\s+VIA\s*:?\s*", re.I)
ORIGIN_VIA_RX = re.compile(r"^(?:\d+[\)\.]\s*)?ORIGIN\s+VIA\s*:?\s*(.*)", re.I | re.M)
ORIGIN_RX = re.compile(r"^(?:\d+[\)\.]\s*)?ORIGIN\s*:?\s*(.*)", re.I | re.M)
DEST_VIA_RX = re.compile(
    r"^(?:\d+[\)\.]\s*)?DEST(?:INATION)?\s+VIA\s*:?\s*(.*)", re.I | re.M
)
DEST_RX = re.compile(r"^(?:\d+[\)\.]\s*)?DEST(?:INATION)?\s*:?\s*(.*)", re.I | re.M)
COMMODITY_RX = re.compile(r"^(?:\d+[\)\.]\s*)?COMMODITY[^:]*:?\s*(.*)", re.I | re.M)
RATE_OVER_RX = re.compile(r"^RATE\s*APPLICABLE\s*OVER\s*:?\s*(.*)", re.I | re.M)
SCOPE_RX = re.compile(r"^\[([^\]]+)\]$", re.M)

# Dates
DATE_RANGE_COMPACT_RX = re.compile(r"\bvalid\s+from\s+(\d{8})\s+to\s+(\d{8})\b", re.I)
DATE_EXPIRY_COMPACT_RX = re.compile(r"\bvalid\s+to\s+(\d{8})\b", re.I)
DATE_RANGE_ISO_RX = re.compile(
    r"\bvalid\s+(\d{4}-\d{2}-\d{1,2})\s+to\s+(\d{4}-\d{2}-\d{1,2})\b", re.I
)
DATE_EFFECTIVE_HEADER_RX = re.compile(
    r"(?i)effective\s+date\s*:?\s*"
    r"(?:(\d{1,2})\s+([A-Za-z]+)|([A-Za-z]+)\s+(\d{1,2})),?\s*(\d{4})"
)
DATE_COMPACT_RX = re.compile(r"^(\d{4})(\d{2})(\d{2})$")
DATE_ISO_RX = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")

# Page furniture (running headers/footers) that must never be read as data or context
PAGE_BOILERPLATE_RX = re.compile(
    r"^(?:page\s+\d+(?:\s*(?:of|/)\s*\d+)?"
    r"|\d+\s*(?:of|/)\s*\d+"
    r"|-\s*\d+\s*-"
    r"|confidential\b.*)$",
    re.I,
)

# Table cells
AMOUNT_CELL_RX = re.compile(r"^[A-Z$€£¥]{0,3}\s*-?\d[\d,]*(?:\.\d+)?$", re.I)

# Cleaners
COMMODITY_TRUNC_RX = re.compile(r"\s*(?:ORIGIN|NOTE|REMARK|;)", re.IGNORECASE)
CITY_PAREN_STRIP_RX = re.compile(r"\s*\([^)]*\)\s*$")
WHITESPACE_RX = re.compile(r"\s+")
