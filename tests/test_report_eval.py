import pytest

from corpus_tools.evaluate import evaluate_run
from corpus_tools.report_eval import write_eval_report

# reuse the workspace builder from the evaluate tests
from test_evaluate import _ws


def test_eval_report_written(tmp_path):
    ws = _ws(tmp_path)
    evaluate_run(ws, "run0")
    out = write_eval_report(ws, "run0")
    html_text = out.read_text(encoding="utf-8")
    assert out.name == "eval_run0.html"
    assert "median CER" in html_text
    assert "ab1234-p002L" in html_text


def test_eval_report_no_evaluations_raises(tmp_path):
    ws = _ws(tmp_path)
    with pytest.raises(ValueError):
        write_eval_report(ws, "nope")
