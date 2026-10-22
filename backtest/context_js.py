"""把回测统计写进 dashboard/live/context.js 给面板用。

文件里每个统计占两行：一行注释 + 一行 `var 名字=JSON;`。每个脚本只替换自己那一块，
不会覆盖其他脚本写的内容。
"""
import json
import os
import re

JS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "dashboard", "live", "context.js")


def write_var(name, comment, obj):
    blocks = {}
    if os.path.exists(JS):
        lines = open(JS, encoding="utf-8").read().splitlines()
        for i, line in enumerate(lines):
            m = re.match(r"var (\w+)=", line)
            if m:
                blocks[m.group(1)] = (lines[i - 1] if i and lines[i - 1].startswith("/*") else "", line)
    blocks[name] = (f"/* {comment} */", f"var {name}=" + json.dumps(obj, ensure_ascii=False) + ";")
    with open(JS, "w", encoding="utf-8") as fh:
        for c, v in blocks.values():
            fh.write((c + "\n" if c else "") + v + "\n")
