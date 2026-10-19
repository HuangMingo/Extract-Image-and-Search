from __future__ import annotations

import json
from pathlib import Path
import sys
from types import SimpleNamespace

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import Settings
from app.search.config import DEFAULT_CONFIG, FEATURE_ORDER
from app.search.service import ImageSearchService


OUT = ROOT / "output" / "report_assets"
QUERY = ROOT / "public" / "tiger" / "tiger_001.png"


def checkerboard(width: int, height: int, square: int = 20) -> Image.Image:
    yy, xx = np.indices((height, width))
    grid = ((xx // square + yy // square) % 2)[..., None]
    colors = np.array([[238, 241, 246], [208, 214, 224]], dtype=np.uint8)
    rgb = colors[grid[..., 0]]
    return Image.fromarray(rgb, "RGB")


def on_checkerboard(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    bg = checkerboard(*rgba.size)
    bg.paste(rgba, (0, 0), rgba)
    return bg


def configure_plotting() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 9,
            "axes.titlesize": 11,
            "axes.labelsize": 9,
            "figure.facecolor": "white",
            "axes.facecolor": "#F8FAFC",
            "axes.edgecolor": "#CBD5E1",
            "axes.grid": True,
            "grid.color": "#E2E8F0",
            "grid.linewidth": 0.6,
        }
    )


def save_preprocessing(query: Image.Image, result) -> None:
    rgba = np.asarray(query.convert("RGBA"), dtype=np.uint8)
    alpha = rgba[..., 3]
    gray = np.asarray(result.feature_result.metadata.get("gray", []))
    rgb = rgba[..., :3].copy()
    rgb[alpha == 0] = 0
    gray512 = np.dot(rgb[..., :3], [0.299, 0.587, 0.114]).astype(np.uint8)
    gray128 = np.asarray(
        Image.fromarray(gray512).resize((128, 128), Image.Resampling.BOX)
    ).copy()
    mask128 = np.asarray(Image.fromarray((alpha > 0).astype(np.uint8) * 255).resize((128, 128), Image.Resampling.NEAREST))
    gray128[mask128 == 0] = 0

    fig, axes = plt.subplots(1, 3, figsize=(11.6, 3.7), constrained_layout=True)
    axes[0].imshow(on_checkerboard(query))
    axes[0].set_title("Ảnh RGBA chuẩn hóa 512×512")
    axes[1].imshow(alpha, cmap="gray", vmin=0, vmax=255)
    axes[1].set_title("Alpha mask dùng để chọn foreground")
    axes[2].imshow(gray128, cmap="gray", vmin=0, vmax=255)
    axes[2].set_title("Ảnh xám 128×128 cho LBP và HOG")
    for ax in axes:
        ax.axis("off")
    fig.savefig(OUT / "01_tien_xu_ly.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


def save_feature_vectors(feature_result) -> None:
    vectors = {name: feature_result.features[name].l2_values for name in FEATURE_ORDER}
    fig, axes = plt.subplots(2, 2, figsize=(11.6, 7.3), constrained_layout=True)
    specifications = [
        ("hsv_global", "HSV toàn cục · 288 chiều", "#2563EB", "bar"),
        ("hsv_spatial", "HSV lưới 2×2 · 1.152 chiều", "#0F766E", "line"),
        ("lbp_spatial", "LBP lưới 4×4 · 160 chiều", "#D97706", "bar"),
        ("hog", "HOG · 1.764 chiều", "#7C3AED", "line"),
    ]
    for ax, (name, title, color, kind) in zip(axes.ravel(), specifications):
        values = vectors[name]
        x = np.arange(values.size)
        if kind == "bar":
            ax.bar(x, values, width=1.0, color=color, linewidth=0)
        else:
            ax.plot(x, values, color=color, linewidth=0.8)
        ax.set_title(title)
        ax.set_xlabel("Chỉ số phần tử")
        ax.set_ylabel("Giá trị sau chuẩn hóa L2")
        ax.set_xlim(0, max(1, values.size - 1))
    fig.savefig(OUT / "02_vector_dac_trung.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


def save_search_montage(query: Image.Image, details: dict) -> None:
    matches = details["matches"]
    fig, axes = plt.subplots(2, 3, figsize=(11.6, 7.2), constrained_layout=True)
    panels = [(query, "Ảnh truy vấn\ntiger_001.png")]
    for match in matches:
        with Image.open(match["source"]) as opened:
            panels.append(
                (
                    on_checkerboard(opened.convert("RGBA")).copy(),
                    f"Hạng {match['rank']} · {Path(match['source']).name}\nĐiểm tổng hợp {match['score']:.6f}",
                )
            )
    for ax, (image, title) in zip(axes.ravel(), panels):
        ax.imshow(on_checkerboard(image) if image.mode == "RGBA" else image)
        ax.set_title(title, fontsize=9.5)
        ax.axis("off")
    fig.savefig(OUT / "03_ket_qua_tim_kiem.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


def save_component_scores(details: dict) -> None:
    matches = details["matches"][1:]
    labels = [f"#{m['rank']} {Path(m['source']).stem}" for m in matches]
    names = ["hsv_global", "hsv_spatial", "lbp_spatial", "hog"]
    display = ["HSV toàn cục", "HSV 2×2", "LBP 4×4", "HOG"]
    colors = ["#2563EB", "#0F766E", "#D97706", "#7C3AED"]
    x = np.arange(len(labels))
    width = 0.18
    fig, ax = plt.subplots(figsize=(11.6, 4.5), constrained_layout=True)
    for idx, (name, title, color) in enumerate(zip(names, display, colors)):
        ax.bar(
            x + (idx - 1.5) * width,
            [m["components"][name] for m in matches],
            width,
            label=title,
            color=color,
        )
    ax.plot(x, [m["score"] for m in matches], "o-", color="#111827", label="Điểm tổng hợp", linewidth=1.8)
    ax.set_xticks(x, labels)
    ax.set_ylim(0.6, 1.02)
    ax.set_ylabel("Độ tương đồng")
    ax.set_title("Điểm thành phần và điểm tổng hợp của bốn kết quả khác ảnh truy vấn")
    ax.legend(ncol=5, loc="lower center", bbox_to_anchor=(0.5, -0.28), frameon=False)
    fig.savefig(OUT / "04_diem_thanh_phan.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    configure_plotting()
    service = ImageSearchService(ROOT / "public")
    output = service.search(
        QUERY,
        SimpleNamespace(settings=Settings()),
        metric="cosine",
        top_k=5,
    )
    details = json.loads(output.details_json)
    save_preprocessing(output.query_image, output)
    save_feature_vectors(output.feature_result)
    save_search_montage(output.query_image, details)
    save_component_scores(details)

    feature_stats = {}
    for name in FEATURE_ORDER:
        feature = output.feature_result.features[name]
        values = feature.l2_values.astype(np.float64)
        feature_stats[name] = {
            "dimension": int(feature.dim),
            "valid_count": int(feature.valid_count or 0),
            "norm_before_l2": float(feature.norm_before_l2),
            "minimum": float(values.min()),
            "maximum": float(values.max()),
            "mean": float(values.mean()),
        }
    summary = {
        "query": str(QUERY.resolve()),
        "preprocessing": output.preprocessing,
        "details": details,
        "feature_stats": feature_stats,
        "weights": dict(DEFAULT_CONFIG.weights),
        "config": DEFAULT_CONFIG.as_dict(),
    }
    (OUT / "run_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output": "output/report_assets",
                "images": details["index"]["images"],
                "elapsed": details["elapsed_seconds"],
            },
            ensure_ascii=True,
        )
    )


if __name__ == "__main__":
    main()
