# -*- coding: utf-8 -*-
"""
同名文件副本一致性体检（防漏同步）

用途：同一份成果在仓库里常存在多个副本（如 standards/ 与发布包、文档附件）。
      改完其中一份后跑本脚本，可立即发现哪些同名副本没跟上，避免「改了 A 处、
      发出的却是 B 处」——这类漏同步在人工流程里极难察觉。

用法：
    python audit_sync_copies.py              # 体检（默认扫本仓库根目录）
    python audit_sync_copies.py --fix SRC    # 把 SRC 的同名副本全部覆盖（自动 .bak）
    python audit_sync_copies.py --all        # 列出全部同名文件组（不只 TARGETS）

目录可用环境变量 PROJECT_ROOT 指定，默认为本仓库根目录。

退出码：0 = 全部一致；1 = 存在不同步（CI 可用）
"""
import os, sys, shutil, hashlib, collections

ROOT = os.environ.get("PROJECT_ROOT") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SKIP_DIRS = {"99_待清理_早期过程成果", ".git", ".workbuddy", "node_modules", "__pycache__",
             # 备份目录：刻意保留旧版本，不参与一致性体检
             "_v2_backup_20260911", "_v2_backup"}

# 必须保持一致的同名文件组（新增成果时往这里追加）
TARGETS = [
    "SCHEMA_v2.2.yaml",
    # —— 33 本标准正本（有副本的会被比对，无副本的自动 OK）——
    "GB50016-2014.yaml", "GB50067-2014.yaml", "GB50108-2008.yaml", "GB50118-2010.yaml",
    "GB50176-2016.yaml", "GB50189-2015.yaml", "GB50210-2018.yaml", "GB50222-2017.yaml",
    "GB50345-2012.yaml", "GB50352-2019.yaml", "GB50763-2012.yaml", "GB55019-2021.yaml",
    "GB55024-2022.yaml", "GB55030-2022.yaml", "GB55031-2022.yaml", "GB55032-2022.yaml",
    "GB55036-2022.yaml", "GB55037-2022.yaml", "GB55038-2025.yaml", "GBT7106-2019.yaml",
    "JGJ100-2015.yaml", "JGJ113-2015.yaml", "JGJ155-2013.yaml", "JGJ218-2010.yaml",
    "JGJ230-2010.yaml", "JGJ57-2016.yaml", "JGJ58-2008.yaml", "JGJT235-2011.yaml",
    "SJG19-2023.yaml", "SJG44-2025.yaml",
    "工具_YAML通用阅读器.html", "yaml-reader.html",
    "_gen_readview_html.py", "gen_readview_html.py",
    "audit_v21.py", "audit_modal_v22.py",
]


def md5(p):
    return hashlib.md5(open(p, "rb").read()).hexdigest()


def build_index():
    idx = collections.defaultdict(list)
    for dp, dns, fns in os.walk(ROOT):
        dns[:] = [d for d in dns if d not in SKIP_DIRS]
        for fn in fns:
            if ".bak" in fn or fn.startswith("._"):
                continue
            idx[fn].append(os.path.join(dp, fn))
    return idx


def main():
    args = sys.argv[1:]
    idx = build_index()

    if args and args[0] == "--all":
        n = 0
        for fn, paths in sorted(idx.items()):
            if len(paths) < 2:
                continue
            hs = {md5(p) for p in paths}
            if len(hs) > 1:
                n += 1
                print(f"!! {fn}  ({len(hs)} 版本)")
                for p in paths:
                    print("     ", md5(p)[:8], p.replace(ROOT, "."))
        print(f"\n不同步文件组: {n}")
        return 1 if n else 0

    if args and args[0] == "--fix":
        src = args[1]
        base = os.path.basename(src)
        sm = md5(src)
        nfix = 0
        for p in idx.get(base, []):
            if os.path.abspath(p) == os.path.abspath(src):
                continue
            if md5(p) == sm:
                continue
            shutil.copy2(p, p + ".bak_sync")
            shutil.copy2(src, p)
            nfix += 1
            print(f"  已同步 {p.replace(ROOT, '.')}  (旧版备份 -> .bak_sync)")
        print(f"同步完成，共 {nfix} 个副本")
        return 0

    bad = 0
    for t in TARGETS:
        paths = idx.get(t, [])
        if len(paths) < 2:
            continue
        hs = {md5(p) for p in paths}
        flag = "OK " if len(hs) == 1 else "!! "
        if len(hs) > 1:
            bad += 1
        print(f"{flag}{t:<26} 副本 {len(paths)}  版本 {len(hs)}  {sorted(h[:8] for h in hs)}")
        if len(hs) > 1:
            for p in paths:
                print("      ", md5(p)[:8], p.replace(ROOT, "."))
    print(f"\n不一致文件组数: {bad}")
    print("提示：`python audit_sync_copies.py --fix <正本路径>` 可一键同步；"
          "`--all` 可扫描全部同名文件（含 TARGETS 之外）。")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
