# -*- coding: utf-8 -*-
"""批量拉取 qsquiz 'qs' 模块全部题目（练习模式多轮抽样 + 逐题作答换取解析）"""
import json, os, time, urllib.request, urllib.error

BASE = "http://8.153.155.219:8300"
HERE = os.path.dirname(os.path.abspath(__file__))
BANK = os.path.join(HERE, "quiz_qs.json")
DIGEST = os.path.join(HERE, "quiz_qs_digest.txt")

def post(path, payload, timeout=25):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

def load_bank():
    if os.path.exists(BANK):
        with open(BANK, encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_bank(bank):
    with open(BANK, "w", encoding="utf-8") as f:
        json.dump(bank, f, ensure_ascii=False, indent=1)

bank = load_bank()
print(f"start: bank has {len(bank)} questions")
no_new_rounds = 0
round_no = 0
try:
    while no_new_rounds < 6 and round_no < 70:
        round_no += 1
        try:
            data = post("/api/start", {"mode": "practice", "module": "qs"})
        except Exception as e:
            print(f"round {round_no}: start failed: {e}; retry in 3s")
            time.sleep(3)
            continue
        sid = data.get("sid")
        paper = data.get("paper", [])
        new = 0
        for q in paper:
            qid = q.get("id")
            if qid in bank:
                continue
            opts = q.get("options", [])
            choice = opts[0] if opts else "A"
            try:
                fb = post("/api/answer", {"sid": sid, "qid": qid, "choice": choice})
            except Exception as e:
                fb = {"error": str(e)}
                print(f"  answer {qid} failed: {e}")
            bank[qid] = {
                "id": qid,
                "module": q.get("module"),
                "q": q.get("q"),
                "options": opts,
                "feedback": fb,
            }
            new += 1
            time.sleep(0.03)
        print(f"round {round_no}: drew {len(paper)}, new {new}, total {len(bank)}/124")
        save_bank(bank)
        no_new_rounds = no_new_rounds + 1 if new == 0 else 0
        time.sleep(0.15)
finally:
    save_bank(bank)

# 生成易读摘要
lines = []
for qid in sorted(bank, key=lambda x: (bank[x].get("module") or "", x)):
    q = bank[qid]
    fb = q.get("feedback", {}) or {}
    lines.append("=" * 70)
    lines.append(f"[{qid}] module={q.get('module')}")
    lines.append(f"Q: {q.get('q')}")
    for j, o in enumerate(q.get("options", [])):
        letter = "ABCD"[j] if j < 4 else str(j)
        mark = "  <-- 正确答案" if o == fb.get("answer") else ""
        lines.append(f"  {letter}. {o}{mark}")
    lines.append(f"正确: {fb.get('answer', '?')}")
    lines.append(f"解析: {fb.get('explain', '(无)')}")
with open(DIGEST, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print(f"DONE: {len(bank)} questions -> {BANK}")
