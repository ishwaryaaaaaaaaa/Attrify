"""Attribute table (items x accepted functions) + coverage graph (PCA -> DBSCAN) + cluster sampler.

Paper (Phase 5): on Accept run the function over the corpus and add a column; standardize
columns, PCA to 2 components, DBSCAN clusters (noise ignored); the largest non-noise
cluster supplies essays for the open-ended question prompt.
DBSCAN parameters are not published; defaults here are my choice (see _auto_eps).
"""
import random
import time

import numpy as np

import pipeline_trace as PT
import sandbox


class AttributeTable:
    def __init__(self, corpus, min_samples=5, seed=0):
        self.corpus = corpus
        self.texts = [c["text"] for c in corpus]
        self.names, self.fids, self.columns = [], [], []   # columns: list[np.ndarray]
        self.min_samples, self.rng = min_samples, random.Random(seed)
        self.explained = [0.0, 0.0]

    # ----- columns -----
    def add_column(self, func):
        """Run func.code on every essay in the sandbox. Raises ValueError on failure so the
        caller can tell the user (accept should not silently add a broken column)."""
        t0 = time.perf_counter()
        vals, err = sandbox.run(func.code, self.texts)
        ms = round((time.perf_counter() - t0) * 1000)
        if err:
            PT.add("Attribute Table", f"Add column “{func.name}” (failed)", "sandbox", status="error", ms=ms,
                   inputs={"essays": len(self.texts)}, outputs={"error": err})
            raise ValueError(f"Function '{func.name}' failed on the corpus: {err}")
        self.names.append(func.name)
        self.fids.append(func.id)
        self.columns.append(np.asarray(vals, dtype=float))
        col = self.columns[-1]
        counts, edges = np.histogram(col, bins=10)
        PT.add("Attribute Table", f"Add column “{func.name}”", "sandbox",
               note="The accepted function runs on EVERY essay of the corpus (same sandbox as before). "
                    "Its numbers become one column of the attribute table.",
               inputs={"function": func.name, "essays": len(self.texts)},
               outputs={"columns_in_table": len(self.names), "min": round(float(col.min()), 4),
                        "max": round(float(col.max()), 4), "mean": round(float(col.mean()), 4),
                        "std": round(float(col.std()), 4), "share_equal_to_most_common_value":
                        round(float(np.unique(col, return_counts=True)[1].max() / len(col)), 3)},
               viz=[{"type": "bars", "title": "How the essays spread over this column (10 bins)",
                     "labels": [f"{edges[i]:.3g}" for i in range(len(counts))], "values": counts.tolist()}],
               ms=ms)
        return self.columns[-1]

    def remove_column(self, fid):
        if fid in self.fids:
            i = self.fids.index(fid)
            name = self.names[i]
            for lst in (self.names, self.fids, self.columns):
                lst.pop(i)
            PT.add("Attribute Table", f"Remove column “{name}”", "compute",
                   note="The column is dropped from the table; the coverage graph is recomputed without it.",
                   outputs={"columns_in_table": len(self.names)})

    def matrix(self):
        return np.column_stack(self.columns) if self.columns else np.zeros((len(self.texts), 0))

    def histogram(self, col, bins=10):
        counts, edges = np.histogram(self.columns[col], bins=bins)
        return counts.tolist(), edges.tolist()

    # ----- coverage graph -----
    def project(self):
        """Standardize, PCA to 2-D. Returns (n,2) array or None if no columns."""
        X = self.matrix()
        if X.shape[1] == 0:
            return None
        sd = X.std(axis=0)
        sd[sd == 0] = 1.0                       # constant column -> contributes nothing
        Z = (X - X.mean(axis=0)) / sd
        from sklearn.decomposition import PCA
        k = min(2, Z.shape[1], Z.shape[0])
        pca = PCA(n_components=k)
        P = pca.fit_transform(Z)
        ev = [float(v) for v in pca.explained_variance_ratio_]
        self.explained = (ev + [0.0, 0.0])[:2]          # share of variance per axis, for the axis labels
        if k < 2:
            P = np.hstack([P, np.zeros((len(P), 2 - k))])
        return P

    def _auto_eps(self, P):
        """eps = 75th percentile of each point's distance to its min_samples-th neighbour."""
        from sklearn.neighbors import NearestNeighbors
        k = min(self.min_samples, len(P) - 1)
        d, _ = NearestNeighbors(n_neighbors=k + 1).fit(P).kneighbors(P)
        return max(float(np.percentile(d[:, -1], 75)), 1e-6)

    def clusters(self, eps=None):
        """Returns (points (n,2), labels (n,)) with label -1 = noise; (None, None) if empty."""
        P = self.project()
        if P is None or len(P) < 2:
            return None, None
        from sklearn.cluster import DBSCAN
        labels = DBSCAN(eps=eps or self._auto_eps(P), min_samples=self.min_samples).fit_predict(P)
        return P, labels

    def trace_coverage(self, eps=None):
        """Record how the coverage graph was (re)computed: standardize -> PCA -> DBSCAN."""
        t0 = time.perf_counter()
        P, labels = self.clusters(eps)
        ms = round((time.perf_counter() - t0) * 1000)
        if P is None or labels is None:
            PT.add("Coverage Graph", "Recompute the graph", "compute",
                   note="No columns in the table, so there is nothing to plot yet.", outputs={"columns": 0})
            return
        used = float(eps or self._auto_eps(P))
        ids, counts = np.unique(labels[labels >= 0], return_counts=True)
        sizes = {int(i): int(c) for i, c in zip(ids, counts)}
        big = self.largest_cluster(labels)
        PT.add("Coverage Graph", "Standardize → PCA → DBSCAN", "compute",
               note="Each essay is a point whose coordinates are its column values. The columns are standardized "
                    "(mean 0, std 1), squeezed to 2-D with PCA, and DBSCAN groups nearby essays. Grey points are noise. "
                    "The largest group feeds the next open-ended question.",
               inputs={"columns": list(self.names), "essays": len(self.texts), "min_samples": self.min_samples,
                       "eps_rule": "eps = 75th percentile of every essay's distance to its 5th nearest neighbour (my choice; the paper does not publish it)"},
               outputs={"explained_variance_pc1_pc2": [round(v, 3) for v in self.explained], "eps": round(used, 4),
                        "clusters": sizes, "noise_points": int((labels < 0).sum()), "largest_cluster": big},
               viz=[{"type": "table", "title": "Standardization (per column)", "columns": ["column", "mean", "std"],
                     "rows": [[n, round(float(c.mean()), 3), round(float(c.std()), 3)] for n, c in zip(self.names, self.columns)]},
                    {"type": "bars", "title": "Essays per cluster (last bar = noise)",
                     "labels": [f"cluster {i}" for i in sizes] + ["noise"], "values": list(sizes.values()) + [int((labels < 0).sum())]}],
               ms=ms)

    def largest_cluster(self, labels):
        ids, counts = np.unique(labels[labels >= 0], return_counts=True)
        return None if len(ids) == 0 else int(ids[np.argmax(counts)])

    def cluster_sample(self, k=5, excerpt_chars=300):
        """Random essays from the largest non-noise cluster, formatted for the open-ended prompt:
        list of (essay_id, cluster_id, excerpt). None if there is no cluster yet."""
        _, labels = self.clusters()
        if labels is None:
            PT.add("Coverage Graph", "Pick essays for the next question", "compute",
                   note="No accepted attributes yet, so there is no cluster; the question is asked without essay evidence.",
                   outputs={"essays": []})
            return None
        cid = self.largest_cluster(labels)
        if cid is None:
            PT.add("Coverage Graph", "Pick essays for the next question", "compute",
                   note="DBSCAN found only noise, so no cluster can be used.", outputs={"essays": []})
            return None
        idx = [i for i, l in enumerate(labels) if l == cid]
        pick = self.rng.sample(idx, min(k, len(idx)))
        out = [(self.corpus[i]["id"], cid, self.texts[i][:excerpt_chars]) for i in pick]
        PT.add("Coverage Graph", "Pick essays for the next question", "compute",
               note=f"Random essays from the largest non-noise cluster (cluster {cid}, {len(idx)} essays). "
                    "They go into the open-ended question prompt as evidence of what the current attributes do not separate.",
               inputs={"cluster": cid, "cluster_size": len(idx), "sample_size": k},
               outputs={"essay_ids": [e[0] for e in out]},
               viz=[{"type": "table", "title": "Essays sent to the Question Agent", "columns": ["essay", "cluster", "excerpt"],
                     "rows": [[e[0], e[1], e[2][:120]] for e in out]}])
        return out

    def plot(self, path):
        """Save the coverage graph (noise in grey). Quick look only; the real UI is Phase 6."""
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        P, labels = self.clusters()
        if P is None:
            return False
        fig, ax = plt.subplots(figsize=(5, 4))
        noise = labels < 0
        ax.scatter(P[noise, 0], P[noise, 1], c="lightgrey", s=14, label="noise")
        sc = ax.scatter(P[~noise, 0], P[~noise, 1], c=labels[~noise], cmap="tab10", s=18)
        ax.set_xlabel("PC1")
        ax.set_ylabel("PC2")
        ax.set_title(f"Coverage: {len(self.names)} attribute(s)")
        del sc
        fig.tight_layout()
        fig.savefig(path, dpi=120)
        plt.close(fig)
        return True
