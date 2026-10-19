from __future__ import annotations

import numpy as np

from .config import DEFAULT_CONFIG, FEATURE_ORDER, FeatureConfig
from .extractors import EXTRACTORS
from .models import FeatureResult, PreparedImage


def extract_features(
    prepared: PreparedImage,
    *,
    config: FeatureConfig = DEFAULT_CONFIG,
    metadata: dict | None = None,
) -> FeatureResult:
    vectors = {name: EXTRACTORS[name](prepared, config) for name in FEATURE_ORDER}
    combined = None
    if all(vectors[name].valid for name in FEATURE_ORDER):
        combined = np.concatenate(
            [
                np.sqrt(config.weight_map[name]) * vectors[name].l2_values
                for name in FEATURE_ORDER
            ]
        ).astype(np.float32)
    return FeatureResult(
        config.schema_version,
        config.config_version,
        config.extractor_version,
        config.fingerprint,
        vectors,
        combined,
        list(FEATURE_ORDER),
        metadata or {},
        list(prepared.warnings),
    )
