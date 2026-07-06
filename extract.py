"""
extract.py — Buoc 1 cua pipeline dich PDF giu bo cuc.
Trich xuat moi khoi text kem toa do, font, co chu, mau tu PDF ra JSON.
Dung: python3 extract.py input.pdf output.json
"""
import fitz, json, sys, re

def span_is_bold(span):
    return bool(span["flags"] & 16) or "bold" in span["font"].lower() or "black" in span["font"].lower()

def span_is_italic(span):
    return bool(span["flags"] & 2) or "italic" in span["font"].lower() or "oblique" in span["font"].lower()

def int_to_rgb(c):
    return ((c >> 16) & 255) / 255.0, ((c >> 8) & 255) / 255.0, (c & 255) / 255.0

def extract(path, out_path):
    doc = fitz.open(path)
    result = {"source": path, "pages": []}
    bid = 0
    for pno, page in enumerate(doc):
        pdata = {"number": pno, "width": page.rect.width, "height": page.rect.height, "blocks": []}
        d = page.get_text("dict")
        for block in d["blocks"]:
            if block["type"] != 0:  # only text blocks
                continue
            lines_out = []
            for line in block["lines"]:
                spans_out = []
                for span in line["spans"]:
                    if not span["text"].strip():
                        continue
                    spans_out.append({
                        "text": span["text"],
                        "bbox": span["bbox"],
                        "font": span["font"],
                        "size": round(span["size"], 2),
                        "color": int_to_rgb(span["color"]),
                        "bold": span_is_bold(span),
                        "italic": span_is_italic(span),
                    })
                if spans_out:
                    lines_out.append({"bbox": line["bbox"], "spans": spans_out})
            if not lines_out:
                continue
            text = " ".join(" ".join(s["text"] for s in l["spans"]) for l in lines_out)
            text = re.sub(r"\s+", " ", text).strip()
            result_block = {
                "id": bid, "page": pno, "bbox": block["bbox"],
                "n_lines": len(lines_out), "lines": lines_out, "text": text,
            }
            pdata["blocks"].append(result_block)
            bid += 1
        result["pages"].append(pdata)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    n_blocks = sum(len(p["blocks"]) for p in result["pages"])
    print(f"Extracted {n_blocks} text blocks from {len(result['pages'])} pages -> {out_path}")

if __name__ == "__main__":
    extract(sys.argv[1], sys.argv[2])
