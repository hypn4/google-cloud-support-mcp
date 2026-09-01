"""The write guard must actually refuse — otherwise it is decoration.

Lives in unit tests on purpose: it validates the safety mechanism itself, so it
must run on every `pytest` invocation rather than only when credentials exist.
"""

import pytest

from tests.integration.conftest import assert_test_case_only


class _Case:
    def __init__(self, test_case: bool) -> None:
        self.test_case = test_case


class _Request:
    def __init__(self, case) -> None:
        self.case = case


def test_rejects_a_case_without_the_test_flag():
    with pytest.raises(AssertionError, match="test_case=True"):
        assert_test_case_only(_Request(_Case(False)))


def test_rejects_a_request_with_no_case_at_all():
    with pytest.raises(AssertionError):
        assert_test_case_only(_Request(None))


def test_allows_a_flagged_test_case():
    assert_test_case_only(_Request(_Case(True)))
