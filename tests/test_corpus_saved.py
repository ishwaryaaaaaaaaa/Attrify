import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import corpus as C  # noqa: E402


def test_sample_dataset_is_50_essays_seeded_into_the_database():
    essays, synth = C.load_dataset()
    assert synth and len(essays) == 50 and os.path.exists(C.db_path())
    genres = [e["genre"] for e in essays]
    assert genres.count("argumentative") == 25 and genres.count("narrative") == 25
    assert len({e["text"] for e in essays}) == 50 and all(30 <= len(e["text"].split()) <= 140 for e in essays)
    assert [e["id"] for e in essays] == list(range(1, 51)) and all(e["title"] for e in essays)


def test_data_is_fixed_second_load_is_identical_and_not_reseeded(monkeypatch):
    first, _ = C.load_dataset()
    monkeypatch.setattr(C, "sample_corpus", lambda: (_ for _ in ()).throw(AssertionError("re-read the seed file")))
    again, _ = C.load_dataset()                     # the seed file is not touched again
    assert again == first


def test_essays_cannot_be_changed_or_deleted():
    C.load_dataset()
    con = C.connect()
    with pytest.raises(sqlite3.DatabaseError, match="read-only"):
        con.execute("UPDATE essays SET text='changed' WHERE id=1")
    with pytest.raises(sqlite3.DatabaseError, match="read-only"):
        con.execute("DELETE FROM essays WHERE id=1")
    assert con.execute("SELECT COUNT(*) FROM essays").fetchone()[0] == 50
    con.close()


def test_import_csv_adds_a_real_dataset_once_and_keeps_the_sample(tmp_path):
    csv = tmp_path / "e.csv"
    csv.write_text("full_text\n" + "\n".join(f"essay number {i} about schools" for i in range(30)), encoding="utf-8")
    name = C.import_csv(str(csv), n=10)
    essays, synth = C.load_dataset(name)
    assert not synth and len(essays) == 10
    assert C.import_csv(str(csv), n=10) == name and C.load_dataset(name)[0] == essays      # not imported twice
    assert len(C.load_dataset()[0]) == 50                                                  # sample untouched


def test_unknown_dataset_is_an_error():
    with pytest.raises(KeyError):
        C.load_dataset("nope")
