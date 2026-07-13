import corpus_tools.__main__ as main_mod
import corpus_tools.assess_run as assess_run_mod
import corpus_tools.ingest as ingest_mod
from corpus_tools.workspace import init_workspace


def _ws(tmp_path):
    ws_path = tmp_path / "ws"
    init_workspace(ws_path, "test")
    src = tmp_path / "in"
    src.mkdir()
    return ws_path, src


def test_main_ingest_exits_nonzero_on_errors(tmp_path, monkeypatch):
    ws_path, src = _ws(tmp_path)

    def fake_ingest_folder(ws, folder, limit=None):
        return {"sources_new": 0, "sources_skipped": 0, "pages": 0, "errors": ["boom"]}

    monkeypatch.setattr(ingest_mod, "ingest_folder", fake_ingest_folder)
    rc = main_mod.main(["ingest", str(src), "--workspace", str(ws_path)])
    assert rc == 1


def test_main_ingest_exits_zero_without_errors(tmp_path, monkeypatch):
    ws_path, src = _ws(tmp_path)

    def fake_ingest_folder(ws, folder, limit=None):
        return {"sources_new": 1, "sources_skipped": 0, "pages": 2, "errors": []}

    monkeypatch.setattr(ingest_mod, "ingest_folder", fake_ingest_folder)
    rc = main_mod.main(["ingest", str(src), "--workspace", str(ws_path)])
    assert rc == 0


def test_main_assess_exits_nonzero_on_errors(tmp_path, monkeypatch):
    ws_path, _ = _ws(tmp_path)

    def fake_assess_workspace(ws, limit=None, force=False):
        return {"assessed": 0, "errors": ["boom"]}

    monkeypatch.setattr(assess_run_mod, "assess_workspace", fake_assess_workspace)
    rc = main_mod.main(["assess", "--workspace", str(ws_path)])
    assert rc == 1


def test_main_assess_exits_zero_without_errors(tmp_path, monkeypatch):
    ws_path, _ = _ws(tmp_path)

    def fake_assess_workspace(ws, limit=None, force=False):
        return {"assessed": 3, "errors": []}

    monkeypatch.setattr(assess_run_mod, "assess_workspace", fake_assess_workspace)
    rc = main_mod.main(["assess", "--workspace", str(ws_path)])
    assert rc == 0


def test_gt_and_evaluate_cli(tmp_path, capsys):
    from test_evaluate import _ws
    from corpus_tools.__main__ import main

    ws = _ws(tmp_path)
    root = str(ws.root)

    assert main(["gt-status", "--workspace", root]) == 0
    out = capsys.readouterr().out
    assert "done: 3" in out

    assert main(["gt-sample", "--workspace", root, "--n", "2"]) == 0

    assert main(["evaluate", "--workspace", root, "--run", "run0"]) == 0
    out = capsys.readouterr().out
    assert "evaluated: 2" in out

    assert main(["eval-report", "--workspace", root, "--run", "run0"]) == 0
    assert (ws.reports_dir / "eval_run0.html").exists()
