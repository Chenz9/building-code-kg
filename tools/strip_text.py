# -*- coding: utf-8 -*-
"""
合规阀：剔除 YAML 中的标准「条文原文」字段，仅保留结构化元数据。

用法:
    python strip_text.py <输入.yaml> <输出.yaml>

清空字段：
    clauses[].text
    tables[].content
    executable_rules[].source_text
    references[].original_text

保留：条文编号 / 章节 / 废止状态 / 适用范围·条件·例外 / 参数阈值 /
     表格结构 headers+rows / 引用编号 / IFC 映射 / 可执行规则。

依赖: pip install pyyaml
"""
import sys
import yaml

TEXT_FIELDS = {
    'clauses': ['text'],
}


def strip(data):
    n = 0
    for c in (data.get('clauses') or []):
        if c.get('text'):
            c['text'] = None
            n += 1
        for t in (c.get('tables') or []):
            if isinstance(t, dict) and t.get('content'):
                t['content'] = None
                n += 1
        for r in (c.get('references') or []):
            if isinstance(r, dict) and r.get('original_text'):
                r['original_text'] = None
                n += 1
    for r in (data.get('executable_rules') or []):
        if r.get('source_text'):
            r['source_text'] = None
            n += 1
    return n


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    src, dst = sys.argv[1], sys.argv[2]
    data = yaml.safe_load(open(src, encoding='utf-8'))
    n = strip(data)
    # sort_keys=False 保持字段顺序，allow_unicode 保证中文可读
    yaml.safe_dump(data, open(dst, 'w', encoding='utf-8'),
                   allow_unicode=True, sort_keys=False, width=1000)
    print(f'已剔除 {n} 处原文 -> {dst}')


if __name__ == '__main__':
    main()
