(() => {
  const key = 'trend-radar-feedback-v1';
  const status = document.getElementById('feedback-status');
  const read = () => {
    const data = JSON.parse(localStorage.getItem(key) || '{"version":1,"items":[]}');
    if (data.version !== 1 || !Array.isArray(data.items) || data.items.length > 1000) throw Error('invalid storage');
    return data;
  };
  for (const button of document.querySelectorAll('.feedback-button')) {
    button.addEventListener('click', () => {
      try {
        const data = read();
        if (data.items.length >= 1000) throw Error('limit');
        data.items.push({at: new Date().toISOString(), analysis_id: button.dataset.analysis, action: button.dataset.action});
        localStorage.setItem(key, JSON.stringify(data));
        status.textContent = data.items.length + '件をこのブラウザー内に保存しました。未送信です。';
      } catch {
        status.textContent = '保存できません。ブラウザーの保存制限・件数上限・既存データを確認してください。';
      }
    });
  }
  document.getElementById('export-feedback').addEventListener('click', () => {
    try {
      const blob = new Blob([JSON.stringify(read(), null, 2)], {type: 'application/json'});
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'trend-radar-feedback.json';
      a.click();
      URL.revokeObjectURL(url);
      status.textContent = 'JSONを出力しました。Actionsへは自動送信されません。';
    } catch {
      status.textContent = 'JSONを出力できません。ブラウザー内の保存内容を確認してください。';
    }
  });
})();
