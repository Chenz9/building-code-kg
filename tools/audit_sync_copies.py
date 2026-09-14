# -*- coding: utf-8 -*-
"""
同名文件副本一致性体检（防漏同步）

用途：项目里同一份成果常有多个副本（正本 03_标准结构化/_v2/、产出包、
      _github_repo/）。改完正本后跑本脚本，可立即发现哪些副本没跟上。

用法：
    python audit_sync_copies.py              # 体检
    python audit_sync_copies.py --fix SRC    # 把 SRC 的同名副本全部覆盖（自动 .bak）
    python audit_sync_copies.py --all        # 列出全部同名文件组（不只 TARGETS）

退出码：0 = 全部一致；1 = 存在不同步（CI 可用）
"""
import os, sys, shutil, hashlib, collections

# 目录可用环境变量 PROJECT_ROOT 指定；未指定时取本脚本所在目录的上一级
# （工作区副本 → 项目根；仓库副本 → 仓库根），两侧同一份代码均可直接用。
ROOT = os.environ.get("PROJECT_ROOT") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..")
SKIP_DIRS = {"99_待清理_早期过程成果", ".git", ".workbuddy", "node_modules", "__pycache__"}
# 备份目录：刻意保留旧版本，不参与一致性体检。
# 用前缀匹配，新建备份目录（如 _v2_backup_20260911_terms）无需再改这里。
SKIP_PREFIX = ("_v2_backup",)

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
    "GB50325-2020.yaml", "GB50365-2019.yaml", "GB50462-2024.yaml",
    "工具_YAML通用阅读器.html", "yaml-reader.html",
    "_gen_readview_html.py", "gen_readview_html.py",
    "audit_v21.py", "audit_modal_v22.py",
]

# 跨名副本对（正本名, 副本名）：两份副本在仓库里改了名，同名比对覆盖不到。
# 注意：04_脚本与中间产物/_refix_modal_v22.py 与仓库版 refix_modal_v22.py 的 import
#      名不同（_rederive_modal / rederive_modal），属预期差异，故不纳入比对。
PAIRS = [
    ("工具_YAML通用阅读器.html", "yaml-reader.html"),
    ("_gen_readview_html.py", "gen_readview_html.py"),
]

# 有意差异：私有工作区版与开源仓库版**刻意不同**，不算漏同步。
#   开源版需脱敏（去掉本地绝对路径），且能在 clone 后独立运行（默认扫 standards/）；
#   私有版需默认扫描全库（03_标准结构化/_v2）。
#   二者内容必然不同，用 --fix 强行同步反而会把私有路径写回仓库——故在此登记为已知差异。
INTENTIONAL_DIVERGENCE = {
    "audit_v21.py": "开源版路径脱敏且默认扫 standards/；私有版默认扫全库",
    "audit_modal_v22.py": "同上",
    "_gen_readview_html.py": "开源版页脚路径改为仓库相对路径",
    "gen_readview_html.py": "同上",
}


def md5(p):
    return hashlib.md5(open(p, "rb").read()).hexdigest()


def build_index():
    idx = collections.defaultdict(list)
    for dp, dns, fns in os.walk(ROOT):
        dns[:] = [d for d in dns if d not in SKIP_DIRS and not d.startswith(SKIP_PREFIX)]
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
        if len(hs) > 1 and t in INTENTIONAL_DIVERGENCE:
            print(f"== {t:<26} 副本 {len(paths)}  版本 {len(hs)}  "
                  f"已知差异（有意）：{INTENTIONAL_DIVERGENCE[t]}")
            continue
        flag = "OK " if len(hs) == 1 else "!! "
        if len(hs) > 1:
            bad += 1
        print(f"{flag}{t:<26} 副本 {len(paths)}  版本 {len(hs)}  {sorted(h[:8] for h in hs)}")
        if len(hs) > 1:
            for p in paths:
                print("      ", md5(p)[:8], p.replace(ROOT, "."))

    # 跨名副本对（如 顶层阅读器 <-> 仓库 yaml-reader.html）
    for a, b in PAIRS:
        pa, pb = idx.get(a, []), idx.get(b, [])
        if not pa or not pb:
            continue
        groups = pa + pb
        hs = {md5(p) for p in groups}
        ikey = a if a in INTENTIONAL_DIVERGENCE else b
        if len(hs) > 1 and ikey in INTENTIONAL_DIVERGENCE:
            print(f"== {a + ' <-> ' + b:<26} 副本 {len(groups)}  版本 {len(hs)}  "
                  f"已知差异（有意）：{INTENTIONAL_DIVERGENCE[ikey]}")
            continue
        flag = "OK " if len(hs) == 1 else "!! "
        if len(hs) > 1:
            bad += 1
        print(f"{flag}{a + ' <-> ' + b:<26} 副本 {len(groups)}  版本 {len(hs)}  {sorted(h[:8] for h in hs)}")
        if len(hs) > 1:
            for p in groups:
                print("      ", md5(p)[:8], p.replace(ROOT, "."))

    print(f"\n不一致文件组数: {bad}")
    print("提示：`python audit_sync_copies.py --fix <正本路径>` 可一键同步；"
          "`--all` 可扫描全部同名文件（含 TARGETS 之外）。")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
