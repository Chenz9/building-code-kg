# -*- coding: utf-8 -*-
"""
audit_v21.py — 全库 v2.1 合规审计

扫描 standards/ 目录下的 *.yaml（不含 SCHEMA_*）；
也可传入自定义目录作为第一个参数。
按 SCHEMA_v2.1.yaml 字段规约逐条核查，记录违规项到 audit_v21_report.json（当前目录）。

检查项：
  META      standard.schema_version / last_reviewed_date 是否齐全
  TEXT      截断/OCR 错别字启发式（文本以非中文符号结尾 / 含「小丁」「合下列规定」等）
  PARAM_NAME  参数名是否落入 v2.1 §2.1 OCR 碎片黑名单
  PARAM_UNIT  单位是否在 v2.1 §2.2 合法词典内
  EXCLUSION   applicability.exceptions 是否带「除…外」/「不适用于」前缀
  MANDATORY   全文强制规范（all_mandatory=True）下 clause 是否全部 is_mandatory_clause=True

输出：_audit_v21_report.json（含每文件 violation_count + 详情）
退出码：violation > 0 时返 1（CI 可用）
"""
from __future__ import annotations
import yaml, json, io, sys, os, glob, re
from collections import Counter
from datetime import datetime
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

V21_DIR = sys.argv[1] if len(sys.argv) > 1 else os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "standards"))
REPORT = os.path.join(os.getcwd(), "audit_v21_report.json")

# OCR 碎片黑名单（v2.1 §2.1）
NAME_BLACKLIST = {
    "取防水措施","容器室长度","气装置长度","指挥语音于",
    "线时其壁厚","口之间距离","合下列规定","列规定m",
    "动作值不大","间不得少于","于mm直径","径不应小丁","檐等部位",
}
# 合法单位词典（v2.1 §2.2）
UNIT_DICT = {
    # 长度
    "mm","cm","m","km",
    # 面积
    "mm²","cm²","m²","㎡","km²",
    # 体积
    "m³","cm³","L","mL",
    # 时间
    "s","min","h","d","a","ms",
    # 质量
    "kg","g","t",
    # 力
    "N","kN",
    # 压强/应力（v2.1 增补：消防/结构常用）
    "Pa","kPa","MPa","GPa","N/mm²",
    # 电流
    "mA","A","kA","μA","uA",
    # 电压
    "mV","V","kV",
    # 频率
    "Hz","kHz","MHz",
    # 声学
    "dB","dBA","dBc",
    # 温度
    "℃","℉","K",
    # 角度
    "°","rad",
    # 其他常用
    "Ω","kΩ","MΩ","%","ppm","倍","次","W","kW","kW·h","kWh",
    # 面密度（v2.1 增补：装修/防水常用）
    "g/m²","kg/m²","mg/m²","g/㎡",
    # 体积密度
    "kg/m³","g/cm³",
    # 热工：导热系数/传热系数
    "W/(m·K)","W/(m²·K)","W/m²",
    # 计数单位（v2.1 增补：座位数/厅数/门数/设备台数等离散量）
    "个","座","处","台","套","人","件","只","组","层","间","樘","扇","盏",
}
# 全文强制规范判定：code 以 GB 55 开头 + 在注册表标记 all_mandatory
def is_all_mandatory(code: str) -> bool:
    if code.startswith("GB 55"):
        return True
    return False

EX_PREFIX = re.compile(r'^(除.+外|不适用于.+)')

report = {"started": datetime.now().isoformat(), "files": [], "summary": {}}
total_v = 0

for p in sorted(glob.glob(os.path.join(V21_DIR, "*.yaml"))):
    if os.path.basename(p).startswith("SCHEMA_"):
        continue
    with open(p, encoding="utf-8") as f:
        d = yaml.safe_load(f)
    code = (d.get("standard") or {}).get("code") or os.path.basename(p)
    file_rep = {"file": os.path.basename(p), "code": code, "violations": []}
    std = d.get("standard") or {}
    cl = d.get("clauses") or []

    # META
    if not std.get("schema_version"):
        file_rep["violations"].append({"rule":"META","msg":"standard.schema_version 缺失"})
    if not std.get("last_reviewed_date"):
        file_rep["violations"].append({"rule":"META","msg":"standard.last_reviewed_date 缺失"})

    all_mand = is_all_mandatory(code)

    for c in cl:
        cno = c.get("clause_no")
        # TEXT
        text = c.get("text") or ""
        if re.search(r"[<>《》()（）]$", text) and len(text) < 15:
            file_rep["violations"].append({"rule":"TEXT_TRUNC","clause":cno,
                                           "text":text[:60]})
        if re.search(r"小丁|台于$", text):
            file_rep["violations"].append({"rule":"TEXT_OCR_TYPO","clause":cno,
                                           "text":text[:80]})

        # PARAM_NAME / PARAM_UNIT
        for p_ in c.get("parameters") or []:
            n = (p_ or {}).get("name") or ""
            if n in NAME_BLACKLIST:
                file_rep["violations"].append({"rule":"PARAM_NAME_BLACKLIST",
                                               "clause":cno,"name":n})
            u = (p_ or {}).get("unit")
            if u and u not in UNIT_DICT:
                file_rep["violations"].append({"rule":"PARAM_UNIT_UNKNOWN",
                                               "clause":cno,"name":n,"unit":u})

        # EXCLUSION
        app = c.get("applicability") or {}
        for ex in app.get("exceptions") or []:
            if ex and EX_PREFIX.match(str(ex)):
                file_rep["violations"].append({"rule":"EXCLUSION_STYLE",
                                               "clause":cno,"value":str(ex)[:60]})

        # MANDATORY
        if all_mand and not (c.get("constraint") or {}).get("is_mandatory_clause"):
            # 豁免：_kind='commentary' 的条文说明不视作强条（详见 _v21_backlog.md）
            # 豁免：_kind='ocr_noise' 的 OCR 垃圾待回源重录（详见 _v21_backlog.md）
            kind = c.get("_kind") or ""
            if kind not in ("commentary", "ocr_noise"):
                file_rep["violations"].append({"rule":"MANDATORY_FALSE",
                                               "clause":cno,
                                               "msg":"全文强制规范下该条 is_mandatory_clause=false",
                                               "kind":kind})

    # ---- executable_rules：参数自动镜像，曾长期未纳入审计，形成隐性债务 ----
    for r in (d.get("executable_rules") or []):
        t = r.get("then") or {}
        src = (r.get("source_clause") or "").split("#")[-1]
        n = t.get("parameter") or ""
        u = t.get("unit")
        if n in NAME_BLACKLIST:
            file_rep["violations"].append({"rule":"RULE_PARAM_NAME",
                                           "clause":src,"name":n,
                                           "rule_id":r.get("rule_id")})
        if u and u not in UNIT_DICT:
            file_rep["violations"].append({"rule":"RULE_PARAM_UNIT",
                                           "clause":src,"name":n,"unit":u,
                                           "rule_id":r.get("rule_id")})

    file_rep["violation_count"] = len(file_rep["violations"])
    total_v += file_rep["violation_count"]
    report["files"].append(file_rep)

report["finished"] = datetime.now().isoformat()
report["summary"] = {
    "files_scanned": len(report["files"]),
    "total_violations": total_v,
    "by_rule": dict(Counter(v["rule"] for f in report["files"] for v in f["violations"])),
}

with open(REPORT, "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)

# 终端输出汇总
print(f"files scanned : {report['summary']['files_scanned']}")
print(f"total violations: {total_v}")
print(f"by rule:")
for k,v in report['summary']['by_rule'].items():
    print(f"  {k:25s} {v}")
print(f"report: {REPORT}")
sys.exit(1 if total_v > 0 else 0)