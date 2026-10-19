from __future__ import annotations

from functools import lru_cache
import logging
from pathlib import Path
from threading import Lock
from uuid import uuid4

import gradio as gr

from app.config import Settings
from app.search import ImageSearchService, build_all_feature_charts, build_feature_chart
from app.services import AnimalDetector, BackgroundRemover, ImageProcessor, ProcessingError
from app.utils.validation import ImageValidationError, load_validated_image

LOGGER = logging.getLogger(__name__)

APP_CSS = """
:root { --ink:#172033; --muted:#667085; --line:#e6e9ef; --brand:#2563eb; }
.gradio-container {max-width:1500px !important; background:#f7f8fb !important; color:var(--ink)}
.app-shell {padding:8px 4px 32px}
.app-title {text-align:center; margin-bottom:0 !important; letter-spacing:-.035em}
.app-subtitle {text-align:center; color:var(--muted); margin:6px auto 24px !important; max-width:780px}
.upload-panel,.result-panel,.chart-card {background:white; border:1px solid var(--line); border-radius:16px; box-shadow:0 8px 28px rgba(16,24,40,.055)}
.upload-panel {padding:18px}.result-panel {padding:8px 14px 16px}.chart-card {padding:14px; margin:10px 0}
.main-layout {align-items:flex-start !important; flex-wrap:nowrap !important}
.main-layout > .upload-panel {flex:0 0 min(34%, 390px) !important}
.main-layout > .result-panel {flex:1 1 auto !important; min-width:0 !important}
.eyebrow {color:var(--brand); font-size:.78rem; font-weight:700; letter-spacing:.08em; text-transform:uppercase}
.status-box {min-height:42px; color:var(--muted); font-size:.92rem}.feature-note {color:var(--muted); font-size:.88rem}
footer {display:none !important}
@media (max-width:800px) {
  .gradio-container {padding:10px !important}.upload-panel {padding:12px}
  .main-layout {flex-wrap:wrap !important}
  .main-layout > .upload-panel,.main-layout > .result-panel {flex:1 1 100% !important}
}
"""

_REQUEST_TOKENS: dict[str, str] = {}
_REQUEST_LOCK = Lock()


@lru_cache(maxsize=1)
def get_processor(settings: Settings | None = None) -> ImageProcessor:
    """Khởi tạo YOLO và BiRefNet một lần, sau đó tái sử dụng."""
    settings = settings or Settings()
    return ImageProcessor(settings, AnimalDetector(settings), BackgroundRemover(settings))


@lru_cache(maxsize=1)
def get_search_service() -> ImageSearchService:
    return ImageSearchService(Path(__file__).resolve().parents[1] / "public")


def _session_id(request: gr.Request | None) -> str:
    return request.session_hash if request and request.session_hash else "anonymous"


def _remember_new_request(request: gr.Request | None) -> str:
    token = uuid4().hex
    with _REQUEST_LOCK:
        _REQUEST_TOKENS[_session_id(request)] = token
    return token


def _ensure_current(token: str, request: gr.Request | None) -> None:
    with _REQUEST_LOCK:
        current = _REQUEST_TOKENS.get(_session_id(request))
    if current != token:
        raise gr.Error("Yêu cầu cũ đã bị hủy vì bạn chọn ảnh khác.")


def _on_image_change(image_path: str | None, settings: Settings, request: gr.Request | None = None):
    token = _remember_new_request(request)
    if not image_path:
        return token, gr.Column(visible=True), "Hãy chọn hoặc kéo thả một ảnh."
    try:
        image = load_validated_image(image_path, settings)
    except ImageValidationError as exc:
        raise gr.Error(str(exc)) from exc
    return (
        token,
        gr.Column(visible=True),
        f"Đã kiểm tra **{Path(image_path).name}** · {image.width}×{image.height}. Sẵn sàng trích xuất.",
    )


def _empty_outputs():
    return (None, [], "", None, "", None, "", None, "", None, "", None)


def _analyze(
    image_path: str | None,
    metric: str,
    top_k: int,
    request_token: str,
    hog_start: int,
    settings: Settings,
    request: gr.Request | None = None,
    progress=None,
):
    if not image_path:
        raise gr.Error("Vui lòng chọn một ảnh JPG, PNG hoặc WEBP.")
    _ensure_current(request_token, request)
    try:
        if progress is not None:
            progress(0.05, desc="Đang tách nền và chuẩn hóa ảnh…")
        output = get_search_service().search(
            image_path, get_processor(settings), metric=metric, top_k=int(top_k)
        )
        _ensure_current(request_token, request)
        if progress is not None:
            progress(0.9, desc="Đang chuẩn bị dữ liệu biểu đồ…")
        charts = build_all_feature_charts(output.feature_result, hog_start=int(hog_start))
    except (OSError, RuntimeError, ValueError, ProcessingError) as exc:
        message = exc.message if isinstance(exc, ProcessingError) else str(exc)
        raise gr.Error(f"Không thể xử lý ảnh: {message}") from exc

    return (
        output.query_image,
        output.gallery,
        output.details_json,
        charts["hsv_global"].dataframe,
        charts["hsv_global"].summary_markdown,
        charts["hsv_spatial"].dataframe,
        charts["hsv_spatial"].summary_markdown,
        charts["lbp_spatial"].dataframe,
        charts["lbp_spatial"].summary_markdown,
        charts["hog"].dataframe,
        charts["hog"].summary_markdown,
        output.feature_result,
        gr.Slider(maximum=max(0, charts["hog"].dimension - 1), value=0),
        f"Hoàn tất · tiền xử lý: **{output.preprocessing}** · {len(output.gallery)} kết quả tương đồng.",
    )


def _update_hog(feature_result, start: int):
    if feature_result is None:
        return None, ""
    chart = build_feature_chart(feature_result.features["hog"], start=int(start), limit=256)
    return chart.dataframe, chart.summary_markdown


def build_ui(output_directory: str | Path | None = None, settings: Settings | None = None) -> gr.Blocks:
    if settings is not None and output_directory is not None:
        raise ValueError("Chỉ truyền settings hoặc output_directory, không truyền cả hai.")
    resolved_settings = settings or (
        Settings(output_directory=Path(output_directory)) if output_directory is not None else Settings()
    )

    def analyze_from_ui(
        image: str | None,
        chosen_metric: str,
        count: int,
        token: str,
        start: int,
        request: gr.Request,
        progress=gr.Progress(),
    ):
        return _analyze(
            image, chosen_metric, count, token, start, resolved_settings, request, progress
        )

    def image_changed_from_ui(image: str | None, request: gr.Request):
        return _on_image_change(image, resolved_settings, request)

    with gr.Blocks(title="Animal Image Search") as demo:
        request_token = gr.State("")
        feature_state = gr.State()
        with gr.Column(elem_classes="app-shell"):
            gr.Markdown("# Animal Image Search", elem_classes="app-title")
            gr.Markdown(
                "Tách nền, chuẩn hóa và khám phá vector đặc trưng được dùng để tìm ảnh tương đồng.",
                elem_classes="app-subtitle",
            )
            with gr.Row(equal_height=False, elem_classes="main-layout"):
                with gr.Column(scale=4, min_width=300, elem_classes="upload-panel"):
                    gr.Markdown("<span class='eyebrow'>Ảnh truy vấn</span>")
                    image_input = gr.Image(
                        type="filepath", label="Kéo thả hoặc chọn ảnh",
                        sources=["upload", "clipboard"], height=330,
                    )
                    extract_button = gr.Button(
                        "Trích xuất đặc trưng & tìm kiếm", variant="primary", size="lg"
                    )
                    status = gr.Markdown("Hãy chọn hoặc kéo thả một ảnh.", elem_classes="status-box")
                    gr.Markdown("#### Thông số tìm kiếm")
                    top_k = gr.Slider(1, 20, value=5, step=1, label="Top K")
                    metric = gr.Dropdown(
                        [("Cosine similarity", "cosine"), ("Khoảng cách L2", "euclidean")],
                        value="cosine", label="Metric",
                    )
                    gr.Markdown(
                        f"Hỗ trợ JPG, PNG, WEBP · tối đa {resolved_settings.max_upload_mb} MB.",
                        elem_classes="feature-note",
                    )

                with gr.Column(scale=8, min_width=480, visible=True, elem_classes="result-panel") as output_panel:
                    with gr.Tabs():
                        with gr.Tab("Kết quả tìm kiếm"):
                            gr.Markdown("## Kết quả tìm kiếm")
                            normalized = gr.Image(
                                type="pil", label="Ảnh sau tách nền và chuẩn hóa 512×512",
                                image_mode="RGBA", height=300, interactive=False,
                            )
                            gallery = gr.Gallery(
                                label="Ảnh tương đồng", columns=3, object_fit="contain", height="auto"
                            )
                            details_json = gr.Code(label="Metadata tìm kiếm", language="json", interactive=False)

                        with gr.Tab("Chi tiết xử lí"):
                            gr.Markdown(
                                "## Chi tiết đặc trưng\nBiểu đồ dùng vector L2 thật được pipeline truyền sang "
                                "bước tìm kiếm. Di chuột lên điểm/cột để xem giá trị."
                            )
                            with gr.Column(elem_classes="chart-card"):
                                hsv_global_meta = gr.Markdown()
                                hsv_global_plot = gr.BarPlot(
                                    x="Chỉ số", y="Giá trị", title="Color Histogram · HSV toàn cục",
                                    x_title="Bin HSV", y_title="Giá trị L2", tooltip="all", height=300,
                                )
                            with gr.Column(elem_classes="chart-card"):
                                hsv_spatial_meta = gr.Markdown()
                                hsv_spatial_plot = gr.BarPlot(
                                    x="Chỉ số", y="Giá trị", color="Vùng", title="Spatial Color Histogram",
                                    x_title="Chỉ số vector ghép", y_title="Giá trị L2", tooltip="all", height=320,
                                )
                            with gr.Column(elem_classes="chart-card"):
                                lbp_meta = gr.Markdown()
                                lbp_plot = gr.BarPlot(
                                    x="Chỉ số", y="Giá trị", color="Vùng", title="LBP Histogram",
                                    x_title="Bin trong vector ghép", y_title="Giá trị L2", tooltip="all", height=320,
                                )
                            with gr.Column(elem_classes="chart-card"):
                                hog_meta = gr.Markdown()
                                hog_start = gr.Slider(
                                    0, 1763, value=0, step=1,
                                    label="Bắt đầu đoạn HOG (hiển thị tối đa 256 phần tử)",
                                )
                                hog_plot = gr.LinePlot(
                                    x="Chỉ số", y="Giá trị", title="HOG", x_title="Chỉ số phần tử",
                                    y_title="Giá trị L2", tooltip="all", height=330,
                                )

        analysis_outputs = [
            normalized, gallery, details_json, hsv_global_plot, hsv_global_meta,
            hsv_spatial_plot, hsv_spatial_meta, lbp_plot, lbp_meta, hog_plot, hog_meta,
            feature_state, hog_start, status,
        ]
        extract_event = extract_button.click(
            analyze_from_ui,
            inputs=[image_input, metric, top_k, request_token, hog_start], outputs=analysis_outputs,
            trigger_mode="once", concurrency_limit=1, show_progress="full", api_name="extract_and_search",
        )
        image_input.change(
            image_changed_from_ui,
            inputs=image_input, outputs=[request_token, output_panel, status], queue=False,
            cancels=[extract_event], api_name=False,
        ).then(
            _empty_outputs,
            outputs=[
                normalized, gallery, details_json, hsv_global_plot, hsv_global_meta,
                hsv_spatial_plot, hsv_spatial_meta, lbp_plot, lbp_meta, hog_plot, hog_meta,
                feature_state,
            ],
            queue=False,
        )
        hog_start.change(
            _update_hog, inputs=[feature_state, hog_start], outputs=[hog_plot, hog_meta],
            queue=False, api_name=False,
        )
    return demo


def launch(output_directory: str | Path | None = None, settings: Settings | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    build_ui(output_directory=output_directory, settings=settings).launch(
        inbrowser=True, css=APP_CSS
    )
