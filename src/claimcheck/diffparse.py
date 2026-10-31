"""Unified-diff parser used by PR coverage check.

Returns ``{filepath: set(added_line_numbers)}`` — 1-indexed line numbers
in the *new* file where ``+`` lines appear.  Binary files, deleted files
and rename metadata are handled; callers exclude test/non‑code paths.
"""

from __future__ import annotations

import re
from typing import Dict, Set

#: Regex for a hunk header: @@ -old_start[,old_count] +new_start[,new_count] @@
_HUNK_RE = re.compile(
    r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@"
)


def _strip_prefix(path: str) -> str:
    """Remove leading ``a/`` or ``b/`` (or ``/dev/null``) from a git diff path."""
    p = path.strip("/")
    if p.startswith("a/"):
        p = p[2:]
    if p.startswith("b/"):
        p = p[2:]
    return p


def parse_unified_diff(diff_text: str) -> Dict[str, Set[int]]:
    """Parse a unified diff and return ``{filepath: set(added_line_numbers)}``.

    * ``filepath`` is the new‑file path (``b/`` side of ``diff --git``).
    * Each integer is a 1‑indexed line number in the new file where a ``+``
      line occurs (i.e. an added line).
    * Binary files, deleted files and renames are handled; the returned dict
      may contain entries with empty sets for those cases.
    """
    result: Dict[str, Set[int]] = {}

    lines = diff_text.splitlines()
    i = 0
    current_path: str | None = None
    current_added: Set[int] = set()
    in_hunk = False
    new_ln = 0  # 1‑indexed line number in the new file
    old_ln = 0
    is_binary = False
    is_deleted = False
    is_new = False

    while i < len(lines):
        line = lines[i]
        i += 1

        # --------------------------------------------------------------
        # 1) Start of a new diff ------------------------------------------------
        # --------------------------------------------------------------
        if line.startswith("diff --git"):
            # finalize previous file
            if current_path is not None:
                result[current_path] = current_added

            # parse a / b paths from the line:  diff --git a/x b/y
            # we allow quoted paths; strip surrounding quotes if present
            parts = line.split()
            a_path = "/dev/null"
            b_path = "/dev/null"
            # find the a/ and b/ tokens; they may be quoted
            for token in parts:
                if token.startswith("a/"):
                    a_path = token[2:]  # strip a/
                elif token.startswith("b/"):
                    b_path = token[2:]  # strip b/

            # determine file kind
            is_new = a_path == "/dev/null"
            is_deleted = b_path == "/dev/null"
            # normal case: both sides are real paths
            current_path = _strip_prefix(b_path)
            current_added = set()
            in_hunk = False
            new_ln = 0
            old_ln = 0
            is_binary = False

            # if the diff marker says "Binary", skip straight to next diff
            # (the very next line may be "Binary files ... differ")
            if "Binary" in line or "GIT binary patch" in line:
                is_binary = True
                # we will skip hunk processing until the next diff --git
                # current_path already set; current_added stays empty
                # just continue to next line
                continue

            # if new file or deleted file, we still need to process any following
            # hunks (new file may have + lines; deleted file should have none).
            # No further special handling needed here.

            continue

        # --------------------------------------------------------------
        # 2) If we already saw a binary marker, skip everything until next diff --git
        # --------------------------------------------------------------
        if is_binary:
            # The binary line may have appeared right after diff --git; if we are
            # still in the binary block, keep skipping.  When we hit the next
            # diff --git we reset state.
            if not line.startswith("diff --git") and not line.startswith("\t") and not line.startswith(" "):
                # also skip lines that look like they belong to the binary block;
                # but we simplify: just ignore everything until next diff marker.
                continue
            # If we see diff --git, fall through to reset state below
            # (the `continue` at the top of the loop will re-evaluate).
            # Fall through by not continuing.

        # --------------------------------------------------------------
        # 3) New file mode / deleted file mode markers -------------------------
        # --------------------------------------------------------------
        if line.startswith("new file mode") or line.startswith("deleted file mode"):
            # these markers just confirm the kind; path already resolved from
            # diff --git.  Do nothing special.
            continue

        # --------------------------------------------------------------
        # 4) Hunk header ------------------------------------------------------
        # --------------------------------------------------------------
        hunk_match = _HUNK_RE.match(line)
        if hunk_match and not is_binary:
            in_hunk = True
            # new_start is the first group
            new_ln = int(hunk_match.group(1))
            old_ln = 0
            # Reset added set for this hunk; we'll accumulate across hunks.
            # (The caller may want per‑hunk data, but the spec returns the union.)
            # We keep a running union in current_added.
            continue

        # --------------------------------------------------------------
        # 5) Inside a hunk ----------------------------------------------------
        # --------------------------------------------------------------
        if in_hunk:
            if line.startswith("+"):
                # added line — record its new‑file line number
                current_added.add(new_ln)
                new_ln += 1
            elif line.startswith("-"):
                # deleted line — do NOT advance new_ln
                old_ln += 1
            elif line.startswith(" "):
                # context line — both old and new advance
                old_ln += 1
                new_ln += 1
            elif line.startswith("\\"):
                # "\ No newline at end of file" — skip, don't change counters
                pass
            # Lines starting with "+++" or "---" inside a hunk are added/deleted
            # lines whose content begins with '+' or '-'; our simple rule already
            # treats any leading '+' as added and any leading '-' as deleted, which
            # matches the vast majority of real‑world diffs.

        # --------------------------------------------------------------
        # 6) End of this diff — next iteration will hit diff --git and finalize
        # --------------------------------------------------------------
        # (handled at the top of the while loop)

    # finalize last file
    if current_path is not None:
        result[current_path] = current_added

    return result