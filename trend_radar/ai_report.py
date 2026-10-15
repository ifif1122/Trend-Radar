import html


def fragment(report, state=None):
    e = lambda value: html.escape(str(value), quote=True)
    if not report:
        return '<section id="ai-analysis"><h2>AIによる需要分析</h2><p>AI分析は未実行です。PC側のChatGPTログイン済みCodexで実行した結果を表示します。</p></section>'
    result = report['result']
    def refs(ids):
        return '<ul>' + ''.join(f'<li><a href="{e(report["evidence"][ref]["url"])}" target="_blank" rel="noopener noreferrer">{e(report["evidence"][ref]["title"])}</a></li>' for ref in ids) + '</ul>'
    observations = ''.join('<article><p>'+e(item['text'])+'</p>'+refs(item['source_ids'])+'</article>' for item in result['observations'])
    opportunities = ''.join(f'<article><h3>{e(item["title"])}</h3><dl><dt>利用者の仮説</dt><dd>{e(item["user"])}</dd><dt>課題の仮説</dt><dd>{e(item["problem"])}</dd><dt>解決案</dt><dd>{e(item["solution"])}</dd><dt>検証方法</dt><dd>{e(item["validation"])}</dd></dl>{refs(item["source_ids"])}</article>' for item in result['opportunities'])
    missing = ''.join('<li>'+e(item)+'</li>' for item in result['unknowns'])
    state_text = '今回の入力に対応' if state == 'current' else '以前の分析結果です。入力変更後の分析は未実行・上限待ちの場合があります。'
    return f'<section id="ai-analysis"><h2>AIによる需要分析</h2><p>{e(report["provider"])} / 実行日時 {e(report["at"])}</p><p>{e(state_text)} 対象{report["source_count"]}件 / 入力上限による未分析{report["omitted"]}件</p><p>{e(report["note"])}</p><p>{e(result["summary"])}</p><h3>AIが読み取った観測・解釈</h3>{observations}<h3>検証する需要・解決案の仮説</h3>{opportunities}<h3>不足する情報</h3><ul>{missing}</ul></section>'
