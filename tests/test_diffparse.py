"""Unit tests for ``src/claimcheck/diffparse.py``.

Covers: simple change, new file, deleted file, rename, multiple hunks,
binary files, "\ No newline at end of file", and edge cases.
"""

from __future__ import annotations

from claimcheck.diffparse import parse_unified_diff


# ---------------------------------------------------------------
# Helper: build a minimal unified-diff string
# ---------------------------------------------------------------
def _diff(*parts: str) -> str:
    """Concatenate diff ``lines`` (each part is a full line or empty)."""
    return "\n".join(parts)


# ---------------------------------------------------------------
# 1) Simple change (one file, one hunk, one added line)
# ---------------------------------------------------------------
def test_simple_change():
    diff = _diff(
        "diff --git a/calc.py b/calc.py",
        "index 83db48f..bf269f4 100644",
        "--- a/calc.py",
        "+++ b/calc.py",
        "@@ -1,3 +1,3 @@",
        " def add(a, b):",
        "+def sub(a, b):",
        " def sub(a, b):",
    )
    got = parse_unified_diff(diff)
    # hunk new_ln starts at 1; context line advances to 2; then + records 2
    assert got == {"calc.py": {2}}


# ---------------------------------------------------------------
# 2) New file
# ---------------------------------------------------------------
def test_new_file():
    diff = _diff(
        "diff --git a/new_script.py b/new_script.py",
        "--- /dev/null",
        "+++ b/new_script.py",
        "@@ -0,0 +1,2 @@",
        "+def hello():",
        " pass",
    )
    got = parse_unified_diff(diff)
    assert got == {"new_script.py": {1}}


# ---------------------------------------------------------------
# 3) Deleted file
# ---------------------------------------------------------------
def test_deleted_file():
    diff = _diff(
        "diff --git a/old_module.py b/old_module.py",
        "--- a/old_module.py",
        "+++ /dev/null",
        "@@ -1,2 +0,0 @@",
        "-def old_func():",
    )
    got = parse_unified_diff(diff)
    # deleted file → empty added‑lines set
    assert got == {"old_module.py": set()}


# ---------------------------------------------------------------
# 4) Rename
# ---------------------------------------------------------------
def test_rename():
    diff = _diff(
        "diff --git a/calc.py b/math_ops.py",
        "rename from: calc.py",
        "rename to: math_ops.py",
        "index a1b2c3d..e5f6g7h 100644",
        "--- a/calc.py",
        "+++ b/math_ops.py",
        "@@ -1,2 +1,2 @@",
        "-def add(a, b):",
        "+def add_int(a, b):",
    )
    got = parse_unified_diff(diff)
    # new file path is the ``b/`` side
    assert got == {"math_ops.py": {1}}


# ---------------------------------------------------------------
# 5) Multiple hunks in the same file
# ---------------------------------------------------------------
def test_multiple_hunks():
    diff = _diff(
        "diff --git a/math.py b/math.py",
        "index a..b 100644",
        "--- a/math.py",
        "+++ b/math.py",
        "@@ -1,2 +1,1 @@",
        "-a",
        "@@ -5,2 +5,2 @@",
        "+e",
        "+f",
    )
    got = parse_unified_diff(diff)
    # hunk 1 adds nothing (only deletion); hunk 2 adds lines at new 5 and 6
    assert got == {"math.py": {5, 6}}


# ---------------------------------------------------------------
# 6) Binary file
# ---------------------------------------------------------------
def test_binary():
    diff = _diff(
        "diff --git a/data.json b/data.json",
        "Binary files a/data.json and b/data.json differ",
    )
    got = parse_unified_diff(diff)
    assert got == {"data.json": set()}


# ---------------------------------------------------------------
# 7) "\ No newline at end of file"
# ---------------------------------------------------------------
def test_no_newline():
    diff = _diff(
        "diff --git a/layout.py b/layout.py",
        "index a..b 100644",
        "--- a/layout.py",
        "+++ b/layout.py",
        "@@ -1,3 +1,3 @@",
        " def render():",
        "+def render:",
        "\\ No newline at end of file",
    )
    got = parse_unified_diff(diff)
    # new_ln starts at 1; context advances to 2; + records 2
    assert got == {"layout.py": {2}}


# ---------------------------------------------------------------
# 8) Multiple files changed at once
# ---------------------------------------------------------------
def test_multiple_files():
    diff = _diff(
        "diff --git a/alpha.py b/alpha.py",
        "index a..b 100644",
        "--- a/alpha.py",
        "+++ b/alpha.py",
        "@@ -1,1 +1,2 @@",
        "+c",
        "diff --git a/beta.py b/beta.py",
        "index c..d 100644",
        "--- b/beta.py",
        "+++ c/beta.py",
        "@@ -1,1 +1,1 @@",
        "-x",
        "+y",
    )
    got = parse_unified_diff(diff)
    # first diff adds line 1 in alpha.py; second diff modifies beta.py
    assert got.get("alpha.py") == {1}


# ---------------------------------------------------------------
# 9) Mixed: some hunks with only deletions, some with additions
# ---------------------------------------------------------------
def test_mixed_hunks():
    diff = _diff(
        "diff --git a/status.py b/status.py",
        "index a..b 100644",
        "--- a/status.py",
        "+++ b/status.py",
        "@@ -1,3 +1,3 @@",
        "-old1",
        "+new1",
        "@@ -10,3 +10,3 @@",
        "-old2",
        # no + lines in this hunk → nothing added
        "@@ -20,1 +20,1 @@",
        "+new3",
    )
    got = parse_unified_diff(diff)
    # first hunk new_ln starts at 1; +new1 records 1; second hunk new_ln=20; +new3 records 20
    assert got == {"status.py": {1, 20}}


# ---------------------------------------------------------------
# 10) Edge: empty diff
# ---------------------------------------------------------------
def test_empty_diff():
    got = parse_unified_diff("")
    assert got == {}


# ---------------------------------------------------------------
# 11) Edge: only context lines, no additions
# ---------------------------------------------------------------
def test_only_context():
    diff = _diff(
        "diff --git a/quiet.py b/quiet.py",
        "index a..b 100644",
        "--- a/quiet.py",
        "+++ b/quiet.py",
        "@@ -1,2 +1,2 @@",
        "def quiet():",
        " pass",
    )
    got = parse_unified_diff(diff)
    assert got == {"quiet.py": set()}


# ---------------------------------------------------------------
# 12) Edge: added line number starts at 1 in new file (new file case)
# ---------------------------------------------------------------
def test_new_file_line_numbering():
    diff = _diff(
        "diff --git a/brand_new.py b/brand_new.py",
        "--- /dev/null",
        "+++ b/brand_new.py",
        "@@ -0,0 +1,1 @@",
        "+only line",
    )
    got = parse_unified_diff(diff)
    assert got == {"brand_new.py": {1}}


# ---------------------------------------------------------------
# 13) Realistic PR‑like diff with several files and hunks
# ---------------------------------------------------------------
def test_pr_like_diff():
    diff = _diff(
        "diff --git a/views.py b/views.py",
        "index a..b 100644",
        "--- a/views.py",
        "+++ b/views.py",
        "@@ -1,3 +1,4 @@",
        " def home():",
        " pass",
        "+def about():",
        " pass",
        "diff --git a/models.py b/models.py",
        "index c..d 100644",
        "--- a/models.py",
        "+++ b/models.py",
        "@@ -1,2 +1,3 @@",
        "class Foo:",
        "+class Bar:",
        "+class Baz:",
    )
    got = parse_unified_diff(diff)
    assert got == {
        "views.py": {3},       # +def about(): is new line 3 in the new file (after 2 context lines)
        "models.py": {1, 2},   # +class Bar: is new 1, +class Baz: is new 2
    }