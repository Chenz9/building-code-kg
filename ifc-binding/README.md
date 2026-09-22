# IFC 绑定层（草案）

把标准条文的「对哪些构件生效」，从宽泛的实体名，精修到 **IFC4 实体 + `PredefinedType` + 空间上下文** 的可执行绑定，并可导出 **IDS** 交给 BIM 审查工具消费。

它闭合的是仓库 README 路线图里挂着的那一条：

> `[ ] IFC 映射逐条精修：当前 rules 的 when 中 component_type 为保守宽匹配（四类实体全量覆盖），尚不构成精确的 BIM 构件级映射`

> ⚠️ **当前状态：草案（draft），不是权威 schema。**
> - 本目录的 `SCHEMA_v2.3_draft.yaml` 是 v0.4 草案；仓库权威 schema 仍是 [`schema/SCHEMA_v2.2.yaml`](../schema/SCHEMA_v2.2.yaml)。
> - 目前**只有 GB 50222-2017 一册**完成了全册绑定并合入 `standards/`；GB 55031 / GB 55024 尚未按本层重映射。
> - 工具与词表可用、可复跑，但接口仍可能随后续批次调整。

***

## 1. 目录结构

```
ifc-binding/
├── README.md                     # 你正在看的文件
├── SCHEMA_v2.3_draft.yaml        # 绑定层 schema 草案（v0.4）：字段定义 + 15 项审计口径
├── ifc_mapping_dict_v0.yaml      # 映射词表（v0.3）：中文部位/构件 → IFC 实体与 PredefinedType，含 space_map 与别名表
├── binding_templates_v1.yaml     # T1–T6 + T1_table 批量重映射模板（v1.1）
├── tools/
│   ├── audit_binding_v23.py      # 绑定层审计（15 项检查；--selftest 自证）
│   ├── rule_compiler.py          # 源数据 → 编译绑定层（规则不手写，避免漂移）
│   ├── rule_engine.py            # 自研规则引擎（ifcopenshell），跑 IFC 模型出判定
│   ├── ifc_model_factory.py      # 由场景 YAML 生成测试用 IFC 模型
│   └── ids_export.py             # 绑定层 → IDS 导出（ifctester）
├── samples/
│   ├── golden20_src.yaml         # 黄金样本源（related_objects + parameters，不含编译规则）
│   └── golden20_bindings.yaml    # 黄金样本编译产物（19 条 / 21 条规则）
├── scenarios/                    # 测试场景（驱动工厂造正反例模型）
└── fixtures/                     # 探针用夹具
```

## 2. 依赖（按需要分级安装）

| 依赖 | 只做审计/编译 | 造模型 + 跑引擎 | 导出 IDS |
| --- | :---: | :---: | :---: |
| `pyyaml` | ✅ | ✅ | ✅ |
| `ifcopenshell` | — | ✅ | ✅ |
| `ifctester`（ifcopenshell 自带） | — | — | ✅ |

```bash
pip install pyyaml          # 最小
pip install ifcopenshell    # 完整（实测 0.8.5 可用）
```

## 3. 快速验证（以下命令均在本仓库实测通过）

```bash
# ① 审计器自证：15 项检查逐一用合成违规数据触发，确认审计器本身没瞎
python ifc-binding/tools/audit_binding_v23.py --selftest
#   → == 自证结论：全部触发（17/17）

# ② 审一份真实绑定层
python ifc-binding/tools/audit_binding_v23.py ifc-binding/samples/golden20_bindings.yaml
#   → 文件 1 | error 0 | warning 0

# ③ 由源数据编译出绑定层（规则必须编译，不允许手写）
python ifc-binding/tools/rule_compiler.py ifc-binding/samples/golden20_src.yaml --emit /tmp/g20.yaml

# ④ 造一个满足条件的测试模型
python ifc-binding/tools/ifc_model_factory.py ifc-binding/scenarios/golden20_pass.yaml /tmp/g20_pass.ifc
#   → spaces: ... zones: 湿区组 elements: 15

# ⑤ 跑规则引擎
python ifc-binding/tools/rule_engine.py ifc-binding/samples/golden20_bindings.yaml /tmp/g20_pass.ifc /tmp/report.json
#   → 记录 24 | pass 24 | fail 0 | error 0
```

换用反例场景 `scenarios/golden20_fail.yaml`（内埋 16 处雷），引擎会给出 **恰好 16 fail / 8 pass / 0 error**，16 处埋雷逐条命中。

## 4. 核心设计（踩过坑才定下来的）

* **绑定粒度分级**：`related_objects.binding_level` 取 `macro / site / building / storey / space / system / element / process / document` 九级之一。宏观章（术语、总则、基本规定…）只能是 `macro`，`component_types` 必须为空——不硬凑实体。

* **属性值单一事实源**：绑定层**只引用** `parameter_ref`，阈值与单位一律回 `parameters[]`。同一数值在两处各写一遍，迟早漂移。

* **规则不手写**：落盘规则由 `rule_compiler` 从源数据编译。审计项 `C-RULE-01` 会用源数据现场重编译并比对，不一致直接报 `RULE_COMPILE_MISMATCH`。

* **IDS 双轨，不硬塞**：值域与存在性检查可导出 IDS；**空间 / 空间组 / 跨对象 / 否定 / 几何** 这几类 IDS 表达不了，走自研引擎。别为了「统一走 IDS」而丢语义。

* **15 项机器门禁**：`C-BINDING-01…12`、`C-BINDING-04a`、`C-RATIO-01/02`、`C-RULE-01`。其中 `C-BINDING-04` 分三支判定——主映射带空间上下文而规则丢了收窄 → **error**；主映射无空间上下文且规则只限实体 → **合法**（即「其他部位」这类部位补集）；规则空间值是主映射真子集 → **warning**。

## 5. 红线：别把燃烧性能绑到耐火极限上

| 语义 | 正确落点 |
| --- | --- |
| GB 8624 燃烧性能等级（A / B1 / B2 / B3） | `FlammabilityRating` 或材料分类 |
| 构件耐火极限（如 1.50h） | `FireRating` |

两者绑串属 `C-BINDING-02` 级错误，会让审查结论完全失真。另：GB 8624 的等级记号 `A/B1/B2` 是**法定记号**，不是 OCR 残渣——参数名里出现属正常。

## 6. 已知边界

* 草案 schema 未升正本；其余 30 余册标准尚未按本层重映射。
* 几何推导量（如「距 XX 不小于 0.5m」）当前保留参数、不生成规则，待几何引擎接入。
* `element` 级绑定若不带空间收窄，其规则是**实体全域**的——模型里同类实体的其他用途会被误卷入。批量迁移时要选**最贴切**的实体，而不是最宽的上位实体。
* ifcopenshell 0.8.5 的两个坑：`unit.assign_unit` 会 `IndexError`（须手工建 `IfcUnitAssignment`）；`IsGroupedBy` 是 `IfcGroup` 侧的**逆属性**，成员侧要走 `IfcObjectDefinition.HasAssignments`——写反了会恒返回 `None`，空间组条件静默失效。

## 7. 与仓库主体的关系

`standards/GB50222-2017.yaml` 已按本层完成全册绑定（49 条 `binding_level`、99 条绑定、64 条参数、64 条条文级编译规则，审计 0 error / 0 warning）。它是**唯一的落实例子**，可对照 `samples/` 里的黄金样本看同样的写法。

本目录不发布内部决策记录与未定稿的批次报告——那些是过程稿，留在私有工作区。
