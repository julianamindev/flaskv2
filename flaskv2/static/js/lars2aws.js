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

$(function () {
  const $form = $('#lars2awsForm');
  const $submit = $form.find('button[type="submit"]');

  function renderResults(payload) {
    const $zone = $('#l2a-alerts');
    if (!payload || payload.ok === undefined) {
      $zone.html('<div class="alert alert-danger">Unexpected server response.</div>');
      return;
    }
    if (!payload.results || !payload.results.length) {
      $zone.html('<div class="alert alert-warning">No uploads were performed.</div>');
      return;
    }
    const rows = payload.results.map(r => {
      const status = r.ok ? '✅' : '❌';
      const key = `s3://${r.bucket}/${r.key}`;
      const src = r.source_url;
      const err = r.ok ? '' : `<div class="small text-danger">${r.error || ''}</div>`;
      return `<li class="mb-1">${status} <code>${key}</code><br><span class="small text-muted">${src}</span>${err}</li>`;
    }).join('');
    const summary = payload.ok ? 'All uploads succeeded.' : 'Some uploads failed.';
    $zone.html(`
      <div class="alert ${payload.ok ? 'alert-success' : 'alert-warning'}">
        <div class="fw-semibold mb-2">${summary}</div>
        <ul class="mb-0 ps-3">${rows}</ul>
      </div>
    `);
  }

  $form.on('submit', function (e) {
    e.preventDefault();
    $('#l2a-alerts').html(`
      <div class="alert alert-info">
        <span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>
        Uploading... This may take a while for large artifacts.
      </div>
    `);
    $submit.prop('disabled', true);

    const formData = new FormData(this);
    $.ajax({
      url: '/lars2aws/upload',
      method: 'POST',
      data: formData,
      processData: false,
      contentType: false
    })
    .done(renderResults)
    .fail(xhr => {
      const msg = (xhr.responseJSON && xhr.responseJSON.message) || xhr.statusText || 'Upload failed.';
      $('#l2a-alerts').html(`<div class="alert alert-danger">${msg}</div>`);
    })
    .always(() => {
      $submit.prop('disabled', false);
    });
  });
});

