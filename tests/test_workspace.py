import pytest
import yaml

from corpus_tools.workspace import init_workspace, load_workspace


def test_init_creates_layout(tmp_path):
    ws = init_workspace(tmp_path / "ws", "kexue-wenyi")
    for sub in ["originals", "pages", "preprocessed", "ocr/runs",
                "ground_truth", "reports", "rebuilt"]:
        assert (ws.root / sub).is_dir()
    assert ws.catalog_path.exists()
    cfg = yaml.safe_load((ws.root / "workspace.yaml").read_text(encoding="utf-8"))
    assert cfg["corpus_name"] == "kexue-wenyi"
    with ws.open_catalog() as cat:
        assert cat.count("pages") == 0


def test_init_idempotent(tmp_path):
    init_workspace(tmp_path / "ws", "kexue-wenyi")
    ws = init_workspace(tmp_path / "ws", "ignored-second-name")
    cfg = yaml.safe_load((ws.root / "workspace.yaml").read_text(encoding="utf-8"))
    assert cfg["corpus_name"] == "kexue-wenyi"


def test_load_requires_existing(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_workspace(tmp_path / "missing")
    init_workspace(tmp_path / "ws", "x")
    ws = load_workspace(tmp_path / "ws")
    assert ws.run_dir("run0") == ws.root / "ocr" / "runs" / "run0"
