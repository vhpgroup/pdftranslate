"""
translate_api_example.py — Module dich TACH RIENG (pluggable translation step).

Vi tri trong pipeline:  extract/plan  ->  [DICH]  ->  apply
Mac dinh tren Hyperagent: agent (LLM) tu dich units.json trong hoi thoai (KHONG dung script nay).
Script nay danh cho viec chay pipeline o NOI KHAC (desktop app) voi bat ky API LLM
tuong thich OpenAI (vd GPT-4.1). Chi can doi bien model/endpoint.

Dung:
  export OPENAI_API_KEY=sk-...
  python3 translate_api_example.py units.json glossary_vi.json translations.json --model gpt-4.1
"""
import json, sys, os, urllib.request

API_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1") + "/chat/completions"

SYSTEM_PROMPT = """Ban la bien dich vien tai lieu ky thuat Anh -> Viet cho catalog san pham.
QUY TAC BAT BUOC:
1. Giu nguyen: so lieu, don vi (dpi, GB, g/m2, V, Hz...), ma model/SKU, ten thuong hieu/phan mem.
2. Ap dung glossary duoc cung cap mot cach NHAT QUAN tuyet doi.
3. Muc nao toan ma san pham/ten rieng -> tra ve nguyen van (khong dich).
4. Tra ve JSON: {"id": "ban dich", ...} cho DUNG cac id duoc giao, khong them bot."""

def call_llm(model, messages):
    req = urllib.request.Request(API_URL, headers={
        "Authorization": "Bearer " + os.environ["OPENAI_API_KEY"],
        "Content-Type": "application/json"},
        data=json.dumps({"model": model, "messages": messages,
                         "response_format": {"type": "json_object"}}).encode())
    with urllib.request.urlopen(req) as r:
        return json.loads(json.load(r)["choices"][0]["message"]["content"])

def main(units_path, glossary_path, out_path, model="gpt-4.1", batch=30):
    units = json.load(open(units_path, encoding="utf-8"))
    glossary = json.load(open(glossary_path, encoding="utf-8"))
    todo = [u for u in units if any(c.isalpha() for c in u["text"])]
    result = {}
    for i in range(0, len(todo), batch):
        chunk = {u["id"]: u["text"] for u in todo[i:i+batch]}
        out = call_llm(model, [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content":
                "GLOSSARY:\n" + json.dumps(glossary["terms"], ensure_ascii=False) +
                "\n\nDich cac muc sau sang tieng Viet (giu nguyen muc la ma/ten rieng):\n" +
                json.dumps(chunk, ensure_ascii=False)}])
        result.update(out)
        print("  translated %d/%d" % (min(i+batch, len(todo)), len(todo)))
    json.dump(result, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("-> " + out_path)

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    model = "gpt-4.1"
    if "--model" in sys.argv:
        model = sys.argv[sys.argv.index("--model") + 1]
    main(args[0], args[1], args[2], model)
