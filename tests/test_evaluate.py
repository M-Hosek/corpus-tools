import json

from corpus_tools.evaluate import evaluate_run
from corpus_tools.workspace import init_workspace


def _ws(tmp_path):
    ws = init_workspace(tmp_path / "ws", "t")
    run_dir = ws.run_dir("run0")
    run_dir.mkdir(parents=True, exist_ok=True)
    with ws.open_catalog() as cat:
        cat.add_run({"run_id": "run0", "engine": "embedded", "engine_version": None,
                     "params_json": "{}", "recipe": None, "created_at": "t"})
        for i, hyp in [(1, "科学文艺"), (2, "科字文艺"), (3, None)]:
            pid = f"ab1234-p{i:03d}L"
            cat.add_page({"page_id": pid, "source_id": "s", "pdf_page_index": i,
                          "side": "L", "image_path": None,
                          "width_px": 1, "height_px": 1})
            cat.upsert_gt_page({"page_id": pid, "stratum": None, "status": "done",
                                "selected_at": "t", "completed_at": "t"})
            (ws.ground_truth_dir / f"{pid}.txt").write_text("科学文艺", encoding="utf-8")
            if hyp is not None:
                (run_dir / f"{pid}.txt").write_text(hyp, encoding="utf-8")
                cat.add_run_page({"run_id": "run0", "page_id": pid,
                                  "text_path": f"ocr/runs/run0/{pid}.txt",
                                  "char_count": len(hyp), "confidence": None})
    return ws


def test_evaluate_run_records_cer(tmp_path):
    ws = _ws(tmp_path)
    stats = evaluate_run(ws, "run0")
    assert stats["evaluated"] == 2
    assert stats["skipped"] == ["ab1234-p003L"]  # no run text
    with ws.open_catalog() as cat:
        perfect = cat.get_evaluation("run0", "ab1234-p001L", "cer")
        onesub = cat.get_evaluation("run0", "ab1234-p002L", "cer")
    assert perfect["value"] == 0.0
    assert onesub["value"] == 0.25
    assert json.loads(onesub["details_json"])["sub"] == 1


def test_evaluate_run_is_rerunnable(tmp_path):
    ws = _ws(tmp_path)
    evaluate_run(ws, "run0")
    # fix the GT, re-evaluate: value must update, no duplicate rows
    (ws.ground_truth_dir / "ab1234-p002L.txt").write_text("科字文艺", encoding="utf-8")
    stats = evaluate_run(ws, "run0")
    assert stats["evaluated"] == 2
    with ws.open_catalog() as cat:
        assert cat.get_evaluation("run0", "ab1234-p002L", "cer")["value"] == 0.0
        assert cat.count("evaluations") == 2
