from __future__ import annotations

import cv2
import numpy as np

from .config import DEFAULT_CONFIG, FeatureConfig
from .models import PreparedImage


class PreprocessError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def prepare_image(
    image: np.ndarray,
    *,
    config: FeatureConfig = DEFAULT_CONFIG,
) -> PreparedImage:
    """Chuẩn hóa mảng RGBA 512×512 và loại RGB nằm ngoài alpha."""
    array = np.asarray(image)
    if array.dtype != np.uint8:
        raise PreprocessError("invalid_dtype", "Ảnh phải có dtype uint8.")
    if array.ndim != 3 or array.shape[2] != 4:
        raise PreprocessError("invalid_channels", "Ảnh tìm kiếm phải là RGBA.")
    if array.shape[:2] != (config.color_size, config.color_size):
        raise PreprocessError(
            "unexpected_size",
            f"Ảnh phải có kích thước {config.color_size}×{config.color_size}.",
        )
    mask = (array[..., 3] > config.alpha_threshold).astype(np.uint8)
    if not np.any(mask):
        raise PreprocessError("empty_mask", "Mask alpha không chứa đối tượng.")
    rgb = array[..., :3].copy()
    rgb[mask == 0] = 0
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    gray_128 = cv2.resize(
        gray,
        (config.gray_size, config.gray_size),
        interpolation=cv2.INTER_AREA,
    )
    mask_128 = cv2.resize(
        mask,
        (config.gray_size, config.gray_size),
        interpolation=cv2.INTER_NEAREST,
    ).astype(np.uint8)
    gray_128[mask_128 == 0] = config.background_gray
    return PreparedImage(
        rgb,
        mask,
        gray_128,
        mask_128,
        (config.color_size, config.color_size),
        "alpha",
        {"mode": "identity", "scale": 1.0, "padding": [0, 0, 0, 0]},
    )
