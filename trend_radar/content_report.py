import html

def e(value):
    return html.escape(str(value), quote=True)


def fragment(analysis):
    counts = analysis['counts']
    cards = []
    for topic in analysis['topics']:
        evidence = []
        for s in topic['evidence']:
            signals = ' / '.join(s['pains']) or '具体的な不満表現なし'
            if s['request']:
                signals += ' / 機能要望表現あり'
            if s['payment_expression']:
                signals += ' / 支払意思の表現あり（購入実績は未確認）'
            evidence.append(f'<li><a href="{e(s["url"])}" target="_blank" rel="noopener noreferrer">{e(s["title"])}</a><p>{e(signals)} · {e(s["scope"])} · <a href="report.html#source-{e(s["id"])}">根拠の確認状況</a></p></li>')
        basis = topic['score_basis']
        cards.append(f'''<article id="topic-{e(topic['id'])}"><h3>{e(topic['title'])}</h3><p>{e(topic['classification'])} · 調査優先度 {topic['score']}/100</p><dl>
<dt>想定する利用者</dt><dd>{e(topic['audience'])}（分野からの仮説）</dd>
<dt>需要仮説</dt><dd>{e(topic['need_hypothesis'])}</dd><dt>小さく試す解決案</dt><dd>{e(topic['prototype'])}</dd><dt>次に検証すること</dt><dd>{e(topic['next_action'])}</dd>
<dt>裏付け</dt><dd>ソース群{topic['independent_groups']} / 配信ドメイン{topic['source_domains']} / 不満{topic['complaint_groups']}群 / 要望{topic['request_groups']}群 / 支払意思の表現{topic['payment_expression_groups']}群</dd>
<dt>変化</dt><dd>直近7日{topic['new_7d']}群、前7日{topic['previous_7d']}群、差{topic['change']:+}。{e(topic['trend_status'])}</dd><dt>確かさ</dt><dd>{e(topic['confidence'])}</dd>
<dt>採点根拠</dt><dd>不満 {basis['pain']}/40、要望 {basis['requests']}/20、配信元 {basis['diversity']}/20、直近収集 {basis['recent']}/10、支払意思表現 {basis['payment_expression']}/10。市場規模や購入確率の点数ではありません。</dd></dl><details open><summary>根拠の元ページと検出した表現の種類</summary><ul>{''.join(evidence)}</ul></details></article>''')
    limitations = ''.join('<li>'+e(limit)+'</li>' for limit in analysis['limits'])
    return f'''<section id="content-analysis"><h2>収集内容の分析</h2><p>{e(analysis['method'])}</p><p>対象 {counts['verified_sources']}件 / API本文・RSS概要の特徴あり {counts['content_sources']}件 / 題名のみ {counts['title_only_sources']}件 / 分野未分類 {counts['unclassified_sources']}件</p><p><a href="analysis.html">内容分析の専用画面</a> · <a href="analysis.json">分析JSON</a> · <a href="analysis_brief.md">AI追加分析用ブリーフ</a></p><details><summary>分析の範囲と限界</summary><ul>{limitations}</ul></details>{''.join(cards) or '<p>分析できる検証済み情報がありません。</p>'}</section>'''


def page(analysis, ai=None, ai_state=None):
    from .ai_report import fragment as ai_fragment
    return '<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Trend Radar 内容分析</title><style>body{font:16px/1.7 system-ui;margin:auto;max-width:1100px;padding:20px;background:#f3f6fa;color:#18283b}article{background:white;padding:20px;margin:20px 0;border:1px solid #d7e0ea;border-radius:12px}a{color:#1460a6;overflow-wrap:anywhere}dl{display:grid;grid-template-columns:150px 1fr;gap:10px}dd{margin:0}button{font:inherit}h3{line-height:1.3}@media(max-width:600px){dl{grid-template-columns:1fr}body{padding:12px}}</style></head><body><h1>Trend Radar 分析レポート</h1><a href="report.html">ダッシュボードへ戻る</a>'+ai_fragment(ai, ai_state)+fragment(analysis)+'</body></html>'
