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



