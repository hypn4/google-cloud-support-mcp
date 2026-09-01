"""fanout.py — cross-org 팬아웃의 복합 커서와 부분 실패 수집 (research.md R-004)."""

import asyncio

import pytest
from google.api_core import exceptions as gexc

from google_cloud_support_mcp.errors import ErrorKind
from google_cloud_support_mcp.fanout import (
    CursorError,
    decode_cursor,
    encode_cursor,
    fanout_list,
)

P1, P2, P3 = "projects/a", "organizations/b", "projects/c"


class TestCompositeCursor:
    def test_roundtrip(self):
        cursors = {P1: "tok-a", P2: "tok-b"}
        assert decode_cursor(encode_cursor(cursors), {P1, P2}) == cursors

    def test_exhausted_parent_is_preserved_as_none(self):
        cursors = {P1: "tok-a", P2: None}
        assert decode_cursor(encode_cursor(cursors), {P1, P2}) == cursors

    def test_all_exhausted_issues_no_cursor(self):
        assert encode_cursor({P1: None, P2: None}) is None

    def test_rejects_corrupt_base64(self):
        with pytest.raises(CursorError):
            decode_cursor("!!!not-base64!!!", {P1})

    def test_rejects_unknown_version(self):
        import base64
        import json

        raw = base64.urlsafe_b64encode(json.dumps({"v": 99, "cursors": {P1: "t"}}).encode())
        with pytest.raises(CursorError):
            decode_cursor(raw.decode(), {P1})

    def test_rejects_parent_set_mismatch(self):
        """페이지 중간에 범위가 바뀌면 결과가 조용히 어긋난다 — 거부해야 한다."""
        token = encode_cursor({P1: "tok-a", P2: "tok-b"})
        with pytest.raises(CursorError):
            decode_cursor(token, {P1, P3})


class TestFanoutMerge:
    async def test_merges_results_from_every_parent(self):
        async def fetch(parent, page_token, page_size):
            return [f"{parent}-1", f"{parent}-2"], None

        env = await fanout_list([P1, P2], page_size=10, cursor=None, fetch=fetch)
        assert len(env.items) == 4
        assert set(env.scopes_queried) == {P1, P2}
        assert env.scopes_failed == []
        assert env.next_cursor is None
        assert env.truncated is False

    async def test_one_denied_parent_does_not_fail_the_call(self):
        """R-004b: 가장 흔한 회귀. 한 parent 의 403 이 전체를 죽이면 안 된다."""

        async def fetch(parent, page_token, page_size):
            if parent == P2:
                raise gexc.PermissionDenied("Permission denied on resource.")
            return [f"{parent}-1"], None

        env = await fanout_list([P1, P2, P3], page_size=10, cursor=None, fetch=fetch)
        assert len(env.items) == 2
        assert {f.parent for f in env.scopes_failed} == {P2}
        assert env.scopes_failed[0].reason is ErrorKind.PERMISSION_DENIED
        assert env.scopes_failed[0].retryable is False
        assert set(env.scopes_queried) == {P1, P2, P3}

    async def test_truncated_and_cursor_when_more_remains(self):
        async def fetch(parent, page_token, page_size):
            return [f"{parent}-1"], "next-tok" if parent == P1 else None

        env = await fanout_list([P1, P2], page_size=1, cursor=None, fetch=fetch)
        assert env.truncated is True
        assert env.next_cursor is not None
        assert decode_cursor(env.next_cursor, {P1, P2}) == {P1: "next-tok", P2: None}

    async def test_exhausted_parent_is_not_called_again(self):
        called = []

        async def fetch(parent, page_token, page_size):
            called.append(parent)
            return [], None

        cursor = encode_cursor({P1: "tok", P2: None})
        await fanout_list([P1, P2], page_size=10, cursor=cursor, fetch=fetch)
        assert called == [P1], "소진된 parent 를 다시 호출하면 안 된다"

    async def test_concurrency_is_bounded(self):
        live, peak = 0, 0

        async def fetch(parent, page_token, page_size):
            nonlocal live, peak
            live += 1
            peak = max(peak, live)
            await asyncio.sleep(0.01)
            live -= 1
            return [], None

        parents = [f"projects/p{i}" for i in range(10)]
        await fanout_list(parents, page_size=10, cursor=None, fetch=fetch, concurrency=3)
        assert peak <= 3
