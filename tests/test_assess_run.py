import shutil

from corpus_tools.assess_run import assess_workspace
from corpus_tools.ingest import ingest_folder
from corpus_tools.workspace import init_workspace


def test_assess_fills_metrics_and_is_resumable(tmp_path, sample_pdf):
    src = tmp_path / "in" / "kexue wenyi 1980.5"
    src.mkdir(parents=True)
    shutil.copy(sample_pdf, src / "0838_043.pdf")
    ws = init_workspace(tmp_path / "ws", "test")
    ingest_folder(ws, tmp_path / "in")

    stats = assess_workspace(ws, limit=2)
    assert stats["assessed"] == 2 and not stats["errors"]
    with ws.open_catalog() as cat:
        done = cat.iter_pages("assessed_at IS NOT NULL")
        assert len(done) == 2
        p = done[0]
        assert p["quality_score"] is not None
        assert p["contrast"] is not None and p["background_gray"] is not None
        assert p["script"] in ("simplified", "traditional", "unknown")

    again = assess_workspace(ws, limit=2)
    assert again["assessed"] == 2  # next two pages, resume not repeat
    with ws.open_catalog() as cat:
        assert len(cat.iter_pages("assessed_at IS NOT NULL")) == 4
