// static/js/aws/s3_builds.js

let injectModal;

(function () {
  'use strict';

  const injectModalEl = document.getElementById('injectModal');
  injectModal = bootstrap.Modal.getOrCreateInstance(injectModalEl, {
      backdrop: 'static',
      keyboard: false
  });

  // ----- Page config handed off by Jinja in s3_builds.html -----
  const S3B = window.S3B || {};
  const PREFIX_MAP = S3B.PREFIX_MAP || {};
  const BUCKET = S3B.BUCKET || 'migops';
  const ROOT   = S3B.ROOT   || 'LARS';

  // Cache S3 version metadata by relative key (e.g., "MT/AUG/LANDMARK.jar")
  const META_CACHE = new Map();

  // ----- Files that should show version metadata (x-amz-meta-version) -----
  const NEEDS_META_SET = new Set([
    'Install-LMMIG.jar',
    'Install-LMIEFIN.jar',
    'Install-LMHCM.jar',
    'LANDMARK.jar',
    'grid-installer.jar',
  ]);

  async function loadRunningStacks() {
    const sum = document.getElementById('stacksSummary');
    const tbody = document.querySelector('#stacksTable tbody');
    // quick loading state
    tbody.innerHTML = `<tr><td colspan="6" class="text-muted">Loading…</td></tr>`;
    sum.textContent = 'Loading…';

    const nextBtn = document.getElementById('inj-next');
    nextBtn.disabled = true;
    try {
      const resp = await fetch('/api/stacks?state=running', { credentials: 'same-origin' });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const list = await resp.json();

      // Adapt to your table columns (Name, Instance ID, Env, Region, Uptime)
      // Uptime may be unknown here; we’ll leave it blank.
      renderStacks(list.map(s => ({
        id: s.id,
        name: s.name,
        env: s.env || '',
        region: s.region || '',
        uptime: ''  // optional later
      })));

      // reset filter & counts
      document.getElementById('stackFilter').value = '';
      filterStacks('');
    } catch (err) {
      tbody.innerHTML = `<tr><td colspan="6" class="text-danger">Failed to load running stacks.</td></tr>`;
      sum.textContent = '0 stacks';
      console.error('loadRunningStacks error:', err);
    } finally {
      nextBtn.disabled = false;
    } 
  }

  function resetInjectModalUI() {
    // steps
    goStep(1);
    document.getElementById('inj-hint').textContent = 'Pick the Landmark stack that will receive the files.';

    // progress pane
    const prog = document.getElementById('inj-progress');
    prog.classList.add('d-none');
    document.getElementById('inj-log').textContent = '';
    const badge = document.getElementById('inj-status-badge');
    badge.className = 'badge bg-secondary';
    badge.textContent = 'Pending';

    // footer buttons
    const submitBtn = document.getElementById('inj-submit');
    submitBtn.disabled = false;
    submitBtn.textContent = 'Inject Builds';
    submitBtn.onclick = null; // remove any previous Close handler

    // state
    injectState.selectedFiles.clear();
    injectState.selectedStack = null;

    // step tables
    document.querySelector('#stacksTable tbody').innerHTML = '';
    document.querySelector('#filesTable tbody').innerHTML = '';
    document.getElementById('stacksSummary').textContent = '0 stacks';
    document.getElementById('filesSummary').textContent = '0 selected';
    const filt = document.getElementById('stackFilter');
    if (filt) filt.value = '';
  }

  function showProgressUI() {
    // hide steps, show progress panel
    document.getElementById('inj-step-1').classList.add('d-none');
    document.getElementById('inj-step-2').classList.add('d-none');
    document.getElementById('inj-step-3').classList.add('d-none');
    document.getElementById('inj-progress').classList.remove('d-none');
    // footer: show only Close (we’ll repurpose submit button label)
    document.getElementById('inj-back').disabled = true;
    document.getElementById('inj-next').classList.add('d-none');
    const submitBtn = document.getElementById('inj-submit');
    submitBtn.classList.remove('d-none');
    submitBtn.disabled = true;
    submitBtn.textContent = 'Injecting…';
    document.getElementById('inj-hint').textContent = 'Running SSM command on the selected stack…';
    // clear log/status
    document.getElementById('inj-log').textContent = '';
    const badge = document.getElementById('inj-status-badge');
    badge.className = 'badge bg-secondary';
    badge.textContent = 'Pending';
  }

  function setProgressStatus(status, details, outText) {
    const badge = document.getElementById('inj-status-badge');
    const logEl = document.getElementById('inj-log');
    const cls = {
      Pending: 'bg-secondary',
      InProgress: 'bg-info',
      Delayed: 'bg-warning',
      Success: 'bg-success',
      Failed: 'bg-danger',
      TimedOut: 'bg-danger',
      Cancelled: 'bg-secondary',
      Cancelling: 'bg-warning'
    }[status] || 'bg-secondary';
    badge.className = `badge ${cls}`;
    badge.textContent = details || status;
    if (outText) logEl.textContent = outText;
  }

  // ----- Build DataTable rows from PREFIX_MAP -----
  function buildRows() {
    return Object.entries(PREFIX_MAP).map(([prefix, files]) => {
      const isRoot = (prefix === 'LARS/' || prefix === '' || prefix === '/');
      return {
        displayPrefix: isRoot ? 'LARS/' : prefix,
        category:      isRoot ? 'ROOT'  : prefix.split('/')[0],
        keyPrefix:     isRoot ? ''      : prefix, // used to build s3://migops/LARS/<keyPrefix>...
        files,
        files_count:   files.length
      };
    });
  }

  // ----- Child row renderer (includes Metadata and Copy action) -----
  function renderChild(row) {
    const s3Base = `s3://${BUCKET}/${ROOT}/${row.keyPrefix}`; // keyPrefix "" => ends with /
    const fileRows = row.files.map(name => {
      const s3Uri  = s3Base + name;
      const relKey = `${row.keyPrefix}${name}`; // relative to LARS/
      const needs  = NEEDS_META_SET.has(name);
      return `
        <tr>
          <td class="py-1">${name}</td>
          <td class="py-1"><code class="small">${s3Uri}</code></td>
          <td class="py-1 meta-cell" data-key="${relKey}">${needs ? "…" : "—"}</td>
          <td class="py-1 text-end">
            <button class="btn btn-sm btn-outline-secondary" data-copy="${s3Uri}">Copy S3 URI</button>
          </td>
        </tr>`;
    }).join("");

    return `
      <div class="p-2">
        <div class="fw-semibold mb-2">Files in <span class="text-nowrap"><code>${row.displayPrefix}</code></span></div>
        <div class="table-responsive">
          <table class="table table-sm mb-0">
            <thead>
              <tr>
                <th>File</th>
                <th>S3 URI</th>
                <th>Metadata</th>
                <th class="text-end">Actions</th>
              </tr>
            </thead>
            <tbody>${fileRows || `<tr><td colspan="4" class="text-muted">No files</td></tr>`}</tbody>
          </table>
        </div>
      </div>`;
  }

  // ----- Fill "Metadata" cells by calling the API for needed files -----
  function hydrateMetaCellsFor(trElem) {
    const $child = $(trElem).next('tr'); // DataTables puts child in next TR
    $child.find('td.meta-cell').each(function () {
      const td   = this;
      const key  = td.getAttribute('data-key') || '';
      if (!key) { td.textContent = '—'; return; }
      const base = key.split('/').pop();
      if (!NEEDS_META_SET.has(base)) { td.textContent = '—'; return; }

      td.textContent = '…';
      fetch(`/api/s3/object_meta?key=${encodeURIComponent(key)}`)
        .then(r => r.json())
        .then(({ ok, metadata }) => {
          const val = (ok && metadata && metadata.version) ? metadata.version : '—';
          META_CACHE.set(key, val);
          td.textContent = val;
        }).catch(() => { td.textContent = '—'; });
    });
  }

  function hydrateModalMeta() {
    document.querySelectorAll('#filesTable td.meta-cell').forEach(td => {
      const key = td.getAttribute('data-key') || '';
      if (!key) { td.textContent = '—'; return; }

      // Use cache if present
      const cached = META_CACHE.get(key);
      if (cached !== undefined) {
        td.textContent = cached;
        return;
      }

      td.textContent = '…';
      fetch(`/api/s3/object_meta?key=${encodeURIComponent(key)}`)
        .then(r => r.json())
        .then(({ ok, metadata }) => {
          const val = (ok && metadata && metadata.version) ? metadata.version : '—';
          META_CACHE.set(key, val);     // cache for future renders
          td.textContent = val;
        })
        .catch(() => { td.textContent = '—'; });
    });
  }

  // ----- Copy buttons (event delegation for both table + child content) -----
  document.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-copy]');
    if (!btn) return;
    const text = btn.getAttribute('data-copy');
    navigator.clipboard.writeText(text).then(() => {
      const prev = btn.textContent;
      btn.textContent = 'Copied!';
      setTimeout(() => (btn.textContent = prev), 1200);
    }).catch(() => {
      alert('Copy failed. You can select the URI text manually.');
    });
  });

  // ----- Inject wizard state + helpers -----
  const injectState = {
    displayPrefix: '',   // "LARS/" or "MT/AUG/"
    keyPrefix: '',       // "" or "MT/AUG/"
    files: [],           // files available under keyPrefix
    selectedStack: null, // {id, name, env, region, uptime}
    selectedFiles: new Set()
  };

  function goStep(n) {
    // show/hide steps
    document.getElementById('inj-step-1').classList.toggle('d-none', n !== 1);
    document.getElementById('inj-step-2').classList.toggle('d-none', n !== 2);
    document.getElementById('inj-step-3').classList.toggle('d-none', n !== 3);

    // footer buttons
    document.getElementById('inj-back').disabled = (n === 1);
    document.getElementById('inj-next').classList.toggle('d-none', n === 3);
    document.getElementById('inj-submit').classList.toggle('d-none', n !== 3);

    // step label
    const stepLbl = document.getElementById('inj-step-indicator');
    if (n === 1) stepLbl.textContent = 'Step 1 of 3 — Select target stack';
    if (n === 2) stepLbl.textContent = 'Step 2 of 3 — Select files to inject';
    if (n === 3) stepLbl.textContent = 'Step 3 of 3 — Confirm & inject';

    // contextual hint
    const hint = document.getElementById('inj-hint');
    if (n === 1) hint.textContent = 'Pick the Landmark stack that will receive the files.';
    if (n === 2) hint.textContent = 'Choose which files to copy into /opt/infor/landmark/tmp.';
    if (n === 3) hint.textContent = 'Review and confirm. We’ll pre-clear conflicting files before copying.';
  }

  function renderStacks(list) {
    const tbody = document.querySelector('#stacksTable tbody');
    const rowsHtml = list.map(s => `
      <tr>
        <td><input type="radio" name="stackPick" value="${s.id}" aria-label="Select ${s.name}"></td>
        <td>${s.name}</td>
        <td><code>${s.id}</code></td>
        <td>${s.env || ''}</td>
        <td>${s.region || ''}</td>
        <td>${s.uptime || ''}</td>
      </tr>
    `).join('');
    tbody.innerHTML = rowsHtml;
    document.getElementById('stacksSummary').textContent = `${list.length} stacks`;
  }

  function filterStacks(term) {
    term = (term || '').trim().toLowerCase();
    const rows = document.querySelectorAll('#stacksTable tbody tr');
    let shown = 0;
    rows.forEach(tr => {
      const txt = tr.textContent.toLowerCase();
      const keep = !term || txt.includes(term);
      tr.classList.toggle('d-none', !keep);
      if (keep) shown++;
    });
    document.getElementById('stacksSummary').textContent = `${shown} stacks`;
  }

  function renderFiles() {
    const tbody = document.querySelector('#filesTable tbody');
    const s3Base = `s3://${BUCKET}/${ROOT}/${injectState.keyPrefix}`;

    const rowsHtml = injectState.files.map(name => {
      const relKey = `${injectState.keyPrefix}${name}`;     // relative to LARS/
      const need   = NEEDS_META_SET.has(name);

      // If cached, show immediately; else show an ellipsis and hydrate later
      const cached = META_CACHE.get(relKey);
      const metaCell = need
        ? `<td class="meta-cell" data-key="${relKey}">${cached !== undefined ? cached : '…'}</td>`
        : `<td>—</td>`;

      return `
        <tr>
          <td><input type="checkbox" class="filePick" value="${name}" ${injectState.selectedFiles.has(name) ? 'checked' : ''}></td>
          <td>${name}</td>
          <td><code class="small">${s3Base + name}</code></td>
          ${metaCell}
        </tr>
      `;
    }).join('');

    tbody.innerHTML = rowsHtml;
    updateFilesSummary();
    hydrateModalMeta();    // <-- fetch versions for “…” cells
  }


  function updateFilesSummary() {
    document.getElementById('filesSummary').textContent = `${injectState.selectedFiles.size} selected`;
  }

  function renderSummary() {
    document.getElementById('sum-stack').textContent  = `${injectState.selectedStack?.name || '—'} (${injectState.selectedStack?.id || ''})`;
    document.getElementById('sum-prefix').textContent = injectState.displayPrefix || '—';
    document.getElementById('sum-count').textContent  = injectState.selectedFiles.size.toString();
    document.getElementById('sum-files').innerHTML    = [...injectState.selectedFiles].map(f => `<code class="d-inline-block me-2 mb-1">${f}</code>`).join('');
  }

  // ----- DOM ready: build DataTable and wire handlers -----
  $(function () {
    const rows = buildRows();

    // DataTable init
    const dt = $('#buildsTable').DataTable({
      data: rows,
      columns: [
        { data: null, orderable: false, className: 'dt-control', defaultContent: '' },
        { data: 'displayPrefix', render: d => `<span class="me-1">📁</span><code>${d}</code>` },
        { data: 'category' },
        { data: 'files_count', className: 'text-end', render: d => d.toLocaleString() },
        {
          data: null,
          orderable: false,
          className: 'text-end',
          render: (_data, _type, row) => {
            const disabled = row.files_count === 0 ? 'disabled' : '';
            return `<button type="button" class="btn btn-sm btn-outline-primary btn-inject"
                      data-prefix="${row.displayPrefix}"
                      data-keyprefix="${row.keyPrefix}"
                      ${disabled}
                      aria-label="Inject builds from ${row.displayPrefix}">
                      Inject Builds
                    </button>`;
          }
        }
      ],
      order: [[1, 'asc']],
      paging: true,
      searching: true
    });

    // Expand/collapse child rows
    $('#buildsTable tbody').on('click', 'td.dt-control', function () {
      const tr  = $(this).closest('tr');
      const row = dt.row(tr);
      if (row.child.isShown()) {
        row.child.hide();
        tr.removeClass('shown');
      } else {
        row.child(renderChild(row.data())).show();
        tr.addClass('shown');
        hydrateMetaCellsFor(tr[0]); // fetch versions for this child panel
      }
    });

    // Open modal from Inject button
    $('#buildsTable tbody').on('click', '.btn-inject', async function () {
      const tr  = $(this).closest('tr');
      const row = dt.row(tr).data();

      injectState.displayPrefix = this.dataset.prefix || row.displayPrefix;
      injectState.keyPrefix     = this.dataset.keyprefix || row.keyPrefix;
      injectState.files         = (row.files || []).slice();
      injectState.selectedFiles = new Set();
      injectState.selectedStack = null;

      // Header
      document.getElementById('inj-prefix').textContent = injectState.displayPrefix;

      resetInjectModalUI();
      
      injectModal.show(); // Show modal

      // Step 1: stacks
      await loadRunningStacks();
      
    });

    // Stack filter
    document.getElementById('stackFilter').addEventListener('input', (e) => {
      filterStacks(e.target.value);
    });

    // Pick a stack (radio)
    document.querySelector('#stacksTable tbody').addEventListener('change', (e) => {
      if (e.target && e.target.name === 'stackPick') {
        const id = e.target.value;
        const tr = e.target.closest('tr');
        injectState.selectedStack = {
          id,
          name:   tr.children[1].textContent,
          env:    tr.children[3].textContent,
          region: tr.children[4].textContent,
          uptime: tr.children[5].textContent
        };
      }
    });

    // Next / Back / Submit
    document.getElementById('inj-next').addEventListener('click', () => {
      const is1 = !document.getElementById('inj-step-1').classList.contains('d-none');
      const is2 = !document.getElementById('inj-step-2').classList.contains('d-none');

      if (is1) {
        if (!injectState.selectedStack) {
          document.getElementById('inj-hint').textContent = 'Please select a stack to continue.';
          return;
        }
        renderFiles();
        goStep(2);
        return;
      }

      if (is2) {
        if (injectState.selectedFiles.size === 0) {
          document.getElementById('inj-hint').textContent = 'Please select at least one file.';
          return;
        }
        renderSummary();
        goStep(3);
        return;
      }
    });

    document.getElementById('inj-back').addEventListener('click', () => {
      const is3 = !document.getElementById('inj-step-3').classList.contains('d-none');
      if (is3) { goStep(2); return; }
      const is2 = !document.getElementById('inj-step-2').classList.contains('d-none');
      if (is2) { goStep(1); return; }
    });

    // File selection handlers
    document.getElementById('filesTable').addEventListener('change', (e) => {
      if (e.target && e.target.classList.contains('filePick')) {
        const name = e.target.value;
        if (e.target.checked) injectState.selectedFiles.add(name);
        else injectState.selectedFiles.delete(name);
        updateFilesSummary();
      }
    });
    document.getElementById('selectAllFiles').addEventListener('click', () => {
      injectState.selectedFiles = new Set(injectState.files);
      renderFiles();
    });
    document.getElementById('clearAllFiles').addEventListener('click', () => {
      injectState.selectedFiles.clear();
      renderFiles();
    });

    // Submit
    document.getElementById('inj-submit').addEventListener('click', async () => {
      // Build payload
      const instanceId = injectState.selectedStack?.id;
      const filesArr   = [...injectState.selectedFiles];
      const keyPrefix  = injectState.keyPrefix; // "" or "MT/AUG/"

      // Safety
      if (!instanceId || filesArr.length === 0) return;

      showProgressUI();

      try {
        const resp = await fetch('/api/inject', {
          method: 'POST',
          headers: {'Content-Type':'application/json'},
          credentials: 'same-origin',
          body: JSON.stringify({
            instance_id: instanceId,
            key_prefix: keyPrefix,
            files: filesArr
          })
        });
        const data = await resp.json();
        if (!resp.ok || !data.ok) throw new Error(data.error || `HTTP ${resp.status}`);

        // Poll
        await pollInjectStatus(data.job_id, data.instance_id);
      } catch (err) {
        setProgressStatus('Failed', 'Failed to start', String(err));
        // enable Close
        const submitBtn = document.getElementById('inj-submit');
        submitBtn.disabled = false;
        submitBtn.textContent = 'Close';
        submitBtn.onclick = () => { injectModal.hide(); };
      }
    });

    async function pollInjectStatus(jobId, instanceId) {
      const submitBtn = document.getElementById('inj-submit');
      let done = false;

      while (!done) {
        const r = await fetch(`/api/inject/${encodeURIComponent(jobId)}/status?instance_id=${encodeURIComponent(instanceId)}`, {
          credentials: 'same-origin'
        });
        const j = await r.json();

        if (!j.ok) {
          setProgressStatus('Failed', 'Status error', j.error || '');
          break;
        }

        // Combine stdout/stderr for display
        const out = [j.stdout || '', j.stderr || ''].filter(Boolean).join('\n');
        setProgressStatus(j.status, j.status_details, out);

        if (['Success','Failed','Cancelled','TimedOut'].includes(j.status)) {
          done = true;
          submitBtn.disabled = false;
          submitBtn.textContent = 'Close';
          submitBtn.onclick = () => { injectModal.hide(); };
          break;
        }

        await new Promise(res => setTimeout(res, 2000));
      }
    }


    // Optional: reset wizard on close
    injectModalEl.addEventListener('hidden.bs.modal', () => {
      resetInjectModalUI();
    });
  });
})();
