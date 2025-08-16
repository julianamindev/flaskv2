(function () {
  const APPS = (window.L2A && window.L2A.APPS) || [];

  function showAlert(msg, type = 'warning') {
    const $zone = $('#l2a-alerts');
    const $el = $(`
      <div class="alert alert-${type} alert-dismissible fade show" role="alert">
        ${msg}
        <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
      </div>`);
    $zone.empty().append($el);
  }

  function initAjaxSelect2ForApp(app) {
    const key = app.toLowerCase();
    const $pane   = $(`#${key}-pane`);
    const $stream = $(`#${key}-stream`);
    const $build  = $(`#${key}-build`);

    const $manualToggle   = $(`#${key}-manual-toggle`);
    const $manualWrap     = $(`#${key}-manual-stream-wrap`);
    const $manualInput    = $(`#${key}-manual-input`);
    const $manualValidate = $(`#${key}-manual-validate`);

    // Which stream is currently active?
    function effectiveStream() {
      if ($manualToggle.is(':checked')) return ($manualInput.val() || '').trim();
      return $stream.val() || '';
    }

    // STREAMS
    $stream.select2({
      width: '100%',
      allowClear: true,
      placeholder: $stream.data('placeholder') || 'Choose a stream',
      minimumInputLength: 0,
      ajax: {
        url: '/api/streams',
        dataType: 'json',
        delay: 250,
        cache: true,
        data: params => ({ app, q: params.term || '', page: params.page || 1 }),
        processResults: data => ({
          results: data.results || [],
          pagination: { more: data.pagination && data.pagination.more }
        })
      },
      dropdownParent: $pane
    });

    // BUILDS (always enabled; pulls from effectiveStream)
    $build.prop('disabled', false).select2({
      width: '100%',
      allowClear: true,
      placeholder: $build.data('placeholder') || 'Choose a build',
      minimumInputLength: 0,
      ajax: {
        url: '/api/builds',
        dataType: 'json',
        delay: 250,
        cache: true,

        // Validate manual stream (if any) before hitting /api/builds
        transport: function (params, success, failure) {
          const sid = effectiveStream();
          if (!sid) { success({ results: [], pagination: { more: false } }); return; }

          if ($manualToggle.is(':checked')) {
            $.getJSON('/api/streams/exists', { app, stream: sid })
              .done(({ exists, stream }) => {
                if (!exists) {
                  showAlert(`Stream <b>${sid}</b> not found for <b>${app}</b>.`, 'danger');
                  success({ results: [], pagination: { more: false } });
                  return;
                }
                // Update manual text with canonical casing
                if (stream && stream !== sid) $manualInput.val(stream);
                $.ajax(params).then(success, failure);
              })
              .fail(() => {
                showAlert('Unable to validate stream right now.', 'danger');
                success({ results: [], pagination: { more: false } });
              });
            return;
          }

          // Normal mode
          return $.ajax(params).then(success, failure);
        },

        // Always send the effective stream
        data: params => ({
          app,
          stream_id: effectiveStream(),
          q: params.term || '',
          page: params.page || 1
        }),

        processResults: data => ({
          results: data.results || [],
          pagination: { more: data.pagination && data.pagination.more }
        })
      },
      dropdownParent: $pane
    });

    // Summary + hidden inputs
    function setSummary(buildVal) {
      const s = effectiveStream();
      $(`#summary-${key}`).val(buildVal || '');
      $(`#hidden-${key}-stream`).val(s);
      $(`#hidden-${key}-build`).val(buildVal || '');
    }

    // Stream (normal) changes: clear build selection
    $stream.on('select2:select select2:clear', () => {
      $build.val(null).trigger('change');
      setSummary('');
    });

    // Builds change: update summary
    $build.on('select2:select select2:clear', () => {
      setSummary($build.val() || '');
    });

    // Manual STREAM mode toggle
    function enterManual(on) {
      const $streamS2 = $stream.next('.select2');
      if (on) {
        $streamS2.addClass('d-none');
        $manualWrap.removeClass('d-none');
        $build.val(null).trigger('change');
        setSummary('');
        $manualInput.focus();
      } else {
        $manualWrap.addClass('d-none');
        $streamS2.removeClass('d-none');
        $build.val(null).trigger('change');
        setSummary('');
      }
    }
    $manualToggle.on('change', function () { enterManual(this.checked); });

    // Optional: "Use stream" button to set into stream Select2 (nice UX)
    function validateAndApplyManualStream() {
      const sid = ($manualInput.val() || '').trim();
      if (!sid) return;
      $.getJSON('/api/streams/exists', { app, stream: sid })
        .done(({ exists, stream }) => {
          if (!exists) {
            showAlert(`Stream <b>${sid}</b> not found for <b>${app}</b>.`, 'danger');
            $build.val(null).trigger('change');
            setSummary('');
            return;
          }
          const $opt = new Option(stream, stream, true, true);
          $stream.append($opt).trigger('change');
          showAlert(`Using stream <b>${stream}</b> for <b>${app}</b>.`, 'success');
        })
        .fail(() => showAlert('Unable to validate stream right now.', 'danger'));
    }
    $manualValidate.on('click', validateAndApplyManualStream);
    $manualInput.on('keypress', function (e) {
      if (e.key === 'Enter') { e.preventDefault(); validateAndApplyManualStream(); }
    });
  }

  $(function () {
    APPS.forEach(initAjaxSelect2ForApp);

    // migops/LARS prefix helper
    const PREFIX = 'migops/LARS/';
    const $suffix = $('#migops-lars-input');
    const $full   = $('#migops-lars-path');
    const updateFull = () => $full.val(PREFIX + ($suffix.val() || '').replace(/^\/+/, ''));
    $suffix.on('input', updateFull);
    updateFull();
  });
})();

// 

$(function () {
  const $form = $('#lars2awsForm');
  const $submit = $form.find('button[type="submit"]');
  const $alerts = $('#l2a-alerts');

  const csrf = $form.find('input[name="csrf_token"]').val() || null;

  function flash(type, html) {
    $alerts.html(`
      <div class="alert alert-${type} alert-dismissible fade show" role="alert">
        ${html}
        <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
      </div>
    `);
  }

  function renderUploading(prefix, items) {
    const lis = items.map((it, i) => {
      const key = `s3://${it.bucket}/${it.key}`;
      return `
        <li id="upl-${i}" class="mb-1">
          <span class="me-2" data-role="icon">⏳</span>
          <code>${key}</code>
          <div class="small text-muted">${it.source_url}</div>
          <div class="small" data-role="msg"></div>
        </li>`;
    }).join('');
    flash('info', `
      <div class="fw-semibold mb-2">Uploading to <code>${prefix}</code></div>
      <ul class="mb-0 ps-3">${lis}</ul>
    `);
  }

  async function uploadSequential(items) {
    let allOk = true;
    for (let i = 0; i < items.length; i++) {
      const it = items[i];
      const $row = $(`#upl-${i}`);
      const $icon = $row.find('[data-role="icon"]');
      const $msg = $row.find('[data-role="msg"]');

      // show "uploading ..." message
      $icon.text('⬆️');
      $msg.text('Uploading...');

      try {
        const res = await $.ajax({
          url: '/lars2aws/upload-item',
          method: 'POST',
          data: JSON.stringify({
            source_url: it.source_url,
            bucket: it.bucket,
            key: it.key,
            metadata: it.metadata || null
          }),
          contentType: 'application/json',
          headers: csrf ? {'X-CSRFToken': csrf} : {}
        });
        // success
        $icon.text('✅');
        $msg.text('Done');
      } catch (xhr) {
        allOk = false;
        $icon.text('❌');
        const err = (xhr.responseJSON && xhr.responseJSON.error) || xhr.statusText || 'Upload failed';
        $msg.addClass('text-danger').text(err);
      }
    }
    // Replace info alert with final status (but keep the list)
    const html = $alerts.find('.alert').html();
    const body = html.replace(/class="alert alert-info/, `class="alert alert-${allOk ? 'success' : 'warning'}`);
    $alerts.html(`
      <div class="alert alert-${allOk ? 'success' : 'warning'} alert-dismissible fade show" role="alert">
        <div class="fw-semibold mb-2">${allOk ? 'All uploads succeeded.' : 'Some uploads failed.'}</div>
        ${$('<div>').html(body).find('ul').prop('outerHTML')}
        <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
      </div>
    `);
  }

  $form.on('submit', function (e) {
    e.preventDefault();
    $submit.prop('disabled', true);

    const formData = new FormData(this);

    // Step 1: build plan
    $.ajax({
      url: '/lars2aws/plan',
      method: 'POST',
      data: formData,
      processData: false,
      contentType: false
    })
    .done(payload => {
      if (!payload || !payload.ok || !payload.artifacts || !payload.artifacts.length) {
        const msg = (payload && payload.message) || 'No artifacts to upload.';
        flash('warning', msg);
        return;
      }
      // Step 2: show live list + target prefix
      renderUploading(payload.s3_prefix, payload.artifacts);
      // Step 3: upload sequentially
      uploadSequential(payload.artifacts);
    })
    .fail(xhr => {
      const msg = (xhr.responseJSON && xhr.responseJSON.message) || xhr.statusText || 'Plan failed.';
      flash('danger', msg);
    })
    .always(() => {
      $submit.prop('disabled', false);
    });
  });
});


// ---- Clear fields: reset all tabs + summary + path ----
(function () {
  function clearApp(app) {
    const key = app.toLowerCase();
    const $stream = $(`#${key}-stream`);
    const $build  = $(`#${key}-build`);
    const $manualToggle = $(`#${key}-manual-toggle`);
    const $manualWrap   = $(`#${key}-manual-stream-wrap`);
    const $manualInput  = $(`#${key}-manual-input`);

    // Exit manual stream mode if on
    if ($manualToggle.length && $manualToggle.is(':checked')) {
      $manualToggle.prop('checked', false).trigger('change');
    }
    $manualWrap.addClass('d-none');
    $manualInput.val('');

    // Clear Select2s
    $stream.val(null).trigger('change');
    $build.val(null).trigger('change');

    // Clear summary + hidden fields
    $(`#summary-${key}`).val('');
    $(`#hidden-${key}-stream`).val('');
    $(`#hidden-${key}-build`).val('');
  }

  function clearAllSelections() {
    const APPS = (window.L2A && window.L2A.APPS) || [];
    APPS.forEach(clearApp);

    // Reset S3 destination suffix + hidden full path
    const PREFIX = 'migops/LARS/';
    $('#migops-lars-input').val('');
    $('#migops-lars-path').val(PREFIX);
  }

  $(function () {
    $('#clear-selections').on('click', function (e) {
      e.preventDefault();
      clearAllSelections();
    });
  });
})();

// ---- Autofill SR Releases: fill all apps with latest R build for REL_YYYY_MM, set MT/<MMM> ----
(function () {
  const APPS = (window.L2A && window.L2A.APPS) || [];

  const monthAbbrev = (d) => d.toLocaleString('en-US', { month: 'short' }).toUpperCase(); // AUG, SEP, ...

  async function fetchStreamExact(app, name) {
    // Page through /api/streams until we find an exact `name`
    let page = 1;
    while (true) {
      const data = await $.getJSON('/api/streams', { app, q: name, page });
      const hit = (data.results || []).find(r => (r.text || r.id) === name);
      if (hit) return hit;
      if (!data.pagination || !data.pagination.more) return null;
      page += 1;
    }
  }

  async function fetchLatestRBuild(app, streamId) {
    // Iterate /api/builds pages; choose the build with maturity 'R' and highest release_id
    let page = 1;
    let best = null;

    const consider = (item) => {
      // Support both enriched payloads and "TEXT--id" labels
      const maturity = (item.maturity || '').toString().toUpperCase();
      const txt = (item.text || '').trim();
      const parts = txt.split('--');
      const code = maturity || (parts[0] || '').trim().toUpperCase();

      if (code !== 'R') return;

      const idStr = item.release_id != null ? String(item.release_id)
                   : item.id != null ? String(item.id)
                   : (parts[1] || '').trim();
      const idNum = parseInt(idStr, 10);
      const rank = Number.isFinite(idNum) ? idNum : idStr;

      if (!best) best = { item, rank };
      else if (typeof rank === 'number' && typeof best.rank === 'number') {
        if (rank > best.rank) best = { item, rank };
      } else if (String(rank) > String(best.rank)) {
        best = { item, rank };
      }
    };

    while (true) {
      const data = await $.getJSON('/api/builds', { app, stream_id: streamId, page });
      (data.results || []).forEach(consider);
      if (!data.pagination || !data.pagination.more) break;
      page += 1;
    }
    return best ? best.item : null;
  }

  function setSelect2Value($select, item) {
    const text = item.text || item.id;
    const val  = item.id != null ? item.id : text;
    if ($select.find(`option[value="${val}"]`).length === 0) {
      $select.append(new Option(text, val, true, true));
    }
    $select.val(val).trigger('change');
  }

  async function autofillSR() {
    try {
      const now = new Date();
      const year = now.getFullYear();
      const mm   = String(now.getMonth() + 1).padStart(2, '0'); // 01..12
      const rel  = `REL_${year}_${mm}`;
      const mmm  = monthAbbrev(now); // e.g., AUG

      // 1) MIG must have this stream or we abort
      const migStream = await fetchStreamExact('MIG', rel);
      if (!migStream) {
        showAlert(`Required MIG stream <b>${rel}</b> is not available for this month.`, 'danger');
        return;
      }

      // 2) For every app, set stream to REL_YYYY_MM and pick latest R build
      for (const app of APPS) {
        const key = app.toLowerCase();
        const $stream = $(`#${key}-stream`);
        const $build  = $(`#${key}-build`);

        // Turn off manual stream mode if on
        const $manualToggle = $(`#${key}-manual-toggle`);
        const $manualWrap   = $(`#${key}-manual-stream-wrap`);
        const $manualInput  = $(`#${key}-manual-input`);
        if ($manualToggle.length && $manualToggle.is(':checked')) {
          $manualToggle.prop('checked', false).trigger('change');
        }
        $manualWrap.addClass('d-none');
        $manualInput.val('');

        // Use MIG's found stream for MIG; search exact for others
        const stream = app === 'MIG' ? migStream : await fetchStreamExact(app, rel);
        if (!stream) continue;

        // Select the stream
        setSelect2Value($stream, stream);

        // Fetch & pick the latest Release-maturity (R) build
        const rBuild = await fetchLatestRBuild(app, stream.id);
        if (!rBuild) continue;

        // Select the build (handlers will update the summary/hidden fields)
        setSelect2Value($build, rBuild);
      }

      // 3) Set destination suffix to MT/<MMM> and update hidden full path
      $('#migops-lars-input').val(`MT/${mmm}`).trigger('input');

      showAlert(`Autofilled SR releases for <b>${rel}</b>. You can still adjust any field.`, 'success');
    } catch (err) {
      console.error(err);
      showAlert('Autofill failed due to an unexpected error.', 'danger');
    }
  }

  $(function () {
    $('#autofill-sr').on('click', function (e) {
      e.preventDefault();
      autofillSR();
    });
  });
})();
