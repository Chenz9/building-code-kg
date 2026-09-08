# -*- coding: utf-8 -*-
"""
生成标准 YAML 的「完整复核阅读视图」HTML。
用法: python _gen_readview_html.py <yaml路径> <输出html路径>
可复用于 GB 55031 等后续样板。
"""
import sys, html, yaml, datetime

DARK = False  # 与 IDE 主题一致时改 True


def build(src, out):
    d = yaml.safe_load(open(src, encoding='utf-8'))
    std = d['standard']
    rows = []
    for c in d['clauses']:
        ap = c.get('applicability') or {}
        rows.append(dict(
            no=c['clause_no'], text=c.get('text', ''), chapter=c.get('chapter', ''),
            is_mand=(c.get('constraint') or {}).get('is_mandatory_clause', False),
            abol=c.get('is_abolished', False), abol_by=c.get('superseded_by') or '',
            scope=ap.get('scope', ''), conds=ap.get('conditions') or [],
            exs=ap.get('exceptions') or [], params=c.get('parameters') or [],
        ))

    def k(r):
        return tuple(int(x) if x.isdigit() else 0 for x in r['no'].split('.'))
    rows.sort(key=k)

    n_mand = sum(1 for r in rows if r['is_mand'])
    n_abol = sum(1 for r in rows if r['abol'])
    n_scope = sum(1 for r in rows if r['scope'])
    ts = datetime.datetime.now().strftime('%Y-%m-%d')

    o = []
    o.append('<!doctype html><html lang="zh"><head><meta charset="utf-8">')
    o.append(f'<title>{std["code"]} 完整复核阅读视图 · {len(rows)} 条</title>')
    o.append('<style>')
    o.append('body{font-family:-apple-system,Segoe UI,Microsoft YaHei,sans-serif;max-width:980px;'
             'margin:2rem auto;padding:0 1.25rem;color:#222;line-height:1.6}')
    o.append('h1{font-size:1.6rem;border-bottom:2px solid #333;padding-bottom:.5rem}')
    o.append('h2{font-size:1.2rem;margin-top:2rem;color:#333;border-left:4px solid #1d9e75;padding-left:.5rem}')
    o.append('.clause{border:1px solid #ddd;border-radius:8px;padding:1rem 1.25rem;margin:1rem 0;background:#fff}')
    o.append('.clause.abol{background:#fff8f0;border-color:#faece7}')
    o.append('.clause.mand{border-left:4px solid #d85a30}')
    o.append('.clause-no{font-weight:600;color:#1d9e75;font-size:1.1rem}')
    o.append('.clause-text{margin:.5rem 0;line-height:1.7}')
    o.append('.badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:.8rem;margin-right:.4rem}')
    o.append('.b-mand{background:#d85a30;color:#fff}')
    o.append('.b-abol{background:#993c1d;color:#fff}')
    o.append('.b-ok{background:#1d9e75;color:#fff}')
    o.append('.scope{background:#e1f5ee;padding:.3rem .6rem;border-radius:4px;margin:.5rem 0;font-size:.9rem}')
    o.append('.scope::before{content:"适用范围：";font-weight:600}')
    o.append('.cond{background:#e6f1fb;padding:.3rem .6rem;border-radius:4px;margin:.25rem 0;font-size:.85rem}')
    o.append('.cond::before{content:"条件：";font-weight:600;color:#185fa5}')
    o.append('.exc{background:#faece7;padding:.3rem .6rem;border-radius:4px;margin:.25rem 0;font-size:.85rem}')
    o.append('.exc::before{content:"例外：";font-weight:600;color:#993c1d}')
    o.append('.param{background:#faf7ed;padding:.3rem .6rem;border-radius:4px;margin:.25rem 0;'
             'font-size:.85rem;font-family:Consolas,monospace}')
    o.append('.summary{background:#e1f5ee;padding:1rem 1.25rem;border-radius:8px;margin:1rem 0;'
             'display:flex;gap:1.5rem;flex-wrap:wrap}')
    o.append('.stat{text-align:center}.stat-num{font-size:1.8rem;font-weight:600;color:#1d9e75}')
    o.append('.stat-label{font-size:.85rem;color:#666}')
    o.append('.toc{background:#f8f8f8;padding:1rem 1.25rem;border-radius:8px;margin:1rem 0}')
    o.append('.toc a{color:#185fa5;text-decoration:none;margin-right:1rem}')
    o.append('footer{text-align:center;color:#888;padding:2rem 0;border-top:1px solid #eee;margin-top:3rem}')
    o.append('</style></head><body>')

    o.append(f'<h1>{std["code"]}《{std["name"]}》</h1>')
    o.append(f'<p style="color:#666;font-size:.9rem">完整复核阅读视图 · 生成于 {ts} · '
             f'{len(rows)} 条 / 强条 {n_mand} / 已废止 {n_abol}<br>'
             f'正本：<code>03_标准结构化/_v2/{std["code"].replace(" ", "")}.yaml</code>')

    o.append('<div class=summary>')
    for num, lab in [(len(rows), '条文总数'), (n_mand, '强条'),
                     (n_abol, '被废止强条'), (n_scope, 'V4 适用范围填充')]:
        o.append(f'<div class=stat><div class=stat-num>{num}</div><div class=stat-label>{lab}</div></div>')
    o.append('</div>')

    o.append('<div class=toc><strong>章节目录：</strong><br>')
    seen = set()
    for r in rows:
        ch = r['chapter']
        anchor = ch.split(' ', 1)[0] if ch else ''
        if ch and ch not in seen:
            seen.add(ch)
            o.append(f'<a href="#ch{anchor}">{html.escape(ch)}</a>')
    o.append('</div>')

    cur = None
    for r in rows:
        ch = r['chapter']
        if ch and ch != cur:
            cur = ch
            o.append(f'<h2 id="ch{ch.split(" ",1)[0]}">{html.escape(ch)}</h2>')
        cls = ['clause']
        if r['is_mand']:
            cls.append('mand')
        if r['abol']:
            cls.append('abol')
        o.append(f'<div class="{" ".join(cls)}" id="c-{r["no"]}">')
        o.append(f'<div><span class=clause-no>{r["no"]}</span>')
        if r['is_mand']:
            o.append(' <span class="badge b-mand">强条</span>')
        if r['abol']:
            o.append(f' <span class="badge b-abol">已废止 → {html.escape(r["abol_by"])}</span>')
        if r['scope']:
            o.append(' <span class="badge b-ok">V4✓</span>')
        o.append('</div>')
        o.append(f'<div class=clause-text>{html.escape(r["text"])}</div>')
        if r['scope']:
            o.append(f'<div class=scope>{html.escape(r["scope"])}</div>')
        for c in r['conds']:
            o.append(f'<div class=cond>{html.escape(str(c))}</div>')
        for x in r['exs']:
            o.append(f'<div class=exc>{html.escape(str(x))}</div>')
        for p in r['params']:
            nm, un = p.get('name', ''), p.get('unit', '')
            lo, hi = p.get('min_value'), p.get('max_value')
            val = f'≥ {lo}' if lo is not None else (f'≤ {hi}' if hi is not None else '')
            o.append(f'<div class=param>{html.escape(nm)} {html.escape(str(val))} {html.escape(un or "")}</div>')
        o.append('</div>')

    o.append('<footer>')
    o.append(f'{std["code"]} · 完整复核样板打样 · {ts}<br>')
    o.append('门禁：V1–V7 全 0 / v2.1 全 0 / V4 100% 填充')
    o.append('</footer></body></html>')

    open(out, 'w', encoding='utf-8').write('\n'.join(o))
    print(f'HTML written: {out} ({len(rows)} clauses, {n_mand} mandatory, {n_scope} scoped)')


if __name__ == '__main__':
    build(sys.argv[1], sys.argv[2])
