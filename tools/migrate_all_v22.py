# -*- coding: utf-8 -*-
"""
v2.1 → v2.2 全库语气字段迁移（通用版，v2.2.2 规约）

与旧版 _migrate_modal_v22.py 的区别（旧版已废弃）：
  旧版用 classify() 取第一档命中即 break → 跨档 mixed（「必须+不得」「应+不宜」）漏判
  本脚本**完全以 text 为唯一权威**重推导，与 _rederive_modal / _refix_modal_v22 同源，
  因此迁移结果天然满足 audit_modal_v22 的重推导规则（MODAL_DERIVE_MISMATCH = 0）

迁移内容（每条 clause 的 constraint 块）：
  删除  modal_level
  新增  strictness / polarity / modal_words_primary / constraint_items
  保留  modal_words（重推导覆盖）/ is_mandatory_clause / mandatory_basis
文件头：schema_version: v2.1 → v2.2

用法：
  python _migrate_all_v22.py                 # dry-run（统计 + 抽样）
  python _migrate_all_v22.py --apply         # 写盘（自动生成 .bak_v21，行尾保持原样）
  python _migrate_all_v22.py --apply --only GB55031-2022.yaml GB50176-2016.yaml
"""
import os, re, sys, shutil, collections

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:                                    # 本地（下划线前缀）
    from _rederive_modal import (split_segments, occ_in, boundary, TIER, RANK,
                                 NEG, POS, _tier_of)
except ImportError:                     # 开源仓库（tools/rederive_modal.py）
    from rederive_modal import (split_segments, occ_in, boundary, TIER, RANK,
                                NEG, POS, _tier_of)

LOCAL = os.environ.get("STANDARDS_DIR", "")


def resolve_root():
    """本地开发路径优先；开源仓库中回退到 ./standards / ../standards / 当前目录"""
    if os.path.isdir(LOCAL):
        return LOCAL
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.join(here, "standards"), os.path.join(here, "..", "standards"),
                 os.getcwd(), os.path.join(os.getcwd(), "standards")):
        if os.path.isdir(cand) and any(f.endswith(".yaml") for f in os.listdir(cand)):
            return cand
    return os.getcwd()


D = resolve_root()
ORDER =["strictness", "polarity", "modal_words", "modal_words_primary",
         "is_mandatory_clause", "mandatory_basis", "constraint_items"]
ID_RE = re.compile(r"^- id:\s*(\S+ \S+)#([\w.]+)\s*$")
# 兼容 PyYAML 生成的锚点/别名写法：`  constraint: &id001` / `  constraint: *id001`
CONS_RE = re.compile(r"^\s{2}constraint:(?:\s*[&*]id\d+)?\s*$")


def build_items(text):
    """按分句拆分逐句标注（含边界语义）；仅 mixed 时使用"""
    items, seq = [], 0
    for seg in split_segments(text):
        occ = occ_in(seg)
        if not occ:
            continue
        words = [w for w, _ in occ]
        contrib = ["prohibited" if (w in NEG and not boundary(seg, w, j))
                   else "required" for w, j in occ]
        ups = set(contrib)
        pol = ("正反并存/mixed" if len(ups) > 1 else
               ("正面/required" if ups == {"required"} else "反面/prohibited"))
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
            contrib.append("prohibited" if (w in NEG and not boundary(seg, w, j))
                           else "required")
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
    body = yaml.safe_dump({k: ct[k] for k in ORDER if k in ct},
                          allow_unicode=True, sort_keys=False,
                          default_flow_style=False, width=10000)
    return "  constraint:\n" + "".join("    " + l + "\n"
                                       for l in body.rstrip("\n").split("\n"))


def norm_lines(text):
    """行尾归一化：CRCRLF / CRLF / CR → LF（必须先收 \\r\\r\\n）"""
    return (text.replace("\r\r\n", "\n")
                .replace("\r\n", "\n")
                .replace("\r", "\n")
                .split("\n"))


def process(path, apply=False):
    raw = open(path, "rb").read()
    text = raw.decode("utf-8")
    crlf = (b"\r\n" in raw) or (b"\r" in raw)
    lines = norm_lines(text)

    doc = yaml.safe_load(text)
    meta = {}
    for c in doc.get("clauses") or []:
        ct = c.get("constraint") or {}
        meta[c["clause_no"]] = (ct.get("is_mandatory_clause"),
                                ct.get("mandatory_basis"),
                                c.get("text") or "",
                                ct)
    # v2.1 → 记录原 modal_level 分布，便于核对
    lv = collections.Counter((c.get("constraint") or {}).get("modal_level")
                             for c in doc.get("clauses") or [])

    out, cur, n_fix = [], None, 0
    stats = collections.Counter()
    samples = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        m = ID_RE.match(ln)
        if m:
            cur = m.group(2)
            out.append(ln); i += 1; continue
        if cur in meta and CONS_RE.match(ln):
            is_mand, basis, txt, old = meta[cur]
            new = derive_constraint(txt, is_mand, basis)
            stats[new["strictness"]] += 1
            stats[new["polarity"]] += 1
            if new["constraint_items"]:
                stats["items"] += 1
            if len(samples) < 6 and new["polarity"] != "正面/required":
                samples.append((cur, new, txt))
            out.append(yaml_block(new).rstrip("\n"))
            n_fix += 1
            i += 1
            while i < len(lines) and re.match(r"^\s{4,}\S", lines[i]):
                i += 1
            continue
        out.append(ln); i += 1

    new_text = "\n".join(out)
    # schema_version: v2.1 → v2.2（仅 v2.1 时替换）
    n_sv = len(re.findall(r"(?m)^(\s{2}schema_version:\s*)v2\.1\s*$", new_text))
    new_text = re.sub(r"(?m)^(\s{2}schema_version:\s*)v2\.1\s*$", r"\1v2.2", new_text)
    if crlf:
        new_text = new_text.replace("\n", "\r\n")

    if n_fix != len(meta):
        print(f"   !! 警告：重写 {n_fix} ≠ 条文 {len(meta)}，结构异常，跳过写盘")
        do_apply = False
    else:
        do_apply = apply

    if do_apply:
        shutil.copy2(path, path + ".bak_v21")
        open(path, "wb").write(new_text.encode("utf-8"))
        chk = open(path, "rb").read().decode("utf-8")
        # 自检 1：行数守恒
        n_st = chk.count("\n    strictness:")
        n_cl = len(re.findall(r"(?m)^- id: \S", chk))
        if n_st != n_cl:
            raise SystemExit(f"!! 自检失败：strictness {n_st} ≠ 条文 {n_cl}；"
                             f"请从 {os.path.basename(path)}.bak_v21 回滚")
        # 自检 2：无 modal_level 残留
        if "modal_level" in chk:
            raise SystemExit("!! 自检失败：仍残留 modal_level；请回滚")
        # 自检 3：YAML 可解析（锚点/别名不得悬空）
        try:
            d2 = yaml.safe_load(chk)
        except Exception as e:
            raise SystemExit(f"!! 自检失败：YAML 无法解析（{e}）；请回滚")
        if len(d2.get("clauses") or []) != len(meta):
            raise SystemExit("!! 自检失败：条文数变化；请回滚")
    return dict(n_fix=n_fix, stats=stats, samples=samples, crlf=crlf,
                lv=lv, sv=n_sv, n_clause=len(doc.get("clauses") or []))


def main():
    do = "--apply" in sys.argv
    only = None
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1:]
    files = [f for f in sorted(os.listdir(D))
             if f.endswith(".yaml") and not f.startswith("SCHEMA") and ".bak" not in f]
    if only:
        files = [f for f in files if f in only]
    tot = collections.Counter()
    for fn in files:
        p = os.path.join(D, fn)
        txt = open(p, "rb").read().decode("utf-8")
        if "strictness:" in txt:
            print(f"[跳过] {fn} 已是 v2.2")
            continue
        if "modal_level" not in txt:
            print(f"[跳过] {fn} 无 modal_level，疑似异常，请人工确认")
            continue
        r = process(p, apply=do)
        tot.update(r["stats"])
        print(f"\n===== {fn}：重写 {r['n_fix']}/{r['n_clause']} 条，"
              f"schema_version 替换 {r['sv']}，行尾 {'CRLF' if r['crlf'] else 'LF'} =====")
        print("   原 modal_level 分布：" +
              ", ".join(f"{k}={v}" for k, v in r["lv"].most_common()))
        print("   新：" + ", ".join(f"{k}={v}" for k, v in r["stats"].most_common()))
        for cid, new, tx in r["samples"]:
            print(f"   · {cid} {new['strictness']} / {new['polarity']} "
                  f"{new['modal_words']} «{tx[:50]}»")
    print("\n合计：" + ", ".join(f"{k}={v}" for k, v in tot.most_common()))
    print("已写盘（备份 .bak_v21）" if do else "dry-run，未写盘；加 --apply 执行")


if __name__ == "__main__":
    main()
