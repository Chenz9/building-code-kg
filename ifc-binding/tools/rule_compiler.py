# -*- coding: utf-8 -*-
"""规则编译器（SCHEMA_v2.3_草案 §9.4：executable_rules 由 parameters + model_bindings 编译生成）。

两个用途：
  ① 生成：从源数据（model_bindings + parameters）编译出规范形态的 compiled_rules
     —— 321 条批量重映射的规则生成器。
  ② 校验（RULE_COMPILE_MISMATCH）：把落盘 compiled_rules 与重编译结果比对，
     语义必须一致（v2.2 MODAL_DERIVE_MISMATCH 思路的延续）。

编译规则（§9.4 分支）：
  - mapped/reviewed 绑定 + property_requirements 有 parameter_ref → 值域规则
    check.op = 该 parameter.operator（in/gte/lte/regex...）
  - mapped/reviewed 绑定 + property_requirements.parameter_ref=null → 存在性规则 check.op=exists
  - mapped/reviewed 系统绑定 + member_requirements → 成员规则 check.op=has_all
  - needs_expert_review / not_applicable / draft 绑定 → 不生成规则（诚实降级）
  - when 条件由绑定字段编译：entity(eq) + predefined_type(eq) + 空间条件(in)
    ★ 空间条件路径由 space_context.carrier 决定（v0.4）：
        IfcSpace.ObjectType → object.space.usage
        IfcZone.Name        → object.zone.name
  - 消息（then.message）为人工文案，不参与一致性比对（比对结构化骨架）

C-BINDING-04 三分支（v0.4，schema §9.6）：
  (a) 主映射有 space_context，规则 when 缺空间条件 → error
  (b) 主映射无 space_context，规则 when 仅 entity/pdt → 合法（不报警）
  (c) 主映射有 space_context，规则空间条件值域是其真子集 → warning
以及 C-BINDING-04a（源数据侧）：声明 space_context 且可编译的绑定，
其规范形态规则必须含空间条件——即使 compiled_rules 缺失也能捕捉收窄丢失。

已知 v1 限制：element 级绑定的 system_context 不编译为 when 条件（DSL 尚无
「对象是否属于某系统」的关系路径）；此类绑定当前一律 needs_expert_review 不生成规则。

用法：
  CLI： python rule_compiler.py <bindings.yaml>              # 只做一致性校验
        python rule_compiler.py <bindings.yaml> --emit out.yaml  # 输出重编译产物
"""
import sys, io, os, json, copy
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import yaml

COMPILABLE_STATUS = ("mapped", "reviewed")
SPACE_PATHS = ("object.space.usage", "object.zone.name")
CARRIERS = ("IfcSpace.ObjectType", "IfcZone.Name")


def space_path_for(mb):
    """space_context.carrier → DSL 空间条件路径（无 space_context 返回 None）。"""
    sc = mb.get("space_context")
    if not sc:
        return None
    carrier = sc.get("carrier") or "IfcSpace.ObjectType"
    return "object.zone.name" if carrier == "IfcZone.Name" else "object.space.usage"


def _space_values(mb):
    sc = mb.get("space_context") or {}
    vals = sc.get("values")
    if vals is None and sc.get("value") is not None:
        vals = [sc["value"]]
    return [str(v) for v in (vals or [])]


def _when_for_binding(mb):
    conds = [{"path": "object.entity", "op": "eq", "value": mb["ifc_entity"]}]
    if mb.get("predefined_type"):
        conds.append({"path": "object.predefined_type", "op": "eq",
                      "value": mb["predefined_type"]})
    sp = space_path_for(mb)
    if sp and _space_values(mb):
        conds.append({"path": sp, "op": "in", "value": _space_values(mb)})
    return conds


def canonical_rules_for(sample):
    """从源数据编译规范形态规则（无 message/rule_id 文案）。

    mapping_refs 约定：
      - 属性规则 → [提供 property_requirements 的绑定 id]
      - 成员规则（has_all）→ [系统绑定 id] + [声明了指向该系统/枚举的
        system_context 的成员绑定 id]（保持『系统要求其成员齐备』的语义来源）
    """
    ro = sample.get("related_objects") or {}
    mbs = ro.get("model_bindings") or []
    params = {p["id"]: p for p in (sample.get("parameters") or [])}
    out = []
    for mb in mbs:
        if mb.get("mapping_status") not in COMPILABLE_STATUS:
            continue
        when = _when_for_binding(mb)
        for pr in mb.get("property_requirements") or []:
            path = f"object.pset[{pr['pset']}].{pr['property']}"
            pref = pr.get("parameter_ref")
            if pref:
                param = params.get(pref)
                # 参数操作符即 check 操作符（in→in / gte→gte ...）
                op = (param or {}).get("operator")
                if op is None:
                    op = "in"
                check = {"path": path, "op": op, "parameter_ref": pref}
            else:
                check = {"path": path, "op": "exists"}
            out.append({"mapping_refs": [mb["id"]], "when": {"all": copy.deepcopy(when)},
                        "check": check})
        if mb.get("member_requirements"):
            supporting = [x["id"] for x in mbs
                          if (x.get("system_context") or {}).get("ifc_entity") == mb.get("ifc_entity")
                          and (x.get("system_context") or {}).get("predefined_type") == mb.get("predefined_type")]
            out.append({"mapping_refs": [mb["id"]] + supporting,
                        "when": {"all": copy.deepcopy(when)},
                        "check": {"path": "object.system.members_object_types",
                                  "op": "has_all", "value": list(mb["member_requirements"])}})
    return out


# ---------- C-BINDING-04（三分支） ----------

def binding04(sample):
    """§9.6 C-BINDING-04 三分支。返回 (errors, warnings)。"""
    cid = sample["clause_id"]
    ro = sample.get("related_objects") or {}
    mbs = {mb["id"]: mb for mb in (ro.get("model_bindings") or [])}
    errors, warnings = [], []
    for d in sample.get("compiled_rules") or []:
        refs = d.get("mapping_refs") or []
        if not refs:
            continue
        mb = mbs.get(refs[0]) or {}
        sc = mb.get("space_context")
        conds = (d.get("when") or {}).get("all") or []
        space_conds = [c for c in conds if c.get("path") in SPACE_PATHS]
        if not sc:
            # (b) 主映射无 space_context → when 仅 entity/pdt 合法，不报警
            continue
        if not space_conds:
            # (a) 收窄条件丢失
            errors.append(f"{cid}: 规则 {d.get('rule_id')} 的 when 无空间条件，"
                          f"但主映射 {refs[0]} 声明了 space_context——收窄条件丢失（恒真）")
            continue
        # (c) 值域被悄悄收窄（规则空间条件 values ⊊ 主映射 values）
        want = set(_space_values(mb))
        got = set()
        for c in space_conds:
            v = c.get("value")
            got |= {str(x) for x in (v if isinstance(v, list) else [v])}
        if got and want and got < want:
            warnings.append(f"{cid}: 规则 {d.get('rule_id')} 的空间条件值域 {sorted(got)} "
                            f"是主映射 {refs[0]} values {sorted(want)} 的真子集——值域收窄，可能漏检")
    return errors, warnings


def binding04a(sample):
    """§9.6 C-BINDING-04a 源数据侧：声明 space_context 且可编译的绑定，
    其**规范形态**规则必须含对应空间条件（不依赖 compiled_rules 是否存在）。"""
    cid = sample["clause_id"]
    ro = sample.get("related_objects") or {}
    errors = []
    for mb in ro.get("model_bindings") or []:
        if not mb.get("space_context"):
            continue
        if mb.get("mapping_status") not in COMPILABLE_STATUS:
            continue
        path = space_path_for(mb)
        rules = [c for c in canonical_rules_for(sample)
                 if mb.get("id") in (c["mapping_refs"] or [])]
        if not rules:
            errors.append(f"{cid}: 绑定 {mb.get('id')} 声明 space_context 且 mapping_status="
                          f"{mb.get('mapping_status')}，但源数据未编译出任何规则（无可编译要求？）")
            continue
        for r in rules:
            paths = {c.get("path") for c in r["when"]["all"]}
            if path not in paths:
                errors.append(f"{cid}: 源数据编译出的规则缺空间条件 {path}"
                              f"（绑定 {mb.get('id')} 声明了 space_context）——编译器/绑定字段不自洽")
    return errors


# ---------- 一致性比对 ----------

def _norm_conds(conds):
    """条件集合归一化为可比较 frozenset（value 列表转 tuple，顺序无关）。"""
    items = []
    for c in conds or []:
        v = c.get("value")
        if isinstance(v, list):
            v = ("LIST", tuple(sorted(map(str, v))))
        items.append((c.get("path"), c.get("op"), v))
    return frozenset(items)


def _rule_key(rule):
    return tuple(rule.get("mapping_refs") or [])


def compare_clause(sample):
    """返回 {missing, extra, mismatched}（每条为可读描述）。"""
    cid = sample["clause_id"]
    canon = canonical_rules_for(sample)
    disk = sample.get("compiled_rules") or []
    canon_by = {}
    for c in canon:
        canon_by.setdefault(_rule_key(c), []).append(c)
    disk_by = {}
    for d in disk:
        disk_by.setdefault(_rule_key(d), []).append(d)

    missing, extra, mismatched = [], [], []
    for key, clist in canon_by.items():
        dlist = disk_by.get(key)
        if not dlist:
            missing.append(f"{cid}: 源数据应生成规则（绑定 {list(key)}）但落盘无对应规则")
            continue
        # 按 check 签名配对
        used = set()
        for c in clist:
            ck = _norm_conds([c["check"]])
            hit = None
            for i, d in enumerate(dlist):
                if i in used:
                    continue
                if _norm_conds([d["then"]["check"]]) == ck:
                    hit = i
                    break
            if hit is None:
                mismatched.append(f"{cid}: 绑定 {list(key)} 的 check {c['check']} 在落盘规则中无匹配")
                continue
            used.add(hit)
            d = dlist[hit]
            if _norm_conds(c["when"]["all"]) != _norm_conds((d.get("when") or {}).get("all")):
                mismatched.append(
                    f"{cid}: 规则 {d.get('rule_id')} 的 when 与源数据重编译结果不一致 "
                    f"（落盘 {len((d.get('when') or {}).get('all') or [])} 条 vs 源 {len(c['when']['all'])} 条）")
            if d.get("not_when"):
                mismatched.append(f"{cid}: 规则 {d.get('rule_id')} 含 not_when，编译器未生成（源数据无来源字段）")
        for i, d in enumerate(dlist):
            if i not in used:
                extra.append(f"{cid}: 规则 {d.get('rule_id')} 无源数据依据（extra）")
    for key, dlist in disk_by.items():
        if key not in canon_by:
            for d in dlist:
                extra.append(f"{cid}: 规则 {d.get('rule_id')} 引用的绑定 {list(key)} 无可编译要求（extra）")
    return {"clause_id": cid, "missing": missing, "extra": extra, "mismatched": mismatched}


def load(path):
    return yaml.safe_load(open(path, encoding="utf-8"))


def check_all(path):
    """汇总：mismatch（RULE_COMPILE_MISMATCH）+ errors/warnings（C-BINDING-04/04a）。"""
    data = load(path)
    mism, errors, warnings = [], [], []
    for s in data.get("samples") or []:
        r = compare_clause(s)
        for k in ("missing", "extra", "mismatched"):
            mism += r[k]
        e, w = binding04(s)
        errors += e + binding04a(s)
        warnings += w
    return {"mismatch": mism, "errors": errors, "warnings": warnings}


def emit(path, out_path):
    """重编译产物：以落盘文件为壳，替换每个样本的 compiled_rules 为编译结果。"""
    data = load(path)
    out = copy.deepcopy(data)
    for s, s2 in zip(data.get("samples") or [], out.get("samples") or []):
        rules = []
        for i, c in enumerate(canonical_rules_for(s)):
            mb = c["mapping_refs"][0]
            rules.append({
                "rule_id": f"R_{s['clause_no'].replace('.', '_')}_{mb.split('_')[-1]}_{i+1}",
                "source_clause": s["clause_id"],
                "mapping_refs": c["mapping_refs"],
                "parameter_refs": [c["check"]["parameter_ref"]] if c["check"].get("parameter_ref") else [],
                "when": c["when"],
                "not_when": [],
                "then": {"severity": "error", "message": "", "check": c["check"]},
            })
        s2["compiled_rules"] = rules
    with open(out_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(out, f, allow_unicode=True, sort_keys=False)
    return out_path


if __name__ == "__main__":
    path = sys.argv[1]
    if "--emit" in sys.argv:
        out = sys.argv[sys.argv.index("--emit") + 1]
        print("编译产物 ->", emit(path, out))
    else:
        res = check_all(path)
        n = len(res["mismatch"]) + len(res["errors"]) + len(res["warnings"])
        print(f"== RULE_COMPILE_MISMATCH / C-BINDING-04 / 04a：{n} 项")
        for x in res["mismatch"]:
            print("   [MISMATCH]", x)
        for x in res["errors"]:
            print("   [04/04a ERROR]", x)
        for x in res["warnings"]:
            print("   [04 WARN]", x)
        print("结论:", "一致" if n == 0 else f"有 {n} 项待处理")
