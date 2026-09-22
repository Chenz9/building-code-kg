# -*- coding: utf-8 -*-
"""规则引擎（SCHEMA_v2.3_草案 §9.5 DSL 的可复用执行器，MVP 引擎的抽象版）。

用法：
  模块：from rule_engine import run; out = run(bindings_path, ifc_path)
  CLI： python rule_engine.py <bindings.yaml> <model.ifc> <out.json>

与 MVP 引擎（scripts/_mvp_rule_engine.py）的差异——全 DSL 超集：
  when  操作符：eq / neq / in / not_in / regex
  when  路径：  object.entity / object.predefined_type / object.space.usage /
                object.zone.name（v0.3：IfcZone 空间组）/ object.object_type /
                object.pset[Pset].prop /
                object.element.classification.<SYS> / object.material.classification.<SYS>
  check 操作符：in / not_in / exists / has_all / gt / gte / lt / lte / regex
  check 路径：  object.pset[Pset].prop / object.system.members_object_types /
                object.element.classification.<SYS> / object.material.classification.<SYS>
  not_when：    支持（MVP 引擎忽略）
  check 回退（§9.3 优先级2）：pset 缺值 → 构件级分类 → 材料级分类（GB8624 组映射）
  组映射：      默认知表词表 GB8624 group_mapping；可由 bindings 顶层
                classification_group_map 覆盖（其他分类系统复用时）
  has_all 匹配：§9.5 三分支——默认精确 / `/正则/` / 词表 member_alias_map 别名归一
                （别名表默认读 07_IFC模型绑定/ifc_mapping_dict_v0.yaml 的
                 member_alias_map，可由 bindings 顶层 member_alias_map 覆盖）
  结构校验：    process / site / macro 级样本（无模型检查）单独校验并输出
  输出追溯链：  rule_id → clause_id → mapping_id → parameter_id → ifc_guid → result
  result：      pass / fail / error（error=取不到值且无回退，与 fail 区分）
"""
import sys, io, os, re, json, datetime
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import ifcopenshell
import ifcopenshell.util.element as ue
import yaml

GB8624 = "GB 8624-2012"
DEFAULT_GROUP_MAP = {"A1": "A", "A2": "A", "B": "B1", "C": "B1",
                     "D": "B2", "E": "B2", "F": "B3"}
PSET_PATH = re.compile(r"^object\.pset\[([^\]]+)\]\.(.+)$")
CLS_ELEM_PATH = re.compile(r"^object\.element\.classification\.(.+)$")
CLS_MAT_PATH = re.compile(r"^object\.material\.classification\.(.+)$")

# 词表 classification_systems 里 GB8624 的实际登记名（dict v0.2 用的就是全名）
CLS_NAME_ALIAS = {"GB8624": GB8624, "GB 8624": GB8624}

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_DICT = os.path.join(ROOT, "ifc_mapping_dict_v0.yaml")


def _cls_name(raw):
    return CLS_NAME_ALIAS.get(raw, raw)


def make_norm_group(group_map):
    def norm_group(v):
        if v is None:
            return None
        return group_map.get(str(v).strip(), str(v).strip())
    return norm_group


# ---------- 系统成员别名归一（§9.5 has_all 匹配语义分支 3） ----------

def load_member_alias_map(path=DEFAULT_DICT, override=None):
    """别名表：alias 写法 → canonical 规范名。override 优先（bindings 顶层）。"""
    entries = override
    if entries is None:
        entries = []
        if os.path.exists(path):
            d = yaml.safe_load(open(path, encoding="utf-8")) or {}
            entries = d.get("member_alias_map") or []
    canon = {}
    for e in entries or []:
        c = e.get("canonical")
        if not c:
            continue
        for a in e.get("aliases") or []:
            canon[str(a).strip()] = c
    return canon


def make_member_norm(alias_canon):
    def norm(s):
        s = str(s).strip()
        return alias_canon.get(s, s)
    return norm


def eval_has_all(need, members, member_norm):
    """§9.5 三分支匹配。返回 (ok, missing, mode_used)。"""
    mem = [str(x).strip() for x in (members or [])]
    mem_canon = {member_norm(x) for x in mem}
    missing = []
    for n in need or []:
        s = str(n).strip()
        if len(s) >= 2 and s.startswith("/") and s.endswith("/"):
            pat = s[1:-1]
            hit = any(re.search(pat, x) for x in mem) or \
                any(re.search(pat, member_norm(x)) for x in mem)
        else:
            hit = member_norm(s) in mem_canon
        if not hit:
            missing.append(s)
    return (not missing), missing


# ---------- 模型取值 ----------

def _containing_space(el):
    for rel in getattr(el, "ContainedInStructure", None) or []:
        sp = rel.RelatingStructure
        if sp is not None and sp.is_a("IfcSpace"):
            return sp
    return None


def get_space_usage(el):
    sp = _containing_space(el)
    return getattr(sp, "ObjectType", None) if sp is not None else None


def get_zone_name(el):
    """构件所属空间所在的 IfcZone.Name（carrier=IfcZone.Name 的空间上下文）。
    路径：构件 →（IfcRelContainedInSpatialStructure）空间 →（IfcRelAssignsToGroup）IfcZone。

    ⚠ 逆属性坑（2026-09-22 实测）：IFC4 中 **IsGroupedBy 是 IfcGroup 的逆属性**
    （IfcRelAssignsToGroup.RelatingGroup），只有**组侧**（IfcZone / IfcDistributionSystem）
    能用；**成员侧**必须走 IfcObjectDefinition.HasAssignments
    （IfcRelAssigns FOR RelatedObjects）。写成 space.IsGroupedBy 会恒返回 None
    → 空间组条件静默失效（不报错、零记录）。"""
    sp = _containing_space(el)
    if sp is None:
        return None
    for rel in getattr(sp, "HasAssignments", None) or []:
        if rel.is_a("IfcRelAssignsToGroup"):
            g = getattr(rel, "RelatingGroup", None)
            if g is not None and g.is_a("IfcZone"):
                return g.Name
    return None


def get_system_members(el):
    """系统成员 ObjectType 集合（组侧逆属性 IsGroupedBy，与成员侧 HasAssignments 相对）。"""
    s = set()
    for rel in getattr(el, "IsGroupedBy", None) or []:
        for o in rel.RelatedObjects or []:
            ot = getattr(o, "ObjectType", None)
            if ot:
                s.add(ot)
    return s


def get_pset_value(el, pset, prop):
    psets = ue.get_psets(el)
    return (psets.get(pset) or {}).get(prop)


def get_element_classification(el, system=GB8624):
    for rel in getattr(el, "HasAssociations", None) or []:
        if rel.is_a("IfcRelAssociatesClassification"):
            ref = rel.RelatingClassification
            if ref is not None and ref.is_a("IfcClassificationReference"):
                src = ref.ReferencedSource
                if src is not None and getattr(src, "Name", None) == system:
                    return ref.Identification
    return None


def get_material(el):
    for rel in getattr(el, "HasAssociations", None) or []:
        if rel.is_a("IfcRelAssociatesMaterial"):
            mat = rel.RelatingMaterial
            if mat is not None and mat.is_a("IfcMaterial"):
                return mat
    return None


def get_material_classification(el, system=GB8624):
    """材料级分类正解：IfcMaterialDefinition.HasExternalReferences
    （IfcMaterial 非 IfcObjectDefinition，不能作 IfcRelAssociatesClassification
    的 RelatedObjects——官方实体层级，2026-09-21 核实）。"""
    mat = get_material(el)
    if mat is None:
        return None
    for rel in getattr(mat, "HasExternalReferences", None) or []:
        ref = getattr(rel, "RelatingReference", None)
        if ref is not None and ref.is_a("IfcClassificationReference"):
            src = ref.ReferencedSource
            if src is not None and getattr(src, "Name", None) == system:
                return ref.Identification
    return None


def get_system_members(el):
    s = set()
    for rel in getattr(el, "IsGroupedBy", None) or []:
        for o in rel.RelatedObjects or []:
            ot = getattr(o, "ObjectType", None)
            if ot:
                s.add(ot)
    return s


# ---------- 路径解析 ----------

def resolve_scalar_path(path, el):
    """解析返回标量的路径（when 用）。"""
    if path == "object.entity":
        return el.is_a()
    if path == "object.predefined_type":
        return getattr(el, "PredefinedType", None)
    if path == "object.object_type":
        return getattr(el, "ObjectType", None)
    if path == "object.space.usage":
        return get_space_usage(el)
    if path == "object.zone.name":
        return get_zone_name(el)
    m = PSET_PATH.match(path)
    if m:
        return get_pset_value(el, m.group(1), m.group(2))
    m = CLS_ELEM_PATH.match(path)
    if m:
        return get_element_classification(el, _cls_name(m.group(1)))
    m = CLS_MAT_PATH.match(path)
    if m:
        return get_material_classification(el, _cls_name(m.group(1)))
    raise NotImplementedError(f"路径不支持: {path}")


# ---------- when 求值 ----------

def eval_when_cond(cond, el):
    path, op = cond["path"], cond["op"]
    value = cond.get("value")
    left = resolve_scalar_path(path, el)
    if op == "regex":
        return left is not None and re.search(str(value), str(left)) is not None
    if left is None:
        return False
    seq = value if isinstance(value, list) else [value]
    if op == "eq":
        return left == value
    if op == "neq":
        return left != value
    if op == "in":
        return left in seq
    if op == "not_in":
        return left not in seq
    raise NotImplementedError(f"when 操作符不支持: {op}")


def when_matches(rule, el):
    for cond in (rule.get("when") or {}).get("all") or []:
        if not eval_when_cond(cond, el):
            return False
    for cond in rule.get("not_when") or []:
        if eval_when_cond(cond, el):
            return False
    return True


# ---------- check 求值 ----------

def resolve_check_value(path, el, material_required, norm_group):
    """按 §9.3 优先级解析 check 值：直读路径 → pset 三级回退（pset→构件分类→材料分类）。"""
    m = PSET_PATH.match(path)
    if m:
        pset, prop = m.group(1), m.group(2)
        v = get_pset_value(el, pset, prop)
        if v is not None:
            return v, "pset"
        if material_required:
            ec = get_element_classification(el)
            if ec is not None:
                return norm_group(ec), "element_classification"
            mc = get_material_classification(el)
            if mc is not None:
                return norm_group(mc), "material_classification"
        return None, None
    m = CLS_ELEM_PATH.match(path)
    if m:
        v = get_element_classification(el, _cls_name(m.group(1)))
        return (norm_group(v) if v is not None else None), "element_classification"
    m = CLS_MAT_PATH.match(path)
    if m:
        v = get_material_classification(el, _cls_name(m.group(1)))
        return (norm_group(v) if v is not None else None), "material_classification"
    if path == "object.system.members_object_types":
        return get_system_members(el), "group_members"
    raise NotImplementedError(f"check 路径不支持: {path}")


def eval_check(check, el, mapping, params, norm_group, member_norm):
    path, op = check["path"], check["op"]
    pref = check.get("parameter_ref")
    param = params.get(pref) if pref else None
    mb = mapping or {}
    material_required = bool((mb.get("material_binding") or {}).get("required"))

    if op == "has_all":
        members, via = resolve_check_value(path, el, material_required, norm_group)
        need = check.get("value") or []
        ok, missing = eval_has_all(need, members, member_norm)
        detail = sorted(members or []) if ok else {"members": sorted(members or []), "missing": missing}
        return ("pass" if ok else "fail"), detail, via

    resolved, via = resolve_check_value(path, el, material_required, norm_group)
    if op == "exists":
        return ("fail" if resolved is None else "pass"), resolved, via
    if resolved is None:
        return "error", None, via
    if op in ("in", "not_in"):
        allowed = (param or {}).get("value")
        if allowed is None:
            allowed = check.get("value") or []
        allowed_g = [norm_group(x) for x in allowed]
        hit = norm_group(resolved) in allowed_g
        ok = hit if op == "in" else (not hit)
        return ("pass" if ok else "fail"), resolved, via
    if op == "regex":
        pat = (param or {}).get("value") or check.get("value")
        ok = re.search(str(pat), str(resolved)) is not None
        return ("pass" if ok else "fail"), resolved, via
    if op in ("gt", "gte", "lt", "lte"):
        if op in ("gt", "gte"):
            thr = (param or {}).get("min_value")
        else:
            thr = (param or {}).get("max_value")
        if thr is None:
            thr = (param or {}).get("value")
        if thr is None:
            thr = check.get("value")
        try:
            rv = float(resolved)
            thr = float(thr)
        except (TypeError, ValueError):
            return "error", resolved, via
        ok = {"gt": rv > thr, "gte": rv >= thr, "lt": rv < thr, "lte": rv <= thr}[op]
        return ("pass" if ok else "fail"), resolved, via
    raise NotImplementedError(f"check 操作符不支持: {op}")


# ---------- 主流程 ----------

def run(bindings_path, ifc_path):
    data = yaml.safe_load(open(bindings_path, encoding="utf-8"))
    group_map = dict(DEFAULT_GROUP_MAP)
    group_map.update(data.get("classification_group_map") or {})
    norm_group = make_norm_group(group_map)
    member_norm = make_member_norm(load_member_alias_map(
        override=data.get("member_alias_map")))
    model = ifcopenshell.open(ifc_path)
    results, structural = [], []

    for sample in data["samples"]:
        cid = sample["clause_id"]
        ro = sample.get("related_objects") or {}
        mbs = {mb["id"]: mb for mb in (ro.get("model_bindings") or [])}
        params = {p["id"]: p for p in (sample.get("parameters") or [])}

        # 结构校验（process / site / macro 级样本：无模型检查）
        level = ro.get("binding_level")
        if level == "process":
            ok = (not (ro.get("model_bindings"))) and \
                 all(isinstance(a, dict) and a.get("id") and a.get("name") and a.get("phase")
                     for a in (ro.get("activity_types") or []))
            structural.append({"clause_id": cid, "type": "process结构",
                               "result": "pass" if ok else "fail",
                               "detail": f"activity_types={len(ro.get('activity_types') or [])} 条结构化"})
            continue
        if level == "site":
            mb_list = ro.get("model_bindings") or []
            ok = bool(mb_list) and all(
                mb.get("mapping_status") in ("needs_expert_review", "not_applicable", "mapped", "reviewed")
                and mb.get("rationale") for mb in mb_list)
            structural.append({"clause_id": cid, "type": "site降级结构",
                               "result": "pass" if ok else "fail",
                               "detail": "绑定+降级理由齐备" if ok else "缺降级理由"})
            continue
        if level == "macro":
            ok = not (ro.get("model_bindings"))
            structural.append({"clause_id": cid, "type": "macro结构",
                               "result": "pass" if ok else "fail",
                               "detail": "宏观章无模型绑定" if ok else "宏观章不得有 model_bindings"})
            continue

        # 规则求值
        for rule in sample.get("compiled_rules") or []:
            when_all = (rule.get("when") or {}).get("all") or []
            entity_name = None
            for cond in when_all:
                if cond["path"] == "object.entity" and cond["op"] == "eq":
                    entity_name = cond["value"]
                    break
            candidates = model.by_type(entity_name) if entity_name else []
            for el in candidates:
                if not when_matches(rule, el):
                    continue  # 不适用（如空间/空间组上下文不匹配）——不产生记录
                mapping = mbs.get((rule.get("mapping_refs") or [None])[0])
                check = rule["then"]["check"]
                result, resolved, via = eval_check(check, el, mapping, params, norm_group, member_norm)
                results.append({
                    "rule_id": rule["rule_id"],
                    "clause_id": cid,
                    "mapping_id": (rule.get("mapping_refs") or [None])[0],
                    "parameter_id": (check.get("parameter_ref")),
                    "ifc_guid": el.GlobalId,
                    "object_name": el.Name,
                    "result": result,
                    "severity": rule["then"].get("severity"),
                    "message": rule["then"].get("message"),
                    "resolved_value": resolved,
                    "resolved_via": via,
                })

    n_pass = sum(1 for r in results if r["result"] == "pass")
    n_fail = sum(1 for r in results if r["result"] == "fail")
    n_err = sum(1 for r in results if r["result"] == "error")
    return {
        "model": os.path.basename(ifc_path),
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "results": results,
        "structural": structural,
        "summary": {"rules_evaluated_records": len(results), "pass": n_pass,
                    "fail": n_fail, "error": n_err},
    }


if __name__ == "__main__":
    bindings, ifc_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
    out = run(bindings, ifc_path)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    s = out["summary"]
    print(f"== {out['model']}: 记录 {s['rules_evaluated_records']} | pass {s['pass']} | fail {s['fail']} | error {s['error']}")
    for st in out["structural"]:
        print(f"   [结构] {st['clause_id']} {st['type']}: {st['result']} ({st['detail']})")
    for r in out["results"]:
        if r["result"] != "pass":
            print(f"   [{r['result'].upper()}] {r['rule_id']} @ {r['object_name']} (via {r['resolved_via']})")
