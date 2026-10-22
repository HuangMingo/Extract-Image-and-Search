from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image
from skimage.exposure import rescale_intensity
from skimage.feature import hog

from .config import DEFAULT_CONFIG, FeatureConfig
from .models import PreparedImage


def save_hog_visualization(
    prepared: PreparedImage,
    output_directory: str | Path,
    source_stem: str,
    *,
    config: FeatureConfig = DEFAULT_CONFIG,
) -> Path:
    """Lưu riêng ảnh trực quan HOG, không tham gia vào dữ liệu giao diện."""
    _, hog_image = hog(
        prepared.gray_128,
        orientations=config.hog_orientations,
        pixels_per_cell=config.hog_pixels_per_cell,
        cells_per_block=config.hog_cells_per_block,
        block_norm=config.hog_block_norm,
        visualize=True,
        transform_sqrt=config.hog_transform_sqrt,
        feature_vector=False,
        channel_axis=None,
    )

    finite = hog_image[np.isfinite(hog_image)]
    upper = float(np.percentile(finite, 99)) if finite.size else 0.0
    if upper > 0:
        hog_image = rescale_intensity(hog_image, in_range=(0, upper), out_range=(0, 1))
    else:
        hog_image = np.zeros_like(hog_image, dtype=np.float32)

    destination = Path(output_directory)
    destination.mkdir(parents=True, exist_ok=True)
    safe_stem = Path(source_stem).stem or "query"
    output_path = destination / f"{safe_stem}_hog.png"
    image_uint8 = np.clip(hog_image * 255, 0, 255).astype(np.uint8)
    Image.fromarray(image_uint8, mode="L").save(output_path)
    return output_path
