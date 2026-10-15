"""Evidence-linked demand priorities, separate from source-volume counts."""
import html
import json


def build(rows, ai, review_path):
    verified = {s['url']: s for s in rows if s.get('verification', {}).get('status') == '確認済み'}
    by_id = {s['id']: s for s in verified.values()}
    ideas = []
    origin, at = '未分析', ''
    try:
        if review_path.is_file() and review_path.stat().st_size <= 500_000:
            review = json.loads(review_path.read_text(encoding='utf-8'))
            for item in review.get('decisions', [])[:20]:
                refs = [verified[u] for u in item.get('sources', []) if u in verified]
                if refs:
                    ideas.append(dict(title=item['title'], priority=item['priority'], features=item['features'], buyer=item['buyer'], value=item['value'], price=item['price'], proof=item['proof'], risks=item['risks'], validation=item['validation'], alternatives=item['alternatives'], source_ids=list(dict.fromkeys(s['id'] for s in refs))))
            if ideas:
                origin, at = '手動再分析の検証優先順位', review.get('generated_at', review.get('date', '不明'))
    except (ValueError, TypeError, KeyError, OSError):
        ideas = []
    if not ideas and ai:
        for item in ai['result']['opportunities']:
            refs = [ref for ref in item['source_ids'] if ref in by_id]
            if refs:
                ideas.append(dict(title=item['title'], priority='AIによる提案順（収益性の順位は未評価）', features=[item['solution']], buyer=item['user'], value=item['problem'], price='独立した価格評価は未実施。検証方法を参照。', proof='購入実績・支払意思は別途確認が必要。', risks='事業性は未検証。', validation=item['validation'], alternatives='検証方法を参照。', source_ids=list(dict.fromkeys(refs))))
        origin, at = 'AI分析の提案順', ai['at']
    for index, idea in enumerate(ideas, 1):
        idea.update(id='demand-'+str(index), rank=index)
    return dict(origin=origin, analyzed_at=at, candidates=ideas)


def fragment(result, rows):
    e = lambda value: html.escape(str(value), quote=True)
    if not result['candidates']:
        return '<p>具体的な機能・収益化の分析は未実施です。以下は情報源件数による集計です。</p>'
    by_id = {s['id']: s for s in rows}
    cards = []
    labels = dict(buyer='利用者・支払主体の仮説', value='支払う理由・解決する課題', price='価格の検証案', proof='有料需要の証拠', alternatives='既存手段・競合', risks='収益化のリスク', validation='次に検証すること')
    for item in result['candidates']:
        refs = ''.join(f'<li><a class="analysis-source-link" href="#source-{e(ref)}">{e(by_id[ref]["title"])}</a> · <a href="{e(by_id[ref]["url"])}" target="_blank" rel="noopener noreferrer">元投稿を開く</a></li>' for ref in item['source_ids'])
        features = ''.join('<li>'+e(f)+'</li>' for f in item['features'])
        fields = ''.join('<dt>'+e(label)+'</dt><dd>'+e(item[key])+'</dd>' for key, label in labels.items())
        cards.append(f'<article id="{e(item["id"])}"><h3>{item["rank"]}位：{e(item["title"])}</h3><p>{e(item["priority"])}</p><h4>具体的に求められる機能・提案</h4><ul>{features}</ul><dl>{fields}</dl><h4>関連する根拠</h4><ul>{refs}</ul></article>')
    return '<p>'+e(result['origin'])+' / 分析日時 '+e(result['analyzed_at'])+'。過去の分析を保持しており、今回の収集で再評価した順位とは限りません。検証済み根拠が残る候補のみ表示します。収益額・購入確率の順位ではありません。価格案は仮説です。</p>'+''.join(cards)
