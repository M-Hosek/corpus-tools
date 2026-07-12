import shutil

from corpus_tools.assess_run import assess_workspace
from corpus_tools.ingest import ingest_folder
from corpus_tools.report import write_assess_report
from corpus_tools.workspace import init_workspace


def test_report_written(tmp_path, sample_pdf):
    src = tmp_path / "in" / "kexue wenyi 1980.5"
    src.mkdir(parents=True)
    shutil.copy(sample_pdf, src / "0838_043.pdf")
    ws = init_workspace(tmp_path / "ws", "test")
    ingest_folder(ws, tmp_path / "in")
    assess_workspace(ws, limit=3)

    out = write_assess_report(ws)
    assert out.exists()
    html = out.read_text(encoding="utf-8")
    assert "quality_score" in html and "sources" in html
    assert list((ws.reports_dir / "thumbs").glob("*.jpg"))
