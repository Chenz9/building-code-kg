# -*- coding: utf-8 -*-
"""绑定层审计器 v2.3（SCHEMA_v2.3 §9.6 的工程化实现）。

检查项（ID 与 schema §9.6 一致）：
  C-BINDING-01 ifc_entity 不在 component 白名单 / 命中 forbidden → error
               ★ 未迁移册轻量检查：component_types 命中 forbidden（死名宽匹配残留）同报
  C-BINDING-03 同册最大单一 (ifc_entity, predefined_type) 组合占比 > 30% → warning
               ★ 分母 = binding_level∈{element,system} 且非「整条降级」的条文数；
                 条文数 < 20 时跳过（样本不足）
  C-BINDING-04 空间收窄条件丢失 → error（三分支 a/c，b 合法不报）
  C-BINDING-04a 源数据侧收窄检查（不依赖编译产物）→ error
  C-BINDING-05 property_requirements 出现字面值（非 parameter_ref）→ error
  C-BINDING-06 IfcBuilding 出现于 binding_level≠building → error
  C-BINDING-07 component_types 与 model_bindings 派生集合不一致 → warning
  C-BINDING-08 system 级绑定缺 predefined_type / ObjectType → error
  C-BINDING-09 property_requirements.parameter_ref 指向不存在的参数 → error
               ★ draft 绑定的占位符（如 PENDING_TABLE_STRUCTURE，表格型未结构化）豁免
  C-BINDING-10 binding_level=macro/process 却带构件实体 → error
  C-BINDING-11 mapping_status=not_applicable 却缺 reason → error
  C-BINDING-12 space_context 合法性：carrier 非法 → error；values 未命中词表
               space_map（仅 carrier=IfcSpace.ObjectType）→ warning
  C-RATIO-01  册级 not_applicable 占比 > 15%（分母=非 macro 条文数）→ warning
  C-RATIO-02  predefined_type_required_entities 的 PredefinedType 使用率 < 90% → warning
              ★ 分母 = model_bindings 中 ifc_entity 命中该列表的绑定条数
  C-RULE-01   RULE_COMPILE_MISMATCH（落盘规则 ≠ 源数据重编译）→ error

用法：
  python audit_binding_v23.py <bundle.yaml> [...]        # 审计（退出码 0=全 0，1=有发现）
  python audit_binding_v23.py --selftest                 # 自证：合成违规数据验证每条检查会触发
支持输入：binding bundle（samples:）或迁移后的标准 YAML（clauses:）。
未迁移文件（无 binding_level）→ 报「未迁移」并跳过绑定检查（不误报）。
"""
import sys, io, os, json, copy
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from rule_compiler import (canonical_rules_for, compare_clause,  # noqa: E402
                           binding04, binding04a, CARRIERS)

DICT_PATH = os.path.join(ROOT, "ifc_mapping_dict_v0.yaml")
MIN_CLAUSES_FOR_RATIO = 20   # 组合占比/比例的样本下限（低于此值不做比例判定）
DEGRADED = ("needs_expert_review", "not_applicable")


def load_dict(path=DICT_PATH):
    return yaml.safe_load(open(path, encoding="utf-8"))


def allowed_space_tokens(dict_data):
    """词表 space_map 允许的空间取值（space_name ∪ convention_value）。"""
    allowed = set()
    for e in dict_data.get("space_map") or []:
        allowed.add(e.get("space_name"))
        allowed.add(e.get("convention_value"))
    allowed.discard(None)
    return allowed


def to_samples(doc):
    """统一视图：binding bundle（samples）或标准 YAML（clauses）→ (samples, migrated)。"""
    if "samples" in doc:
        return doc["samples"], True     # binding bundle 天然是绑定层数据
    clauses = doc.get("clauses") or []
    out = []
    migrated = False
    for c in clauses:
        ro = c.get("related_objects") or {}
        if ro.get("binding_level"):
            migrated = True
        out.append({
            "clause_id": c.get("standard_code", "?") + "#" + str(c.get("clause_no")),
            "standard_code": c.get("standard_code"),
            "clause_no": c.get("clause_no"),
            "chapter": c.get("chapter"),
            "related_objects": ro,
            "parameters": c.get("parameters") or [],
            "compiled_rules": c.get("executable_rules") or [],
        })
    return out, migrated


def _space_values(mb):
    sc = mb.get("space_context") or {}
    vals = sc.get("values")
    if vals is None and sc.get("value") is not None:
        vals = [sc["value"]]
    return [str(v) for v in (vals or [])]


def ratio_scope(ss):
    """C-BINDING-03 分母口径（v0.4）：binding_level∈{element,system} 且非整条降级。"""
    out = []
    for s in ss:
        ro = s.get("related_objects") or {}
        if ro.get("binding_level") not in ("element", "system"):
            continue
        mbs = ro.get("model_bindings") or []
        if mbs and all(mb.get("mapping_status") in DEGRADED for mb in mbs):
            continue
        out.append(s)
    return out


def run_checks(samples, dict_data):
    F = []
    comp = set(dict_data["entity_whitelist"]["component_ifc4"])
    comp |= set(dict_data["entity_whitelist"].get("component_ifc4_3_ext") or [])
    forbidden = {x["entity"]: x["reason"] for x in dict_data["entity_whitelist"].get("forbidden") or []}
    pdt_required = set((dict_data.get("naming_conventions") or {}).get(
        "predefined_type_required_entities") or [])
    spaces_ok = allowed_space_tokens(dict_data)
    micro = ("macro", "process")

    for s in samples:
        cid = s["clause_id"]
        ro = s.get("related_objects") or {}
        level = ro.get("binding_level")
        mbs = ro.get("model_bindings") or []
        params = {p["id"]: p for p in (s.get("parameters") or []) if isinstance(p, dict) and p.get("id")}

        # C-BINDING-10
        if level in micro and mbs:
            F.append(("C-BINDING-10", "error", f"{cid}: binding_level={level} 却带 {len(mbs)} 条 model_bindings"))

        for mb in mbs:
            mid = mb.get("id")
            ent = mb.get("ifc_entity")
            # C-BINDING-01
            if ent in forbidden:
                F.append(("C-BINDING-01", "error", f"{cid}/{mid}: ifc_entity={ent} 在 forbidden（{forbidden[ent]}）"))
            elif ent not in comp:
                F.append(("C-BINDING-01", "error", f"{cid}/{mid}: ifc_entity={ent} 不在 component 白名单"))
            # C-BINDING-06
            if ent == "IfcBuilding" and level != "building":
                F.append(("C-BINDING-06", "error",
                          f"{cid}/{mid}: IfcBuilding 出现于 binding_level={level}（仅 building 级可用）"))
            # C-BINDING-08
            if ent in ("IfcDistributionSystem", "IfcSystem") and not (mb.get("predefined_type") or mb.get("object_type")):
                F.append(("C-BINDING-08", "error", f"{cid}/{mid}: 系统级绑定缺 predefined_type/ObjectType"))
            # C-BINDING-05 / C-BINDING-09
            for pr in mb.get("property_requirements") or []:
                if "value" in pr or "min" in pr or "max" in pr:
                    F.append(("C-BINDING-05", "error",
                              f"{cid}/{mid}: property_requirements 出现字面值（应只引用 parameter_ref）"))
                pref = pr.get("parameter_ref")
                # draft 绑定的占位符（如 PENDING_TABLE_STRUCTURE）豁免——表格型分阶段第一步
                if pref and pref not in params and mb.get("mapping_status") != "draft":
                    F.append(("C-BINDING-09", "error", f"{cid}/{mid}: parameter_ref={pref} 指向不存在的参数"))
            # not_applicable 必附 reason（§9.2）→ C-BINDING-11
            if mb.get("mapping_status") == "not_applicable" and not mb.get("reason"):
                F.append(("C-BINDING-11", "error", f"{cid}/{mid}: mapping_status=not_applicable 但缺 reason"))
            # C-BINDING-12 space_context 合法性
            sc = mb.get("space_context")
            if sc:
                carrier = sc.get("carrier") or "IfcSpace.ObjectType"
                if carrier not in CARRIERS:
                    F.append(("C-BINDING-12", "error",
                              f"{cid}/{mid}: space_context.carrier={carrier} 不在枚举 {list(CARRIERS)}"))
                elif carrier == "IfcSpace.ObjectType":
                    unknown = [v for v in _space_values(mb) if v not in spaces_ok]
                    if unknown:
                        F.append(("C-BINDING-12", "warning",
                                  f"{cid}/{mid}: 空间取值 {unknown} 未命中词表 space_map（项目约定漂移）"))

        # C-BINDING-07（component_types 与派生集合一致性，迁移期 warning）
        if mbs and ro.get("component_types") is not None:
            derived = {mb.get("ifc_entity") for mb in mbs if mb.get("ifc_entity")}
            if set(ro.get("component_types") or []) != derived:
                F.append(("C-BINDING-07", "warning",
                          f"{cid}: component_types={ro.get('component_types')} ≠ 派生集合={sorted(derived)}"))

        # C-BINDING-04（三分支）/ C-BINDING-04a / C-RULE-01
        e4, w4 = binding04(s)
        F += [(("C-BINDING-04", "error", m)) for m in e4]
        F += [(("C-BINDING-04", "warning", m)) for m in w4]
        F += [(("C-BINDING-04a", "error", m)) for m in binding04a(s)]
        r = compare_clause(s)
        for k in ("missing", "extra", "mismatched"):
            F += [(("C-RULE-01", "error", m)) for m in r[k]]

    # ---- 册级比例（按 standard_code 分组）----
    books = {}
    for s in samples:
        books.setdefault(s.get("standard_code"), []).append(s)
    for book, ss in books.items():
        non_macro = [s for s in ss if (s.get("related_objects") or {}).get("binding_level") not in ("macro",)]
        if book is None or not non_macro:
            continue

        # C-BINDING-03 组合占比（分母收紧：element/system 且非整条降级）
        scope = ratio_scope(ss)
        if len(scope) >= MIN_CLAUSES_FOR_RATIO:
            combo_count = {}
            for s in scope:
                combos = {(mb.get("ifc_entity"), mb.get("predefined_type"))
                          for mb in ((s.get("related_objects") or {}).get("model_bindings") or [])}
                for c in combos:
                    combo_count[c] = combo_count.get(c, 0) + 1
            if combo_count:
                top, n = max(combo_count.items(), key=lambda kv: kv[1])
                if n / len(scope) > 0.30:
                    F.append(("C-BINDING-03", "warning",
                              f"{book}: 最大单一组合 {top} 占 {n}/{len(scope)}="
                              f"{n/len(scope):.0%} > 30%（分母=element/system 非降级条文）"))

        # C-RATIO-01 not_applicable 占比（分母=非 macro 条文数，v0.3 口径）
        na = sum(1 for s in non_macro
                 if any(mb.get("mapping_status") == "not_applicable"
                        for mb in ((s.get("related_objects") or {}).get("model_bindings") or [])))
        if na / len(non_macro) > 0.15:
            F.append(("C-RATIO-01", "warning",
                      f"{book}: not_applicable {na}/{len(non_macro)}={na/len(non_macro):.0%} > 15%"))

        # C-RATIO-02 PredefinedType 使用率（分母=命中 required 实体的绑定条数）
        hit = total = 0
        for s in non_macro:
            for mb in ((s.get("related_objects") or {}).get("model_bindings") or []):
                if mb.get("ifc_entity") in pdt_required:
                    total += 1
                    if mb.get("predefined_type"):
                        hit += 1
        if total and hit / total < 0.90:
            F.append(("C-RATIO-02", "warning",
                      f"{book}: required 实体 PredefinedType 使用率 {hit}/{total}={hit/total:.0%} < 90%"))
    return F


def ct_forbidden_findings(samples, dict_data):
    """未迁移册轻量检查：component_types 命中 forbidden（死名宽匹配残留）。"""
    forbidden = {x["entity"]: x["reason"] for x in dict_data["entity_whitelist"].get("forbidden") or []}
    F = []
    for s in samples:
        cts = (s.get("related_objects") or {}).get("component_types") or []
        hits = [c for c in cts if c in forbidden]
        if hits:
            F.append(("C-BINDING-01", "error",
                      f"{s['clause_id']}: component_types 死名 {hits}（{'；'.join(forbidden[h] for h in hits)}）"))
    return F


def audit_files(paths):
    dict_data = load_dict()
    all_F, skipped = [], []
    for p in paths:
        doc = yaml.safe_load(open(p, encoding="utf-8"))
        samples, migrated = to_samples(doc)
        if not migrated:
            F = ct_forbidden_findings(samples, dict_data)
            all_F += [(os.path.basename(p),) + f for f in F]
            if not F:
                skipped.append(f"{os.path.basename(p)}：未迁移（无 binding_level），跳过绑定层检查")
            continue
        for f in run_checks(samples, dict_data):
            all_F.append((os.path.basename(p),) + f)
    return all_F, skipped


# ---------- 自证模式 ----------

def selftest():
    """合成违规数据，逐条检查必须触发（证明审计不是摆设）。"""
    comp = "IfcCovering"
    samples = []
    # 25 条非 macro 条文，全部同一组合 (IfcCovering, CEILING) → C-BINDING-03
    # 其中 5 条 not_applicable → C-RATIO-01；5 条缺 pdt → C-RATIO-02
    # i=6  space_context + 字面值 → C-BINDING-05（且 when 无空间条件 → 04a/04a）
    # i=11 space_context.values=[] → C-BINDING-04a（源数据侧收窄丢失）
    # i=12 space_context + 规则值域真子集 → C-BINDING-04 警告分支 (c)
    # i=13 carrier 非法 → C-BINDING-12 error
    # i=14 空间取值未命中词表 → C-BINDING-12 warning
    for i in range(25):
        cid = f"GB 99999-2020#4.0.{i+1}"
        mb = {"id": f"mb_{i}", "role": "顶棚", "ifc_entity": comp,
              # 0..3 与 10 缺 pdt → C-RATIO-02（缺失 > 10%）
              "predefined_type": None if i in (0, 1, 2, 3, 10) else "CEILING",
              "property_requirements": [{"parameter_ref": f"p_{i}", "pset": "Pset_CoveringCommon",
                                         "property": "FlammabilityRating"}],
              "mapping_status": "not_applicable" if i < 5 else "mapped",
              "confidence": "high", "rationale": "自证用"}
        if i < 5:
            mb.pop("reason", None)          # 同时触发 C-BINDING-11
        if i == 6:
            mb["space_context"] = {"carrier": "IfcSpace.ObjectType", "values": ["疏散楼梯间"]}
            mb["property_requirements"] = [{"parameter_ref": f"p_{i}", "pset": "Pset_CoveringCommon",
                                            "property": "FlammabilityRating", "value": [10]}]
        if i == 7:
            mb["property_requirements"] = [{"parameter_ref": "p_missing", "pset": "Pset_CoveringCommon",
                                            "property": "FlammabilityRating"}]
        if i == 8:
            mb["ifc_entity"] = "IfcCeiling"          # forbidden → C-BINDING-01
        if i == 9:
            mb["ifc_entity"] = "IfcBuilding"         # → C-BINDING-06
        if i == 10:
            mb["ifc_entity"] = "IfcDistributionSystem"   # 缺 pdt → C-BINDING-08
        if i == 11:
            mb["space_context"] = {"carrier": "IfcSpace.ObjectType", "values": []}  # → 04a
        if i == 12:
            mb["space_context"] = {"carrier": "IfcSpace.ObjectType", "values": ["疏散楼梯间", "前室"]}
        if i == 13:
            mb["space_context"] = {"carrier": "IfcSpace.RoomName", "values": ["疏散楼梯间"]}
        if i == 14:
            mb["space_context"] = {"carrier": "IfcSpace.ObjectType", "values": ["不存在空间"]}

        when = [{"path": "object.entity", "op": "eq", "value": mb["ifc_entity"]}]
        if i == 12:      # 真子集 → C-BINDING-04 (c) warning
            when.append({"path": "object.space.usage", "op": "in", "value": ["疏散楼梯间"]})
        if i == 14:      # 有空间条件（避免误触发 (a)），但取值未命中词表
            when.append({"path": "object.space.usage", "op": "in", "value": ["不存在空间"]})
        rules = [{
            "rule_id": f"R_{i}", "source_clause": cid,
            "mapping_refs": [f"mb_{i}"], "parameter_refs": [f"p_{i}"],
            "when": {"all": when},
            "not_when": [],
            "then": {"severity": "error", "message": "x",
                     "check": {"path": "object.pset[Pset_CoveringCommon].FlammabilityRating",
                               "op": "in", "parameter_ref": f"p_{i}"}},
        }] if i not in (7,) else []
        samples.append({
            "clause_id": cid, "standard_code": "GB 99999-2020", "clause_no": f"4.0.{i+1}",
            "related_objects": {"binding_level": "element", "model_bindings": [mb]},
            "parameters": [{"id": f"p_{i}", "name": "x", "operator": "in", "value": ["A"]}],
            "compiled_rules": rules,
        })
    # macro 带构件 → C-BINDING-10
    samples.append({
        "clause_id": "GB 99999-2020#1.0.1", "standard_code": "GB 99999-2020", "clause_no": "1.0.1",
        "related_objects": {"binding_level": "macro",
                            "model_bindings": [{"id": "mb_macro", "ifc_entity": "IfcWall",
                                                "predefined_type": "STANDARD", "mapping_status": "mapped",
                                                "rationale": "x"}]},
        "parameters": [], "compiled_rules": [],
    })
    # component_types 不一致 → C-BINDING-07
    samples[1]["related_objects"]["component_types"] = ["IfcWall"]

    dict_data = load_dict()
    findings = run_checks(samples, dict_data)
    got = {f[0] for f in findings}
    expect = {"C-BINDING-01", "C-BINDING-03", "C-BINDING-04", "C-BINDING-04a", "C-BINDING-05",
              "C-BINDING-06", "C-BINDING-07", "C-BINDING-08", "C-BINDING-09", "C-BINDING-10",
              "C-BINDING-11", "C-BINDING-12", "C-RATIO-01", "C-RATIO-02", "C-RULE-01"}
    print("== 自证：合成违规数据触发检查项")
    for cid in sorted(expect):
        n = sum(1 for f in findings if f[0] == cid)
        print(f"   [{'OK ' if cid in got else 'MISS'}] {cid}: {n} 条")
    # 分支覆盖细查：C-BINDING-04 的 (a) error 与 (c) warning 都要出现
    sev4 = {f[1] for f in findings if f[0] == "C-BINDING-04"}
    print(f"   [{'OK ' if 'error' in sev4 else 'MISS'}] C-BINDING-04 (a) 收窄丢失 error")
    print(f"   [{'OK ' if 'warning' in sev4 else 'MISS'}] C-BINDING-04 (c) 值域收窄 warning")
    # 未迁移册 CT 死名 → C-BINDING-01（ct_forbidden_findings，audit_files 未迁移分支）
    unmig = [{"clause_id": "GB 99999-2020#2.0.1",
             "related_objects": {"component_types": ["IfcEntrance", "IfcDoor"]}}]
    ctF = ct_forbidden_findings(unmig, dict_data)
    ok_ct = len(ctF) == 1 and ctF[0][0] == "C-BINDING-01"
    print(f"   [{'OK ' if ok_ct else 'MISS'}] C-BINDING-01(未迁移CT死名): {len(ctF)} 条")
    missing = expect - got
    br_missing = set()
    if "error" not in sev4:
        br_missing.add("04a分支")
    if "warning" not in sev4:
        br_missing.add("04c分支")
    print(f"== 自证结论：{'全部触发' if not missing and not br_missing and ok_ct else f'未触发 {sorted(missing | br_missing)}'}")
    return 0 if not missing and not br_missing and ok_ct else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    paths = [a for a in sys.argv[1:] if not a.startswith("--")]
    findings, skipped = audit_files(paths)
    errors = [f for f in findings if f[2] == "error"]
    warns = [f for f in findings if f[2] == "warning"]
    print(f"== 绑定层审计 v2.3：文件 {len(paths)} | error {len(errors)} | warning {len(warns)}")
    for f in findings:
        print(f"   [{f[2].upper():>7}] {f[1]}  {f[3]}")
    for s in skipped:
        print(f"   [SKIP] {s}")
    sys.exit(1 if findings else 0)
