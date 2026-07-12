import corpus_tools


def test_package_importable():
    assert corpus_tools.__version__ == "0.1.0"
