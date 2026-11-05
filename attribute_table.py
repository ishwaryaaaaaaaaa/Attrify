"""Attribute table (items x accepted functions) + coverage graph (PCA -> DBSCAN) + cluster sampler.

Paper (Phase 5): on Accept run the function over the corpus and add a column; standardize
columns, PCA to 2 components, DBSCAN clusters (noise ignored); the largest non-noise
cluster supplies essays for the open-ended question prompt.
DBSCAN parameters are not published; defaults here are my choice (see _auto_eps).
"""
import random

import numpy as np

import sandbox


class AttributeTable:
    def __init__(self, corpus, min_samples=5, seed=0):
        self.corpus = corpus
        self.texts = [c["text"] for c in corpus]
        self.names, self.fids, self.columns = [], [], []   # columns: list[np.ndarray]
        self.min_samples, self.rng = min_samples, random.Random(seed)

    # ----- columns -----
    def add_column(self, func):
        """Run func.code on every essay in the sandbox. Raises ValueError on failure so the
        caller can tell the user (accept should not silently add a broken column)."""
        vals, err = sandbox.run(func.code, self.texts)
        if err:
            raise ValueError(f"Function '{func.name}' failed on the corpus: {err}")
        self.names.append(func.name)
        self.fids.append(func.id)
        self.columns.append(np.asarray(vals, dtype=float))
        return self.columns[-1]

    def remove_column(self, fid):
        if fid in self.fids:
            i = self.fids.index(fid)
            for lst in (self.names, self.fids, self.columns):
                lst.pop(i)

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
        P = PCA(n_components=k).fit_transform(Z)
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

    def largest_cluster(self, labels):
        ids, counts = np.unique(labels[labels >= 0], return_counts=True)
        return None if len(ids) == 0 else int(ids[np.argmax(counts)])

    def cluster_sample(self, k=5, excerpt_chars=300):
        """Random essays from the largest non-noise cluster, formatted for the open-ended prompt:
        list of (essay_id, cluster_id, excerpt). None if there is no cluster yet."""
        _, labels = self.clusters()
        if labels is None:
            return None
        cid = self.largest_cluster(labels)
        if cid is None:
            return None
        idx = [i for i, l in enumerate(labels) if l == cid]
        pick = self.rng.sample(idx, min(k, len(idx)))
        return [(self.corpus[i]["id"], cid, self.texts[i][:excerpt_chars]) for i in pick]

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
