import json, os, glob
root = os.path.join(os.environ["APPDATA"], "com.kcoder.app", "runtime-data", "sessions")
rows = []
for p in glob.glob(os.path.join(root, "*.jsonl")):
    try:
        with open(p, encoding="utf-8") as h:
            for line in h:
                try: o = json.loads(line)
                except Exception: continue
                d = o.get("data") or {}
                if o.get("type") != "tool_result": continue
                r = d.get("result") or {}
                if r.get("success"): continue
                if d.get("name") != "run_command": continue
                args = d.get("arguments") or {}
                cmd = args.get("command") or ""
                md = r.get("metadata") or {}
                rows.append((cmd.replace("\n", " ")[:78], md.get("exitCode"), md.get("resultKind"), (r.get("output") or "").strip()[:70]))
    except Exception as e:
        pass
print("failed run_command tool_results:", len(rows))
seen = {}
for c, ec, rk, out in rows:
    k = (c, ec, rk, out)
    seen[k] = seen.get(k, 0) + 1
for (c, ec, rk, out), n in sorted(seen.items(), key=lambda kv: -kv[1]):
    print(f"[x{n}] exit={ec} kind={rk} :: {c}\n      out={out}")
