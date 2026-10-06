const state = { token: null, filename: '', originalAnalysis: null, cleanedAnalysis: null, currentAnalysis: null, preview: null, validationConfig: {} };
const byId = (id) => document.getElementById(id);
const fileInput = byId('file-input');
let toastTimer;

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`);
  return payload;
}
function notify(message) {
  const toast = byId('toast');
  toast.textContent = message;
  toast.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove('show'), 3200);
}
function setBusy(button, busy, label) {
  button.disabled = busy;
  if (label) button.dataset.label = button.dataset.label || button.innerHTML;
  if (busy) button.innerHTML = '<span>…</span> Working';
  else if (button.dataset.label) { button.innerHTML = button.dataset.label; delete button.dataset.label; }
}
function formatCount(number) { return Number(number || 0).toLocaleString(); }
function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[character]);
}
function renderTable(target, preview) {
  if (!preview || !preview.columns.length) {
    target.innerHTML = '<div class="empty-state">No columns found in this dataset.</div>';
    return;
  }
  const heading = preview.columns.map((column) => `<th>${escapeHtml(column)}</th>`).join('');
  const rows = preview.rows.map((row) => `<tr>${row.map((cell) => `<td title="${escapeHtml(cell)}">${escapeHtml(cell) || '<span aria-label="empty">—</span>'}</td>`).join('')}</tr>`).join('');
  target.innerHTML = `<table><thead><tr>${heading}</tr></thead><tbody>${rows}</tbody></table>`;
}
function issueItems(analysis) {
  return [
    ['Missing values', analysis.missingTotal],
    ['Duplicate rows', analysis.duplicateRows],
    ['Completely empty rows', analysis.emptyRows],
    ['Invalid numerical values', analysis.invalidNumeric],
    ['Invalid date values', analysis.invalidDates],
    ['Duplicate ID values', analysis.duplicateIds],
    ['Cells with extra spaces', analysis.whitespaceCells],
    ['Mixed-type columns', analysis.mixedColumns.length],
  ];
}
function renderIssues(analysis) {
  const items = issueItems(analysis);
  byId('issue-list').innerHTML = items.map(([label, count]) => `<div class="issue-item"><span class="issue-name"><i class="issue-dot"></i>${label}</span><b class="issue-count">${formatCount(count)}</b></div>`).join('');
  byId('scan-state').textContent = 'Scan complete';
  byId('scan-state').classList.add('ready');
}
function renderChart(rawAnalysis, cleanAnalysis = null) {
  const measures = [
    ['Missing', rawAnalysis.missingTotal, cleanAnalysis?.missingTotal],
    ['Duplicates', rawAnalysis.duplicateRows, cleanAnalysis?.duplicateRows],
    ['Invalid cells', rawAnalysis.invalidCells, cleanAnalysis?.invalidCells],
    ['Whitespace', rawAnalysis.whitespaceCells, cleanAnalysis?.whitespaceCells],
  ];
  const max = Math.max(1, ...measures.flatMap((item) => [item[1], item[2] ?? 0]));
  byId('issue-chart').innerHTML = measures.map(([label, before, after]) => {
    const beforeWidth = Math.max(before ? 2 : 0, before / max * 100);
    const afterWidth = Math.max(after ? 2 : 0, (after ?? 0) / max * 100);
    return `<div class="chart-row"><span>${label}</span><div class="chart-track"><div class="chart-fill" style="width:${beforeWidth}%"></div>${cleanAnalysis ? `<div class="chart-fill clean" style="width:${afterWidth}%"></div>` : ''}</div><b>${formatCount(before)}</b></div>`;
  }).join('');
}
function populateColumns(analysis) {
  const names = analysis.profiles.map((profile) => profile.name);
  const required = byId('required-fields');
  const selected = new Set(Array.from(required.selectedOptions).map((option) => option.value));
  required.innerHTML = names.map((name) => `<option value="${escapeHtml(name)}" ${selected.has(name) ? 'selected' : ''}>${escapeHtml(name)}</option>`).join('');
  const idSelect = byId('id-column');
  const previousId = idSelect.value || analysis.idColumn;
  idSelect.innerHTML = `<option value="">Auto-detect if possible</option>${names.map((name) => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`).join('')}`;
  if (names.includes(previousId)) idSelect.value = previousId;
  const rangeSelect = byId('range-column');
  const previousRange = rangeSelect.value;
  const numeric = analysis.profiles.filter((profile) => profile.kind === 'number').map((profile) => profile.name);
  rangeSelect.innerHTML = `<option value="">No range check</option>${numeric.map((name) => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`).join('')}`;
  if (numeric.includes(previousRange)) rangeSelect.value = previousRange;
}
function configPayload() {
  return {
    token: state.token,
    requiredFields: Array.from(byId('required-fields').selectedOptions).map((option) => option.value),
    idColumn: byId('id-column').value,
    rangeColumn: byId('range-column').value,
    rangeMin: byId('range-min').value,
    rangeMax: byId('range-max').value,
  };
}
function renderValidations(validations) {
  const icons = { valid: '✓', warning: '⚠', invalid: '×' };
  byId('validation-list').innerHTML = validations.map((item) => `<div class="validation-item"><i class="status-icon ${item.status}">${icons[item.status]}</i><strong>${escapeHtml(item.label)}</strong><span>${escapeHtml(item.detail)}</span></div>`).join('');
  const invalid = validations.filter((item) => item.status === 'invalid').length;
  const warning = validations.filter((item) => item.status === 'warning').length;
  const summary = byId('validation-summary');
  summary.textContent = invalid ? `${invalid} invalid` : warning ? `${warning} warning${warning > 1 ? 's' : ''}` : 'All valid';
  summary.className = `validation-summary ${invalid ? 'invalid' : warning ? '' : 'valid'}`;
}
function renderAnalysis(analysis, raw = true) {
  state.currentAnalysis = analysis;
  byId('metric-rows').textContent = formatCount(analysis.rows);
  byId('metric-columns').textContent = formatCount(analysis.columns);
  byId('metric-missing').textContent = formatCount(analysis.missingTotal);
  byId('metric-duplicates').textContent = formatCount(analysis.duplicateRows);
  byId('metric-invalid').textContent = formatCount(analysis.invalidRecords);
  byId('hero-score').innerHTML = `${analysis.qualityScore}<small>/100</small>`;
  renderIssues(analysis);
  renderChart(state.originalAnalysis || analysis, raw ? null : analysis);
  populateColumns(analysis);
  renderValidations(analysis.validations);
}
function updateOperationCounts(analysis) {
  byId('op-duplicates').textContent = `${formatCount(analysis.duplicateRows)} found`;
  byId('op-empty').textContent = `${formatCount(analysis.emptyRows)} found`;
  byId('op-spaces').textContent = `${formatCount(analysis.whitespaceCells)} cells`;
  byId('op-caps').textContent = `${formatCount(analysis.capitalizationCells)} cells`;
  byId('op-invalid').textContent = `${formatCount(analysis.invalidNumeric)} values`;
  byId('op-types').textContent = `${analysis.profiles.filter((profile) => profile.kind === 'number' || profile.kind === 'date').length} fields`;
}
function showDataset(payload) {
  state.token = payload.token;
  state.filename = payload.filename;
  state.preview = payload.preview;
  state.originalAnalysis = payload.analysis;
  state.cleanedAnalysis = null;
  byId('dataset-label').textContent = payload.filename.toUpperCase();
  byId('upload-status').textContent = `${payload.filename} · ${formatCount(payload.analysis.rows)} rows loaded`;
  byId('raw-table-count').textContent = `${formatCount(payload.analysis.rows)} records · first 8 shown`;
  renderTable(byId('raw-table'), payload.preview);
  renderAnalysis(payload.analysis, true);
  updateOperationCounts(payload.analysis);
  byId('clean-button').disabled = false;
  byId('validate-button').disabled = false;
  byId('download-button').disabled = true;
  byId('comparison-state').textContent = 'AWAITING CLEANING';
  byId('operation-log').hidden = true;
  byId('clean-table').innerHTML = '<div class="empty-state">Apply cleaning to generate the comparison copy.</div>';
  notify('Dataset loaded. The original source is protected.');
}
async function analyzeWithRules() {
  if (!state.token) return;
  const result = await requestJson('/api/analyze', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(configPayload()) });
  state.originalAnalysis = result.analysis;
  renderValidations(result.analysis.validations);
}

fileInput.addEventListener('change', async () => {
  const file = fileInput.files[0];
  if (!file) return;
  const button = document.querySelector('label[for="file-input"]');
  button.classList.add('loading');
  byId('upload-status').textContent = `Reading ${file.name}…`;
  try {
    const body = new FormData();
    body.append('file', file);
    showDataset(await requestJson('/api/upload', { method: 'POST', body }));
  } catch (error) { notify(error.message); byId('upload-status').textContent = 'Upload failed'; }
  finally { button.classList.remove('loading'); fileInput.value = ''; }
});
byId('sample-button').addEventListener('click', async (event) => {
  const button = event.currentTarget;
  setBusy(button, true);
  try { showDataset(await requestJson('/api/sample', { method: 'POST' })); }
  catch (error) { notify(error.message); }
  finally { setBusy(button, false); }
});
byId('custom-value').hidden = true;
byId('missing-strategy').addEventListener('change', (event) => { byId('custom-value').hidden = event.target.value !== 'custom'; });
byId('validate-button').addEventListener('click', async (event) => {
  const button = event.currentTarget;
  setBusy(button, true);
  try { await analyzeWithRules(); notify('Validation checks updated.'); }
  catch (error) { notify(error.message); }
  finally { setBusy(button, false); }
});
byId('clean-button').addEventListener('click', async (event) => {
  const button = event.currentTarget;
  setBusy(button, true);
  const options = Object.fromEntries(Array.from(document.querySelectorAll('input[name="operation"]')).map((input) => [input.value, input.checked]));
  try {
    const result = await requestJson('/api/clean', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...configPayload(), options, missingStrategy: byId('missing-strategy').value, customValue: byId('custom-value').value }),
    });
    state.cleanedAnalysis = result.analysis;
    byId('clean-table-count').textContent = `${formatCount(result.stats.cleanedRows)} records · first 8 shown`;
    renderTable(byId('clean-table'), result.preview);
    byId('compare-original-rows').textContent = formatCount(result.stats.originalRows);
    byId('compare-cleaned-rows').textContent = formatCount(result.stats.cleanedRows);
    byId('change-duplicates').textContent = formatCount(result.stats.duplicatesRemoved);
    byId('change-missing').textContent = formatCount(result.stats.missingDetected);
    byId('change-handled').textContent = formatCount(result.stats.missingHandled);
    byId('change-invalid').textContent = formatCount(result.stats.invalidRecords);
    byId('change-formatting').textContent = formatCount(result.stats.formattingCorrections);
    byId('comparison-state').textContent = 'CLEANING COMPLETE';
    byId('operation-log').hidden = false;
    byId('log-list').innerHTML = result.stats.operations.length ? result.stats.operations.map((line) => `<li>${escapeHtml(line)}</li>`).join('') : '<li>No cleaning operations were selected; a separate copy was created.</li>';
    renderAnalysis(result.analysis, false);
    renderChart(result.originalAnalysis, result.analysis);
    renderValidations(result.analysis.validations);
    byId('download-button').disabled = false;
    renderComparisonBars(result.originalAnalysis, result.analysis);
    notify('Cleaning complete. Review the comparison before downloading.');
  } catch (error) { notify(error.message); }
  finally { setBusy(button, false); }
});
function renderComparisonBars(before, after) {
  const measures = [
    ['Missing values', before.missingTotal, after.missingTotal],
    ['Duplicate rows', before.duplicateRows, after.duplicateRows],
    ['Invalid cells', before.invalidCells, after.invalidCells],
  ];
  byId('comparison-bars').innerHTML = measures.map(([label, raw, clean]) => {
    const max = Math.max(1, raw, clean);
    const rawWidth = raw ? Math.max(3, raw / max * 100) : 0;
    const cleanWidth = clean ? Math.max(3, clean / max * 100) : 0;
    return `<div class="compare-bar-row"><span>${label}</span><div class="compare-bar-track"><span style="width:${rawWidth}%"></span><span class="after" style="width:${cleanWidth}%"></span></div><b>${formatCount(raw)} → ${formatCount(clean)}</b></div>`;
  }).join('');
}
byId('download-button').addEventListener('click', () => {
  if (!state.token) return;
  window.location.href = `/api/download/${encodeURIComponent(state.token)}`;
});
for (const input of [byId('required-fields'), byId('id-column'), byId('range-column'), byId('range-min'), byId('range-max')]) {
  input.addEventListener('change', () => {
    if (!state.token) return;
    analyzeWithRules().catch((error) => notify(error.message));
  });
}
const navLinks = Array.from(document.querySelectorAll('.nav-link'));
const sections = navLinks.map((link) => document.querySelector(link.getAttribute('href'))).filter(Boolean);
const observer = new IntersectionObserver((entries) => {
  const visible = entries.filter((entry) => entry.isIntersecting).sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
  if (!visible) return;
  navLinks.forEach((link) => link.classList.toggle('active', link.getAttribute('href') === `#${visible.target.id}`));
}, { rootMargin: '-15% 0px -70% 0px', threshold: [0, .2, .5] });
sections.forEach((section) => observer.observe(section));
