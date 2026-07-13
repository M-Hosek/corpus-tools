from corpus_tools.sampling import quality_band, stratified_sample, stratum


def _page(pid, q, script="simplified", issue="1979.1"):
    return {"page_id": pid, "quality_score": q, "script": script,
            "issue_label": issue, "source_id": "ca4071deadbeef"}


def test_quality_band_edges():
    assert quality_band(0.49) == "low"
    assert quality_band(0.5) == "mid"
    assert quality_band(0.75) == "high"


def test_stratum_label():
    assert stratum(_page("a-p1L", 0.9)) == "1979.1|simplified|high"
    assert stratum(_page("a-p1L", 0.9, script=None, issue=None)) == "ca4071|unknown|high"


def test_sample_is_deterministic_and_sized():
    pages = [_page(f"a-p{i:03d}L", 0.2 + 0.007 * i) for i in range(100)]
    s1 = stratified_sample(pages, n=10, seed=42)
    s2 = stratified_sample(pages, n=10, seed=42)
    assert [p["page_id"] for p in s1] == [p["page_id"] for p in s2]
    assert len(s1) == 10
    assert all("stratum" in p for p in s1)


def test_sample_covers_every_stratum():
    pages = ([_page(f"a-p{i:03d}L", 0.3) for i in range(50)]
             + [_page(f"b-p{i:03d}L", 0.9, script="traditional") for i in range(3)])
    chosen = stratified_sample(pages, n=10, seed=1)
    assert any(p["stratum"].startswith("1979.1|traditional") for p in chosen)


def test_sample_skips_unassessed_and_caps_at_population():
    pages = [_page("a-p001L", 0.6), _page("a-p002L", None)]
    chosen = stratified_sample(pages, n=40, seed=1)
    assert [p["page_id"] for p in chosen] == ["a-p001L"]
