# -*- coding: utf-8 -*-
"""
v2.2 语气字段「以原文为准」全量重推导修复（v2.2.2）

背景（第三方审查 + 自查发现）：
  1. 边界语义：否定词 + 紧邻边界动词（不得少于3间 / 不应大于50N）语义是设定边界(≥/≤)，
     不是"禁止做某事" → polarity 应为 正面/required（方向由 parameters.min/max 承载）
  2. 跨档 mixed 漏判：_migrate_modal_v22.classify() 取第一档命中即 break，
     导致「必须 + 不得」「应 + 不宜」这类**跨档正反并存**被判为单一极性
  3. 遗留误抽：modal_words 含正文中不存在的词（如 4.0.20 的『不应』、6.0.5 的『不得』）
  4. 上下文误抽：『可能』『可靠』『可视』被当成许可语气『可』

原则：text 是唯一权威。由 text 重推导 strictness / polarity / modal_words /
      modal_words_primary / constraint_items，逐条覆盖。

用法：
  python _refix_modal_v22.py            # dry-run（列出全部差异）
  python _refix_modal_v22.py --apply    # 写盘（自动 .bak_refix_v222，行尾正规化为 CRLF）
"""
import os, re, sys, shutil, collections
import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:                                    # 本地（下划线前缀）
    from rederive_modal import (split_segments, occ_in, boundary, TIER, RANK,
                                 NEG, POS, _tier_of)
except ImportError:                     # 开源仓库（tools/rederive_modal.py）
    from rederive_modal import (split_segments, occ_in, boundary, TIER, RANK,
                                NEG, POS, _tier_of)

D = os.environ.get("STANDARDS_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "standards")
FILES = ["GB50222-2017.yaml", "GB55031-2022.yaml"]
ORDER = ["strictness", "polarity", "modal_words", "modal_words_primary",
         "is_mandatory_clause", "mandatory_basis", "constraint_items"]


def build_items(text):
    """按分句拆分，逐句标注（含边界语义）；仅 mixed 时使用"""
    items, seq = [], 0
    for seg in split_segments(text):
        occ = occ_in(seg)
        if not occ:
            continue
        words = [w for w, _ in occ]
        contrib = []
        for w, j in occ:
            contrib.append("prohibited" if (w in NEG and not boundary(seg, w, j)) else "required")
        ups = set(contrib)
        if len(ups) > 1:
            pol = "正反并存/mixed"
        else:
            pol = "正面/required" if ups == {"required"} else "反面/prohibited"
        tiers = [t for t, p, n in TIER if (set(words) & p) or (set(words) & n)]
        st = min(tiers, key=lambda x: RANK[x]) if tiers else "无/none"
        seq += 1
        items.append({"seq": seq, "text_segment": seg, "strictness": st,
                      "polarity": pol, "modal_word": "/".join(sorted(set(words)))})
    return items


def derive_constraint(text, is_mand, basis):
    words, contrib = [], []
    for seg in split_segments(text):
        for w, j in occ_in(seg):
            words.append(w)
            contrib.append("prohibited" if (w in NEG and not boundary(seg, w, j)) else "required")
    tiers = [t for t, p, n in TIER if (set(words) & p) or (set(words) & n)]
    st = min(tiers, key=lambda x: RANK[x]) if tiers else "无/none"
    ups = set(contrib)
    pol = ("正反并存/mixed" if len(ups) > 1 else
           ("正面/required" if ups == {"required"} else
            ("反面/prohibited" if ups == {"prohibited"} else "无/null")))
    ws = sorted(set(words))
    primary = sorted({w for w in ws if _tier_of(w) == st})
    items = build_items(text) if pol == "正反并存/mixed" else []
    return {"strictness": st, "polarity": pol, "modal_words": ws,
            "modal_words_primary": primary,
            "is_mandatory_clause": is_mand, "mandatory_basis": basis,
            "constraint_items": items}


def yaml_block(ct):
    """生成 4 空格缩进的 constraint 块（含 '  constraint:' 首行）"""
    body = yaml.safe_dump({k: ct[k] for k in ORDER if k in ct},
                          allow_unicode=True, sort_keys=False,
                          default_flow_style=False, width=10000)
    return "  constraint:\n" + "".join("    " + l + "\n" for l in body.rstrip("\n").split("\n"))


def scan_and_patch(path, apply=False):
    raw = open(path, "rb").read()
    text = raw.decode("utf-8")
    crlf = b"\r\n" in raw or b"\r" in raw
    # 行尾归一化：CRCRLF / CRLF / CR → LF
    # 必须先收 \r\r\n，否则 \r\r\n 会被拆成两个 \n（凭空多出空行）
    lines = (text.replace("\r\r\n", "\n")
                 .replace("\r\n", "\n")
                 .replace("\r", "\n")
                 .split("\n"))

    # 先解析出每条 clause 的 (is_mandatory, basis, text)
    doc = yaml.safe_load(text)
    meta = {}
    for c in doc.get("clauses") or []:
        ct = c.get("constraint") or {}
        if "strictness" not in ct:
            continue
        meta[c["clause_no"]] = (ct.get("is_mandatory_clause"),
                                ct.get("mandatory_basis"),
                                c.get("text") or "",
                                ct)

    out, cur, n_fix = [], None, 0
    diffs = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        m = re.match(r"^- id:\s*(?:\S.*?)#([^#\s]+)\s*$", ln)   # 泛化：GB/JGJ/SJG/DB 均可
        if m:
            cur = m.group(1)
            out.append(ln); i += 1; continue
        if cur in meta and re.match(r"^\s{2}constraint:\s*$", ln):
            is_mand, basis, txt, old = meta[cur]
            new = derive_constraint(txt, is_mand, basis)
            # 差异报告
            ch = []
            for k in ("strictness", "polarity", "modal_words", "modal_words_primary"):
                if old.get(k) != new.get(k):
                    ch.append(f"{k} {old.get(k)} → {new.get(k)}")
            if bool(old.get("constraint_items")) != bool(new["constraint_items"]):
                ch.append("items " + ("清空" if not new["constraint_items"] else "新增"))
            if ch:
                diffs.append((cur, ch, txt))
            out.append(yaml_block(new).rstrip("\n"))
            n_fix += 1
            # 跳过旧块（缩进 >= 4 的非空行；遇空行/2空格字段即止，保留原分隔空行）
            i += 1
            while i < len(lines) and re.match(r"^\s{4,}\S", lines[i]):
                i += 1
            continue
        out.append(ln); i += 1

    new_text = "\n".join(out)
    if crlf:
        new_text = new_text.replace("\n", "\r\n")

    if apply:
        shutil.copy2(path, path + ".bak_refix_v222")
        open(path, "wb").write(new_text.encode("utf-8"))
        # 写盘自检：constraint 字段数必须与 top-level 条文数一致（防字段重复/块未闭合）
        chk = open(path, "rb").read().decode("utf-8")
        n_st = chk.count("\n    strictness:")
        n_cl = len(re.findall(r"(?m)^- id: \S", chk))
        if n_st != n_cl:
            raise SystemExit(f"!! 自检失败：strictness {n_st} ≠ 条文 {n_cl}；"
                             f"请从 {os.path.basename(path)}.bak_refix_v222 回滚")
    return n_fix, diffs


def main():
    do = "--apply" in sys.argv
    files = FILES
    if "--files" in sys.argv:                      # 逗号分隔的文件名
        files = [x.strip() for x in sys.argv[sys.argv.index("--files") + 1].split(",") if x.strip()]
    elif "--all" in sys.argv:
        import glob
        files = [os.path.basename(p) for p in sorted(glob.glob(os.path.join(D, "*.yaml")))]
    for fn in files:
        p = os.path.join(D, fn)
        n, diffs = scan_and_patch(p, apply=do)
        print(f"\n===== {fn}：重写 {n} 条 constraint，差异 {len(diffs)} 条 =====")
        for cid, ch, txt in diffs:
            print(f"  {cid:<8} " + " | ".join(ch))
            print(f"           «{txt[:66]}»")
    print("\n" + ("已写盘（备份 .bak_refix_v222）" if do else "dry-run，未写盘；加 --apply 执行"))


if __name__ == "__main__":
    main()
