"""Base HTML parsing utilities shared across all parsers."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag


def parse_html(html: str, parser: str = "lxml") -> BeautifulSoup:
    """Parse an HTML string and return a BeautifulSoup document.

    Args:
        html: Raw HTML content from the switch response.
        parser: Parser library to use (default: ``lxml``).

    Returns:
        Parsed BeautifulSoup document.
    """
    return BeautifulSoup(html, parser)


def normalize_text(s: str) -> str:
    """Strip surrounding whitespace and collapse internal runs.

    Args:
        s: Raw text extracted from an HTML element.

    Returns:
        Cleaned string with single spaces between words.
    """
    return re.sub(r"\s+", " ", s).strip()


def find_table_with_headers(
    soup: BeautifulSoup,
    required_headers: list[str],
) -> Tag | None:
    """Return the first ``<table>`` whose header row contains all
    *required_headers* (case-insensitive substring match).

    Args:
        soup: Parsed document.
        required_headers: List of header texts that must all be present.

    Returns:
        Matching ``<table>`` tag, or ``None`` if not found.
    """
    lowered = [h.lower() for h in required_headers]
    for table in soup.find_all("table"):
        header_texts = [
            normalize_text(th.get_text()).lower()
            for th in table.find_all("th")
        ]
        if all(any(req in ht for ht in header_texts) for req in lowered):
            return table
    return None
