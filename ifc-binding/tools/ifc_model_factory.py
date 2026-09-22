# -*- coding: utf-8 -*-
"""测试 IFC 模型工厂（_gen_test_ifc.py 的抽象版：场景全由 YAML 驱动）。

用法：
  CLI： python ifc_model_factory.py <scenario.yaml> <out.ifc>
  模块：from ifc_model_factory import build_from_scenario; build_from_scenario(path, out)

场景 YAML 结构（见 scenarios/mvp_pass.yaml 完整示例）：
  project_name: 项目名
  spatial: {site: 场地, building: 测试楼, storeys: [1F]}
  spaces:  [{name, object_type, storey}]
  zones:   [{name, spaces: [<space 名>…]}]        # v0.3：IfcZone 空间组
  classification: {name: "GB 8624-2012"}        # 分类框架（可选）
  elements: [{ifc_class, name, predefined_type, container, object_type,
              psets: [{name, properties}],
              material: {name, classification},
              element_classification: <标识>}]
  systems:  [{ifc_class, name, predefined_type, psets, members: [{ifc_class, name, object_type}]}]

container 取值：space 名 → spatial.assign_container 到该空间；
                storey 名 → 到楼层；缺省 → 不指定容器。
环境：ifcopenshell 0.8.5。已知坑：unit.assign_unit 签名异常 → 手工建 IfcUnitAssignment。
"""
import sys, io, os
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import ifcopenshell
import ifcopenshell.api as api
import ifcopenshell.guid as guid
import yaml


def new_model(project_name):
    m = ifcopenshell.file(schema="IFC4")
    units = [
        m.create_entity("IfcSIUnit", UnitType="LENGTHUNIT", Name="METRE"),
        m.create_entity("IfcSIUnit", UnitType="AREAUNIT", Name="SQUARE_METRE"),
        m.create_entity("IfcSIUnit", UnitType="VOLUMEUNIT", Name="CUBIC_METRE"),
        m.create_entity("IfcSIUnit", UnitType="PLANEANGLEUNIT", Name="RADIAN"),
    ]
    ua = m.create_entity("IfcUnitAssignment", Units=units)
    project = api.run("root.create_entity", m, ifc_class="IfcProject", name=project_name)
    project.UnitsInContext = ua
    return m, project


def build_from_scenario(scenario_path, out_path):
    sc = yaml.safe_load(open(scenario_path, encoding="utf-8"))
    m, project = new_model(sc.get("project_name", "测试项目"))
    log = []

    # ---- 空间结构 ----
    sp_cfg = sc.get("spatial") or {}
    site = api.run("root.create_entity", m, ifc_class="IfcSite", name=sp_cfg.get("site", "场地"))
    building = api.run("root.create_entity", m, ifc_class="IfcBuilding", name=sp_cfg.get("building", "测试楼"))
    api.run("aggregate.assign_object", m, products=[site], relating_object=project)
    api.run("aggregate.assign_object", m, products=[building], relating_object=site)
    storeys = {}
    for st_name in sp_cfg.get("storeys") or ["1F"]:
        st = api.run("root.create_entity", m, ifc_class="IfcBuildingStorey", name=st_name)
        api.run("aggregate.assign_object", m, products=[st], relating_object=building)
        storeys[st_name] = st

    spaces = {}
    for sp_def in sc.get("spaces") or []:
        sp = api.run("root.create_entity", m, ifc_class="IfcSpace", name=sp_def["name"])
        sp.ObjectType = sp_def.get("object_type") or sp_def["name"]  # 词表表6：规范原文用语
        api.run("aggregate.assign_object", m, products=[sp],
                relating_object=storeys[sp_def.get("storey", "1F")])
        spaces[sp_def["name"]] = sp
    log.append(f"spaces: {'/'.join(spaces) or '-'}")

    # ---- 空间组（IfcZone，v0.3：carrier=IfcZone.Name 的空间上下文载体）----
    zones = {}
    for z_def in sc.get("zones") or []:
        zone = api.run("root.create_entity", m, ifc_class="IfcZone", name=z_def["name"])
        names = z_def.get("spaces") or []
        missing = [n for n in names if n not in spaces]
        if missing:
            raise KeyError(f"zone {z_def['name']} 成员空间未定义: {missing}")
        members = [spaces[n] for n in names]
        if members:
            # IfcZone 是 IfcGroup 子类：成员经 IfcRelAssignsToGroup 编组
            api.run("group.assign_group", m, products=members, group=zone)
        zones[z_def["name"]] = zone
    if zones:
        log.append(f"zones: {'/'.join(zones)}")

    # ---- 分类框架 ----
    cls = None
    cls_cfg = sc.get("classification")
    if cls_cfg:
        cls = m.create_entity("IfcClassification", Name=cls_cfg["name"])

    def cls_ref(ident):
        return m.create_entity("IfcClassificationReference",
                               Identification=ident, ReferencedSource=cls)

    # ---- 构件 ----
    def add_psets(product, psets):
        for ps_def in psets or []:
            ps = api.run("pset.add_pset", m, product=product, name=ps_def["name"])
            api.run("pset.edit_pset", m, pset=ps, properties=ps_def.get("properties") or {})

    n_elem = 0
    for e in sc.get("elements") or []:
        el = api.run("root.create_entity", m, ifc_class=e["ifc_class"], name=e["name"])
        if e.get("predefined_type"):
            el.PredefinedType = e["predefined_type"]
        if e.get("object_type"):
            el.ObjectType = e["object_type"]
        container = e.get("container")
        if container:
            host = spaces.get(container) or storeys.get(container) or zones.get(container)
            if host is None:
                raise KeyError(f"container 未定义: {container}")
            api.run("spatial.assign_container", m, products=[el], relating_structure=host)
        add_psets(el, e.get("psets"))
        mat_cfg = e.get("material")
        if mat_cfg:
            mat = api.run("material.add_material", m, name=mat_cfg["name"])
            api.run("material.assign_material", m, products=[el], material=mat)
            if mat_cfg.get("classification") and cls is not None:
                # 材料级分类正解：IfcExternalReferenceRelationship
                # （IfcMaterial 非 IfcObjectDefinition）
                m.create_entity("IfcExternalReferenceRelationship",
                                RelatedResourceObjects=[mat],
                                RelatingReference=cls_ref(mat_cfg["classification"]))
        if e.get("element_classification") and cls is not None:
            m.create_entity("IfcRelAssociatesClassification", GlobalId=guid.new(),
                            RelatedObjects=[el],
                            RelatingClassification=cls_ref(e["element_classification"]))
        n_elem += 1
    log.append(f"elements: {n_elem}")

    # ---- 系统 ----
    for s in sc.get("systems") or []:
        sys_el = api.run("root.create_entity", m, ifc_class=s["ifc_class"], name=s["name"])
        if s.get("predefined_type"):
            sys_el.PredefinedType = s["predefined_type"]
        add_psets(sys_el, s.get("psets"))
        members = []
        for mem in s.get("members") or []:
            de = api.run("root.create_entity", m,
                         ifc_class=mem.get("ifc_class", "IfcDistributionElement"),
                         name=mem["name"])
            if mem.get("object_type"):
                de.ObjectType = mem["object_type"]
            members.append(de)
        if members:
            api.run("group.assign_group", m, products=members, group=sys_el)
        log.append(f"system {s['name']}: members={[x['name'] for x in (s.get('members') or [])]}")

    m.write(out_path)
    return log


if __name__ == "__main__":
    scenario, out = sys.argv[1], sys.argv[2]
    for line in build_from_scenario(scenario, out):
        print("  ", line)
    print(f"写入 {out}")
