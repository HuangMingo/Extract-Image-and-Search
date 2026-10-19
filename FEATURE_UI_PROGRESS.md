# Tiến trình giao diện trích xuất đặc trưng

## Đã hoàn thành

- Thay giao diện nhiều chức năng bằng một trang truy vấn ảnh duy nhất.
- Giữ cố định bố cục hai cột input/output ngay cả khi chưa chọn ảnh; chỉ xếp dọc trên màn hình nhỏ dưới 800px.
- Kiểm tra dung lượng, định dạng, khả năng giải mã và số pixel ngay khi chọn ảnh.
- Tái sử dụng pipeline `YOLO-World → BiRefNet/rembg → RGBA 512×512 → extract_features`.
- Hiển thị hai tab kết quả sau khi có ảnh hợp lệ: **Kết quả tìm kiếm** và **Chi tiết xử lý**.
- Hiển thị vector L2 thật của bốn nhóm pipeline hỗ trợ: HSV toàn cục, HSV 2×2, LBP 4×4 và HOG.
- Mỗi khung có số chiều, min/max/mean trên toàn vector, tham số, chuẩn hóa và tooltip.
- HOG hiển thị tối đa 256 phần tử mỗi đoạn; thanh trượt cho phép xem đủ 1.764 phần tử và ghi rõ phạm vi.
- Token theo phiên hủy yêu cầu cũ khi đổi ảnh; sự kiện trích xuất chỉ cho phép một lần chạy đồng thời.
- Vector rỗng, sai số chiều, invalid, NaN và Infinity bị từ chối thay vì vẽ biểu đồ trống.

## Cách chạy

```powershell
pip install -r requirements.txt
python run.py
```

Chọn hoặc kéo thả JPG/PNG/WEBP, sau đó nhấn **Trích xuất đặc trưng & tìm kiếm**. PNG đã có alpha mask hữu ích được dùng trực tiếp; ảnh còn nền đi qua YOLO-World và BiRefNet.

## Kiểm tra

- `python -m unittest discover -v`: 24/24 test qua.
- End-to-end với `public/tiger/tiger_001.png` và `public/cheetah/cheetah_004.png`: index 130 ảnh, PCA 128 chiều, Top-5 hoạt động.
- Số điểm/cột xác nhận: 288 / 1.152 / 160; HOG có 1.764 chiều và hiển thị theo đoạn 256.

## Hạn chế

- Lần truy vấn đầu tiên phải lập chỉ mục trong bộ nhớ nên chậm hơn các lần sau.
- Ảnh chưa có alpha cần model YOLO-World/BiRefNet và checkpoint đã được cài hoặc cache.
- Môi trường kiểm tra không cung cấp browser UI automation; endpoint local đã trả HTTP 200 và cấu hình Gradio đã build thành công, nhưng chưa có visual screenshot QA tự động.
