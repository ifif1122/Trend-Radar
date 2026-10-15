import html
import json
import re
from pathlib import Path

from .core import CATEGORIES, KINDS, now, ranking, sources
from .dashboard import data as dashboard_data, feedback_script, fragment
from .storage import atomic_text, write_json
from .content import brief
from .content_report import page as content_page
from .demand_ranking import build as demand_ranking, fragment as demand_fragment


def render(db, output, mode, errors=()):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    rows = sources(db)
    ranks = ranking(rows)
    versions = [dict(r) for r in db.execute('SELECT * FROM versions ORDER BY id DESC')]
    checks = [dict(r) for r in db.execute('SELECT * FROM checks ORDER BY id DESC')]
    payload = dict(name='Trend Radar', mode=mode, generated_at=now(), sources=rows, ranking=ranks, versions=versions, checks=checks, errors=list(errors))
    payload.update(dashboard_data(db, rows))
    e = lambda x: html.escape(str(x), quote=True)
    options = lambda values: ''.join(f'<option>{e(v)}</option>' for v in values)
    candidates = ''.join(f'<article id="candidate-{e(a["id"])}"><h3>{e(a["title"])}</h3><p>順位 {i+1} · 検証済み独立ソース群 {a["score"]}件</p><p>件数順の仮説ランキングです。市場規模・購入意思を推定する点数ではありません。</p><a href="#evidence" class="candidate-link" data-analysis="{e(a["id"])}">この候補の根拠を見る</a></article>' for i, a in enumerate(ranks))
    demand = demand_ranking(rows, payload.get('ai_analysis'), output / 'market_analysis.json')
    payload['demand_ranking'] = demand
    candidates = demand_fragment(demand, rows) + '<details><summary>従来の情報源別集計（検証済み根拠の件数順）</summary>' + candidates + '</details>'
    demand_backs = {}
    for idea in demand['candidates']:
        for ref in idea['source_ids']:
            demand_backs.setdefault(ref, []).append(f'<a href="#{e(idea["id"])}">{e(idea["title"])}へ戻る</a>')
    cards = []
    groups = {}
    for s in rows:
        groups.setdefault(s['group_id'], []).append(s)
    for members in groups.values():
        entries = []
        for s in members:
            v = s['verification']
            entries.append(f'''<section id="source-{e(s['id'])}"><h3><a href="{e(s['url'])}" target="_blank" rel="noopener noreferrer">{e(s['title'])}</a></h3>
<p class="badge">{e(s['kind'])} · {e(s['media'])} · {e(' / '.join(s['categories']))}</p>
<dl><dt>投稿日時</dt><dd>{e(s.get('published_at') or '不明')}</dd><dt>取得日時</dt><dd>{e(s['fetched_at'])}</dd><dt>初回取得</dt><dd>{e(s['first_seen'])}</dd><dt>URL</dt><dd><a href="{e(s['url'])}" target="_blank" rel="noopener noreferrer">{e(s['url'])}</a></dd><dt>概要</dt><dd>{e(s['summary'])}</dd><dt>関連する分析・分類理由</dt><dd>{e(s['reason'])} <a class="back" href="#candidate-{e(s['analysis_id'])}">{e(s['analysis_title'])}へ戻る</a></dd><dt>信頼性</dt><dd>{e(s.get('reliability', '未評価'))}</dd><dt>確認状況</dt><dd>{e(v['status'])} / HTTP {e(v['http'])} / {e(v['checked_at'])}。内容の真偽・再現性：{'確認済み' if s.get('content_verified') else '未確認'}。分類：{e(s.get('classification', '人手入力'))}</dd><dt>転送先</dt><dd>{e(v.get('final_url') or 'なし')}</dd><dt>関連する具体的需要候補</dt><dd>{' / '.join(demand_backs.get(s['id'], [])) or '個別分析なし'}</dd><dt>履歴</dt><dd>メタデータ {s['versions']}版（取得・URL確認履歴はreport.jsonとSQLiteに保持）</dd></dl></section>''')
        data = dict(analyses=sorted({s['analysis_id'] for s in members}), kinds=sorted({s['kind'] for s in members}), media=sorted({s['media'] for s in members}), categories=sorted({c for s in members for c in s['categories']}), dates=[(s.get('published_at') or '')[:10] for s in members], first_seen=[s['first_seen'][:10] for s in members], search=' '.join(str(s.get(k, '')) for s in members for k in ('title', 'summary', 'media', 'url', 'analysis_title')))
        data['relevance'] = max((a['score'] for a in ranks if a['id'] in data['analyses']), default=0)
        cards.append(f'<article class="source" data-filter="{e(json.dumps(data, ensure_ascii=False))}"><p>同一・類似ソース群：{len(members)}件（ランキングでは1件）</p>{"".join(entries)}</article>')
    error_html = ''.join(f'<li>{e(x)}</li>' for x in errors)
    media_control = f'<label>メディア<select id="media"><option value="">すべて</option>{options(sorted({s["media"] for s in rows}))}</select></label>'
    page = '''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Trend Radar — 根拠レポート</title>
<style>body{font:16px/1.65 system-ui,sans-serif;background:#f3f6fa;color:#18283b;margin:0}header,main{max-width:1100px;margin:auto;padding:24px}header{background:#152c46;color:white;max-width:none}header>div{max-width:1100px;margin:auto}nav{display:flex;gap:10px;flex-wrap:wrap}a{color:#1460a6;overflow-wrap:anywhere}header a{color:#bfe1ff}article{background:white;border:1px solid #d7e0ea;border-radius:12px;padding:20px;margin:16px 0}h1,h2,h3{line-height:1.3}h3{font-size:18px}label{display:inline-flex;flex-direction:column;margin:5px}input,select,button{font:inherit;padding:9px;border:1px solid #8297ae;border-radius:5px}button{cursor:pointer}dl{display:grid;grid-template-columns:140px 1fr;gap:8px}dt{font-weight:bold}dd{margin:0;overflow-wrap:anywhere}.badge{color:#4a6075}section+section{border-top:1px solid #ccc;margin-top:18px}article[hidden]{display:none}@media(max-width:600px){dl{grid-template-columns:1fr}header,main{padding:16px}}</style></head><body>
<header><div><h1>Trend Radar</h1><p>根拠をたどれるトレンド・需要候補レポート</p><p>MODE_PLACEHOLDER · TIME_PLACEHOLDER</p><nav><a href="#ranking">需要候補ランキング</a><a href="#evidence">根拠ソース一覧</a><a href="#history">収集履歴</a></nav></div></header><main>
<p>公開ページへのアクセス確認と、投稿内容の事実確認は別です。個人投稿は意見・自己申告として扱います。短い概要とメタデータのみ保存し、記事本文・投稿全文は複製しません。</p>
<h2 id="ranking">需要候補ランキング</h2>CANDIDATES_PLACEHOLDER
<h2 id="evidence" tabindex="-1">根拠ソース一覧</h2><nav aria-label="根拠画面"><button data-view="all">根拠ソース一覧</button><button data-view="trend">トレンド別の根拠一覧</button><button data-view="complaint">利用者の不満一覧</button><button data-view="paid">有料需要を裏付ける情報一覧</button><button data-view="new">新着記事・新着投稿一覧</button></nav>
<p id="view-name">根拠ソース一覧</p><div><label>投稿開始日（不明日付は日付指定時に除外）<input id="from" type="date"></label><label>投稿終了日<input id="to" type="date"></label><label>情報源<select id="kind"><option value="">すべて</option>KINDS_PLACEHOLDER</select></label><label>カテゴリー<select id="category"><option value="">すべて</option>CATEGORIES_PLACEHOLDER</select></label><label>トレンド・需要候補<select id="analysis"><option value="">すべて</option>ANALYSES_PLACEHOLDER</select></label><label>キーワード<input id="keyword" type="search" placeholder="タイトル・概要・メディア・URL"></label><button id="reset">絞り込み解除</button></div>
<p id="count" role="status" aria-live="polite"></p>SOURCES_PLACEHOLDER
<h2 id="history">収集履歴</h2><p>HISTORY_PLACEHOLDER</p><p>全メタデータ版・URL確認履歴：<a href="report.json">report.json</a>。元ページが削除・非公開になっても既存記録は削除せず、最新状況を表示しランキングから除外します。</p><ul>ERRORS_PLACEHOLDER</ul>
<script>
const $=id=>document.getElementById(id);let view='all';const cards=[...document.querySelectorAll('.source')];
function filter(){let count=0;for(const card of cards){const d=JSON.parse(card.dataset.filter);const dates=d.dates.filter(Boolean);let show=(!$('kind').value||d.kinds.includes($('kind').value))&&(!$('category').value||d.categories.includes($('category').value))&&(!$('analysis').value||d.analyses.includes($('analysis').value))&&d.search.toLowerCase().includes($('keyword').value.toLowerCase());show=show&&(!($('from').value||$('to').value)||dates.some(x=>(!$('from').value||x>=$('from').value)&&(!$('to').value||x<=$('to').value)));if(view==='complaint')show=show&&d.categories.includes('実際の不満');if(view==='paid')show=show&&d.categories.includes('有料需要の証拠');if(view==='new')show=show&&d.first_seen.includes('TODAY_PLACEHOLDER');card.hidden=!show;if(show)count++;}const ordered=[...cards].sort((a,b)=>{let da=JSON.parse(a.dataset.filter),db=JSON.parse(b.dataset.filter);return view==='trend'?da.analyses.join().localeCompare(db.analyses.join()):view==='new'?db.first_seen.join().localeCompare(da.first_seen.join()):0;});for(const c of ordered)$('history').before(c);$('count').textContent=count+' ソース群を表示'+(count===0?' — 該当する検証済み根拠はありません。':'');}
for(const id of ['from','to','kind','category','analysis','keyword'])$(id).addEventListener('input',filter);
function reset(){for(const id of ['from','to','kind','category','analysis','keyword'])$(id).value='';view='all';$('view-name').textContent='根拠ソース一覧';filter();}
$('reset').onclick=reset;for(const b of document.querySelectorAll('[data-view]'))b.onclick=()=>{view=b.dataset.view;$('view-name').textContent=b.textContent;filter();};for(const a of document.querySelectorAll('.candidate-link'))a.onclick=()=>{reset();$('analysis').value=a.dataset.analysis;view='trend';$('view-name').textContent='トレンド別の根拠一覧';filter();};filter();
</script></main></body></html>'''
    page = page.replace('<label>カテゴリー', media_control + '<label>カテゴリー')
    page = page.replace("['from','to','kind','category','analysis','keyword']", "['from','to','kind','media','category','analysis','keyword']")
    page = page.replace("let show=", "let show=(!$('media').value||d.media.includes($('media').value))&&")
    page = page.replace('<button id="reset">', '<label>表示順<select id="sort-order"><option value="date">投稿日順</option><option value="relevance">関連度順</option></select></label><button id="reset">')
    page = page.replace("'media','category','analysis','keyword'", "'media','category','analysis','keyword','sort-order'")
    page = page.replace("return view==='trend'?", "return $('sort-order').value==='relevance'?relevance(db)-relevance(da):view==='trend'?")
    page = page.replace("function filter(){", "function relevance(d){const q=$('keyword').value.toLowerCase().trim();return(q?d.search.toLowerCase().split(q).length-1:0)*10+(d.relevance||0);}function filter(){")
    page = page.replace(":0;});for(const c", ":db.dates.filter(Boolean).sort().at(-1)?.localeCompare(da.dates.filter(Boolean).sort().at(-1)||'')||0;});for(const c")
    replacements = dict(MODE=mode, TIME=payload['generated_at'], CANDIDATES=candidates or '<p>検証済み根拠なし</p>', KINDS=options(KINDS), CATEGORIES=options(CATEGORIES), ANALYSES=''.join(f'<option value="{e(a["id"])}">{e(a["title"])}</option>' for a in ranks), SOURCES=''.join(cards), HISTORY=f'保存ソース {len(rows)}件 / メタデータ履歴 {len(versions)}版 / URL確認 {len(checks)}回', ERRORS=error_html, TODAY=payload['generated_at'][:10])
    page = re.sub(r'([A-Z]+)_PLACEHOLDER', lambda m: e(replacements[m[1]]) if m[1] in ('MODE', 'TIME') else replacements[m[1]], page)
    page = page.replace('filter();\n</script>', "filter();for(const a of document.querySelectorAll('.analysis-source-link'))a.onclick=()=>reset();\n</script>")
    page = page.replace('<a href="#history">収集履歴</a>', '<a href="#history">収集履歴</a><a href="#research">社会需要</a><a href="#quality">品質</a><a href="#proposals">改善提案</a><a href="#effects">効果検証</a><a href="#feedback">評価</a>')
    page = page.replace('</main></body>', fragment(payload) + feedback_script() + '</main></body>')
    write_json(output / 'report.json', payload)
    write_json(output / 'analysis.json', payload['content_analysis'])
    analysis_page = content_page(payload['content_analysis'], payload['ai_analysis'], payload['ai_input_state'])
    if (output / 'market_analysis.html').is_file():
        review_link = '<aside><p><a href="market_analysis.html">具体的な機能需要・収益化の手動再分析を開く</a>（分析日時・対象範囲はリンク先を確認）</p></aside>'
        page = page.replace('<main>', '<main>'+review_link, 1)
        analysis_page = analysis_page.replace('<body>', '<body>'+review_link, 1)
    atomic_text(output / 'analysis.html', analysis_page)
    atomic_text(output / 'analysis_brief.md', brief(payload['content_analysis']))
    atomic_text(output / 'report.html', page)
    return payload
