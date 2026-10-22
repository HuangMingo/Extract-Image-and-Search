from __future__ import annotations

import cv2
import numpy as np
from skimage.feature import hog, local_binary_pattern

from .config import DEFAULT_CONFIG, FEATURE_DIMS, FeatureConfig
from .models import FeatureVector, PreparedImage


def _finalize(
    name: str,
    values: np.ndarray,
    config: FeatureConfig,
    *,
    valid_count: int | None = None,
    region_valid_counts: list[int] | None = None,
    empty_regions: list[bool] | None = None,
) -> FeatureVector:
    vector = np.asarray(values, dtype=np.float32).reshape(-1)
    expected = FEATURE_DIMS[name]
    if vector.size != expected:
        raise ValueError(f"{name}: nhận {vector.size} chiều, cần {expected}.")
    if not np.all(np.isfinite(vector)) or np.any(vector < 0):
        raise ValueError(f"{name}: vector chứa giá trị không hợp lệ.")
    norm = float(np.linalg.norm(vector.astype(np.float64)))
    valid = norm > config.l2_eps
    l2_values = (
        (vector / norm).astype(np.float32) if valid else np.zeros_like(vector)
    )
    return FeatureVector(
        name,
        vector,
        l2_values,
        expected,
        valid,
        None if valid else "zero_norm",
        norm,
        valid_count,
        region_valid_counts,
        empty_regions,
    )


def _quantized_hsv(prepared: PreparedImage, config: FeatureConfig) -> np.ndarray:
    hsv = cv2.cvtColor(prepared.rgb_512, cv2.COLOR_RGB2HSV)
    h, s, v = hsv[..., 0].copy(), hsv[..., 1], hsv[..., 2]
    h[(s < config.achromatic_s_threshold) | (v < config.achromatic_v_threshold)] = 0
    h_bin = h // (180 // config.hsv_h_bins)
    s_bin = s // (256 // config.hsv_s_bins)
    v_bin = v // (256 // config.hsv_v_bins)
    return (
        (h_bin.astype(np.int32) * config.hsv_s_bins + s_bin)
        * config.hsv_v_bins
        + v_bin
    )


def _histogram(
    indices: np.ndarray, mask: np.ndarray, bins: int
) -> tuple[np.ndarray, int]:
    selected = indices[mask.astype(bool)]
    count = int(selected.size)
    if count == 0:
        return np.zeros(bins, dtype=np.float32), 0
    values = np.bincount(selected, minlength=bins).astype(np.float32)
    values /= count
    return values, count


def extract_hsv_global(
    prepared: PreparedImage, config: FeatureConfig = DEFAULT_CONFIG
) -> FeatureVector:
    bins = config.hsv_h_bins * config.hsv_s_bins * config.hsv_v_bins
    values, count = _histogram(
        _quantized_hsv(prepared, config), prepared.mask_512, bins
    )
    return _finalize("hsv_global", values, config, valid_count=count)


def extract_hsv_spatial(
    prepared: PreparedImage, config: FeatureConfig = DEFAULT_CONFIG
) -> FeatureVector:
    indices = _quantized_hsv(prepared, config)
    bins = config.hsv_h_bins * config.hsv_s_bins * config.hsv_v_bins
    vectors, counts = [], []
    height, width = indices.shape
    for row in range(config.hsv_spatial_rows):
        y0 = row * height // config.hsv_spatial_rows
        y1 = (row + 1) * height // config.hsv_spatial_rows
        for col in range(config.hsv_spatial_cols):
            x0 = col * width // config.hsv_spatial_cols
            x1 = (col + 1) * width // config.hsv_spatial_cols
            values, count = _histogram(
                indices[y0:y1, x0:x1], prepared.mask_512[y0:y1, x0:x1], bins
            )
            vectors.append(values)
            counts.append(count)
    return _finalize(
        "hsv_spatial",
        np.concatenate(vectors),
        config,
        valid_count=sum(counts),
        region_valid_counts=counts,
        empty_regions=[count == 0 for count in counts],
    )


def extract_lbp_spatial(
    prepared: PreparedImage, config: FeatureConfig = DEFAULT_CONFIG
) -> FeatureVector:
    lbp_map = local_binary_pattern(
        prepared.gray_128,
        P=config.lbp_points,
        R=config.lbp_radius,
        method=config.lbp_method,
    )
    valid_centers = cv2.erode(
        prepared.mask_128,
        np.ones((3, 3), dtype=np.uint8),
        iterations=1,
        borderType=cv2.BORDER_CONSTANT,
        borderValue=0,
    )
    vectors, counts = [], []
    height, width = lbp_map.shape
    for row in range(config.lbp_rows):
        y0 = row * height // config.lbp_rows
        y1 = (row + 1) * height // config.lbp_rows
        for col in range(config.lbp_cols):
            x0 = col * width // config.lbp_cols
            x1 = (col + 1) * width // config.lbp_cols
            values, count = _histogram(
                lbp_map[y0:y1, x0:x1].astype(np.int32),
                valid_centers[y0:y1, x0:x1],
                config.lbp_bins,
            )
            vectors.append(values)
            counts.append(count)
    return _finalize(
        "lbp_spatial",
        np.concatenate(vectors),
        config,
        valid_count=sum(counts),
        region_valid_counts=counts,
        empty_regions=[count == 0 for count in counts],
    )


def extract_hog(
    prepared: PreparedImage, config: FeatureConfig = DEFAULT_CONFIG
) -> FeatureVector:
    tensor = hog(
        prepared.gray_128,
        orientations=config.hog_orientations,
        pixels_per_cell=config.hog_pixels_per_cell,
        cells_per_block=config.hog_cells_per_block,
        block_norm=config.hog_block_norm,
        visualize=False,
        transform_sqrt=config.hog_transform_sqrt,
        feature_vector=False,
        channel_axis=None,
    )
    expected_shape = (7, 7, 2, 2, 9)
    if tensor.shape != expected_shape:
        raise ValueError(f"HOG shape {tensor.shape}, cần {expected_shape}.")
    return _finalize(
        "hog",
        tensor.reshape(-1),
        config,
        valid_count=int(np.count_nonzero(prepared.mask_128)),
    )


def extract_gabor_spatial(
    prepared: PreparedImage, config: FeatureConfig = DEFAULT_CONFIG
) -> FeatureVector:
    """Mô tả texture theo lưới bằng năng lượng Gabor đa tỉ lệ, đa hướng."""
    gray = prepared.gray_128.astype(np.float32) / 255.0
    kernel_size = int(config.gabor_kernel_size)
    if kernel_size < 3 or kernel_size % 2 == 0:
        raise ValueError("gabor_kernel_size phải là số lẻ và không nhỏ hơn 3.")

    # Loại vùng mà kernel có thể chạm nền trong suốt để đường viền silhouette
    # không lấn át hoa văn bên trong lông.
    valid_centers = cv2.erode(
        prepared.mask_128,
        np.ones((kernel_size, kernel_size), dtype=np.uint8),
        iterations=1,
        borderType=cv2.BORDER_CONSTANT,
        borderValue=0,
    )
    if not np.any(valid_centers):
        valid_centers = cv2.erode(
            prepared.mask_128,
            np.ones((3, 3), dtype=np.uint8),
            iterations=1,
            borderType=cv2.BORDER_CONSTANT,
            borderValue=0,
        )

    responses: list[np.ndarray] = []
    for wavelength in config.gabor_wavelengths:
        for orientation in range(config.gabor_orientations):
            theta = orientation * np.pi / config.gabor_orientations
            kernel = cv2.getGaborKernel(
                (kernel_size, kernel_size),
                config.gabor_sigma_ratio * wavelength,
                theta,
                wavelength,
                config.gabor_gamma,
                0,
                ktype=cv2.CV_32F,
            )
            kernel -= float(kernel.mean())
            kernel /= float(np.linalg.norm(kernel)) + config.l2_eps
            responses.append(np.abs(cv2.filter2D(gray, cv2.CV_32F, kernel)))

    values: list[float] = []
    counts: list[int] = []
    height, width = gray.shape
    for row in range(config.gabor_rows):
        y0 = row * height // config.gabor_rows
        y1 = (row + 1) * height // config.gabor_rows
        for col in range(config.gabor_cols):
            x0 = col * width // config.gabor_cols
            x1 = (col + 1) * width // config.gabor_cols
            region_mask = valid_centers[y0:y1, x0:x1].astype(bool)
            count = int(np.count_nonzero(region_mask))
            counts.append(count)
            for response in responses:
                pixels = response[y0:y1, x0:x1][region_mask]
                if pixels.size:
                    values.extend((float(pixels.mean()), float(pixels.std())))
                else:
                    values.extend((0.0, 0.0))

    return _finalize(
        "gabor_spatial",
        np.asarray(values, dtype=np.float32),
        config,
        valid_count=sum(counts),
        region_valid_counts=counts,
        empty_regions=[count == 0 for count in counts],
    )


EXTRACTORS = {
    "hsv_global": extract_hsv_global,
    "hsv_spatial": extract_hsv_spatial,
    "lbp_spatial": extract_lbp_spatial,
    "hog": extract_hog,
    "gabor_spatial": extract_gabor_spatial,
}
