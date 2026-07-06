"""
rebuild.py — Pipeline dich PDF giu nguyen bo cuc (layout-preserving PDF translation).

Che do:
  plan  input.pdf units.json          -> liet ke cac don vi dich (cell / paragraph / block)
  apply input.pdf units.json translations.json output.pdf -> xoa chu goc, chen ban dich

Thiet ke:
- Don vi CELL: 1 dong trong bang -> chen tai dung baseline goc, tu thu nho font theo be rong cot.
- Don vi PARA: cac dong don lien tiep cung co chu/le trai -> gop, dich ca doan, chay lai trong vung goc.
- Don vi BLOCK: khoi nhieu dong (tieu de, ghi chu phap ly) -> chay lai trong bbox khoi.
- Xoa chu bang redaction KHONG to mau nen + giu nguyen anh/do hoa -> hinh va duong ke bang giu 100%.
- Font: DejaVu Sans Condensed (ho tro day du dau tieng Viet, dang gon gan voi Frutiger goc).
"""
import fitz, json, sys, re

import os

def _find_font(env_key, candidates, fallback=None):
    """Do font da nen tang: uu tien bien moi truong, roi danh sach duong dan pho bien."""
    p = os.environ.get(env_key)
    if p and os.path.exists(p):
        return p
    for c in candidates:
        if os.path.exists(c):
            return c
    if fallback:
        return fallback
    raise FileNotFoundError(
        f"Khong tim thay font tieng Viet ({env_key}). "
        f"Cai dat DejaVu fonts (Debian/Ubuntu: apt install fonts-dejavu-core fonts-dejavu-extra; "
        f"Fedora: dnf install dejavu-sans-fonts) hoac dat bien moi truong {env_key}=/duong/dan/font.ttf")

FONT_REG = _find_font("PDFTRANSLATE_FONT_REG", [
    "/usr/share/fonts/dejavu-sans-fonts/DejaVuSansCondensed.ttf",    # Fedora/RHEL/Amazon Linux
    "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf",      # Debian/Ubuntu (fonts-dejavu-extra)
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",               # Debian/Ubuntu (core)
    "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf",
    "/usr/local/share/fonts/DejaVuSansCondensed.ttf",
    os.path.expanduser("~/Library/Fonts/DejaVuSans.ttf"),            # macOS (user)
    "C:/Windows/Fonts/DejaVuSans.ttf",                               # Windows
])
FONT_BOLD = _find_font("PDFTRANSLATE_FONT_BOLD", [
    "/usr/share/fonts/dejavu-sans-fonts/DejaVuSansCondensed-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf",
    os.path.expanduser("~/Library/Fonts/DejaVuSans-Bold.ttf"),
    "C:/Windows/Fonts/DejaVuSans-Bold.ttf",
], fallback=None)
FONT_ITAL = _find_font("PDFTRANSLATE_FONT_ITAL", [
    "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Oblique.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
], fallback=FONT_REG)
MIN_FONTSIZE = 4.0

def rgb(c):
    return ((c >> 16) & 255) / 255.0, ((c >> 8) & 255) / 255.0, (c & 255) / 255.0

def is_bold(span):
    f = span["font"].lower()
    return bool(span["flags"] & 16) or "bold" in f or "black" in f or "heavy" in f

def is_italic(span):
    f = span["font"].lower()
    return bool(span["flags"] & 2) or "italic" in f or "oblique" in f

def line_text(line):
    return re.sub(r"\s+", " ", "".join(s["text"] for s in line["spans"])).strip()

def collect_units(doc):
    """Phan tich PDF thanh cac don vi dich."""
    units = []
    for pno, page in enumerate(doc):
        d = page.get_text("dict")
        tblocks = [b for b in d["blocks"] if b["type"] == 0]
        singles = []   # single-line blocks, candidates for paragraph grouping
        for bi, block in enumerate(tblocks):
            lines = [l for l in block["lines"] if line_text(l)]
            if not lines:
                continue
            if len(lines) == 1:
                singles.append((bi, block, lines[0]))
                continue
            # multi-line block: table row hoac heading/paragraph khoi
            xs = sorted(set(round(l["bbox"][0]) for l in lines))
            same_x = len(xs) <= 2 and (len(xs) == 1 or xs[1]-xs[0] < 8)
            if same_x:
                # khoi van ban nhieu dong (heading 2 dong, doan ghi chu) -> BLOCK unit
                units.append(make_block_unit(pno, bi, block, lines))
            else:
                # hang bang -> moi dong la mot CELL
                for li, l in enumerate(lines):
                    units.append(make_cell_unit(pno, bi, li, l, lines, page))
        # nhom paragraph tu cac single-line blocks
        used = set()
        singles.sort(key=lambda t: (round(t[2]["bbox"][1],1), t[2]["bbox"][0]))
        for i, (bi, block, line) in enumerate(singles):
            if i in used: continue
            size = line["spans"][0]["size"]
            group = [(bi, block, line)]
            used.add(i)
            if size <= 9.5:
                cur = line
                for j in range(i+1, len(singles)):
                    if j in used: continue
                    bj, blkj, lj = singles[j]
                    szj = lj["spans"][0]["size"]
                    if abs(szj - size) > 0.1: continue
                    if abs(lj["bbox"][0] - cur["bbox"][0]) > 2.5: continue
                    gap = lj["bbox"][1] - cur["bbox"][3]
                    if -2 < gap < size * 0.9:
                        group.append((bj, blkj, lj)); used.add(j); cur = lj
            if len(group) == 1:
                units.append(make_cell_unit(pno, bi, 0, line, [line], None))
            else:
                units.append(make_para_unit(pno, group))
    return units

def make_cell_unit(pno, bi, li, line, all_lines, page):
    s0 = line["spans"][0]
    # be rong kha dung: den o ke tiep cung hang, hoac le phai trang
    x0, y0, x1, y1 = line["bbox"]
    limit = None
    for l in all_lines:
        if l is line: continue
        # cung hang (y giao nhau) va nam ben phai
        ov = min(y1, l["bbox"][3]) - max(y0, l["bbox"][1])
        mh = min(y1 - y0, l["bbox"][3] - l["bbox"][1])
        if l["bbox"][0] > x0 + 1 and ov > 0.5 * max(mh, 0.1):
            cand = l["bbox"][0] - 3
            limit = cand if limit is None else min(limit, cand)
    return {
        "id": f"c{pno}b{bi}l{li}", "mode": "cell", "page": pno,
        "text": line_text(line),
        "bbox": [x0, y0, x1, y1],
        "origin": list(line["spans"][0]["origin"]),
        "spans": [list(s["bbox"]) for s in line["spans"]],
        "size": s0["size"], "color": rgb(s0["color"]),
        "bold": is_bold(s0), "italic": is_italic(s0),
        "maxx": limit,  # None -> gioi han theo le trang khi apply
        "dir": list(line.get("dir", (1,0))),
    }

def make_para_unit(pno, group):
    lines = [l for _,_,l in group]
    x0 = min(l["bbox"][0] for l in lines); y0 = min(l["bbox"][1] for l in lines)
    x1 = max(l["bbox"][2] for l in lines); y1 = max(l["bbox"][3] for l in lines)
    s0 = lines[0]["spans"][0]
    return {
        "id": f"p{pno}b{group[0][0]}", "mode": "para", "page": pno,
        "text": " ".join(line_text(l) for l in lines),
        "bbox": [x0, y0, x1, y1],
        "spans": [list(s["bbox"]) for l in lines for s in l["spans"]],
        "size": s0["size"], "color": rgb(s0["color"]),
        "bold": is_bold(s0), "italic": is_italic(s0),
    }

def make_block_unit(pno, bi, block, lines):
    s0 = lines[0]["spans"][0]
    x0 = min(l["bbox"][0] for l in lines); y0 = min(l["bbox"][1] for l in lines)
    x1 = max(l["bbox"][2] for l in lines); y1 = max(l["bbox"][3] for l in lines)
    return {
        "id": f"k{pno}b{bi}", "mode": "block", "page": pno,
        "text": " ".join(line_text(l) for l in lines),
        "bbox": [x0, y0, x1, y1],
        "spans": [list(s["bbox"]) for l in lines for s in l["spans"]],
        "size": s0["size"], "color": rgb(s0["color"]),
        "bold": is_bold(s0), "italic": is_italic(s0),
    }

def cmd_plan(pdf_path, out_path):
    doc = fitz.open(pdf_path)
    units = collect_units(doc)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(units, f, ensure_ascii=False, indent=1)
    print(f"{len(units)} units -> {out_path}")
    for u in units:
        print(f"  [{u['id']}] ({u['mode']},sz{u['size']:.0f}) {u['text'][:90]}")

def fit_fontsize(font, text, size, max_width):
    while size > MIN_FONTSIZE and font.text_length(text, fontsize=size) > max_width:
        size -= 0.25
    return size

def find_bullet_squares(page, u):
    """Tim cac o vuong bullet (line art nho) ben trai don vi."""
    x0, y0, x1, y1 = u["bbox"]
    sqs = []
    for d in page.get_drawings():
        r = d["rect"]
        if r.width < 8 and r.height < 8 and d.get("fill") and \
           x0 - 14 <= r.x0 <= x0 + 4 and y0 - 4 <= r.y0 <= y1 + 4:
            sqs.append(r.y0)
    return sorted(sqs)

def cmd_apply(pdf_path, units_path, trans_path, out_path, anchors_path=None):
    doc = fitz.open(pdf_path)
    units = json.load(open(units_path, encoding="utf-8"))
    trans = json.load(open(trans_path, encoding="utf-8"))
    anchors = json.load(open(anchors_path, encoding="utf-8")) if anchors_path else {}
    font_reg, font_bold, font_ital = fitz.Font(fontfile=FONT_REG), fitz.Font(fontfile=FONT_BOLD), fitz.Font(fontfile=FONT_ITAL)
    by_page = {}
    deleted = set()
    for u in units:
        if u["id"] in anchors:
            by_page.setdefault(u["page"], []).append((u, "@ANCHORED@"))
            continue
        t = trans.get(u["id"])
        if t is None or t == u["text"]:
            continue  # khong doi -> giu nguyen pixel goc
        if isinstance(t, str) and not t.strip():
            deleted.add(u["id"])
        by_page.setdefault(u["page"], []).append((u, t))
    # ban do cell theo trang de tinh lai be rong cot (bo qua cell da xoa)
    cells_by_page = {}
    for u in units:
        if u["mode"] == "cell" and u["id"] not in deleted:
            cells_by_page.setdefault(u["page"], []).append(u)
    def avail_maxx(u, page_w):
        x0, y0, x1, y1 = u["bbox"]; lim = page_w - 14
        for o in cells_by_page.get(u["page"], []):
            if o["id"] == u["id"]: continue
            ov = min(y1, o["bbox"][3]) - max(y0, o["bbox"][1])
            mh = min(y1 - y0, o["bbox"][3] - o["bbox"][1])
            if o["bbox"][0] > x0 + 1 and ov > 0.5 * max(mh, 0.1):
                lim = min(lim, o["bbox"][0] - 3)
        return lim
    changed = skipped = 0
    for pno, items in sorted(by_page.items()):
        page = doc[pno]
        # 1) xoa chu goc — KHONG to nen, giu anh & do hoa
        for u, _ in items:
            for sb in u["spans"]:
                r = fitz.Rect(sb) + (-0.5, -0.5, 0.5, 0.5)
                page.add_redact_annot(r)
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,
                              graphics=fitz.PDF_REDACT_LINE_ART_NONE)
        # 2) chen ban dich
        for u, t in items:
            font = font_bold if u["bold"] else (font_ital if u["italic"] else font_reg)
            fname = "dvcb" if u["bold"] else ("dvio" if u["italic"] else "dvcr")
            ffile = FONT_BOLD if u["bold"] else (FONT_ITAL if u["italic"] else FONT_REG)
            color = tuple(u["color"])
            if t == "@ANCHORED@":
                # che do danh sach bullet: dat tung muc vao vi tri o vuong
                items = anchors[u["id"]]["items"]
                sqs = find_bullet_squares(page, u)
                x0 = u["bbox"][0]; x1 = max(u["bbox"][2], x0 + 30) + 2
                if len(sqs) != len(items):
                    # khong khop -> chay dong nhu para thuong
                    t = " • ".join(items)
                else:
                    ok = True
                    for i, (item, sy) in enumerate(zip(items, sqs)):
                        ybot = (sqs[i+1] - 1.5) if i + 1 < len(sqs) else u["bbox"][3] + 9
                        rect = fitz.Rect(x0, sy - 1.6, x1, ybot)
                        size = u["size"]
                        while size > MIN_FONTSIZE:
                            rc = page.insert_textbox(rect, item, fontsize=size,
                                    fontname=fname, fontfile=ffile, color=color,
                                    align=fitz.TEXT_ALIGN_LEFT, lineheight=1.12)
                            if rc >= 0: break
                            size -= 0.5
                        changed += 1
                    continue
            if not t.strip():
                changed += 1
                continue  # chi xoa, khong chen (manh ®/™ da gop vao o khac)
            if u["mode"] == "cell":
                x0 = u["bbox"][0]
                maxw = max(10, avail_maxx(u, page.rect.width) - x0)
                eff = u["size"]
                bh = u["bbox"][3] - u["bbox"][1]
                if eff < 0.55 * bh:  # size khai bao << chieu cao that (VD tieu de co ™ superscript)
                    eff = 0.72 * bh
                size = fit_fontsize(font, t, eff, maxw)
                page.insert_text((x0, u["origin"][1]), t, fontsize=size,
                                 fontname=fname, fontfile=ffile, color=color)
                changed += 1
            else:
                rect = fitz.Rect(u["bbox"])
                rect.x1 = max(rect.x1, rect.x0 + 30)
                size = u["size"]
                lh = 1.12
                parts = t.split("\n")
                if len(parts) > 1 and len(parts) == len(u.get("spans", [])):
                    # ngat dong thu cong khop so dong goc -> dat tung dong dung vi tri goc
                    for part, sb in zip(parts, u["spans"]):
                        s = fit_fontsize(font, part, size, max(14, rect.x1 + 4 - sb[0]))
                        page.insert_text((sb[0], sb[3] - 0.24 * s), part, fontsize=s,
                                         fontname=fname, fontfile=ffile, color=color)
                    changed += 1
                    continue
                if len(parts) > 1:  # ngat dong thu cong khac -> gian deu trong khung
                    bh = rect.height
                    lh = min(2.4, max(1.05, (bh * 0.92) / (len(parts) * size)))
                while size > MIN_FONTSIZE:
                    # thu chen; am -> khong vua, giam co chu
                    rc = page.insert_textbox(rect + (0,-1,2,6), t, fontsize=size,
                            fontname=fname, fontfile=ffile, color=color,
                            align=fitz.TEXT_ALIGN_LEFT, lineheight=lh)
                    if rc >= 0: break
                    size -= 0.5
                if size <= MIN_FONTSIZE:
                    skipped += 1
                changed += 1
    doc.subset_fonts()
    doc.ez_save(out_path)
    print(f"Applied {changed} translations ({skipped} needed extreme shrink) -> {out_path}")

if __name__ == "__main__":
    if sys.argv[1] == "plan":
        cmd_plan(sys.argv[2], sys.argv[3])
    elif sys.argv[1] == "apply":
        cmd_apply(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5],
                  sys.argv[6] if len(sys.argv) > 6 else None)
