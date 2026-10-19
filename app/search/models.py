from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class PreparedImage:
    rgb_512: np.ndarray
    mask_512: np.ndarray
    gray_128: np.ndarray
    mask_128: np.ndarray
    original_size: tuple[int, int]
    mask_source: str
    transform: dict[str, Any]
    warnings: list[str] = field(default_factory=list)


@dataclass
class FeatureVector:
    name: str
    values: np.ndarray
    l2_values: np.ndarray
    dim: int
    valid: bool
    reason: str | None
    norm_before_l2: float
    valid_count: int | None = None
    region_valid_counts: list[int] | None = None
    empty_regions: list[bool] | None = None


@dataclass
class FeatureResult:
    schema_version: str
    config_version: str
    extractor_version: str
    config_fingerprint: str
    features: dict[str, FeatureVector]
    combined: np.ndarray | None
    combined_order: list[str]
    metadata: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
