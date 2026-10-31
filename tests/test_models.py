from claimcheck.models import Claim, Evidence, ReportType, Verdict, build_report, overall_verdict


def _ev(verdict: Verdict) -> Evidence:
    return Evidence(check="symbol_exists", verdict=verdict, summary="x")


def test_overall_any_refuted_wins():
    evidence = [_ev(Verdict.CONFIRMED), _ev(Verdict.REFUTED), _ev(Verdict.WARNING)]
    assert overall_verdict(evidence) == Verdict.REFUTED


def test_overall_warning_beats_confirmed():
    evidence = [_ev(Verdict.CONFIRMED), _ev(Verdict.WARNING)]
    assert overall_verdict(evidence) == Verdict.WARNING


def test_overall_confirmed_when_no_negative():
    evidence = [_ev(Verdict.CONFIRMED)]
    assert overall_verdict(evidence) == Verdict.CONFIRMED


def test_overall_inconclusive_when_empty():
    assert overall_verdict([]) == Verdict.INCONCLUSIVE


def test_build_report_sets_overall():
    claim = Claim(type=ReportType.BUG, raw_text="t", title="t")
    report = build_report(claim, [_ev(Verdict.REFUTED)])
    assert report.overall == Verdict.REFUTED
    assert report.evidence[0].verdict == Verdict.REFUTED
