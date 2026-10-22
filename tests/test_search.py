from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from app.search import (
    DEFAULT_CONFIG,
    COMBINED_FEATURE_DIM,
    FEATURE_DIMS,
    FEATURE_ORDER,
    LocalSearchIndex,
    SearchItem,
    extract_features,
    build_all_feature_charts,
    build_feature_chart,
    prepare_image,
    save_hog_visualization,
    standardize_rgba,
)
from app.search.models import FeatureResult, FeatureVector
from app.search.service import _format_result_caption


def rgba_fixture(color=(180, 90, 30)) -> Image.Image:
    image = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((70, 40, 442, 480), fill=(*color, 255))
    draw.rectangle((125, 90, 385, 430), fill=(*color, 255))
    return image


class FeatureExtractionTests(unittest.TestCase):
    def test_hog_visualization_is_saved_as_an_image(self):
        prepared = prepare_image(np.asarray(rgba_fixture(), dtype=np.uint8))
        with tempfile.TemporaryDirectory() as directory:
            output = save_hog_visualization(prepared, directory, "tiger_001")

            self.assertEqual(output, Path(directory) / "tiger_001_hog.png")
            self.assertTrue(output.is_file())
            with Image.open(output) as image:
                self.assertEqual(image.size, (128, 128))

    def test_feature_dimensions_and_combined_vector(self):
        image = np.asarray(rgba_fixture(), dtype=np.uint8)
        result = extract_features(prepare_image(image))
        self.assertEqual(
            {name: result.features[name].dim for name in FEATURE_ORDER},
            FEATURE_DIMS,
        )
        self.assertEqual(result.combined.shape, (COMBINED_FEATURE_DIM,))
        self.assertAlmostEqual(float(np.linalg.norm(result.combined)), 1.0, places=5)

    def test_standardize_keeps_aspect_ratio_and_alpha(self):
        source = Image.new("RGBA", (300, 120), (0, 0, 0, 0))
        ImageDraw.Draw(source).rectangle((80, 20, 220, 100), fill=(90, 120, 180, 255))
        output = standardize_rgba(source)
        self.assertEqual(output.size, (512, 512))
        bbox = output.getchannel("A").getbbox()
        self.assertIsNotNone(bbox)
        self.assertAlmostEqual(
            (bbox[2] - bbox[0]) / (bbox[3] - bbox[1]), 140 / 80, delta=0.04
        )

    def test_chart_data_matches_real_feature_vectors(self):
        result = extract_features(
            prepare_image(np.asarray(rgba_fixture(), dtype=np.uint8))
        )
        charts = build_all_feature_charts(result, hog_start=256, hog_limit=128)

        for name in ("hsv_global", "hsv_spatial", "lbp_spatial", "gabor_spatial"):
            self.assertEqual(len(charts[name].dataframe), result.features[name].dim)
            np.testing.assert_allclose(
                charts[name].dataframe["Giá trị"].to_numpy(),
                result.features[name].l2_values,
            )
        self.assertEqual(len(charts["hog"].dataframe), 128)
        self.assertEqual(int(charts["hog"].dataframe.iloc[0]["Chỉ số"]), 256)
        self.assertIn("[256, 383] / 1764", charts["hog"].summary_markdown)

    def test_chart_rejects_nan_instead_of_rendering_empty_result(self):
        result = extract_features(
            prepare_image(np.asarray(rgba_fixture(), dtype=np.uint8))
        )
        result.features["hog"].l2_values[4] = np.nan
        with self.assertRaisesRegex(ValueError, "NaN hoặc Infinity"):
            build_feature_chart(result.features["hog"])

    def test_gabor_spatial_is_finite_and_uses_expected_dimension(self):
        result = extract_features(
            prepare_image(np.asarray(rgba_fixture(), dtype=np.uint8))
        )
        gabor = result.features["gabor_spatial"]
        self.assertTrue(gabor.valid)
        self.assertEqual(gabor.dim, 512)
        self.assertTrue(np.all(np.isfinite(gabor.l2_values)))
        self.assertAlmostEqual(float(np.linalg.norm(gabor.l2_values)), 1.0, places=5)


class SearchIndexTests(unittest.TestCase):
    def test_gallery_caption_contains_rank_filename_and_score(self):
        caption = _format_result_caption(
            {
                "rank": 3,
                "source": r"D:\images\tiger_012.png",
                "score": 0.8361034,
            }
        )
        self.assertEqual(caption, "#3 tiger_012.png 0.836103")

    def test_self_query_is_ranked_first(self):
        rng = np.random.default_rng(11)
        count = 5
        groups: dict[str, np.ndarray] = {}
        for name in FEATURE_ORDER:
            values = rng.random((count, FEATURE_DIMS[name]), dtype=np.float32)
            values /= np.linalg.norm(values, axis=1, keepdims=True)
            groups[name] = values
        weights = dict(DEFAULT_CONFIG.weights)
        combined = np.stack(
            [
                np.concatenate(
                    [np.sqrt(weights[name]) * groups[name][row] for name in FEATURE_ORDER]
                )
                for row in range(count)
            ]
        ).astype(np.float32)
        index = LocalSearchIndex(
            [SearchItem(str(i), f"{i}.png", "test") for i in range(count)],
            combined,
            groups,
            target_pca_dim=4,
        )
        row = 2
        features = {
            name: FeatureVector(
                name,
                groups[name][row],
                groups[name][row],
                FEATURE_DIMS[name],
                True,
                None,
                1.0,
            )
            for name in FEATURE_ORDER
        }
        query = FeatureResult(
            DEFAULT_CONFIG.schema_version,
            DEFAULT_CONFIG.config_version,
            DEFAULT_CONFIG.extractor_version,
            DEFAULT_CONFIG.fingerprint,
            features,
            combined[row],
            list(FEATURE_ORDER),
            {},
        )
        response = index.search(query, top_k=3, metric="cosine")
        self.assertEqual(response["matches"][0]["image_id"], str(row))
        self.assertAlmostEqual(response["matches"][0]["score"], 1.0, places=5)
        self.assertEqual(
            set(response["matches"][0]["components"]), set(FEATURE_ORDER)
        )


if __name__ == "__main__":
    unittest.main()
