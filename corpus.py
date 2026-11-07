"""Corpus loading. Real data: ASAP 2.0 (Kaggle, ~24k essays) -- download it yourself, then
load_csv("path.csv", text_col=...). Check the actual column names in your copy.
demo_corpus() is SYNTHETIC filler for testing the pipeline only; never report results on it.
"""
import random


def load_csv(path, text_col="full_text", n=200, seed=0, genre_col=None, genre=None):
    import pandas as pd
    df = pd.read_csv(path)
    if genre_col and genre:
        df = df[df[genre_col] == genre]
    if text_col not in df.columns:
        raise KeyError(f"{text_col!r} not in columns {list(df.columns)}")
    df = df.dropna(subset=[text_col])
    df = df.sample(n=min(n, len(df)), random_state=seed)
    return [{"id": int(i), "text": str(t)} for i, t in zip(df.index, df[text_col])]


_OPEN = ["Schools should change.", "Social media is harmful.", "Remote work is the future.",
         "Homework is overrated.", "Cities need more parks."]
_STAT = ["A 2020 study found {n}% of students agreed.", "Surveys show {n}% support this (Kim, 2019).",
         "Roughly {n} out of 100 people reported gains."]
_OPIN = ["I honestly feel this is right.", "My friends and I always thought so.",
         "In my opinion it is obvious."]
_NARR = ["The rain hammered the window as she packed.", "He remembered the old road and the dog.",
         "Nobody spoke at the funeral."]


def demo_corpus(n=90, seed=0):
    """Three loose styles (stat-heavy / opinionated / narrative) with varying length."""
    rng = random.Random(seed)
    out = []
    for i in range(n):
        style = i % 3
        parts = [rng.choice(_OPEN)]
        for _ in range(rng.randint(2, 8)):
            if style == 0:
                parts.append(rng.choice(_STAT).format(n=rng.randint(5, 95)))
            elif style == 1:
                parts.append(rng.choice(_OPIN))
            else:
                parts.append(rng.choice(_NARR))
        out.append({"id": i, "text": " ".join(parts)})
    return out


# ----- the dataset lives in a SQLite database (data/attrify.db) -----
# Essays are written ONCE and never change: triggers refuse UPDATE and DELETE on the essays table.
# To replace the data, delete the .db file (or import another dataset under a new name).
import json
import os
import sqlite3

SAMPLE = "sample"


def data_dir():
    """Folder of the database (ATTRIFY_DATA_DIR overrides; tests point it at a temp folder)."""
    return os.environ.get("ATTRIFY_DATA_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def db_path():
    return os.path.join(data_dir(), "attrify.db")


def connect():
    """Open the database, creating the tables and the read-only triggers on first use."""
    os.makedirs(data_dir(), exist_ok=True)
    con = sqlite3.connect(db_path())
    con.executescript("""
        CREATE TABLE IF NOT EXISTS datasets (
            name TEXT PRIMARY KEY, source TEXT NOT NULL, synthetic INTEGER NOT NULL,
            created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS essays (
            dataset TEXT NOT NULL REFERENCES datasets(name), id INTEGER NOT NULL,
            genre TEXT, title TEXT, text TEXT NOT NULL, PRIMARY KEY (dataset, id));
        CREATE TRIGGER IF NOT EXISTS essays_no_update BEFORE UPDATE ON essays
            BEGIN SELECT RAISE(ABORT, 'essays are read-only'); END;
        CREATE TRIGGER IF NOT EXISTS essays_no_delete BEFORE DELETE ON essays
            BEGIN SELECT RAISE(ABORT, 'essays are read-only'); END;
    """)
    return con


def sample_corpus():
    """The 50 hand-written sample essays in sample_essays.json (25 argumentative, 25 narrative).
    This file is only the SEED: once loaded into the database it is not read again.
    They are written for testing and are NOT real student essays."""
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample_essays.json"), encoding="utf-8") as f:
        return json.load(f)


def add_dataset(name, source, essays, synthetic):
    """Insert a dataset ONCE. Returns True if it was added, False if that name already exists (kept as is)."""
    con = connect()
    try:
        if con.execute("SELECT 1 FROM datasets WHERE name=?", (name,)).fetchone():
            return False
        with con:
            con.execute("INSERT INTO datasets(name, source, synthetic) VALUES (?,?,?)", (name, source, int(synthetic)))
            con.executemany("INSERT INTO essays(dataset, id, genre, title, text) VALUES (?,?,?,?,?)",
                            [(name, int(e["id"]), e.get("genre"), e.get("title"), e["text"]) for e in essays])
        return True
    finally:
        con.close()


def import_csv(path, text_col="full_text", n=200, name=None, genre_col=None, genre=None):
    """Load a real corpus (for example ASAP 2.0) from a CSV into the database, once, under `name`."""
    name = name or f"{os.path.splitext(os.path.basename(path))[0]}-{n}"
    con = connect()
    exists = con.execute("SELECT 1 FROM datasets WHERE name=?", (name,)).fetchone()
    con.close()
    if not exists:
        add_dataset(name, f"csv:{os.path.abspath(path)}:{text_col}:{n}",
                    load_csv(path, text_col=text_col, n=n, genre_col=genre_col, genre=genre), synthetic=False)
    return name


def load_dataset(name=SAMPLE):
    """Read a dataset from the database: (essays, synthetic). The sample is seeded on first use."""
    con = connect()
    if name == SAMPLE and not con.execute("SELECT 1 FROM datasets WHERE name=?", (SAMPLE,)).fetchone():
        con.close()
        add_dataset(SAMPLE, "sample_essays.json", sample_corpus(), synthetic=True)   # seed file read only now
        con = connect()
    try:
        row = con.execute("SELECT synthetic FROM datasets WHERE name=?", (name,)).fetchone()
        if row is None:
            raise KeyError(f"No dataset named {name!r} in {db_path()}")
        rows = con.execute("SELECT id, genre, title, text FROM essays WHERE dataset=? ORDER BY id", (name,)).fetchall()
    finally:
        con.close()
    return [{"id": i, "genre": g, "title": t, "text": x} for i, g, t, x in rows], bool(row[0])
