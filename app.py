# -*- coding: utf-8 -*-
"""
PDF Translate — App desktop dịch catalog PDF Anh → Việt giữ nguyên bố cục.

GUI Tkinter (đóng gói được thành .exe bằng PyInstaller). Quy trình:
  1. Chọn file PDF tiếng Anh
  2. Nhập API key (OpenAI-compatible, mặc định model gpt-4.1)
  3. Bấm "Dịch" — app chạy: plan → dịch theo glossary → apply → lưu PDF tiếng Việt

Chạy từ mã nguồn:  python3 app.py
Đóng gói .exe:     pyinstaller --onefile --windowed --name PDFTranslate ^
                     --add-data "glossaries;glossaries" app.py
"""
import json
import os
import re
import sys
import threading
import urllib.request

# ---------------------------------------------------------------- resources
def resource_dir():
    """Thư mục tài nguyên: cạnh script, hoặc trong bundle PyInstaller."""
    if getattr(sys, "_MEIPASS", None):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


sys.path.insert(0, resource_dir())
import rebuild  # noqa: E402  (pipeline chính, cùng thư mục)


# ---------------------------------------------------------------- dịch (module tách rời)
SYSTEM_PROMPT = """Ban la bien dich vien tai lieu ky thuat Anh -> Viet cho catalog san pham.
QUY TAC BAT BUOC:
1. Giu nguyen: so lieu, don vi (dpi, GB, g/m2, V, Hz...), ma model/SKU, ten thuong hieu/phan mem, ten tin hieu dien.
2. Ap dung glossary duoc cung cap mot cach NHAT QUAN tuyet doi.
3. Muc nao toan ma san pham/ten rieng/danh sach phien ban (Windows, Adobe, Intel...) -> tra ve NGUYEN VAN 100%, khong sua mot ky tu nao.
4. Tra ve JSON: {"id": "ban dich", ...} cho DUNG cac id duoc giao, khong them bot."""


INVISIBLE_CHARS = "\u200b\u200c\u200d\ufeff\u00a0\u2060"


def sanitize_api_key(key):
    """Loai ky tu an/xuong dong do copy-paste; bat loi key khong hop le TRUOC khi goi API."""
    key = "".join(ch for ch in (key or "") if not ch.isspace() and ch not in INVISIBLE_CHARS)
    if not key:
        raise ValueError("Chưa nhập API key.")
    if not key.isascii():
        bad = sorted({ch for ch in key if ord(ch) > 127})[:5]
        raise ValueError(
            "API key chứa ký tự không hợp lệ (thường do copy/paste kèm ký tự ẩn "
            f"hoặc bị chuyển mã): {', '.join(repr(b) for b in bad)}\n"
            "→ Hãy dán lại key trực tiếp từ trang API của nhà cung cấp (platform.openai.com).")
    return key


def call_llm(base_url, api_key, model, messages):
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        headers={"Authorization": "Bearer " + sanitize_api_key(api_key),
                 "Content-Type": "application/json"},
        data=json.dumps({"model": model, "messages": messages,
                         "response_format": {"type": "json_object"}}).encode())
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(json.load(r)["choices"][0]["message"]["content"])
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode("utf-8", "replace"))["error"]["message"]
        except Exception:  # noqa: BLE001
            detail = e.reason
        hint = {401: "API key sai hoặc hết hạn.",
                403: "Key không có quyền dùng model này.",
                404: "Model không tồn tại — kiểm tra ô Model.",
                429: "Hết hạn mức/quota hoặc gọi quá nhanh."}.get(e.code, "")
        raise RuntimeError(f"API trả lỗi {e.code}: {detail} {hint}".strip()) from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"Không kết nối được API ({e.reason}). "
                           "Kiểm tra mạng và Base URL.") from None


VN_DIACRITICS = re.compile(r"[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ]", re.I)


def is_fragile(u):
    """Don vi de vo: manh ®/™ co nho, danh sach ten rieng — KHONG gui cho LLM."""
    t = u["text"].strip()
    if u.get("size", 9) <= 5.2:          # manh superscript (®/™) co 4-5pt
        return True
    if t[:1] in "®™©":
        return True
    return False


def echo_mutated(original, translated):
    """LLM 'echo' lai ten rieng nhung sai lech nho -> giu nguyen ban goc.
    Dau hieu: ban dich KHONG co dau tieng Viet nhung van trung >=50% tu voi goc."""
    if VN_DIACRITICS.search(translated):
        return False
    ot = set(re.findall(r"[A-Za-z0-9]+", original.lower()))
    tt = set(re.findall(r"[A-Za-z0-9]+", translated.lower()))
    if not ot or not tt:
        return False
    overlap = len(ot & tt) / max(len(ot), len(tt))
    return overlap >= 0.5


def translate_units(units, glossary, base_url, api_key, model,
                    batch=30, progress=lambda msg: None, llm=None):
    """Dịch các đơn vị có chữ. llm: hàm inject để test không cần API thật."""
    llm = llm or (lambda msgs: call_llm(base_url, api_key, model, msgs))
    todo = [u for u in units
            if re.search(r"[A-Za-z]{2,}", u["text"]) and not is_fragile(u)]
    result = {}
    for i in range(0, len(todo), batch):
        chunk = {u["id"]: u["text"] for u in todo[i:i + batch]}
        out = llm([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content":
                "GLOSSARY:\n" + json.dumps(glossary.get("terms", {}), ensure_ascii=False)
                + "\n\nDich cac muc sau sang tieng Viet (muc la ma/ten rieng thi tra ve nguyen van):\n"
                + json.dumps(chunk, ensure_ascii=False)}])
        texts = {u["id"]: u["text"] for u in todo[i:i + batch]}
        for k, v in out.items():
            if not isinstance(v, str) or k not in texts:
                continue
            if echo_mutated(texts[k], v):
                continue  # echo dot bien ten rieng -> giu nguyen pixel goc
            result[k] = v
        progress(f"đã dịch {min(i + batch, len(todo))}/{len(todo)} đơn vị")
    return result


def run_pipeline(pdf_path, out_path, glossary_path, base_url, api_key, model,
                 progress=lambda msg: None, llm=None):
    """Chạy trọn pipeline: plan → dịch → apply. Trả về đường dẫn PDF kết quả."""
    work = os.path.join(os.path.dirname(out_path) or ".", "_pdftranslate_work")
    os.makedirs(work, exist_ok=True)
    units_p = os.path.join(work, "units.json")
    trans_p = os.path.join(work, "translations.json")

    progress("Bước 1/3 — Phân tích bố cục PDF…")
    rebuild.cmd_plan(pdf_path, units_p)
    units = json.load(open(units_p, encoding="utf-8"))
    progress(f"  → {len(units)} đơn vị bố cục")

    progress(f"Bước 2/3 — Dịch bằng {model}…")
    glossary = json.load(open(glossary_path, encoding="utf-8")) if glossary_path else {"terms": {}}
    trans = translate_units(units, glossary, base_url, api_key, model,
                            progress=progress, llm=llm)
    # bỏ các bản dịch trùng nguyên văn (giữ nguyên pixel gốc)
    trans = {k: v for k, v in trans.items()
             if v.strip() and v != next((u["text"] for u in units if u["id"] == k), None)}
    json.dump(trans, open(trans_p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    progress(f"  → {len(trans)} bản dịch (phần còn lại giữ nguyên)")

    progress("Bước 3/3 — Dựng lại PDF (giữ hình ảnh, bảng, đồ họa)…")
    rebuild.cmd_apply(pdf_path, units_p, trans_p, out_path)
    progress(f"✓ Hoàn tất: {out_path}")
    return out_path


def list_glossaries():
    gdir = os.path.join(resource_dir(), "glossaries")
    if not os.path.isdir(gdir):
        return {}
    return {fn: os.path.join(gdir, fn)
            for fn in sorted(os.listdir(gdir)) if fn.endswith(".json")}


# ---------------------------------------------------------------- GUI
def main():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title("PDF Translate — Dịch catalog Anh → Việt giữ bố cục")
    root.geometry("720x560")

    frm = ttk.Frame(root, padding=14)
    frm.pack(fill="both", expand=True)

    # --- chọn file
    pdf_var = tk.StringVar()
    ttk.Label(frm, text="File PDF tiếng Anh:").grid(row=0, column=0, sticky="w")
    ttk.Entry(frm, textvariable=pdf_var, width=62).grid(row=0, column=1, sticky="we", padx=6)

    def pick():
        p = filedialog.askopenfilename(filetypes=[("PDF", "*.pdf")])
        if p:
            pdf_var.set(p)
    ttk.Button(frm, text="Chọn…", command=pick).grid(row=0, column=2)

    # --- cấu hình API
    box = ttk.LabelFrame(frm, text=" Model dịch (OpenAI-compatible) ", padding=10)
    box.grid(row=1, column=0, columnspan=3, sticky="we", pady=(12, 0))
    url_var = tk.StringVar(value=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"))
    key_var = tk.StringVar(value=os.environ.get("OPENAI_API_KEY", ""))
    model_var = tk.StringVar(value="gpt-4.1")
    ttk.Label(box, text="Base URL:").grid(row=0, column=0, sticky="w")
    ttk.Entry(box, textvariable=url_var, width=44).grid(row=0, column=1, sticky="we", padx=6)
    ttk.Label(box, text="Model:").grid(row=0, column=2, sticky="w")
    ttk.Entry(box, textvariable=model_var, width=14).grid(row=0, column=3, padx=6)
    ttk.Label(box, text="API key:").grid(row=1, column=0, sticky="w", pady=(6, 0))
    ttk.Entry(box, textvariable=key_var, width=44, show="•").grid(
        row=1, column=1, sticky="we", padx=6, pady=(6, 0))
    ttk.Label(box, text="Glossary:").grid(row=1, column=2, sticky="w", pady=(6, 0))
    glossaries = list_glossaries()
    gl_var = tk.StringVar(value=next(iter(glossaries), ""))
    ttk.Combobox(box, textvariable=gl_var, values=list(glossaries), width=26,
                 state="readonly").grid(row=1, column=3, padx=6, pady=(6, 0))

    # --- log + progress
    prog = ttk.Progressbar(frm, mode="indeterminate")
    prog.grid(row=2, column=0, columnspan=3, sticky="we", pady=(12, 4))
    log = tk.Text(frm, height=14, state="disabled", bg="#111420", fg="#d7dce8",
                  font=("Consolas", 9))
    log.grid(row=3, column=0, columnspan=3, sticky="nsew", pady=(4, 8))
    frm.rowconfigure(3, weight=1)
    frm.columnconfigure(1, weight=1)

    def add_log(msg):
        log.configure(state="normal")
        log.insert("end", msg + "\n")
        log.see("end")
        log.configure(state="disabled")

    # --- nút chạy
    def start():
        pdf = pdf_var.get().strip()
        if not pdf or not os.path.exists(pdf):
            messagebox.showwarning("Thiếu file", "Hãy chọn file PDF tiếng Anh.")
            return
        try:
            sanitize_api_key(key_var.get())
        except ValueError as ve:
            messagebox.showwarning("API key không hợp lệ", str(ve))
            return
        out = os.path.splitext(pdf)[0] + "_TiengViet.pdf"
        btn.configure(state="disabled")
        prog.start(12)

        def work():
            try:
                run_pipeline(pdf, out, glossaries.get(gl_var.get()),
                             url_var.get().strip(), key_var.get().strip(),
                             model_var.get().strip() or "gpt-4.1",
                             progress=lambda m: root.after(0, add_log, m))
                root.after(0, lambda: messagebox.showinfo(
                    "Hoàn tất", f"Đã lưu bản dịch:\n{out}"))
            except Exception as e:  # noqa: BLE001
                root.after(0, add_log, f"✗ LỖI: {e}")
                root.after(0, lambda: messagebox.showerror("Lỗi", str(e)))
            finally:
                root.after(0, prog.stop)
                root.after(0, lambda: btn.configure(state="normal"))

        threading.Thread(target=work, daemon=True).start()

    btn = ttk.Button(frm, text="▶  Dịch PDF", command=start)
    btn.grid(row=4, column=0, columnspan=3, sticky="we")
    add_log("Sẵn sàng. Chọn PDF, nhập API key rồi bấm Dịch.")
    add_log("Kết quả lưu cạnh file gốc: <tên>_TiengViet.pdf")
    root.mainloop()


if __name__ == "__main__":
    main()
