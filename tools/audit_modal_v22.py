# -*- coding: utf-8 -*-
"""
语气字段 v2.2 合规审计（v2.2.2）
规则见 SCHEMA_v2.2.yaml §6

用法:
  python audit_modal_v22.py                 # 扫描 standards/ 全部 *.yaml
  python audit_modal_v22.py <dir>           # 指定目录

规则:
  MODAL_ENUM_STRICTNESS   strictness 必须是 §6.1 的 5 个合法值
  MODAL_ENUM_POLARITY     polarity 必须是 §6.2 的 4 个合法值
  MODAL_MIXED_ITEMS       polarity=正反并存/mixed 必须带非空 constraint_items
  MODAL_ITEMS_ONLY_MIXED  非 mixed 的条文 constraint_items 必须为空
  MODAL_PRIMARY_MISSING   modal_words 非空但 strictness=无/none（抽取器漏判）
  MODAL_NULL_BUT_MANDATORY 强条但 strictness=无/none
  MODAL_ITEM_ENUM         constraint_items 内的 strictness/polarity 合法
  MODAL_LEGACY_FIELD      仍残留已废弃的 modal_level
  MODAL_TEXT_MISMATCH     modal_words 含正文中不存在的词（遗留误抽/上下文误抽）
  MODAL_DERIVE_MISMATCH   strictness/polarity/modal_words/modal_words_primary
                          与「由 text 重推导」结果不一致（含边界语义、跨档 mixed）

v2.2.2 关键判定（与 §6.2 边界规约一致）：
  - 抽词：单次扫描 + 长词优先（杜绝「不应」被拆成「应」）+ 上下文排除
    （「可能/可靠/可视」的『可』、「明令禁止」的『禁止』、「便宜/事宜」的『宜』）
  - 边界语义：否定词 + 紧邻边界动词（间隔 ≤3 字且无实义动词）→ 语义为边界(≥/≤)，
    计入 正面/required，不得标为 反面/prohibited
  - 跨档 mixed：定级取严的同时，正反贡献并存即 mixed（「必须 + 不得」也须识别）
"""
import os, sys, glob, collections, re
import yaml

STRICTNESS_OK = {"必须/hard", "应/shall", "宜/should", "可/may", "无/none"}
POLARITY_OK = {"正面/required", "反面/prohibited", "正反并存/mixed", "无/null"}

# 白名单：已人工裁定的「强条但无语气词」条文（见 _modal_allowlist.txt）
# 格式：条文id | 类别 | 说明   —— 只取 '|' 前的内容作 id
ALLOW_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "_modal_allowlist.txt")


def load_allowlist():
    s = set()
    if not os.path.exists(ALLOW_FILE):
        return s
    for ln in open(ALLOW_FILE, encoding="utf-8"):
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        s.add(ln.split("|")[0].strip())
    return s


ALLOW = load_allowlist()

NEG_WORDS = {"严禁", "禁止", "不应", "不得", "不宜"}
BOUND_WORDS = ["小于", "少于", "低于", "短于", "窄于", "薄于",
               "大于", "超过", "高于", "多于", "长于", "宽于", "厚于"]
TIER = [("必须/hard", {"必须"}, {"严禁", "禁止"}),
        ("应/shall", {"应"}, {"不应", "不得"}),
        ("宜/should", {"宜"}, {"不宜"}),
        ("可/may", {"可"}, set())]
TIER_RANK = {"必须/hard": 0, "应/shall": 1, "宜/should": 2, "可/may": 3, "无/none": 4}
SCAN = ["严禁", "不得", "不应", "不宜", "必须", "禁止", "应", "宜", "可"]
YING_EX = {"急", "用", "力", "变", "邀", "届", "付", "税", "答"}
YI_EX = {"便", "适", "因", "事", "机", "权", "得", "合"}
KE_EX = {"燃", "靠", "见", "听", "溶", "拆", "移", "视", "供", "能", "操", "维"}


def _split_segments(text):
    t = re.sub(r"(\d)\.(\d)", r"\1<DOT>\2", text)
    t = re.sub(r"(\d)\.(\d)", r"\1<DOT>\2", t)
    t = re.sub(r"(\d):(\d)", r"\1<COLON>\2", t)
    return [p.replace("<DOT>", ".").replace("<COLON>", ":")
            for p in (x.strip() for x in re.split(r"[，；。：:]", t)) if p]


def _occ(seg):
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


def _is_boundary(seg, mw, j=None):
    if mw not in NEG_WORDS or not seg:
        return False
    if j is None:
        j = seg.find(mw)
        if j < 0:
            return False
    for b in BOUND_WORDS:
        k = seg.find(b, j + len(mw))
        if k < 0:
            continue
        gap = seg[j + len(mw):k]
        if len(gap) <= 3 and not re.search(r"[在装设采使改用拆埋做]", gap):
            return True
    return False


def _tier_of(w):
    for name, p, n in TIER:
        if w in p or w in n:
            return name
    return None


def _derive(text):
    """由原文重推导 → (strictness, polarity, sorted words, sorted primary)"""
    words, contrib = [], []
    for seg in _split_segments(text):
        for w, j in _occ(seg):
            words.append(w)
            contrib.append("prohibited" if (w in NEG_WORDS and not _is_boundary(seg, w, j)) else "required")
    tiers = [t for t, p, n in TIER if (set(words) & p) or (set(words) & n)]
    st = min(tiers, key=lambda x: TIER_RANK[x]) if tiers else "无/none"
    ups = set(contrib)
    pol = ("正反并存/mixed" if len(ups) > 1 else
           ("正面/required" if ups == {"required"} else
            ("反面/prohibited" if ups == {"prohibited"} else "无/null")))
    ws = sorted(set(words))
    return st, pol, ws, sorted({w for w in ws if _tier_of(w) == st})


def audit_file(path):
    v = []
    try:
        doc = yaml.safe_load(open(path, encoding="utf-8"))
    except Exception as e:
        return [("YAML_PARSE", "-", str(e))]
    if not isinstance(doc, dict) or "clauses" not in doc:
        return v
    for c in (doc.get("clauses") or []):
        cid = c.get("id")
        ct = c.get("constraint") or {}
        if "strictness" not in ct:
            continue                      # 尚未迁移到 v2.2 的册，跳过
        if "modal_level" in ct:
            v.append(("MODAL_LEGACY_FIELD", cid, "残留 modal_level=%r" % ct["modal_level"]))
        st, pol = ct.get("strictness"), ct.get("polarity")
        words = ct.get("modal_words") or []
        items = ct.get("constraint_items") or []
        txt = c.get("text") or ""
        mand = ct.get("is_mandatory_clause")

        if st not in STRICTNESS_OK:
            v.append(("MODAL_ENUM_STRICTNESS", cid, repr(st)))
        if pol not in POLARITY_OK:
            v.append(("MODAL_ENUM_POLARITY", cid, repr(pol)))
        if words and st == "无/none":
            v.append(("MODAL_PRIMARY_MISSING", cid, "modal_words=%s 但 strictness=none" % words))
        if mand and st == "无/none" and cid not in ALLOW:
            v.append(("MODAL_NULL_BUT_MANDATORY", cid, "强条但无语气词"))
        if pol == "正反并存/mixed" and not items:
            v.append(("MODAL_MIXED_ITEMS", cid, "mixed 但 constraint_items 为空"))
        if pol != "正反并存/mixed" and items:
            v.append(("MODAL_ITEMS_ONLY_MIXED", cid, "非 mixed 却有 %d 条 items" % len(items)))

        # 正文一致性
        for w in words:
            if w not in txt:
                v.append(("MODAL_TEXT_MISMATCH", cid, "『%s』不在正文中" % w))
                break

        # 由原文重推导一致性（最强规则）
        if txt:
            dst, dpol, dws, dpri = _derive(txt)
            bad = []
            if st != dst:   bad.append("strictness %s→%s" % (st, dst))
            if pol != dpol: bad.append("polarity %s→%s" % (pol, dpol))
            if sorted(set(words)) != dws: bad.append("words %s→%s" % (sorted(set(words)), dws))
            if sorted(set(ct.get("modal_words_primary") or [])) != dpri:
                bad.append("primary %s→%s" % (sorted(set(ct.get("modal_words_primary") or [])), dpri))
            if bad:
                v.append(("MODAL_DERIVE_MISMATCH", cid, " | ".join(bad)))

        for it in items:
            if it.get("strictness") not in STRICTNESS_OK:
                v.append(("MODAL_ITEM_ENUM", cid, "item%s strictness=%r" % (it.get("seq"), it.get("strictness"))))
            if it.get("polarity") not in POLARITY_OK:
                v.append(("MODAL_ITEM_ENUM", cid, "item%s polarity=%r" % (it.get("seq"), it.get("polarity"))))
            if it.get("polarity") == "反面/prohibited" and \
               _is_boundary(it.get("text_segment") or "", it.get("modal_word") or ""):
                v.append(("MODAL_BOUNDARY_POLARITY", cid,
                          "item%s «%s» 是边界(≥/≤)非禁止" % (it.get("seq"), (it.get("text_segment") or "")[:24])))
    return v


def default_root():
    """定位 standards/ 目录：优先命令行传入 > 环境变量 STANDARDS_DIR > ./standards > ../standards > 当前目录"""
    env = os.environ.get("STANDARDS_DIR")
    if env and os.path.isdir(env):
        return env
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.join(here, "standards"), os.path.join(here, "..", "standards"),
                 os.getcwd(), os.path.join(os.getcwd(), "standards")):
        if os.path.isdir(cand) and any(f.endswith(".yaml") for f in os.listdir(cand)):
            return cand
    return os.getcwd()


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else default_root()
    files = sorted(glob.glob(os.path.join(root, "*.yaml")))
    files = [f for f in files
             if not os.path.basename(f).startswith("SCHEMA") and ".bak" not in f]
    all_v, migrated = [], 0
    for f in files:
        v = audit_file(f)
        all_v += v
        try:
            d = yaml.safe_load(open(f, encoding="utf-8"))
            if any("strictness" in (c.get("constraint") or {}) for c in (d.get("clauses") or [])):
                migrated += 1
        except Exception:
            pass
    cnt = collections.Counter(x[0] for x in all_v)
    total = sum(cnt.values())
    print(f"scanned: {len(files)} files ({migrated} migrated to v2.2)")
    if ALLOW:
        print(f"allowlist: {len(ALLOW)} 条已人工裁定豁免（MODAL_NULL_BUT_MANDATORY）")
    print(f"violations: {total}")
    for k, n in sorted(cnt.items()):
        print(f"  {n:5d}  {k}")
    if total:
        print("\n样例（前 20）：")
        for r in all_v[:20]:
            print("  ", r[0], r[1], r[2])
    return 0 if total == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
