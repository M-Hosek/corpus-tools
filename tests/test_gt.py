from corpus_tools.gt import scaffold_sample, sync_gt_status
from corpus_tools.workspace import init_workspace


def _ws_with_pages(tmp_path, n_pages=6):
    ws = init_workspace(tmp_path / "ws", "t")
    run_dir = ws.run_dir("run0")
    run_dir.mkdir(parents=True, exist_ok=True)
    with ws.open_catalog() as cat:
        cat.add_run({"run_id": "run0", "engine": "embedded", "engine_version": None,
                     "params_json": "{}", "recipe": None, "created_at": "t"})
        for i in range(1, n_pages + 1):
            pid = f"ab1234-p{i:03d}L"
            cat.add_page({"page_id": pid, "source_id": "ab1234ffff",
                          "pdf_page_index": i, "side": "L",
                          "image_path": f"pages/{pid}.png",
                          "width_px": 100, "height_px": 150})
            cat.update_page(pid, {"quality_score": 0.3 + 0.1 * i,
                                  "script": "simplified",
                                  "issue_label": "1979.1",
                                  "assessed_at": "t"})
            txt = run_dir / f"{pid}.txt"
            txt.write_text(f"run0 text {i}", encoding="utf-8")
            cat.add_run_page({"run_id": "run0", "page_id": pid,
                              "text_path": f"ocr/runs/run0/{pid}.txt",
                              "char_count": 10, "confidence": None})
    return ws


def test_scaffold_writes_drafts_and_catalog_rows(tmp_path):
    ws = _ws_with_pages(tmp_path)
    stats = scaffold_sample(ws, n=3, seed=1)
    assert stats["selected"] == 3 and stats["drafts_written"] == 3
    with ws.open_catalog() as cat:
        rows = cat.iter_gt_pages(status="selected")
    assert len(rows) == 3
    pid = rows[0]["page_id"]
    draft = ws.gt_drafts_dir / f"{pid}.txt"
    assert draft.read_text(encoding="utf-8").startswith("run0 text")
    assert (ws.gt_drafts_dir / f"{pid}.notes.md").exists()


def test_scaffold_is_additive_and_preserves_edits(tmp_path):
    ws = _ws_with_pages(tmp_path)
    scaffold_sample(ws, n=3, seed=1)
    with ws.open_catalog() as cat:
        pid = cat.iter_gt_pages()[0]["page_id"]
    (ws.gt_drafts_dir / f"{pid}.txt").write_text("my edits", encoding="utf-8")
    stats = scaffold_sample(ws, n=3, seed=1)
    assert stats["selected"] == 0 and stats["already"] == 3
    assert (ws.gt_drafts_dir / f"{pid}.txt").read_text(encoding="utf-8") == "my edits"


def test_sync_marks_done_and_adopts(tmp_path):
    ws = _ws_with_pages(tmp_path)
    scaffold_sample(ws, n=2, seed=1)
    with ws.open_catalog() as cat:
        pid = cat.iter_gt_pages()[0]["page_id"]
    (ws.ground_truth_dir / f"{pid}.txt").write_text("最终文本", encoding="utf-8")
    # an ad-hoc final file for a page never sampled
    (ws.ground_truth_dir / "ab1234-p006L.txt").write_text("adopted", encoding="utf-8")
    stats = sync_gt_status(ws)
    assert stats["done"] == 2 and stats["adopted"] == 1
    with ws.open_catalog() as cat:
        assert cat.get_gt_page(pid)["status"] == "done"
        assert cat.get_gt_page(pid)["completed_at"]
        assert cat.get_gt_page("ab1234-p006L")["status"] == "done"


def test_sync_ignores_empty_final_files(tmp_path):
    ws = _ws_with_pages(tmp_path)
    scaffold_sample(ws, n=1, seed=1)
    with ws.open_catalog() as cat:
        pid = cat.iter_gt_pages()[0]["page_id"]
    (ws.ground_truth_dir / f"{pid}.txt").write_text("  \n", encoding="utf-8")
    stats = sync_gt_status(ws)
    assert stats["done"] == 0
