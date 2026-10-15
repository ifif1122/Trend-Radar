import fs from 'node:fs/promises';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import {Blob} from 'node:buffer';

export async function testFeedback(path) {
  const script = await fs.readFile(path, 'utf8');
  const handlers = {};
  const storage = new Map();
  let downloaded = false;
  let blob;
  const status = {textContent: ''};
  const context = vm.createContext({
    Date, Blob,
    URL: {createObjectURL(b) {blob = b; return 'blob:local-test';}, revokeObjectURL() {}},
    localStorage: {getItem: k => storage.get(k), setItem: (k, v) => storage.set(k, v)},
    document: {
      getElementById: id => id === 'feedback-status' ? status : {addEventListener: (e, fn) => handlers.export = fn},
      querySelectorAll: () => [{dataset: {analysis: 'editor', action: '役立った'}, addEventListener: (e, fn) => handlers.feedback = fn}],
      createElement: () => ({click() {downloaded = true;}})
    }
  });
  vm.runInContext(script, context);
  handlers.feedback();
  const saved = JSON.parse(storage.get('trend-radar-feedback-v1'));
  assert.equal(saved.version, 1);
  assert.equal(saved.items[0].action, '役立った');
  assert.equal(saved.items[0].analysis_id, 'editor');
  handlers.export();
  assert(downloaded);
  assert.deepEqual(JSON.parse(await blob.text()), saved);
  storage.set('trend-radar-feedback-v1', 'corrupt');
  handlers.feedback();
  assert(status.textContent.includes('保存できません'));
  assert.equal(storage.get('trend-radar-feedback-v1'), 'corrupt');
  return {feedbackSave: 'PASS', JSONExport: 'PASS', corruptStorage: 'PASS'};
}
if (typeof process !== 'undefined' && process.argv[1]?.endsWith('test_feedback.mjs')) console.log(await testFeedback(process.argv[2] || 'trend_radar/feedback.js'));
