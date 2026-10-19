from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from threading import Lock
import time
from typing import Any

import numpy as np
from PIL import Image, ImageOps

from app.utils.image_utils import resize_and_center
from app.utils.validation import ImageValidationError, load_validated_image

from .config import FEATURE_ORDER
from .index import LocalSearchIndex, SearchItem
from .models import FeatureResult
from .pipeline import extract_features
from .preprocess import prepare_image

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def _format_result_caption(match: dict[str, Any]) -> str:
    """Format gallery captions as: #rank filename score."""
    return (
        f"#{int(match['rank'])} "
        f"{Path(str(match['source'])).name} "
        f"{float(match['score']):.6f}"
    )


@dataclass
class SearchOutput:
    query_image: Image.Image
    gallery: list[tuple[str, str]]
    details_json: str
    feature_result: FeatureResult
    preprocessing: str


def standardize_rgba(image: Image.Image) -> Image.Image:
    rgba = ImageOps.exif_transpose(image).convert("RGBA")
    alpha = np.asarray(rgba.getchannel("A"))
    if not np.any(alpha > 0):
        raise ValueError("Mask alpha của ảnh bị rỗng.")
    if rgba.size == (512, 512):
        return rgba
    return resize_and_center(rgba, (512, 512), 0.94)


class ImageSearchService:
    def __init__(self, database_root: Path) -> None:
        self.database_root = database_root
        self._index: LocalSearchIndex | None = None
        self._lock = Lock()

    def _build_index(self) -> LocalSearchIndex:
        items: list[SearchItem] = []
        combined: list[np.ndarray] = []
        groups: dict[str, list[np.ndarray]] = {name: [] for name in FEATURE_ORDER}
        paths = sorted(
            (
                path
                for path in self.database_root.rglob("*")
                if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
            ),
            key=lambda path: path.as_posix().lower(),
        )
        for path in paths:
            try:
                with Image.open(path) as opened:
                    normalized = standardize_rgba(opened)
                result = extract_features(
                    prepare_image(np.asarray(normalized, dtype=np.uint8)),
                    metadata={"source": str(path), "label": path.parent.name},
                )
                if result.combined is None:
                    continue
                content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
                items.append(SearchItem(content_hash, str(path.resolve()), path.parent.name))
                combined.append(result.combined)
                for name in FEATURE_ORDER:
                    groups[name].append(result.features[name].l2_values)
            except (OSError, ValueError):
                continue
        if len(items) < 2:
            raise ValueError("Kho ảnh không có đủ hai ảnh hợp lệ để tìm kiếm.")
        return LocalSearchIndex(
            items,
            np.stack(combined),
            {name: np.stack(values) for name, values in groups.items()},
            target_pca_dim=128,
        )

    def get_index(self) -> LocalSearchIndex:
        if self._index is None:
            with self._lock:
                if self._index is None:
                    self._index = self._build_index()
        return self._index

    @staticmethod
    def _has_useful_alpha(path: str | Path) -> bool:
        try:
            with Image.open(path) as opened:
                if "A" not in opened.getbands():
                    return False
                alpha = np.asarray(opened.getchannel("A"))
                return bool(np.any(alpha < 255) and np.any(alpha > 0))
        except OSError:
            return False

    def search(
        self,
        source: str | Path,
        processor: Any,
        *,
        metric: str = "cosine",
        top_k: int = 5,
    ) -> SearchOutput:
        started = time.perf_counter()
        # Validate bytes, format, decodeability and size through the same
        # project contract before either alpha reuse or model inference.
        try:
            load_validated_image(source, processor.settings)
        except ImageValidationError as exc:
            raise ValueError(str(exc)) from exc
        if self._has_useful_alpha(source):
            with Image.open(source) as opened:
                query_image = standardize_rgba(opened)
            preprocessing = "existing_alpha"
        else:
            detected = processor.detect(source)
            removed = processor.process_detection(detected, selected_index=0)
            query_image = standardize_rgba(removed.output)
            preprocessing = removed.metadata.get("detection_method", "yolo_rembg")

        features = extract_features(
            prepare_image(np.asarray(query_image, dtype=np.uint8))
        )
        index = self.get_index()
        response = index.search(features, top_k=top_k, metric=metric)
        gallery = [
            (
                match["source"],
                _format_result_caption(match),
            )
            for match in response["matches"]
        ]
        details = {
            "success": True,
            "preprocessing": preprocessing,
            "query_size": [512, 512],
            "feature_dimension": int(features.combined.size) if features.combined is not None else 0,
            "feature_groups": {
                name: {
                    "dimension": int(features.features[name].dim),
                    "normalization": "L2",
                    "valid": bool(features.features[name].valid),
                }
                for name in features.combined_order
            },
            "pca_dimension": index.pca_dimension,
            "metric": response["metric"],
            "fallback_used": response["fallback_used"],
            "top_k": len(response["matches"]),
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "index": index.stats(),
            "matches": response["matches"],
        }
        return SearchOutput(
            query_image,
            gallery,
            json.dumps(details, ensure_ascii=False, indent=2),
            features,
            preprocessing,
        )
