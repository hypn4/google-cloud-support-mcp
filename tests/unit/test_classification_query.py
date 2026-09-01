"""The classification filter expression, learned from the live API.

Passing raw keywords fails with "Function operators are not supported" — the
field is a filter expression, and display names are hierarchical paths, so only
a substring glob is useful. Verified against the real service on 2026-09-01.
"""

import pytest

from google_cloud_support_mcp.tools.classifications import build_classification_query


@pytest.mark.parametrize(
    ("keywords", "expected"),
    [
        ("Compute Engine", 'display_name:"*Compute Engine*"'),
        ("  Compute   Engine  ", 'display_name:"*Compute Engine*"'),
        ("BigQuery", 'display_name:"*BigQuery*"'),
    ],
)
def test_keywords_become_a_substring_glob(keywords, expected):
    assert build_classification_query(keywords) == expected


def test_empty_input_stays_empty():
    """An empty query returns the whole catalogue; a glob of nothing would not."""
    assert build_classification_query("") == ""
    assert build_classification_query("   ") == ""


def test_quotes_cannot_break_out_of_the_expression():
    assert '""' not in build_classification_query('Compute "Engine"')
    assert build_classification_query('Compute "Engine"') == 'display_name:"*Compute Engine*"'
