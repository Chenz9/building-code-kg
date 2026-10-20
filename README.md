# 建筑规范结构化知识库（Building Code Knowledge Base）

把中文工程建设标准（国标 GB / 行标 JGJ 等）从 PDF/OCR 文本，**提炼为机器可读、可被设计软件与审查流程直接消费的 YAML 结构化数据**：条文编号、适用条件与例外、数值阈值、查表逻辑、强条与废止状态、IFC 对象映射、可执行规则。

本仓库交付的不只是数据，还有一套**明示的提炼规约**：一条中文规范条文由哪些要素构成、每个要素用什么关键字识别、识别结果落到哪个字段、书写时遵守哪些规矩。规约的权威定义在 [`schema/SCHEMA_v2.2.yaml`](schema/SCHEMA_v2.2.yaml)（条文层）与 [`schema/SCHEMA_v2.3.yaml`](schema/SCHEMA_v2.3.yaml)（BIM 绑定层）。本文 §2 用 GB 50222-2017 等真实条文，把整套走法完整走一遍。

| 标准 | 名称 | 条文 | 强条 | 特点 |
| --- | --- | --: | --: | --- |
| **GB 50222-2017** | 建筑内部装修设计防火规范 | 49 | 18 | 防火装修；18 条强条**全部已被 GB 55037-2022 废止效力**，逐条标注 `superseded_by`；已完成 IFC 绑定层精修 |
| **GB 55031-2022** | 民用建筑通用规范 | 141 | 141 | **全文强制**；覆盖建筑面积与高度、室外场地、通用空间、部件与构造 |
| **GB 55024-2022** | 建筑电气与智能化通用规范 | 207 | 207 | **全文强制**；建筑电气与智能化系统设计/施工/验收的现行强制通用规范；`applicability` 回填进行中（80/207） |
| **GB 55019-2021** | 建筑与市政工程无障碍通用规范 | 102 | 102 | **全文强制**；无障碍设施建设与运行维护；`applicability` 回填进行中（17/102） |
| **GB 55036-2022** | 消防设施通用规范 | 122 | 122 | **全文强制**；建设工程消防设施设置与运行；`applicability` 回填进行中（21/122） |
| **GB 55032-2022** | 建筑与市政工程施工质量控制通用规范 | 66 | 65 | **全文强制**；施工质量控制基本要求；`applicability` 回填尚未开始（0/66） |

六册合计 **687 条**条文（其中强制性条文 655 条，含 GB 50222 已废止效力的 18 条强条）。

其余标准仍在私有工作区进行结构化与人工校对，**每册完成人工校对后才进入本仓库，不提前放出完全未检查的初稿**。GB 55024 / GB 55019 / GB 55036 / GB 55032 为阶段性发布：条文文本与数值参数已通过机器门禁，但 `applicability`（对谁有效）回填尚未完成，检索「适用性」时仅部分可用，使用前请务必回源核对官方版本。

> ⚠️ 样板册的**全册逐条人工校对仍在进行中，尚未完成**。「审计 0 违规」指结构层面的机器校验，不等于内容语义零差错——2026-09-08 的外部评审就在机检全 0 的数据里发现了 4 处实质错误，本仓库已完成整改并如实公示（见 §7）。涉及工程决策前，请务必回源核对官方版本。
>
> ⚠️ 标准文本的权利声明与免责条款见 [DISCLAIMER.md](DISCLAIMER.md)，使用前请先阅读。

方法论的完整论证（六层框架、门禁体系设计、GB 50222 全书绑定实证）已成文：

* 📄 [工程建设标准条文结构化表示与 IFC 模型机器可执行绑定的全链条方法（公开版）](docs/工程建设标准条文结构化与IFC模型机器可执行绑定的全链条方法（公开版）.md)

***

## 1. 为什么做这件事

工程设计行业信息化程度整体偏低，规范校验长期依赖人工完成，而代价最高的一类错误往往不是计算失误，而是规范读漏、读错。一份建筑总说明里散落着数十条引用规范，条文冲突、版本错配、图纸与规范不符等问题，常到施工图审查甚至现场返工才暴露，造成工期与成本损失。

要从根源解决问题，核心是让规范的形态从「给人读的 PDF」转向「给程序读的结构化数据」。本仓库把每条规范拆解为可被程序识别判定的最小单元：

| 需求 | 结构化之后能做到 |
| --- | --- |
| 设计说明里的引用条文是否齐全 | 每条带 `standard_code` + `clause_no`，可精确比对清单 |
| 这条规定对我这个部位适不适用 | `applicability.scope` / `conditions` / `exceptions` 三元组 |
| 我的取值达标了吗 | `parameters[].min_value/max_value/unit` |
| 该查哪张表 | `tables[].headers/rows`（六册共 10 张表 92 行已结构化） |
| 是不是强条 / 有没有被废止 | `constraint.is_mandatory_clause` + `is_abolished` + `superseded_by` |
| 能不能进 BIM 审查 | 部位词 / 空间词 → IFC 实体 + `PredefinedType` + 空间上下文（§2.10） |
| 能不能直接被规则引擎跑 | `executable_rules`（when → then） |

***

## 2. 规范条文是怎么提炼成 YAML 的

提炼一条条文分三步：先按要素**解剖**（§2.1），再逐要素**识别与落位**（§2.2–§2.9），最后按需要把条文**匹配到 BIM 模型**（§2.10）。所有规矩都有权威定义（`schema/` 两个文件），本文只讲「怎么用」。

### 2.1 先解剖：一条中文规范条文里有什么

| 条文要素 | 在原文里的形态 | YAML 落点 |
| --- | --- | --- |
| 编号与章节 | 「4.0.16」、章标题 | `clause_no` / `chapter` / `section` |
| 条文正文 | 全句 | `text`（唯一权威，结构化字段与之冲突时以它为准） |
| 语气强弱 | 必须 / 应 / 宜 / 可 / 不得 / 严禁… | `constraint.strictness`（§2.2） |
| 约束方向 | 下界 ≥ / 上界 ≤ / 禁止 | `constraint.polarity`（§2.3） |
| 对谁有效 | 主体名词短语 | `applicability.scope`（§2.4） |
| 生效条件 | 当…时 / 设于…时 | `applicability.conditions`（§2.4） |
| 排除对象 | 除…外 / 不适用于… | `applicability.exceptions`（§2.4） |
| 数值与单位 | 500mm、1.5kg/m²、A/B1 级 | `parameters[]` 五字段签名（§2.5） |
| 查表 | 表 5.1.1 等 | `tables[].headers/rows`（§2.6） |
| 引用别的标准 | 《…》GB xxxx | `references[]`（§2.7） |
| 强条 / 废止 | 黑体、发布公告、上位规范 | `is_mandatory_clause` / `is_abolished` / `superseded_by`（§2.7） |
| 管到哪些构件 | 顶棚 / 墙面 / 楼梯间… | `related_objects` → IFC 绑定（§2.10） |
| 机器判定 | 条件 → 结论 | `executable_rules[]`（§2.9） |

### 2.2 关键字识别 ①：情态词 → 约束强度（strictness）

中文规范用词有法定分级。依据《工程建设标准编写规定》「本规范用词说明」，强度分四档，每档各有正面词与反面词：

| 等级 | 枚举值（中文/英文） | 正面词 | 反面词 | 含义 |
| --- | --- | --- | --- | --- |
| L1 强制 | `必须/hard` | 必须 | 严禁、禁止 | 非这样做不可 |
| L2 严格 | `应/shall` | 应 | 不应、不得 | 正常情况下均应这样做 |
| L3 推荐 | `宜/should` | 宜 | 不宜 | 条件许可时首先应这样做 |
| L4 允许 | `可/may` | 可 | — | 一定条件下可以这样做 |
| — | `无/none` | — | — | 定义性 / 说明性条文 |

识别规则（`tools/audit_modal_v22.py` 里有可复跑的参考实现）：

1. **长词优先扫描**。先匹配「不应」「不得」「不宜」「严禁」，再匹配单字「应」「宜」「可」——否则「不应」会被拆成「应」，整条强度翻倍。
2. **上下文排除**。不是所有「可 / 宜 / 应 / 禁止」都是语气词：「应急」「可靠」「可燃」的「可」，「便宜」「事宜」「适宜」的「宜」，「明令禁止」的「禁止」（名词性定语）都不计入；「禁止」仅当直接支配动作（禁止停放 / 禁止干摆干铺）时才计入，语义等同「严禁」归 L1。
3. **多档取严**。同一条出现多个档位的词时取最高档：hard > shall > should > may。
4. **证据留痕**。`modal_words` 记录正文中实际出现的语气词全集，`modal_words_primary` 记录定级主词——两者都必须能在 `text` 里找到，不允许出现正文中不存在的词。

六册 687 条条文的实测词频（词表就是按这个分布设计的）：

| 语气词 | 应 | 不应 | 可 | 必须 | 不得 | 严禁 | 宜 | 不宜 | 禁止 |
| --- | --: | --: | --: | --: | --: | --: | --: | --: | --: |
| 出现条次 | 598 | 185 | 60 | 26 | 22 | 20 | 2 | 1 | 1 |

定级结果分布：`应/shall` 621 · `必须/hard` 43 · `可/may` 11 · `无/none` 12（目的条、术语条、列表式指标条）。

### 2.3 关键字识别 ②：极性 → 约束方向（polarity），边界语义是最大的坑

强度回答「多强」，方向回答「管哪头」。`polarity` 四值：`正面/required`（义务 / 允许）、`反面/prohibited`（禁止）、`正反并存/mixed`、`无/null`。六册分布：正面 555 · 正反并存 94 · 反面 26 · 无 12。

**最容易错的一类：边界语义不等于禁止。**「不得小于」「不应低于」含有否定词，语义却是**正向下界约束**（≥），不是「禁止做某事」。判据形式化为：

> 否定词 + 紧邻边界动词（小于 / 少于 / 低于 / 大于 / 超过 / 高于…），两者间隔 ≤ 3 字，且中间不含实义动词（在 / 装 / 设 / 采 / 使 / 改 / 用 / 拆 / 埋 / 做）→ 判 `正面/required`，方向由 `min_value` / `max_value` 承载。

三个真实判例（GB 50222-2017）：

| 原文片段 | 判定 | 落点 |
| --- | --- | --- |
| 「与窗帘、帷幕、幕布、软包等装修材料的距离**不应小于**500mm」（4.0.16） | 否定词与「小于」间隔 0 字 → 边界约束 ≥ | `正面/required` + `min_value: 500` |
| 「湿涂覆比**小于**1.5kg/m²」「涂层干膜厚度**不大于**1.0mm」（3.0.6） | 边界约束 < / ≤ | `max_value: 1.5` / `max_value: 1.0` |
| 「**不应**直接安装**在低于**B1 级的装修材料上」 | 「低于」是材料定语，中间隔着实义动词「直接安装在」→ 真禁止 | `反面/prohibited` |

**跨档 mixed**：定级取严与极性判定相互独立。一条文可以同时是 `应/shall` 档且正反并存——「必须…不得…」也不能因为命中最高档就停止扫描低档反面词。mixed 条文按分句拆进 `constraint_items`，每个分句标注自身的等级与极性。实例（GB 55024-2022 第 2.0.3 条，设备用房设置规定，节选）：

```yaml
constraint:
  strictness: 应/shall
  polarity: 正反并存/mixed
  constraint_items:
    - seq: 4
      text_segment: 地面或门槛应高出本层楼地面
      strictness: 应/shall
      polarity: 正面/required
      modal_word: 应
    - seq: 5
      text_segment: 其标高差值不应小于0.10m
      strictness: 应/shall
      polarity: 正面/required      # 边界 ≥，不是禁止
      modal_word: 不应
    - seq: 7
      text_segment: 无关的管道和线路不得穿越
      strictness: 应/shall
      polarity: 反面/prohibited
      modal_word: 不得
```

分句切分以「，；。、」为界，但必须保护数字小数点（1.0m、3.5mm）与条文编号（3.4.1）不被误切。

### 2.4 适用范围三元组：scope / conditions / exceptions

「这条规定对谁有效」拆成三个字段，分工固定：

* `scope`：主体——规定约束谁（名词短语，可多项）。
* `conditions`：条件——满足什么前提才触发（「当靠近非 A 级装修材料或构件时」）。
* `exceptions`：被排除的对象本身。

实例（GB 50222-2017 第 4.0.16 条）：

```yaml
applicability:
  scope: 照明灯具及电气设备、线路的高温部位；窗帘、帷幕、幕布、软包等装修材料；灯饰
  conditions: [当靠近非A级装修材料或构件时]
  exceptions: []
```

书写规矩（踩过坑才定下来的）：**「除 X 外」不写进 `exceptions`**。那是 SQL 式排除思维。范围限定应并入 `scope`（限定主体）或 `conditions`（条件分支）；`exceptions` 只放被排除对象本身，且不写「除…外」「不适用于…」前缀。

### 2.5 数值参数：五字段统一签名

每个数值参数必须五字段齐名：`name / unit / condition / min_value / max_value`，缺 `unit` 也要显式 `null`。这是所有下游脚本的字段签名。

三条识别规矩：

1. **参数名必须是可读语义短语**，禁 OCR 碎片。典型反词库：「口之间距离」「位面积质量」（缺字）、「上湿涂覆比」（多字）。4.0.16 的参数名就经历过「材料的距离」（OCR 碎片）→「高温部位与装修材料距离」的更正。
2. **单位必须命中词典**：长度 mm/cm/m，面积 mm²/m²/㎡，力 N/kN，质量 kg/t，温度 ℃/K，声学 dB/dBA，面密度 kg/m²，以及「间 / 座 / 樘 / 套」等计数单位。
3. **等级型 / 枚举型条款不是阈值约束**。像「B1 级可视同 A 级」这种等效规则，`>=` 数值比较是错的——用 `operator: in` + `value` 表达值域，换算逻辑放 `executable_rules`。实例：

| 原文 | 参数落点 |
| --- | --- |
| 「燃烧性能达到 B1 级的纸面石膏板…可作为 A 级装修材料使用」（3.0.4） | `operator: in`，`value: [B1]`，无数值阈值 |
| 「燃烧性能等级不应低于表 5.1.1 的规定，顶棚列取 A 的场所」（5.1.1） | `operator: in`，`value: [A]`；顶棚列取 B1 的场所 → `value: [A, B1]` |
| 「距离不应小于 500mm」（4.0.16） | `operator: gte`，`min_value: 500`，`unit: mm` |

v2.3 起参数增加两个字段：`id`（唯一标识，绑定层只引用不存值）与 `ifc_binding`（落点描述：构件属性 / 材料分类 / 几何推导 / 过程参数）。

### 2.6 查表条款：表格的结构化

规范表格按内容分三类，处置原则不同：

| 表型 | 处置 | 例 |
| --- | --- | --- |
| 资料清单 / 阶段要求（定性） | 转文本 | — |
| 参数查表（燃烧等级、厚度、宽度） | 结构化 `{headers, rows}`，并可编译为规则 | GB 50222 表 5.1.1 |
| 计算查表（承载力等） | 保留行列结构 | — |

实例（GB 50222-2017 表 5.1.1，单层多层民用建筑各部位燃烧性能等级）：`headers` 九列（序号 / 建筑物及场所 / 建筑规模性质 / 顶棚 / 墙面 / 地面 / 隔断 / 固定家具 / 装饰织物 / 其他装修装饰材料），逐行结构化。条文「不应低于表 5.1.1」+ 表 → 按「场所 × 部位」展开成一组值域参数（顶棚列取 A 的场所 → `in ['A']`，取 B1 的场所 → `in ['A', 'B1']`）。GB 50222 六张表共 79 行全部按此落地，绑定层另按逐格展开核对 **136 / 136 与正本一致**（5 张表）。

**带条件行的表不强行展开**：按建筑规模 / 性质分档的行（如「每层建筑面积 > 1500㎡」）依赖建筑分类上下文，硬拆会与分档语义冲突——只展开无条件行，条件行整条降级为专家复核标记。宁可降级，不做伪绑定。

### 2.7 引用、废止链与强条

**跨标准引用**（`references[]`）：记录 `target_standard` / `target_clause` / `original_text` / `resolution_status`。被引标准不在库内的标 `unresolved` 并注明待补录，不假装已核对。

**废止链**（条文级）：`is_abolished` + `superseded_by` + `abolition_note`。GB 50222-2017 的 18 条强条全部被 GB 55037-2022《建筑防火通用规范》废止强制性效力，逐条标注——检索时不会被误导去执行已失效条文。GB 50222 与 GB 55031 恰好覆盖「已废止但仍在图纸中被引用」与「现行强制」两种典型状态。

**强条是法定属性，不是语气属性**。`is_mandatory_clause` 以发布公告 / 黑体为准，与 `strictness` 正交：语气严格 ≠ 强条，强条也可能无语气词（列表式指标），二者不可互相推导。判定捷径：GB 55xxx 全文强制规范的所有条文 `is_mandatory_clause=True`。

### 2.8 两个特例：术语条与宏观章

**术语条**用字典式内联约定，三段内容（中文名 / 英文 / 定义）写成一行：

```yaml
text: "{装饰织物: decorative fabric} 满足建筑内部功能需求，由棉、麻、丝、毛等天然纤维及其他合成纤维制作的纺织品，如窗帘、帷幕等。"
```

全库 465 条术语 100% 覆盖该格式，阅读器据此渲染「术语卡片」。

**宏观章节**（总则 / 术语 / 基本规定 / 分类分级 / 分部验收…）是「全册级」要求，不指向任何具体构件。识别方法：章名剔除序号与字间空格（OCR 常产出「1 总 则」）后匹配关键词表——总则 / 术语 / 符号 / 代号 / 基本规定 / 基本技术要求 / 一般要求 / 一般性规定 / 规范性引用文件 / 引用标准 / 分类 / 分级 / 分部工程 / 单位工程。命中的条文 `component_types` 必须为空，但保留 `activity_types`（宏观条文仍归属本册业务活动）。若按册统一挂一组 IFC 类型，等于「什么都指向」，信息量为零。

### 2.9 从条文到可执行规则：when → then

`executable_rules` 是 `parameters` 的机器可读镜像：`when` 条件数组 → `then` 结论，`not_when` 黑名单例外（命中任一即跳过本规则），`source_text` 保留原文出处供回溯。参数变更而规则未同步即违规——同一数值只存一处（`parameters[]`），规则只引用参数标识，杜绝多处存值后漂移。

```yaml
- rule_id: R_GB50222_4_0_16_lamp_clearance
  source_clause: GB 50222-2017#4.0.16
  when: ["near_soft_combustible_material == true"]
  not_when: ["space_area_m2 > 400"]
  then: { min_clearance_mm: 500 }
  source_text: 与窗帘、幕布、软包等装修材料的距离不应小于500mm
```

GB 50222 全书 77 条规则 = 13 条册级遗留 + 64 条条文级编译产物（v2.3 绑定层编译生成，不手写）。

### 2.10 从条文到 BIM 模型：部位词 / 空间词怎么匹配到 IFC

条文里的「顶棚」「墙面」「楼梯间」要落到 IFC 实体上，靠一张**映射词表**（[`ifc-binding/ifc_mapping_dict_v0.yaml`](ifc-binding/ifc_mapping_dict_v0.yaml)，v0.6）而不是逐条拍脑袋：

| 词表 | 规模 | 管什么 |
| --- | --: | --- |
| `part_component_map` | 16 部位 | 部位词 → IFC 实体 + `PredefinedType`，标覆盖度 strong / medium / weak |
| `space_map` | 48 类空间 | 空间词 → `IfcSpace.ObjectType` 或 `IfcZone.Name`（空间组） |
| `system_map` / `member_alias_map` | 8 / 7 | 系统编组与成员别名归一（防雷系统组成完整性等） |
| `concept_property_map` | 11 | 概念属性落点（燃烧性能、耐火极限、传热系数…） |
| `entity_whitelist` + `forbidden` | — | 可用实体白名单 + 死名黑名单 |

三条匹配规矩：

1. **一个部位多种候选就拆多条绑定**。「墙面」指装修面层时 → `IfcCovering.CLADDING`；涉及墙体本体（耐火极限）时 → 另拆一条 `IfcWall.STANDARD`。单条绑定保持语义单纯。
2. **燃烧性能 ≠ 耐火极限**。GB 8624 的 A/B1/B2 绑 `FlammabilityRating` 或材料分类；构件耐火极限（1.50h）绑 `FireRating`。绑串属语义级事故，审计器强制拦截。
3. **词表必须同时定义「可用」与「禁用」**。宽匹配会产生 IFC4 里根本不存在的实体名（死名）：`IfcCeiling`（正解 `IfcCovering.CEILING`）、`IfcFloor`（正解 `IfcSlab.FLOOR`）、`IfcEntrance`（正解 `IfcDoor`）——收录进 `forbidden` 清单并拦截，全库累计清理 690 处。只定义「可用」必然漏检。

匹配的粒度用 `binding_level` 九级表达（macro / site / building / storey / space / system / element / process / document），其中 macro / process / document 三级不得携带构件绑定。批量生产收敛为七类模板（T1 部位值域、T1_table 表格型部位值域、T2 属性存在性、T3 系统成员齐备、T4 系统设备属性值域、T5 过程活动、T6 宏观场地），定义见 [`ifc-binding/binding_templates_v1.yaml`](ifc-binding/binding_templates_v1.yaml)。

执行时分双轨：单对象属性值域 / 枚举 / 存在性 / 禁止值走 **IDS 标准导出**，交任意 IDS 兼容检查器；空间 / 空间组上下文、跨对象编组、几何推导、过程类条文走**自研规则引擎**（IfcOpenShell）。IDS 表达不了空间上下文，硬塞会把检查口径从「限定空间」放大为「全楼」——使用者须知情。

GB 50222-2017 是首个全书绑定实证：49 条全部落绑定（element 30 / document 7 / macro 12），99 条 `model_bindings`、64 条条文级编译规则，审计 0 error / 0 warning。工具、词表、黄金样本与实测命令见 [`ifc-binding/README.md`](ifc-binding/README.md)。

***

## 3. 一条条文的完整样子

把 §2 的所有规矩合起来，GB 50222-2017 第 4.0.16 条在 YAML 里是这样（节选）：

```yaml
- id: GB 50222-2017#4.0.16
  clause_no: 4.0.16
  chapter: 4 特别场所
  text: 照明灯具及电气设备、线路的高温部位，当靠近非A级装修材料或构件时，应采取隔热、散热等防火保护措施，与窗帘、帷幕、幕布、软包等装修材料的距离不应小于500mm；灯饰应采用不低于B1级的材料。
  is_abolished: false
  applicability:            # §2.4 三元组
    scope: 照明灯具及电气设备、线路的高温部位；窗帘、帷幕、幕布、软包等装修材料；灯饰
    conditions: [当靠近非A级装修材料或构件时]
    exceptions: []
  constraint:               # §2.2 + §2.3 强度 × 方向
    strictness: 应/shall
    polarity: 正面/required  # 「不应小于500mm」是边界 ≥，不是禁止
    modal_words: [不应, 应]
    modal_words_primary: [不应, 应]
    is_mandatory_clause: false
    constraint_items: []
  parameters:               # §2.5 五字段签名
    - id: p_gb50222_4_0_16_distance
      name: 高温部位与装修材料距离
      operator: gte
      unit: mm
      min_value: 500
      max_value: null
      ifc_binding: { target: geometric, path: 几何推导（高温部位与软质装修材料的最近距离） }
  related_objects:          # §2.10 部位词匹配
    binding_level: element
    component_types: [IfcCovering, IfcFurniture]
    activity_types: [内部装修防火设计]
    model_bindings:
      - id: mb_gb50222_4_0_16_distance
        role: 高温部位与装修材料距离
        ifc_entity: IfcCovering
        predefined_type: CLADDING
        property_requirements:
          - parameter_ref: p_gb50222_4_0_16_distance   # 只引用，不存值
            pset: GB_装修防火
            property: 高温部位与装修材料距离
        mapping_status: needs_expert_review           # 几何量，v1 不生成规则
        rationale: 距离≥500mm 为几何推导量，参数保留供几何引擎消费
```

**几条立规矩的经验**（都是踩过坑才定下来的）：

* **参数必须五字段齐名**。缺 `unit` 也要显式 `null`。这是所有下游脚本的字段签名。
* **「除 X 外」不写进 `exceptions`**。范围限定并入 `scope` 或 `conditions`，`exceptions` 只放被排除对象本身。
* **等级型 / 枚举型条款不是阈值约束**。`>=` 数值比较是错的，用 `in` 值域 + `executable_rules` 表达换算逻辑。
* **不要发明新字段名**。`operator` / `value` 这类自定义键不会被任何脚本识别，也不会进规则镜像。

***

## 4. 仓库结构

```
.
├── README.md                      # 你正在看的文件
├── DISCLAIMER.md                  # 标准文本来源说明与免责条款
├── LICENSE                        # MIT（仅覆盖代码与工具，不含标准文本）
├── docs/                          # 方法论论文（公开节选版；其余文稿留在私有工作区）
│   └── 工程建设标准条文结构化与IFC模型机器可执行绑定的全链条方法（公开版）.md
├── schema/
│   ├── SCHEMA_v2.3.yaml           # 数据结构定义（当前权威版本：v2.2 条文结构 + v2.3 IFC 绑定层）
│   ├── SCHEMA_v2.2.yaml           # 条文结构定义（带书写规约；v2.3 兼容其全部字段）
│   └── SCHEMA_v2.1.yaml           # 上一版（留存备查）
├── standards/
│   ├── GB50222-2017.yaml          # 深度复核样板 ①：49 条（防火装修；18 强条已废止效力；含 v2.3 绑定层）
│   ├── GB55031-2022.yaml          # 深度复核样板 ②：141 条（民用建筑通用规范，全文强制）
│   ├── GB55024-2022.yaml          # 深度复核样板 ③：207 条（建筑电气与智能化通用规范，全文强制；适用性回填 80/207）
│   ├── GB55019-2021.yaml          # 通用规范④：102 条（无障碍通用规范，全文强制；适用性回填 17/102）
│   ├── GB55036-2022.yaml          # 通用规范⑤：122 条（消防设施通用规范，全文强制；适用性回填 21/122）
│   └── GB55032-2022.yaml          # 通用规范⑥：66 条（施工质量控制通用规范，全文强制；适用性回填 0/66）
├── ifc-binding/                   # IFC 绑定层（schema v2.3 已升正本）：词表 + 模板 + 编译/审计/引擎工具链
│   ├── README.md                  # 说明、依赖、实测命令、设计红线
│   ├── SCHEMA_v2.3_draft.yaml     # 升格前草案（备查；正本为 schema/SCHEMA_v2.3.yaml）
│   ├── ifc_mapping_dict_v0.yaml   # 映射词表 v0.6（部位/构件/空间/系统 → IFC 实体与枚举，含 space_map、别名表、forbidden）
│   ├── binding_templates_v1.yaml  # T1–T6 + T1_table 批量重映射模板 v1.1
│   ├── tools/                     # 编译 / 审计（15 项）/ 自研引擎 / 造测试模型 / IDS 导出
│   ├── samples/                   # 黄金样本套件（golden20，19 条样本）：源数据 + 编译产物
│   ├── scenarios/                 # 正反例测试场景（驱动工厂造 IFC 模型）
│   └── fixtures/                  # 探针夹具（zone_probe）
└── tools/
    ├── yaml-reader.html           # 通用 YAML 阅读器（离线单文件，零依赖）
    ├── audit_v21.py               # v2.1 合规审计脚本（开源，可独立复跑验证）
    ├── audit_sync_copies.py       # 正本 / 副本 / 开源仓库三轨一致性审计
    ├── _modal_allowlist.txt       # 语气字段审计白名单（人工裁定的「强条但无语气词」豁免条目）
    ├── audit_modal_v22.py         # v2.2 语气字段审计（含 §2.2/§2.3 识别规则的参考实现与「由 text 重推导」一致性校验）
    ├── migrate_all_v22.py         # v2.1 → v2.2 全库语气字段迁移（以 text 为唯一权威，文本级替换 + 三重写盘自检）
    ├── rederive_modal.py          # 由 text 重推导语气字段的只读比对工具
    ├── refix_modal_v22.py         # 以 text 为准重写 constraint 块（dry-run / --apply，含行尾正规化与写盘自检）
    ├── fix_macro_component_types.py  # 宏观章节 component_types 清空工具（dry-run / --apply / --scan-all）
    ├── gen_readview_html.py       # 由 YAML 生成静态阅读视图的脚本
    └── strip_text.py              # 合规阀：一键剔除条文原文，仅留结构化元数据
```

***

## 5. 数据概况

| 标准 | 条文 | 强条 | 适用性回填 | 数值参数 | 可执行规则 | 结构化表 | 文件体积 |
| --- | --: | --: | --- | --: | --: | --: | --: |
| GB 50222-2017 | 49 | 18（已废止效力） | 49 / 49 | 64 | 77（13 册级 + 64 条文级） | 6（79 行） | 242 KB |
| GB 55031-2022 | 141 | 141 | 141 / 141 | 45 | 44 | 2（5 行） | 198 KB |
| GB 55024-2022 | 207 | 207 | 80 / 207 | 76 | 75 | 1（4 行） | 332 KB |
| GB 55019-2021 | 102 | 102 | 17 / 102 | 92 | 89 | 0 | 180 KB |
| GB 55036-2022 | 122 | 122 | 21 / 122 | 36 | 34 | 1（4 行） | 176 KB |
| GB 55032-2022 | 66 | 65 | 0 / 66 | 1 | 1 | 0 | 97 KB |

GB 50222-2017 另含 IFC 绑定层：49 条 `binding_level`（element 30 / document 7 / macro 12）、99 条 `model_bindings`、64 条条文级编译规则，审计 0 error / 0 warning；绑定层按「场所 × 部位」逐格展开核对 136 / 136 一致（5 张表）。

两点须知：

* **适用性回填率低于 100% 的册，检索「对谁有效」时部分条文不可用**。GB 55032 尚未开始，GB 55019 / GB 55036 仅回填少量典型条文。
* **文本命中率要分辨归因**。全库条文与源基线逐字命中率 70.3%（4664/6636），未命中部分主要是源扫描件无文本层与 OCR 噪声——这是「源基线缺陷」，不是「结构化缺陷」，两类口径必须分开评价。

各册全文强制规范的 1.0.1 均为目的条（「为…制定本规范」），本就无约束语气，`strictness: 无/none` 属合法状态，审计豁免记录在 [`tools/_modal_allowlist.txt`](tools/_modal_allowlist.txt)。

***

## 6. 怎么用

### 6.1 最省事：拖进阅读器

打开 [`tools/yaml-reader.html`](tools/yaml-reader.html)（下载后双击，或在本仓库页面直接预览），把 `standards/` 下的 YAML 拖进窗口即可。

* **零依赖**：内置纯 JS YAML 解析器，不联网、不需要 Python/Node，file:// 下直接可用
* **书模式**：自动识别 `standard` + `clauses` 结构，渲染封面信息、章节目录、强条/废止徽标、适用范围/条件/例外、参数阈值表、原表格、引用与规则（「当…且… → 则…」）、术语卡片
* **树模式**：任意 YAML 的通用层级树，支持路径面包屑与值复制
* 支持多文件/整目录加载、实时搜索高亮、按强条/废止/参数/条件/表格/引用筛选、字号与深浅主题

该解析器已与 PyYAML 对内部知识库 34 份 YAML 做过**逐字段一致性比对，零差异**。

### 6.2 用 Python 读数据

```python
import yaml
d = yaml.safe_load(open('standards/GB55031-2022.yaml', encoding='utf-8'))

for c in d['clauses']:
    if c['constraint']['is_mandatory_clause'] and not c['is_abolished']:
        print(c['clause_no'], c['text'])
```

> 六册共 687 条条文中，GB 55031 / GB 55024 / GB 55019 / GB 55036 / GB 55032 的全部现行强制条文（637 条）均为 `is_abolished: false`；GB 50222-2017 的 18 条强条均已 `is_abolished: true`，会被上面这段过滤掉——这正是结构化数据能自动规避「误用废止条文」的地方。

如需**静态分发版**（自包含单文件 HTML，可直接发给别人双击打开）：

```bash
pip install pyyaml
python tools/gen_readview_html.py standards/GB55031-2022.yaml 阅读视图.html
```

***

## 7. 质量观：门禁是工作方式，不是目的

这套数据既不是纯手写，也不是纯自动生成，走的是**「LLM 辅助抽取 → 机器审计 → 人工精校」**三段式。机器门禁（模式合规、语气推导一致性、副本一致性）只是把「人工看得过来的部分」交给脚本，替代不了语义判断；**全册逐条人工校对与回源核验才是质量的主来源，目前仍在进行中**。

* **机器审计**：`tools/audit_v21.py`（参数名/单位/排除项/强条归位/规则镜像）与 `tools/audit_modal_v22.py`（§2.2/§2.3 识别规则的重推导一致性），clone 后可独立复跑：`python tools/audit_v21.py` → files scanned: 6 / total violations: 0；`python tools/audit_modal_v22.py` → scanned: 6 files / violations: 0。
* **人工精校**：标准 PDF 按 120 DPI 全本渲染后逐页视觉比对，处理机器判不了的部分（语义归属、等级型条款、误抽与幽灵条文）。
* **如实公示**：机器门禁全 0 ≠ 语义零差错。2026-09-08 外部评审在机检全 0 的数据里发现了实质错误，全部整改完毕：

| 评审发现 | 整改 |
| --- | --- |
| 3.0.6「涂层干膜厚度**不大于** 1.0mm」被标成 `min_value: 1.0`（方向反，会导致合规判定反判） | 参数与规则镜像同步改为 `max_value: 1.0` |
| 4.0.16 参数名「材料的距离」为 OCR 碎片 | 更名「高温部位与装修材料距离」，规则镜像同步 |
| 3 条自动规则参数名碎片（「位面积质量」缺字、「上湿涂覆比」多字） | 已修正，note 从「待人工精修」更新为「已人工校正」 |
| `standard.clauses` 索引中 5.1.2 排在 5.1.1 前 | 已排序修正 |
| extraction_notes 残留过期矛盾记录 | 已清理过期项，追加整改记录 |

**门禁盲区教训**：阈值方向反写（min/max 颠倒）、参数名截断碎片混入规则镜像、审计日志过期——这三类此前不在机检规则覆盖范围内。方向类校验规则将纳入审计脚本下一版。

***

## 8. 路线图

* [x] 首册开源：GB 50222-2017 深度复核样板（2026-09-08）
* [x] 第二册开源：GB 55031-2022《民用建筑通用规范》（全文强制，141 条）（2026-09-15）
* [x] 全库升级至 v2.2 schema（`strictness` × `polarity` 正交）（2026-09-11）
* [x] 第三册开源：GB 55024-2022《建筑电气与智能化通用规范》（全文强制，207 条）（2026-09-21；**适用性回填 80/207，进行中**）
* [x] 第四至六册开源：GB 55019-2021《无障碍通用规范》、GB 55036-2022《消防设施通用规范》、GB 55032-2022《施工质量控制通用规范》（均为全文强制，合计 290 条）（2026-09-23；**适用性回填进行中，GB55032 尚未开始**）
* [x] IFC 绑定层 + 工具链开源，并完成 **GB 50222-2017 全册绑定精修**（2026-09-22；49 条 `binding_level` / 99 条绑定 / 64 条条文级编译规则，审计 0 error 0 warning，见 [`ifc-binding/`](ifc-binding/README.md)）
* [x] SCHEMA v2.3 升正本 + 全库 IFC 死名清理（2026-09-24；GB 55019 清除 `IfcEntrance` 死名 170 处，全库累计 690 处，词表 forbidden 补齐并升 v0.6，审计器新增未迁移册 CT 死名检查）
* [x] 黄金样本正反例回归套件固化（2026-09-29；19 条样本覆盖全部模板类型，正例 24 / 反例 16 检查记录全部符合预期，回归套件 81 项断言全通过）
* [x] 全链条方法论整理成文并开源（2026-09-29；[`docs/`](docs/) 收录论文《工程建设标准条文结构化表示与 IFC 模型机器可执行绑定的全链条方法》公开节选版）
* [ ] 完成三册样板全册逐条人工校对
* [ ] 回填 GB 55024-2022 的 `applicability`（剩余 127 条）
* [ ] 陆续开源其余标准——每册完成人工校对后发布，不提前放出未校对初稿（防火、防水、节能、无障碍、隔声、热工、门窗、玻璃、屋面、车库、剧场、展览、消防设施、施工质控、数据中心等）
* [ ] 开源 V1–V9 审计脚本，并把阈值方向校验（min/max 反写检测）等本次整改沉淀的新机检规则纳入
* [ ] IFC 映射逐条精修（续）：GB 50222-2017 已完成；**GB 55031 / GB 55024 仍为宽匹配**，待按 `ifc-binding/binding_templates_v1.yaml` 的 T1–T6 逐册重映射
* [ ] 提供 English field dictionary，便于国际工具链对接
* [ ] 跨标准冲突检测（`conflicts` 字段目前尚未批量填充）
* [ ] 与设计说明提取对接：自动比对「说明里写了」与「规范里要求」

***

## 9. 引用与参考文献

如果这套结构对你的研究或产品有帮助，欢迎引用并提 issue 交流。仓库也接受 issue 形式的勘误——标准数据天然需要众人校对。

**本项目论文**：

> 工程建设标准条文结构化表示与 IFC 模型机器可执行绑定的全链条方法——基于 33 本标准 6636 条条文的工程实践（见 [`docs/`](docs/)）

**相关标准与文献**：

* [1] ISO 16739-1:2018. Industry Foundation Classes (IFC) for data sharing in the construction and facility management industries — Part 1: Data schema[S].
* [2] buildingSMART. Information Delivery Specification (IDS) 1.0[S]. buildingSMART International, 2024.
* [3] buildingSMART. bSDD: buildingSMART Data Dictionary[EB/OL]. https://www.buildingsmart.org/users/services/buildingsmart-data-dictionary/
* [4] Eastman C, Lee J, Jeong Y, et al. Automatic rule-based checking of building designs[J]. Automation in Construction, 2009, 18(8): 1011-1033.
* [5] Zhang S, El-Gohary N. Semantic NLP-based information extraction from construction regulatory documents for automated compliance checking[J]. Journal of Computing in Civil Engineering, 2016, 30(2): 04015014.
* [6] GB 50222—2017 建筑内部装修设计防火规范[S]. 北京: 中国计划出版社, 2017.
* [7] GB 55031—2022 民用建筑通用规范[S]. 北京: 中国建筑工业出版社, 2022.
* [8] GB 8624—2012 建筑材料及制品燃烧性能分级[S]. 北京: 中国标准出版社, 2012.
