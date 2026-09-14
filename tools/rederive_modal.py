# -*- coding: utf-8 -*-
"""v2.2 语气字段「从原文重推导」一致性比对（只读）

对已迁移册逐条重算 strictness / polarity / modal_words / primary / items，
与当前落盘值逐字段比对，列出全部不一致。

重推导规则（含边界例外）：
  - 抽词：单次扫描 + 长词优先 + 上下文排除（与 _migrate_modal_v22 一致）
  - 边界例外：否定词 + 紧邻边界动词（≤3字且无实义动词）→ 语义为边界(≥/≤)，
    计入「正面/required」而非「反面/prohibited」
  - 定级取严；同一档内既有正向贡献又有反向贡献 → mixed
"""
import os, re, sys, yaml, collections

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


def target_files():
    """优先两本已迁移册；否则扫目录下全部非 SCHEMA YAML"""
    if os.path.isdir(LOCAL):
        return ["GB50222-2017.yaml", "GB50210-2018.yaml"]
    return [f for f in sorted(os.listdir(D))
            if f.endswith(".yaml") and not f.startswith("SCHEMA") and ".bak" not in f]

TIER = [("必须/hard", {"必须"}, {"严禁", "禁止"}),
        ("应/shall", {"应"}, {"不应", "不得"}),
        ("宜/should", {"宜"}, {"不宜"}),
        ("可/may", {"可"}, set())]
NEG = {"严禁", "禁止", "不应", "不得", "不宜"}
POS = {"必须", "应", "宜", "可"}
SCAN = ["严禁", "不得", "不应", "不宜", "必须", "禁止", "应", "宜", "可"]
YING_EX = {"急", "用", "力", "变", "邀", "届", "付", "税", "答"}
YI_EX = {"便", "适", "因", "事", "机", "权", "得", "合"}
KE_EX = {"燃", "靠", "见", "听", "溶", "拆", "移", "视", "供", "能", "操", "维"}
BOUND = ["小于", "少于", "低于", "短于", "窄于", "薄于",
         "大于", "超过", "高于", "多于", "长于", "宽于", "厚于"]
RANK = {"必须/hard": 0, "应/shall": 1, "宜/should": 2, "可/may": 3}


def split_segments(text):
    t = re.sub(r"(\d)\.(\d)", r"\1<DOT>\2", text)
    t = re.sub(r"(\d)\.(\d)", r"\1<DOT>\2", t)
    t = re.sub(r"(\d):(\d)", r"\1<COLON>\2", t)
    out = [p.replace("<DOT>", ".").replace("<COLON>", ":").strip()
           for p in re.split(r"[，；。：:]", t)]
    return [p for p in out if p]


def occ_in(seg):
    """返回 [(word, pos)]，长词优先 + 排除"""
    out, i = [], 0
    while i < len(seg):
        hit = None
        for w in SCAN:
            if not seg.startswith(w, i):
                continue
            nxt = seg[i + len(w):i + len(w) + 1]
            if w == "应" and nxt in YING_EX: continue
            if w == "宜" and seg[i - 1:i] in YI_EX: continue
            if w == "可" and nxt in KE_EX: continue
            if w == "禁止" and seg[max(0, i - 2):i].endswith("明令"): continue
            hit = w
            break
        if hit:
            out.append((hit, i)); i += len(hit)
        else:
            i += 1
    return out


def boundary(seg, mw, j):
    if mw not in NEG:
        return False
    for b in BOUND:
        k = seg.find(b, j + len(mw))
        if k < 0: continue
        gap = seg[j + len(mw):k]
        if len(gap) <= 3 and not re.search(r"[在装设采使改用拆埋做]", gap):
            return True
    return False


def derive(text):
    words, contrib, tiers, segmaps = [], [], [], []
    for n, seg in enumerate(split_segments(text), 1):
        sw, sc = [], []
        for w, j in occ_in(seg):
            words.append(w)
            b = boundary(seg, w, j)
            if w in NEG and not b:
                sc.append("prohibited")
            else:
                sc.append("required")
            sw.append((w, b))
        contrib += sc
        segmaps.append((n, seg, sw))
    tiers = [t for t, p, nn in TIER if (set(words) & p) or (set(words) & nn)]
    st = min(tiers, key=lambda x: RANK[x]) if tiers else "无/none"
    ups = {c for c in contrib}
    pol = ("正反并存/mixed" if len(ups) > 1 else
           (next(iter(ups)) if ups else None))
    pol = {"required": "正面/required", "prohibited": "反面/prohibited"}.get(pol, pol) or "无/null"
    # primary = 最高档词集
    top_tier = st
    primary = sorted({w for n, s, sw in segmaps for w, b in sw
                      if _tier_of(w) == top_tier})
    return st, pol, sorted(set(words)), primary, segmaps


def _tier_of(w):
    for name, p, nn in TIER:
        if w in p or w in nn:
            return name
    return None


def main():
    for fn in target_files():
        path = fn if os.path.isabs(fn) else os.path.join(D, fn)
        if not os.path.exists(path):
            print(f"\n[跳过] 不存在：{path}")
            continue
        d = yaml.safe_load(open(path, encoding="utf-8"))
        diffs = []
        for c in d["clauses"]:
            ct = c.get("constraint") or {}
            if "strictness" not in ct:
                continue
            txt = c.get("text") or ""
            st, pol, words, primary, segmaps = derive(txt)
            cur = (ct.get("strictness"), ct.get("polarity"),
                   sorted(set(ct.get("modal_words") or [])),
                   sorted(set(ct.get("modal_words_primary") or [])))
            exp = (st, pol, words, primary)
            msgs = []
            if cur[0] != exp[0]:
                msgs.append(f"strictness {cur[0]} → {exp[0]}")
            if cur[1] != exp[1]:
                msgs.append(f"polarity {cur[1]} → {exp[1]}")
            if cur[2] != exp[2]:
                msgs.append(f"words {cur[2]} → {exp[2]}")
            if cur[3] != exp[3]:
                msgs.append(f"primary {cur[3]} → {exp[3]}")
            # items 存在性
            has = bool(ct.get("constraint_items"))
            need = exp[1] == "正反并存/mixed"
            if has != need:
                msgs.append(f"items {'有' if has else '无'} → {'需要' if need else '应清空'}")
            if msgs:
                diffs.append((c["clause_no"], msgs, txt))
        print(f"\n########## {os.path.basename(path)}：不一致 {len(diffs)} 条 ##########")
        for no, msgs, txt in diffs:
            print(f"  {no:<8} " + " | ".join(msgs))
            print(f"           «{txt[:70]}»")


if __name__ == "__main__":
    main()
