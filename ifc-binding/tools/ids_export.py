# -*- coding: utf-8 -*-
"""IDS 导出器 + 交付说明自动生成（_mvp_ids_export.py 的抽象版）。

用法：
  CLI： python ids_export.py <bindings.yaml> <out.ids> [model.ifc ...]
  模块：from ids_export import build_ids, audit, write_notes

导出边界（SCHEMA_v2.3_草案 §9.5 双轨制）：
  ✅ 可导出：entity + predefinedType + pset.prop
       - op in  → 枚举（单值 simpleValue / 多值 enumeration 限制）
       - op exists → 属性存在性（交付完整性）
       - op gt/gte/lt/lte → 数值范围限制（minInclusive / maxInclusive 等）
       - op not_in → 以 cardinality=prohibited 表达（"该值不得出现"）
  ❌ 不导出（自研引擎 / 人工）：
       - space_context 空间上下文（IDS 无空间条件——导出的要求比条文严）
       - material_binding 材料级回退（IDS 无材料分类回退语义）
       - member_requirements 系统成员 has_all（跨对象编组关系）
       - 几何推导量、过程/文档类条文（binding_level=process）
  交付说明由 write_notes() 自动生成（_ids_export_notes.md），不手写。
"""
import sys, io, os, json, datetime
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import yaml
import ifcopenshell
from ifctester.ids import Ids, Specification
from ifctester.facet import Entity, Property, Restriction

RANGE_OP = {"gt": "minExclusive", "gte": "minInclusive",
            "lt": "maxExclusive", "lte": "maxInclusive"}


def _value_obj(op, param, check_value=None):
    """把参数值转成 IDS Property 可用的 value 对象。"""
    if op == "exists":
        return None
    if op in ("in", "not_in"):
        vals = None
        if param is not None:
            vals = param.get("value")
        if vals is None:
            vals = check_value
        vals = vals if isinstance(vals, list) else [vals]
        if len(vals) == 1:
            return vals[0]                       # 单值：simpleValue
        return Restriction(base="string", options={"enumeration": [str(v) for v in vals]})
    if op in RANGE_OP:
        thr = None
        if param is not None:
            thr = param.get("min_value") if op in ("gt", "gte") else param.get("max_value")
        if thr is None and param is not None:
            thr = param.get("value")
        if thr is None:
            raise ValueError(f"范围型参数缺少阈值: {param}")
        base = "double" if isinstance(thr, (int, float)) else "string"
        return Restriction(base=base, options={RANGE_OP[op]: thr})
    raise NotImplementedError(f"IDS 导出不支持操作符: {op}")


def make_spec(name, entity, pdt, prop_req):
    """★ entity 必须大写（ifctester Entity.__call__ 用 is_a().upper()==name 比较，
    混合大小写静默返回 applicable=0——2026-09-21 实测）。"""
    entity = entity.upper()
    spec = Specification(name=name, ifcVersion=["IFC4"])
    spec.applicability = [Entity(name=entity, predefinedType=pdt)]
    reqs = [Entity(name=entity, predefinedType=pdt)]
    if prop_req:
        pset, prop, value, cardinality = prop_req
        reqs.append(Property(propertySet=pset, baseName=prop, value=value,
                             cardinality=cardinality))
    spec.requirements = reqs
    return spec


def build_ids(bindings_path, title=None, version="auto"):
    """从源数据（parameters + model_bindings，单一事实源）编译 IDS。"""
    data = yaml.safe_load(open(bindings_path, encoding="utf-8"))
    specs, entries, skipped = [], [], []
    for s in data.get("samples") or []:
        cid = s["clause_id"]
        ro = s.get("related_objects") or {}
        level = ro.get("binding_level")
        params = {p["id"]: p for p in (s.get("parameters") or [])}

        if level == "process":
            skipped.append({"clause_id": cid, "kind": "过程/文档类条文",
                            "reason": "无模型检查，不走 IDS"})
            continue

        for mb in ro.get("model_bindings") or []:
            not_exported = []
            if mb.get("space_context"):
                vals = mb["space_context"].get("values") or []
                not_exported.append(f"空间限定（{('/'.join(map(str, vals))) or '-'}）")
            if (mb.get("material_binding") or {}).get("required"):
                not_exported.append("材料级回退")
            if mb.get("mapping_status") not in ("mapped", "reviewed"):
                skipped.append({"clause_id": cid, "kind": f"绑定 {mb['id']}",
                                "reason": f"mapping_status={mb.get('mapping_status')}（未复核，不导出）"})
                continue
            for pr in mb.get("property_requirements") or []:
                pref = pr.get("parameter_ref")
                param = params.get(pref) if pref else None
                op = (param or {}).get("operator") or "exists"
                try:
                    value = _value_obj(op, param)
                except (ValueError, NotImplementedError) as e:
                    skipped.append({"clause_id": cid, "kind": f"{pr['pset']}.{pr['property']}",
                                    "reason": f"值域无法导出：{e}"})
                    continue
                card = "prohibited" if op == "not_in" else "required"
                name = (f"{cid} {mb.get('role', '')} {pr['pset']}.{pr['property']}"
                        f" [{op}]")
                specs.append(make_spec(name, mb["ifc_entity"], mb.get("predefined_type"),
                                       (pr["pset"], pr["property"], value, card)))
                entries.append({"clause_id": cid, "mapping_id": mb["id"],
                                "spec": name, "op": op,
                                "parameter_ref": pref,
                                "not_exported": not_exported,
                                "exported": [f"{pr['pset']}.{pr['property']}",
                                             f"predefined_type={mb.get('predefined_type')}"]})
            if mb.get("member_requirements"):
                skipped.append({"clause_id": cid, "kind": f"绑定 {mb['id']}.member_requirements",
                                "reason": "系统成员 has_all（跨对象编组）——IDS 无该语义，走自研引擎"})
        # 规则层不可导出项（负向条件 / 几何）
        for r in s.get("compiled_rules") or []:
            if r.get("not_when"):
                skipped.append({"clause_id": cid, "kind": f"规则 {r.get('rule_id')}.not_when",
                                "reason": "负向条件——v1 导出器不生成"})
        for p in s.get("parameters") or []:
            tgt = (p.get("ifc_binding") or {}).get("target")
            if tgt in ("site", "geometry") or "几何" in str((p.get("ifc_binding") or {}).get("path", "")):
                skipped.append({"clause_id": cid, "kind": f"参数 {p['id']}",
                                "reason": "几何推导量——需几何引擎/人工复核"})

    ids_obj = Ids(title=title or f"规范 YAML 编译导出（{os.path.basename(bindings_path)}）",
                  version=version,
                  description="由规范 YAML 的 parameters+model_bindings 编译生成；"
                              "空间限定、材料级回退、系统成员、几何量未包含（见 _ids_export_notes.md）。")
    ids_obj.specifications = specs
    return ids_obj, entries, skipped


def audit(ids_obj, ifc_path):
    model = ifcopenshell.open(ifc_path)
    ids_obj.validate(model)
    recs = []
    for spec in ids_obj.specifications:
        recs.append({"specification": spec.name,
                     "applicable": len(spec.applicable_entities),
                     "passed": len(spec.passed_entities),
                     "failed": len(spec.failed_entities),
                     "status": spec.status})
    return recs


def write_notes(path, entries, skipped, ids_path, models=None):
    """自动生成交付说明（每条 IDS 的边界与限制）。"""
    lines = [f"# IDS 交付说明（自动生成）· {datetime.date.today().isoformat()}", ""]
    lines.append(f"> 对应文件：`{os.path.basename(ids_path)}`")
    lines.append(f"> 生成方式：由规范 YAML 的 `parameters` + `model_bindings` 编译导出（值不在 IDS 层存第二份）")
    lines.append(f"> ⚠ **本 IDS 不完整等价于条文**——下列 facet 有意未包含，详见下文逐条说明。")
    lines.append("")
    lines.append("## 1. 通用限制（模板）")
    lines.append("")
    lines.append("| # | 限制 | 工程含义 |")
    lines.append("|---|---|---|")
    lines.append("| 1 | 未包含空间限定（如「疏散楼梯间/前室」） | 本 IDS 是**全楼要求，比条文更严**；按 IDS 校验可能对条文不约束的部位报错 |")
    lines.append("| 2 | 不支持材料级回退 | 材料燃烧性能等**必须直填构件 pset**，否则按 IDS 判缺失 |")
    lines.append("| 3 | 不表达系统成员关系（has_all） | 相关条文（防雷装置齐备等）走自研引擎 |")
    lines.append("| 4 | 不表达几何推导量 | 距离/视距/遮挡类条文需几何引擎或人工复核 |")
    lines.append("| 5 | 不表达过程/文档类要求 | 施工、检验、验收条文以文档交付要求承载 |")
    lines.append("")
    lines.append("## 2. 逐条导出清单（含未包含 facet）")
    lines.append("")
    lines.append("| 条文 | 绑定 | 导出属性 | 操作符 | 值来源 | 未包含 |")
    lines.append("|---|---|---|---|---|---|")
    for e in entries:
        src = f"parameters.{e['parameter_ref']}" if e["parameter_ref"] else "—（存在性检查）"
        ne = "、".join(e["not_exported"]) or "—"
        lines.append(f"| {e['clause_id']} | {e['mapping_id']} | {e['exported'][0]} "
                     f"| `{e['op']}` | {src} | {ne} |")
    lines.append("")
    lines.append("## 3. 未导出项清单（走自研引擎 / 人工）")
    lines.append("")
    if skipped:
        lines.append("| 条文 | 未导出项 | 原因 |")
        lines.append("|---|---|---|")
        for k in skipped:
            lines.append(f"| {k['clause_id']} | {k['kind']} | {k['reason']} |")
    else:
        lines.append("（无）")
    lines.append("")
    if models:
        lines.append("## 4. 模型审计结果（如有）")
        lines.append("")
        lines.append("| 模型 | Spec | 适用 | 通过 | 失败 | 状态 |")
        lines.append("|---|---|---|---|---|---|")
        for mn, recs in models.items():
            for r in recs:
                st = "pass" if r["status"] and r["failed"] == 0 else "fail"
                lines.append(f"| {mn} | {r['specification']} | {r['applicable']} "
                             f"| {r['passed']} | {r['failed']} | {st} |")
        lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path


if __name__ == "__main__":
    bindings, out_ids = sys.argv[1], sys.argv[2]
    model_paths = sys.argv[3:]
    ids_obj, entries, skipped = build_ids(bindings)
    xsd_ok = ids_obj.to_xml(out_ids)
    print(f"== IDS 写出 {'OK' if xsd_ok else 'XSD失败!'} -> {out_ids}（{len(ids_obj.specifications)} spec）")
    models_report = {}
    for mp in model_paths:
        recs = audit(ids_obj, mp)
        models_report[os.path.basename(mp)] = recs
        print(f"== {os.path.basename(mp)}:")
        for r in recs:
            st = "pass" if r["status"] and r["failed"] == 0 else "fail"
            print(f"   {st:>4} | applicable {r['applicable']:>2} | pass {r['passed']:>2} "
                  f"| fail {r['failed']:>2} | {r['specification'][:56]}")
    notes = os.path.join(os.path.dirname(os.path.abspath(out_ids)) or ".", "_ids_export_notes.md")
    write_notes(notes, entries, skipped, out_ids, models_report or None)
    print("== 交付说明 ->", notes)
