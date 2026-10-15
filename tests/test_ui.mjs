// Run with Node: node tests/test_ui.mjs [reports/report.html]
// This tests event handlers against a small DOM fixture, not browser rendering.
import fs from 'node:fs/promises';
import vm from 'node:vm';
import assert from 'node:assert/strict';

export async function testUI(path) {
  const page = await fs.readFile(path, 'utf8');
  const decode = s => s.replaceAll('&quot;', '"').replaceAll('&#x27;', "'").replaceAll('&lt;', '<').replaceAll('&gt;', '>').replaceAll('&amp;', '&');
  const cards = [...page.matchAll(/class="source" data-filter="([^"]+)"/g)].map(m => ({dataset: {filter: decode(m[1])}, hidden: false}));
  const elements = Object.fromEntries(['from', 'to', 'kind', 'media', 'category', 'analysis', 'keyword', 'sort-order', 'history', 'view-name', 'count', 'reset'].map(id => [id, {value: '', textContent: '', addEventListener() {}, before() {}}]));
  const ordered = [];
  elements.history.before = card => {const i = ordered.indexOf(card); if(i >= 0) ordered.splice(i, 1); ordered.push(card);};
  const buttons = ['all', 'trend', 'complaint', 'paid', 'new'].map(view => ({dataset: {view}, textContent: view}));
  const data = cards.map(c => JSON.parse(c.dataset.filter));
  const analysis = data[0]?.analyses[0];
  const links = analysis ? [{dataset: {analysis}}] : [];
  const document = {getElementById: id => elements[id], querySelectorAll: s => s === '.source' ? cards : s === '[data-view]' ? buttons : s === '.candidate-link' ? links : []};
  const context = vm.createContext({document});
  vm.runInContext(page.match(/<script>([\s\S]*?)<\/script>/)[1], context);
  const visible = () => cards.filter(c => !c.hidden).length;
  const reset = () => elements.reset.onclick();
  const filter = () => vm.runInContext('filter()', context);
  assert.equal(visible(), cards.length);
  elements['sort-order'].value = 'relevance'; filter();
  if(cards.length) assert.equal(JSON.parse(ordered[0].dataset.filter).relevance, Math.max(...data.map(d => d.relevance || 0)));
  buttons[3].onclick(); assert.equal(visible(), data.filter(d => d.categories.includes('有料需要の証拠')).length);
  reset(); buttons[2].onclick(); assert.equal(visible(), data.filter(d => d.categories.includes('実際の不満')).length);
  if (analysis) {
    reset(); links[0].onclick(); assert.equal(visible(), data.filter(d => d.analyses.includes(analysis)).length);
    reset(); elements.media.value = data[0].media[0]; filter(); assert.equal(visible(), data.filter(d => d.media.includes(elements.media.value)).length);
  }
  reset(); elements.kind.value = '公式発表'; filter(); assert.equal(visible(), data.filter(d => d.kinds.includes('公式発表')).length);
  reset(); elements.keyword.value = 'NO_SUCH_KEYWORD_123'; filter(); assert.equal(visible(), 0);
  reset(); elements.from.value = '2099-01-01'; filter(); assert.equal(visible(), 0);
  reset(); buttons[4].onclick(); assert.equal(visible(), data.filter(d => d.first_seen.includes(page.match(/d.first_seen.includes\('([^']+)'\)/)[1])).length);
  const external = [...page.matchAll(/<a\s+[^>]*href="https:[^"]+"[^>]*>/g)].map(m => m[0]);
  assert(external.every(a => a.includes('target="_blank"') && a.includes('rel="noopener noreferrer"')));
  return {cards: cards.length, externalLinks: external.length, result: 'PASS'};
}

if (typeof process !== 'undefined' && process.argv[1]?.endsWith('test_ui.mjs')) console.log(await testUI(process.argv[2] || 'reports/report.html'));
