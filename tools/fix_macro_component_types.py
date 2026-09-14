# -*- coding: utf-8 -*-
"""
宏观章节 component_types 清空工具（v2.2 书写规约）

背景：术语 / 总则 / 基本规定 等宏观章节的条文是"全册级"要求，
      不指向任何具体构件。若按册统一挂一组 IFC 类型（甚至挂全册并集），
      等于"什么都指向"，信息量为零，且会污染下游按构件检索的结果。

规则（写入 SCHEMA_v2.2 §7 与作业规范）：
  章名去掉序号后命中 MACRO_KEYWORDS 之一 → related_objects.component_types = []
  保留 activity_types（宏观条文仍属于该业务活动范畴）。

用法：
  python _fix_macro_component_types.py                 # dry-run，只报告
  python _fix_macro_component_types.py --apply         # 写盘（自动留 .bak_macro_ct）
  python _fix_macro_component_types.py --scan-all      # 扫全库影响面（不写）
"""
import os, re, sys, shutil, glob

D = os.environ.get("STANDARDS_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "standards")

# 宏观章节关键词（章名去掉前导序号/空格后命中任一即视为宏观章）
MACRO_KEYWORDS = [
    "总则", "术语", "符号", "代号",
    "基本规定", "基本技术要求", "一般要求", "一般性规定",
    "规范性引用文件", "引用标准",
    "分类", "分级",
    "分部工程", "单位工程",
]

# 章名前导（"1 总则" / "3 基本规定" / "附录A 术语"）
_CH_PREFIX = re.compile(r"^\s*(?:附录\s*[A-Z]\s*)?\d+(?:\.\d+)*\s*")


def chapter_core(ch):
    """去掉前导序号，返回章名核心"""
    if not ch:
        return ""
    return _CH_PREFIX.sub("", str(ch)).strip()


def is_macro_chapter(ch):
    # OCR 来源的章名常在字间夹空格（如「1 总 则」「2 术 语」），匹配前先剔除
    core = chapter_core(ch).replace(" ", "").replace("\u3000", "")
    if not core:
        return False
    return any(k in core for k in MACRO_KEYWORDS)


def parse_targets(path):
    """返回 (需要清空的 clause_id 集合, 统计)"""
    cur_id, in_ro, cur_has_ct = None, False, False
    targets, stat = set(), {"total": 0, "macro": 0, "macro_has_ct": 0}
    chapter_of = {}
    lines = open(path, encoding="utf-8").read().split("\n")
    i = 0
    while i < len(lines):
        ln = lines[i]
        m = re.match(r"^- id:\s*(.+?)\s*$", ln)
        if m:
            cur_id, in_ro, cur_has_ct = m.group(1), False, False
            stat["total"] += 1
            # 读后续 chapter（注意：standard_code 在 chapter 之前，不能提前 break）
            j = i + 1
            ch = ""
            while j < len(lines) and not lines[j].startswith("- id:"):
                mm = re.match(r"^\s{2}chapter:\s*(.+?)\s*$", lines[j])
                if mm:
                    ch = mm.group(1).strip().strip("'\"")
                    break
                j += 1
            chapter_of[cur_id] = ch
            if is_macro_chapter(ch):
                stat["macro"] += 1
        elif cur_id and re.match(r"^\s{2}related_objects:\s*$", ln):
            in_ro = True
        elif in_ro and re.match(r"^\s{4}component_types:", ln):
            val = ln.split(":", 1)[1].strip()
            if val not in ("[]", ""):
                cur_has_ct = True          # 流式 [a, b]
            elif i + 1 < len(lines) and re.match(r"^\s{4}-\s*\S", lines[i + 1]):
                cur_has_ct = True          # 块式：下一行起是列表项
        elif in_ro and re.match(r"^\s{4}-\s*\S", ln):
            pass
        elif in_ro and re.match(r"^\s{2}\w", ln):
            # 离开 related_objects 块
            if cur_has_ct and is_macro_chapter(chapter_of.get(cur_id, "")):
                targets.add(cur_id)
                stat["macro_has_ct"] += 1
            in_ro, cur_has_ct = False, False
        i += 1
    if cur_has_ct and is_macro_chapter(chapter_of.get(cur_id, "")):
        targets.add(cur_id)
        stat["macro_has_ct"] += 1
    return targets, stat, chapter_of


def clear_in_text(path, targets):
    """文本级精确替换：把目标条文的 component_types 列表清空，其余字节不动"""
    raw = open(path, "rb").read()
    text = raw.decode("utf-8")
    # 行尾归一化：CRCRLF / CRLF / CR → LF（必须先收 \r\r\n）
    lines = (text.replace("\r\r\n", "\n")
                 .replace("\r\n", "\n")
                 .replace("\r", "\n")
                 .split("\n"))
    out, cur_id, in_ro, n_clear = [], None, False, 0
    i = 0
    while i < len(lines):
        ln = lines[i]
        m = re.match(r"^- id:\s*(.+?)\s*$", ln)
        if m:
            cur_id, in_ro = m.group(1), False
            out.append(ln); i += 1; continue
        if re.match(r"^\s{2}related_objects:\s*$", ln):
            in_ro = True
            out.append(ln); i += 1; continue
        if in_ro and cur_id in targets and re.match(r"^\s{4}component_types:", ln):
            indent = re.match(r"^(\s*)", ln).group(1)
            out.append(f"{indent}component_types: []")
            n_clear += 1
            # 跳过原列表项 / 流式的剩余内容
            i += 1
            while i < len(lines) and re.match(r"^\s{4}-\s*\S", lines[i]):
                i += 1
            continue
        if in_ro and re.match(r"^\s{2}\w", ln):
            in_ro = False
        out.append(ln); i += 1
    new_text = "\n".join(out)
    # 保持原行尾（正规化：CRCRLF/CR/LF → 单一 CRLF 或 LF）
    crlf = "\r\n" in text or "\r" in text
    if crlf:
        new_text = new_text.replace("\n", "\r\n")
    open(path, "wb").write(new_text.encode("utf-8"))
    return n_clear


def main():
    args = sys.argv[1:]
    apply_ = "--apply" in args
    scan_all = "--scan-all" in args

    files = sorted(glob.glob(os.path.join(D, "*.yaml")))
    files = [f for f in files
             if not os.path.basename(f).startswith("SCHEMA") and ".bak" not in f]
    if not scan_all:
        files = [f for f in files if os.path.basename(f) in
                 ("GB50222-2017.yaml", "GB50210-2018.yaml")]

    tot = {"total": 0, "macro": 0, "macro_has_ct": 0, "cleared": 0}
    for f in files:
        targets, stat, chapter_of = parse_targets(f)
        tot["total"] += stat["total"]; tot["macro"] += stat["macro"]
        tot["macro_has_ct"] += stat["macro_has_ct"]
        flag = ""
        if apply_ and targets:
            shutil.copy2(f, f + ".bak_macro_ct")
            n = clear_in_text(f, targets)
            tot["cleared"] += n
            flag = f"  >> 已清空 {n} 条（备份 .bak_macro_ct）"
        elif targets:
            # dry-run 展示样例
            sample = sorted(targets)[:3]
            flag = f"  将清空 {len(targets)} 条，例：{', '.join(sample)}"
        print(f"{os.path.basename(f):<24} 条文 {stat['total']:>4} | "
              f"宏观章 {stat['macro']:>4} | 挂CT {stat['macro_has_ct']:>4}{flag}")

    print(f"\n合计：条文 {tot['total']} / 宏观章 {tot['macro']} / "
          f"需清空 {tot['macro_has_ct']}" + (f" / 已清空 {tot['cleared']}" if apply_ else "（dry-run）"))


if __name__ == "__main__":
    main()
