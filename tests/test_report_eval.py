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


def test_eval_report_calibration_section(tmp_path):
    ws = _ws(tmp_path)
    # give the third fixture page run text so it evaluates too
    (ws.run_dir("run0") / "ab1234-p003L.txt").write_text("科学文", encoding="utf-8")
    with ws.open_catalog() as cat:
        cat.add_run_page({"run_id": "run0", "page_id": "ab1234-p003L",
                          "text_path": "ocr/runs/run0/ab1234-p003L.txt",
                          "char_count": 3, "confidence": None})
        for i, q in [(1, 0.9), (2, 0.4), (3, 0.6)]:
            cat.update_page(f"ab1234-p{i:03d}L", {"quality_score": q})
    stats = evaluate_run(ws, "run0")
    assert stats["evaluated"] == 3
    html_text = write_eval_report(ws, "run0").read_text(encoding="utf-8")
    assert "Pearson r" in html_text
    assert "n/a" not in html_text          # numeric r actually computed
    assert "0.900" in html_text and "0.400" in html_text and "0.600" in html_text
