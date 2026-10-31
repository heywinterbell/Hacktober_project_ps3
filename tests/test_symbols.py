from claimcheck.checks.symbols import check_symbol, check_symbols, find_definitions
from claimcheck.models import Claim, ReportType, Verdict


def test_find_definitions_parse_url(sample_project):
    defs = find_definitions(sample_project, "parse_url")
    assert len(defs) == 1
    assert defs[0].file.endswith("urls.py")
    assert defs[0].line > 0


def test_check_symbol_confirmed(sample_project):
    ev = check_symbol(sample_project, "parse_url")
    assert ev.verdict == Verdict.CONFIRMED
    assert ev.check == "symbol_exists"
    assert "parse_url" in ev.summary
    assert ev.sandboxed is False


def test_check_symbol_refuted_with_suggestion(sample_project):
    ev = check_symbol(sample_project, "parse_url_v2")
    assert ev.verdict == Verdict.REFUTED
    assert "parse_url" in ev.details["did_you_mean"]


def test_check_symbols_for_claim(sample_project):
    claim = Claim(
        type=ReportType.SECURITY,
        raw_text="x",
        title="x",
        symbols=["parse_url", "parse_url_v2"],
    )
    evidence = check_symbols(sample_project, claim)
    assert [e.verdict for e in evidence] == [Verdict.CONFIRMED, Verdict.REFUTED]


def test_find_nested_method(sample_project):
    defs = find_definitions(sample_project, "fetch")
    assert len(defs) == 1
    assert defs[0].qualname == "UrlClient.fetch"
    assert defs[0].file.endswith("urls.py")


def test_check_nested_method_confirmed(sample_project):
    ev = check_symbol(sample_project, "fetch")
    assert ev.verdict == Verdict.CONFIRMED
    assert ev.details["locations"][0]["qualname"] == "UrlClient.fetch"


def test_syntax_error_file_skipped_safely(tmp_path):
    (tmp_path / "broken.py").write_text("def oops(:\n", encoding="utf-8")
    (tmp_path / "good.py").write_text("def healthy():\n    return 1\n", encoding="utf-8")
    # found path: broken file skipped, good file found
    defs = find_definitions(tmp_path, "healthy")
    assert len(defs) == 1
    assert defs[0].file == "good.py"
    # miss path: did-you-mean still works with a broken file present
    ev = check_symbol(tmp_path, "healthyy")
    assert ev.verdict == Verdict.REFUTED
    assert ev.details["did_you_mean"] == ["healthy"]


def test_binary_file_skipped_safely(tmp_path):
    (tmp_path / "data.py").write_bytes(b"\xff\xfe\x00 not python \x80\x81")
    (tmp_path / "good.py").write_text("def healthy():\n    return 1\n", encoding="utf-8")
    defs = find_definitions(tmp_path, "healthy")
    assert len(defs) == 1
