(function () {
  const APPS = (window.L2A && window.L2A.APPS) || [];

  function initAjaxSelect2ForApp(app) {
    const key = app.toLowerCase();
    const $pane   = $(`#${key}-pane`);
    const $stream = $(`#${key}-stream`);
    const $build  = $(`#${key}-build`);
    const $manualToggle = $(`#${key}-manual-toggle`);
    const $manualInput  = $(`#${key}-manual-input`);

    // Streams
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

    // Builds
    $build.prop('disabled', true).select2({
      width: '100%',
      allowClear: true,
      placeholder: $build.data('placeholder') || 'Choose a build',
      minimumInputLength: 0,
      ajax: {
        url: '/api/builds',
        dataType: 'json',
        delay: 250,
        cache: true,
        transport: (params, ok, fail) => {
          if (!$stream.val()) { ok({ results: [], pagination: { more: false } }); return; }
          return $.ajax(params).then(ok, fail);
        },
        data: params => ({ app, stream_id: $stream.val(), q: params.term || '', page: params.page || 1 }),
        processResults: data => ({
          results: data.results || [],
          pagination: { more: data.pagination && data.pagination.more }
        })
      },
      dropdownParent: $pane
    });

    // Summary helpers
    const setSummary = (buildVal) => {
      const streamVal = $stream.val() || '';
      $(`#summary-${key}`).val(buildVal || '');
      $(`#hidden-${key}-stream`).val(streamVal);
      $(`#hidden-${key}-build`).val(buildVal || '');
    };

    // Events
    $stream.on('select2:select select2:clear', () => {
      const hasStream = !!$stream.val();
      if ($manualToggle.is(':checked')) {
        setSummary($manualInput.val().trim());
      } else {
        $build.prop('disabled', !hasStream).val(null).trigger('change');
        setSummary('');
      }
    });

    $build.on('select2:select select2:clear', () => {
      setSummary($build.val() || '');
    });

    $manualToggle.on('change', function () {
      const on = this.checked;
      const $buildS2 = $build.next('.select2');
      if (on) {
        $buildS2.addClass('d-none');
        $build.prop('disabled', true).val(null).trigger('change');
        $manualInput.removeClass('d-none').focus();
        setSummary($manualInput.val().trim());
      } else {
        $manualInput.addClass('d-none');
        $buildS2.removeClass('d-none');
        $build.prop('disabled', !$stream.val());
        setSummary($build.val() || '');
      }
    });

    $manualInput.on('input', () => {
      if ($manualToggle.is(':checked')) setSummary($manualInput.val().trim());
    });
  }

  // On ready
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
