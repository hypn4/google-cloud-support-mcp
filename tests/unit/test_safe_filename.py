"""`Attachment.filename` is remote input, and it is joined to a local directory.

Every case here is an input the Cloud Support API could return. The joins were
run to confirm the untreated behaviour before the guard existed: `directory /
"/etc/passwd"` yields `/etc/passwd`, discarding the directory entirely, and
`..\\..\\x` is one harmless filename on POSIX but a two-level traversal on
Windows. The point of the table is that the same input is now inert on both.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from google_cloud_support_mcp.media import _MAX_NAME_BYTES, safe_filename, unique_path


class TestOrdinaryNamesSurvive:
    """The guard must not damage the names people actually attach."""

    @pytest.mark.parametrize(
        "name",
        [
            "diag.log",
            "data (1).csv",
            "screenshot 2026-01-01.png",
            "rapport-final.pdf",
            "  spaced.txt",  # only *trailing* space is meaningful to Windows
            ".gitignore",  # leading dot is not a trailing dot
            "archive.tar.gz",
            "報告書.pdf",  # non-ASCII is left alone
            "CONTRACT.pdf",  # starts with CON but is not the reserved name
        ],
    )
    def test_passes_through_unchanged(self, name):
        assert safe_filename(name) == name


class TestEscapeIsNeutralised:
    @pytest.mark.parametrize(
        ("hostile", "expected"),
        [
            # Absolute paths are the sharpest case: joining one *replaces* the
            # base directory rather than extending it.
            ("/etc/passwd", "passwd"),
            ("/etc/cron.d/evil", "evil"),
            # Ordinary traversal.
            ("../../etc/x", "x"),
            ("../../../root/.ssh/authorized_keys", "authorized_keys"),
            # Inert on POSIX, a real traversal on Windows.
            ("..\\..\\x", "x"),
            ("..\\..\\Windows\\System32\\drivers\\etc\\hosts", "hosts"),
            # Mixed separators, so neither split alone is sufficient.
            ("../..\\x", "x"),
            ("a/b\\c", "c"),
            # Drive-relative: "C:evil" means "evil in the current directory of
            # drive C" on Windows. The colon is dropped rather than treated as a
            # separator — equally safe, and it keeps more of a real filename
            # ("report:v2.pdf" becomes "reportv2.pdf", not "v2.pdf"). Dropping it
            # also defuses NTFS alternate data streams for free.
            ("C:evil", "Cevil"),
            ("file.txt:hidden", "file.txthidden"),
            # Bare traversal tokens reduce to nothing and take the fallback.
            ("..", "attachment"),
            (".", "attachment"),
            ("...", "attachment"),
            ("/", "attachment"),
            ("../", "attachment"),
            # Empty and missing.
            ("", "attachment"),
            (None, "attachment"),
            ("   ", "attachment"),
        ],
    )
    def test_reduces_to_a_single_harmless_component(self, hostile, expected):
        assert safe_filename(hostile) == expected

    @pytest.mark.parametrize(
        "hostile",
        [
            "/etc/passwd",
            "../../etc/x",
            "..\\..\\x",
            "C:evil",
            "..",
            "a/b\\c",
        ],
    )
    def test_result_is_always_one_component(self, hostile):
        out = safe_filename(hostile)
        assert "/" not in out and "\\" not in out
        assert Path(out).name == out
        assert not Path(out).is_absolute()


class TestHostileCharacters:
    def test_nul_and_control_characters_are_dropped(self):
        # A NUL truncates the path at the OS boundary regardless of what Python
        # thinks the string is.
        assert safe_filename("evil\x00.log") == "evil.log"
        assert safe_filename("a\nb\tc.log") == "abc.log"

    def test_windows_forbidden_characters_are_dropped(self):
        assert safe_filename('a<b>c:d"e|f?g*h.log') == "abcdefgh.log"

    def test_trailing_dots_and_spaces_go(self):
        # Windows drops these silently, so "x. " and "x" are the same file there.
        assert safe_filename("file.txt.") == "file.txt"
        assert safe_filename("file.txt   ") == "file.txt"
        assert safe_filename("file.txt . . ") == "file.txt"

    @pytest.mark.parametrize("reserved", ["CON", "NUL", "AUX", "COM1", "LPT9", "con.txt"])
    def test_windows_device_names_are_defused(self, reserved):
        out = safe_filename(reserved)
        assert out != reserved
        assert out.partition(".")[0].upper() not in {"CON", "NUL", "AUX", "COM1", "LPT9"}


class TestLength:
    def test_long_names_are_capped_in_bytes_keeping_the_extension(self):
        out = safe_filename("a" * 500 + ".log")
        assert len(out.encode()) <= _MAX_NAME_BYTES
        assert out.endswith(".log")

    def test_multibyte_names_are_capped_by_bytes_not_characters(self):
        # 300 characters is only 300 bytes in ASCII but 900 in UTF-8, so a
        # character-based cap would sail past the filesystem limit here.
        out = safe_filename("é" * 300 + ".log")
        assert len(out.encode()) <= _MAX_NAME_BYTES
        assert out.endswith(".log")
        # Truncation must not leave a broken character behind.
        out.encode().decode()

    def test_a_long_name_with_no_extension_is_still_capped(self):
        out = safe_filename("z" * 500)
        assert len(out.encode()) <= _MAX_NAME_BYTES


class TestUniquePathContainment:
    """`unique_path` is where the sanitised name meets the filesystem."""

    @pytest.mark.parametrize(
        "hostile",
        ["/etc/passwd", "../../etc/x", "..\\..\\x", "..", "C:evil", ""],
    )
    def test_the_result_stays_inside_the_destination(self, hostile, tmp_path):
        target = unique_path(tmp_path, hostile)
        assert target.resolve().is_relative_to(tmp_path.resolve())
        assert target.parent.resolve() == tmp_path.resolve()

    def test_a_traversal_cannot_reach_a_sibling_directory(self, tmp_path):
        downloads = tmp_path / "downloads"
        secret = tmp_path / "secret.txt"
        secret.write_bytes(b"original")

        target = unique_path(downloads, "../secret.txt")

        assert target.parent.resolve() == downloads.resolve()
        assert target.name == "secret.txt"
        assert secret.read_bytes() == b"original"

    def test_collision_suffixes_stay_inside_too(self, tmp_path):
        (tmp_path / "passwd").write_bytes(b"first")
        target = unique_path(tmp_path, "/etc/passwd")
        assert target.parent.resolve() == tmp_path.resolve()
        assert target.name != "passwd"
        assert (tmp_path / "passwd").read_bytes() == b"first"
