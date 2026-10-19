from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .config import DEFAULT_CONFIG, FeatureConfig
from .models import FeatureResult, FeatureVector


FEATURE_TITLES = {
    "hsv_global": "Color Histogram · HSV toàn cục",
    "hsv_spatial": "Spatial Color Histogram · HSV 2×2",
    "lbp_spatial": "LBP Histogram · lưới 4×4",
    "hog": "HOG · Histogram of Oriented Gradients",
}


@dataclass(frozen=True)
class FeatureChart:
    """Dữ liệu trình bày tách biệt khỏi bộ trích xuất."""

    name: str
    title: str
    dataframe: pd.DataFrame
    summary_markdown: str
    dimension: int


def _validated_display_vector(feature: FeatureVector) -> np.ndarray:
    vector = np.asarray(feature.l2_values, dtype=np.float32).reshape(-1)
    if vector.size == 0:
        raise ValueError(f"{feature.name}: vector rỗng.")
    if vector.size != feature.dim:
        raise ValueError(
            f"{feature.name}: vector có {vector.size} phần tử, metadata ghi {feature.dim}."
        )
    if not feature.valid:
        raise ValueError(
            f"{feature.name}: vector không hợp lệ ({feature.reason or 'không rõ nguyên nhân'})."
        )
    if not np.all(np.isfinite(vector)):
        raise ValueError(f"{feature.name}: vector chứa NaN hoặc Infinity.")
    return vector


def _parameters(name: str, config: FeatureConfig) -> str:
    if name == "hsv_global":
        return (
            f"HSV; bins H/S/V = {config.hsv_h_bins}/{config.hsv_s_bins}/{config.hsv_v_bins}; "
            "ghép bin theo thứ tự H → S → V; chỉ tính pixel trong alpha mask"
        )
    if name == "hsv_spatial":
        return (
            f"HSV; lưới {config.hsv_spatial_rows}×{config.hsv_spatial_cols} theo hàng; "
            f"mỗi vùng {config.hsv_h_bins}×{config.hsv_s_bins}×{config.hsv_v_bins} bins; "
            "ghép vùng từ trái sang phải, trên xuống dưới"
        )
    if name == "lbp_spatial":
        return (
            f"gray {config.gray_size}×{config.gray_size}; P={config.lbp_points}, "
            f"R={config.lbp_radius}, method={config.lbp_method}; lưới "
            f"{config.lbp_rows}×{config.lbp_cols}, {config.lbp_bins} bins/vùng; "
            "mask erode 3×3 cho tâm LBP hợp lệ"
        )
    if name == "hog":
        return (
            f"gray {config.gray_size}×{config.gray_size}; orientations={config.hog_orientations}; "
            f"pixels/cell={config.hog_pixels_per_cell}; cells/block={config.hog_cells_per_block}; "
            f"block norm={config.hog_block_norm}; transform_sqrt={config.hog_transform_sqrt}"
        )
    raise KeyError(name)


def _region_labels(name: str, length: int, config: FeatureConfig) -> list[str]:
    if name == "hsv_spatial":
        per_region = config.hsv_h_bins * config.hsv_s_bins * config.hsv_v_bins
        cols = config.hsv_spatial_cols
        return [
            f"Vùng {index // per_region + 1} "
            f"(r{index // per_region // cols + 1}, c{index // per_region % cols + 1})"
            for index in range(length)
        ]
    if name == "lbp_spatial":
        per_region = config.lbp_bins
        cols = config.lbp_cols
        return [
            f"Vùng {index // per_region + 1} "
            f"(r{index // per_region // cols + 1}, c{index // per_region % cols + 1})"
            for index in range(length)
        ]
    return ["Toàn ảnh"] * length


def build_feature_chart(
    feature: FeatureVector,
    *,
    config: FeatureConfig = DEFAULT_CONFIG,
    start: int = 0,
    limit: int | None = None,
) -> FeatureChart:
    vector = _validated_display_vector(feature)
    dimension = int(vector.size)
    start = max(0, min(int(start), dimension - 1))
    stop = dimension if limit is None else min(dimension, start + max(1, int(limit)))
    indices = np.arange(start, stop, dtype=np.int32)
    shown = vector[start:stop]
    data: dict[str, Any] = {
        "Chỉ số": indices,
        "Giá trị": shown,
    }
    if feature.name in {"hsv_spatial", "lbp_spatial"}:
        data["Vùng"] = _region_labels(feature.name, dimension, config)[start:stop]
    dataframe = pd.DataFrame(data)

    minimum = float(np.min(vector))
    maximum = float(np.max(vector))
    mean = float(np.mean(vector, dtype=np.float64))
    range_note = (
        f"  \n**Phạm vi đang xem:** [{start}, {stop - 1}] / {dimension} phần tử."
        if start != 0 or stop != dimension
        else ""
    )
    valid_pixels = (
        f" · Pixel/mẫu hợp lệ: **{feature.valid_count:,}**"
        if feature.valid_count is not None
        else ""
    )
    summary = (
        f"### {FEATURE_TITLES[feature.name]}\n"
        f"**Số chiều:** {dimension:,} · **Min:** {minimum:.6g} · "
        f"**Max:** {maximum:.6g} · **Mean:** {mean:.6g}{valid_pixels}  \n"
        f"**Chuẩn hóa hiển thị/tìm kiếm:** L2 (norm thô trước L2 = "
        f"{feature.norm_before_l2:.6g})  \n"
        f"**Tham số:** {_parameters(feature.name, config)}"
        f"{range_note}"
    )
    return FeatureChart(
        feature.name,
        FEATURE_TITLES[feature.name],
        dataframe,
        summary,
        dimension,
    )


def build_all_feature_charts(
    result: FeatureResult,
    *,
    config: FeatureConfig = DEFAULT_CONFIG,
    hog_start: int = 0,
    hog_limit: int = 256,
) -> dict[str, FeatureChart]:
    missing = [name for name in result.combined_order if name not in result.features]
    if missing:
        raise ValueError(f"Thiếu nhóm đặc trưng: {', '.join(missing)}.")
    return {
        name: build_feature_chart(
            result.features[name],
            config=config,
            start=hog_start if name == "hog" else 0,
            limit=hog_limit if name == "hog" else None,
        )
        for name in result.combined_order
    }
