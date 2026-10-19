from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Mapping

FEATURE_ORDER = ("hsv_global", "hsv_spatial", "lbp_spatial", "hog")
FEATURE_DIMS = {
    "hsv_global": 288,
    "hsv_spatial": 1152,
    "lbp_spatial": 160,
    "hog": 1764,
}


@dataclass(frozen=True)
class FeatureConfig:
    """Cấu hình bốn bộ mô tả trong báo cáo Mục 2."""

    config_version: str = "animal-face-v1"
    schema_version: str = "animal-feature-result-v1"
    extractor_version: str = "0.1.0"
    color_size: int = 512
    gray_size: int = 128
    size_mode: str = "strict"
    alpha_threshold: int = 0
    hsv_h_bins: int = 18
    hsv_s_bins: int = 4
    hsv_v_bins: int = 4
    achromatic_s_threshold: int = 16
    achromatic_v_threshold: int = 16
    hsv_spatial_rows: int = 2
    hsv_spatial_cols: int = 2
    lbp_points: int = 8
    lbp_radius: int = 1
    lbp_method: str = "uniform"
    lbp_rows: int = 4
    lbp_cols: int = 4
    lbp_bins: int = 10
    hog_orientations: int = 9
    hog_pixels_per_cell: tuple[int, int] = (16, 16)
    hog_cells_per_block: tuple[int, int] = (2, 2)
    hog_block_norm: str = "L2-Hys"
    hog_transform_sqrt: bool = False
    background_gray: int = 0
    l2_eps: float = 1e-12
    weights: tuple[tuple[str, float], ...] = (
        ("hsv_global", 0.15),
        ("hsv_spatial", 0.25),
        ("lbp_spatial", 0.25),
        ("hog", 0.35),
    )

    def as_dict(self) -> dict:
        return asdict(self)

    @property
    def weight_map(self) -> Mapping[str, float]:
        return dict(self.weights)

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(
            self.as_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


DEFAULT_CONFIG = FeatureConfig()
