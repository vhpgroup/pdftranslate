# -*- coding: utf-8 -*-
"""
Bo test tu dong cho pipeline dich PDF giu bo cuc.

Khong phu thuoc file ngoai: tu sinh PDF mau bang PyMuPDF (bang thong so gia lap,
doan van, tieu de, do hoa vector) roi chay tron ven plan -> translations -> apply
va kiem chung ket qua.

Chay:  pytest tests/ -v   (hoac: python3 tests/test_pipeline.py)
"""
import json
import os
import subprocess
import sys

import fitz  # PyMuPDF

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REBUILD = os.path.join(ROOT, "rebuild.py")


# ---------------------------------------------------------------- helpers
def make_sample_pdf(path):
    """PDF mau: tieu de + 3 hang bang (nhan|gia tri) + doan van 3 dong + khung ve."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    # tieu de dam
    page.insert_text((50, 60), "Product Specifications", fontsize=16, fontname="hebo")
    # khung bang (line art — phai duoc GIU sau khi dich)
    page.draw_rect(fitz.Rect(45, 95, 500, 185), color=(0.2, 0.2, 0.2), width=0.8)
    # 3 hang bang: nhan (x=55) va gia tri (x=260) cung dong
    rows = [("Warm-up time", "18 seconds"),
            ("Print speed", "25 ppm"),
            ("Memory capacity", "2 GB")]
    y = 115
    for label, val in rows:
        page.insert_text((55, y), label, fontsize=10)
        page.insert_text((260, y), val, fontsize=10)
        y += 25
    # doan van 3 dong don, cung co chu & le trai -> pipeline gop thanh 'para'
    para_lines = [
        "This device prints professional documents",
        "with high quality and reliable speed for",
        "modern office environments.",
    ]
    y = 230
    for line in para_lines:
        page.insert_text((55, y), line, fontsize=9)
        y += 11
    # dong don le de test redact-only (dich = "")
    page.insert_text((55, 320), "Internal draft note", fontsize=8)
    doc.save(path)
    doc.close()


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0, f"lenh {' '.join(cmd)} loi:\n{r.stdout}\n{r.stderr}"
    return r.stdout


def pipeline(tmp, translations_by_text):
    """Chay plan -> map ban dich theo text -> apply. Tra ve (units, out_pdf_path)."""
    src = os.path.join(tmp, "sample.pdf")
    units_p = os.path.join(tmp, "units.json")
    trans_p = os.path.join(tmp, "translations.json")
    out_p = os.path.join(tmp, "out.pdf")
    make_sample_pdf(src)
    run([sys.executable, REBUILD, "plan", src, units_p])
    units = json.load(open(units_p, encoding="utf-8"))
    trans = {}
    for u in units:
        for key, vi in translations_by_text.items():
            if u["text"].startswith(key):
                trans[u["id"]] = vi
    json.dump(trans, open(trans_p, "w", encoding="utf-8"), ensure_ascii=False)
    run([sys.executable, REBUILD, "apply", src, units_p, trans_p, out_p])
    return units, out_p


TRANS = {
    # moi o (label / value) la mot don vi rieng — dich theo tung o nhu catalog that
    "Product Specifications": "Thông số kỹ thuật sản phẩm",
    "Warm-up time": "Thời gian khởi động",
    "18 seconds": "18 giây",
    "Print speed": "Tốc độ in",
    "25 ppm": "25 trang/phút",
    "Internal draft note": "",  # redact-only: chi xoa, khong chen
    "This device prints professional documents":
        "Thiết bị này in tài liệu chuyên nghiệp với chất lượng cao và tốc độ "
        "ổn định cho môi trường văn phòng hiện đại.",
    # hang "Memory capacity" + "2 GB" khong dua vao -> giu nguyen pixel goc
}


# ---------------------------------------------------------------- tests
def test_plan_detects_units(tmp_path):
    src = str(tmp_path / "sample.pdf")
    units_p = str(tmp_path / "units.json")
    make_sample_pdf(src)
    run([sys.executable, REBUILD, "plan", src, units_p])
    units = json.load(open(units_p, encoding="utf-8"))
    texts = " | ".join(u["text"] for u in units)
    assert len(units) >= 5, f"qua it don vi: {len(units)}"
    for expected in ("Product Specifications", "Warm-up time", "18 seconds", "2 GB"):
        assert expected in texts, f"thieu don vi '{expected}'"
    # doan van 3 dong phai duoc GOP thanh 1 unit (para hoac block deu hop le)
    para = [u for u in units if u["text"].startswith("This device prints")]
    assert para, "khong thay unit doan van"
    assert para[0]["mode"] in ("para", "block"), f"mode la {para[0]['mode']}"
    assert "office environments" in para[0]["text"], "doan van gop thieu dong"


def test_apply_translates_and_preserves(tmp_path):
    _, out_p = pipeline(str(tmp_path), TRANS)
    doc = fitz.open(out_p)
    # chuan hoa khoang trang: text chay dong co the ngat giua cum tu
    norm = " ".join("".join(p.get_text() for p in doc).split())
    # 1) ban dich tieng Viet co mat, dung dau
    for vi in ("Thông số kỹ thuật sản phẩm", "Thời gian khởi động",
               "18 giây", "25 trang/phút", "môi trường văn phòng"):
        assert vi in norm, f"thieu ban dich: {vi}"
    # 2) chu goc da bi xoa
    for en in ("Warm-up time", "18 seconds", "Product Specifications"):
        assert en not in norm, f"chu goc con sot: {en}"
    # 3) hang khong dich -> giu nguyen pixel goc (ca nhan lan gia tri)
    assert "Memory capacity" in norm and "2 GB" in norm, "hang khong dich phai giu nguyen"
    # 4) redact-only (''): chu bien mat, khong co gi thay the
    assert "Internal draft note" not in norm, "redact-only khong xoa duoc chu"
    # 5) do hoa vector (khung bang) phai con
    assert len(doc[0].get_drawings()) >= 1, "line art bi mat sau khi dich"


def test_unchanged_units_untouched(tmp_path):
    """Khong dich gi ca -> file giu nguyen text goc."""
    src = str(tmp_path / "sample.pdf")
    units_p = str(tmp_path / "units.json")
    trans_p = str(tmp_path / "translations.json")
    out_p = str(tmp_path / "out.pdf")
    make_sample_pdf(src)
    run([sys.executable, REBUILD, "plan", src, units_p])
    json.dump({}, open(trans_p, "w"))
    run([sys.executable, REBUILD, "apply", src, units_p, trans_p, out_p])
    text = "".join(p.get_text() for p in fitz.open(out_p))
    assert "Warm-up time" in text and "2 GB" in text


def test_glossaries_valid():
    for name in ("glossary_vi.json", "glossary_camera_vi.json"):
        p = os.path.join(ROOT, "glossaries", name)
        d = json.load(open(p, encoding="utf-8"))
        assert isinstance(d.get("terms"), dict) and len(d["terms"]) >= 50, name
        # gia tri glossary phai la tieng Viet co dau (unicode ngoai ASCII)
        joined = "".join(d["terms"].values())
        assert any(ord(c) > 127 for c in joined), f"{name}: khong thay dau tieng Viet"


def test_scripts_compile():
    import py_compile
    for f in ("rebuild.py", "extract.py", "translate_api_example.py"):
        py_compile.compile(os.path.join(ROOT, f), doraise=True)


if __name__ == "__main__":
    # chay khong can pytest
    import tempfile
    fails = 0
    for fn in (test_plan_detects_units, test_apply_translates_and_preserves,
               test_unchanged_units_untouched):
        with tempfile.TemporaryDirectory() as td:
            try:
                from pathlib import Path
                fn(Path(td))
                print(f"PASS {fn.__name__}")
            except AssertionError as e:
                print(f"FAIL {fn.__name__}: {e}"); fails += 1
    for fn in (test_glossaries_valid, test_scripts_compile):
        try:
            fn(); print(f"PASS {fn.__name__}")
        except AssertionError as e:
            print(f"FAIL {fn.__name__}: {e}"); fails += 1
    sys.exit(1 if fails else 0)
