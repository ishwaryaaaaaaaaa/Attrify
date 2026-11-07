import pytest


@pytest.fixture(autouse=True)
def _temp_data_dir(tmp_path, monkeypatch):
    """Keep the saved dataset out of the real attrify/data folder while tests run."""
    monkeypatch.setenv("ATTRIFY_DATA_DIR", str(tmp_path / "data"))
