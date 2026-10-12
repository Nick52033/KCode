import json, os, glob
root = os.path.join(os.environ["APPDATA"], "com.kcoder.app", "runtime-data", "sessions")
files = sorted(glob.glob(os.path.join(root, "*.jsonl")), key=os.path.getmtime, reverse=True)
shown = 0
for p in files:
    with open(p, encoding="utf-8") as h:
        for line in h:
            try: o = json.loads(line)
            except Exception: continue
            if o.get("type") != "tool_result": continue
            d = o.get("data") or {}
            if (d.get("name") or "") != "run_command": continue
            r = d.get("result") or {}
            if r.get("success"): continue
            print("FILE=", os.path.basename(p))
            print("DATA KEYS=", sorted(d.keys()))
            print("CALL=", json.dumps(d.get("call") or d.get("arguments"), ensure_ascii=False)[:400])
            print("RESULT=", json.dumps(r, ensure_ascii=False)[:400])
            shown += 1
            if shown >= 3: break
    if shown >= 3: break
