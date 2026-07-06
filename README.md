# pdftranslate — Dịch catalog PDF giữ nguyên bố cục (EN → VI)

[![tests](https://github.com/vhpgroup/pdftranslate/actions/workflows/test.yml/badge.svg)](https://github.com/vhpgroup/pdftranslate/actions/workflows/test.yml)

Pipeline dịch file PDF dạng catalog/brochure/tài liệu kỹ thuật từ tiếng Anh sang tiếng Việt,
**giữ nguyên 100% bố cục**: hình ảnh, bảng biểu, bản vẽ kỹ thuật, màu chữ, vị trí từng ô.
Chỉ lớp chữ được thay bằng tiếng Việt.

Đã kiểm chứng trên 2 catalog thực tế (12 trang, ~570 đơn vị dịch):
- RICOH IM 2500–6000 (brochure máy in, bảng thông số 6 cột)
- RICOH FV Series (camera công nghiệp: bản vẽ kỹ thuật, sơ đồ chân, biểu đồ timing)

## Kiến trúc — 3 bước tách rời

```
┌──────────┐     ┌─────────────┐     ┌──────────┐     ┌──────────┐
│  1. PLAN │ ──▶ │  2. DỊCH    │ ──▶ │ 3. APPLY │ ──▶ │  4. QA   │
│ phân tích│     │ (thay được: │     │ dựng lại │     │ render   │
│ units.json│    │ GPT-4.1/...)│     │   PDF    │     │ so sánh  │
└──────────┘     └─────────────┘     └──────────┘     └──────────┘
```

Bước DỊCH là **module tách rời** (`units.json → translations.json`) — gắn bất kỳ
LLM nào tương thích OpenAI API (GPT-4.1, ...) hoặc dịch thủ công/bằng agent.

## Cài đặt

```bash
pip install -r requirements.txt   # pymupdf
```

Cần font hỗ trợ tiếng Việt (mặc định DejaVu Sans Condensed — có sẵn trên đa số Linux;
Windows/macOS: sửa đường dẫn `FONT_REG`/`FONT_BOLD` đầu file `rebuild.py`).

## Sử dụng

### Bước 1 — Phân tích PDF thành đơn vị dịch
```bash
python3 rebuild.py plan input.pdf units.json
```
Tự nhận dạng 3 loại đơn vị:
- `cell` — ô bảng / nhãn / chú thích bản vẽ (thay tại đúng baseline, tự thu nhỏ theo bề rộng cột)
- `para` — đoạn văn nhiều dòng (gộp, dịch cả đoạn, chảy lại trong vùng gốc)
- `block` — khối tiêu đề / ghi chú (chảy lại trong bbox)

### Bước 2 — Dịch (chọn một trong hai)
```bash
# a) Dùng LLM qua API (OpenAI-compatible, ví dụ GPT-4.1):
export OPENAI_API_KEY=sk-...
python3 translate_api_example.py units.json glossaries/glossary_vi.json translations.json --model gpt-4.1

# b) Hoặc tự tạo translations.json = {"unit_id": "bản dịch", ...}
```
Quy ước quan trọng:
- Đơn vị **không có** trong translations.json → giữ nguyên pixel gốc (dùng cho ô thuần số liệu/mã).
- Bản dịch `""` (rỗng) → chỉ xóa, không chèn (gộp mảnh ®/™, nhãn xếp chồng 2 dòng vào ô chính).
- Bản dịch có `\n` khớp số dòng gốc → đặt từng dòng vào đúng vị trí dòng gốc (badge có đường kẻ giữa).

### Bước 3 — Dựng lại PDF
```bash
python3 rebuild.py apply input.pdf units.json translations.json output.pdf [anchors.json]
```
- Xóa chữ gốc bằng redaction **không tô nền**, giữ nguyên ảnh + đồ họa vector.
- `anchors.json` (tùy chọn) — danh sách bullet neo ô vuông vector:
  `{"unit_id": {"items": ["mục 1", "mục 2"]}}` — mỗi mục đặt đúng vị trí từng ô vuông bullet.

### Bước 4 — QA (bắt buộc)
Render từng trang gốc/dịch cạnh nhau và duyệt bằng mắt:
```python
import fitz
doc = fitz.open("output.pdf")
for i, page in enumerate(doc):
    page.get_pixmap(dpi=110).save(f"qa_p{i+1}.png")
```
Sửa translations.json → chạy lại apply **từ file gốc** (không apply chồng lên file đã dịch).

## Quy tắc dịch (bất di bất dịch)

GIỮ NGUYÊN: số liệu, đơn vị kỹ thuật (dpi, GB, g/m², V, Hz, lux, fps...), mã model/SKU,
thương hiệu/phần mềm/chuẩn (PostScript, Camera Link, GigE Vision...), tên tín hiệu điện
(GND, TRIGGER, POWER IN...), badge/logo. Chi tiết + thuật ngữ chuẩn: xem `glossaries/`.

## Cấu trúc repo

| File | Vai trò |
|------|---------|
| `rebuild.py` | Pipeline chính: `plan` / `apply` (redaction, anchored bullets, title-size fix) |
| `extract.py` | Công cụ chẩn đoán: dump block/span kèm font, cỡ, màu ra JSON |
| `translate_api_example.py` | Module dịch tách rời — gắn GPT-4.1 hoặc API tương thích OpenAI |
| `glossaries/glossary_vi.json` | Thuật ngữ máy in / thiết bị văn phòng (112 mục) |
| `glossaries/glossary_camera_vi.json` | Thuật ngữ camera công nghiệp / machine vision (63 mục) |
| `app.py` | App desktop Tkinter — chạy trọn pipeline, đóng gói được .exe |
| `docs/ui-mockup.html` | Mockup UI app desktop (mở trực tiếp bằng trình duyệt) |

## App desktop (.exe)

`app.py` là GUI Tkinter chạy trọn pipeline (chọn PDF → nhập API key GPT-4.1 → nhận PDF tiếng Việt):

```bash
python3 app.py                      # chạy từ mã nguồn (cần Python + pymupdf)
```

**Tải .exe Windows**: vào tab **Actions → build-exe → Run workflow**, chờ build xong rồi
tải artifact **PDFTranslate-windows** (không cần cài Python). Push tag `v*` sẽ tự tạo
Release kèm file .exe. Trên Windows app dùng font Arial/Segoe UI bản địa (đủ dấu tiếng Việt).

## Chạy test

```bash
pip install pytest
pytest tests/ -v            # hoac: python3 tests/test_pipeline.py
```
Bộ test tự sinh PDF mẫu (không cần file ngoài) và kiểm chứng trọn pipeline:
phát hiện đơn vị, dịch đúng dấu tiếng Việt, giữ nguyên ô không dịch, redact-only,
bảo toàn đồ họa vector. CI chạy tự động trên Ubuntu (Python 3.9 & 3.12) mỗi khi push.

Font: `rebuild.py` tự dò DejaVu trên Fedora/Ubuntu/macOS/Windows; ghi đè bằng biến
môi trường `PDFTRANSLATE_FONT_REG` / `PDFTRANSLATE_FONT_BOLD` / `PDFTRANSLATE_FONT_ITAL`.

## Giới hạn đã biết

- **PDF scan** (không có lớp chữ): cần OCR trước (tesseract + vie/eng), độ trung thực thấp hơn.
- **Chữ in chết trong ảnh bitmap**: không thay được bằng redaction.
- **Chữ xoay dọc**: hiện chưa hỗ trợ chèn xoay (hiếm gặp ở catalog).
- Tiếng Việt dài hơn EN 15–30% → pipeline tự thu nhỏ font; ô quá chật nên dịch ngắn lại.
