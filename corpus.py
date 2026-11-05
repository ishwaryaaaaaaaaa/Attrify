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
