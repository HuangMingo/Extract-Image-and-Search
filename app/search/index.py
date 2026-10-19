from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .config import DEFAULT_CONFIG, FEATURE_ORDER
from .models import FeatureResult


@dataclass(frozen=True)
class SearchItem:
    image_id: str
    source: str
    label: str


class LocalSearchIndex:
    """PCA 128 chiều và rerank bằng bốn điểm thành phần có trọng số."""

    def __init__(
        self,
        items: list[SearchItem],
        combined: np.ndarray,
        groups: dict[str, np.ndarray],
        *,
        target_pca_dim: int = 128,
    ) -> None:
        matrix = np.asarray(combined, dtype=np.float32)
        if matrix.ndim != 2 or matrix.shape[0] != len(items) or len(items) < 2:
            raise ValueError("Chỉ mục cần ít nhất hai ảnh hợp lệ.")
        if matrix.shape[1] != 3364 or not np.all(np.isfinite(matrix)):
            raise ValueError("Ma trận vector chỉ mục không hợp lệ.")
        self.items = items
        self.groups = {
            name: np.asarray(groups[name], dtype=np.float32) for name in FEATURE_ORDER
        }
        self.input_dimension = 3364
        self.mean = matrix.mean(axis=0, dtype=np.float64).astype(np.float32)
        centered = matrix - self.mean

        gram = centered @ centered.T
        eigenvalues, eigenvectors = np.linalg.eigh(gram.astype(np.float64))
        order = np.argsort(eigenvalues)[::-1]
        eigenvalues = eigenvalues[order]
        eigenvectors = eigenvectors[:, order]
        threshold = max(1e-12, float(eigenvalues[0]) * 1e-10)
        component_count = min(
            target_pca_dim,
            matrix.shape[0] - 1,
            int(np.count_nonzero(eigenvalues > threshold)),
        )
        if component_count < 1:
            raise ValueError("Không thể fit PCA vì dữ liệu không có phương sai.")
        selected_values = eigenvalues[:component_count]
        selected_vectors = eigenvectors[:, :component_count]
        self.components = (
            (selected_vectors.T @ centered.astype(np.float64))
            / np.sqrt(selected_values)[:, None]
        ).astype(np.float32)
        self.pca_vectors = (centered @ self.components.T).astype(np.float32)
        self.pca_dimension = component_count
        norms = np.linalg.norm(
            self.pca_vectors.astype(np.float64), axis=1, keepdims=True
        )
        self.pca_normalized = np.divide(
            self.pca_vectors,
            norms,
            out=np.zeros_like(self.pca_vectors),
            where=norms > 1e-12,
        )

    def _transform_pca(self, vector: np.ndarray) -> np.ndarray:
        value = np.asarray(vector, dtype=np.float32).reshape(-1)
        if value.size != self.input_dimension:
            raise ValueError("Vector truy vấn không đủ 3364 chiều.")
        return ((value - self.mean) @ self.components.T).astype(np.float32)

    def search(
        self,
        query: FeatureResult,
        *,
        top_k: int = 5,
        metric: str = "cosine",
    ) -> dict:
        if query.combined is None:
            raise ValueError("Ảnh truy vấn không tạo đủ bốn nhóm đặc trưng.")
        selected_metric = metric if metric in {"cosine", "euclidean"} else "cosine"
        fallback_used = selected_metric != metric
        top_k = max(1, min(int(top_k), 30, len(self.items)))

        component_scores: dict[str, np.ndarray] = {}
        for name in FEATURE_ORDER:
            query_vector = query.features[name].l2_values.astype(np.float32)
            if selected_metric == "cosine":
                scores = np.clip(self.groups[name] @ query_vector, 0.0, 1.0)
            else:
                distances = np.linalg.norm(
                    self.groups[name] - query_vector[None, :], axis=1
                )
                scores = 1.0 / (1.0 + distances)
            component_scores[name] = scores.astype(np.float32)

        weighted = np.zeros(len(self.items), dtype=np.float32)
        for name, weight in DEFAULT_CONFIG.weights:
            weighted += weight * component_scores[name]

        query_pca = self._transform_pca(query.combined)
        if selected_metric == "cosine":
            norm = float(np.linalg.norm(query_pca.astype(np.float64)))
            if norm <= 1e-12:
                raise ValueError("Vector PCA truy vấn có norm bằng 0.")
            raw = np.clip(self.pca_normalized @ (query_pca / norm), -1.0, 1.0)
            pca_similarity = np.clip((raw + 1.0) / 2.0, 0.0, 1.0)
            pca_distance = 1.0 - raw
        else:
            pca_distance = np.linalg.norm(
                self.pca_vectors - query_pca[None, :], axis=1
            )
            pca_similarity = 1.0 / (1.0 + pca_distance)

        order = np.lexsort((-pca_similarity, -weighted))[:top_k]
        matches = []
        for rank, index in enumerate(order, start=1):
            item = self.items[int(index)]
            matches.append(
                {
                    "rank": rank,
                    "image_id": item.image_id,
                    "source": item.source,
                    "label": item.label,
                    "score": float(weighted[index]),
                    "pca_similarity": float(pca_similarity[index]),
                    "pca_distance": float(pca_distance[index]),
                    "components": {
                        name: float(component_scores[name][index])
                        for name in FEATURE_ORDER
                    },
                }
            )
        return {
            "metric": selected_metric,
            "fallback_used": fallback_used,
            "matches": matches,
        }

    def stats(self) -> dict:
        groups: dict[str, int] = {}
        for item in self.items:
            groups[item.label] = groups.get(item.label, 0) + 1
        return {
            "images": len(self.items),
            "groups": groups,
            "input_dimension": self.input_dimension,
            "pca_dimension": self.pca_dimension,
            "storage": "local_memory",
        }
