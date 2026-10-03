// BEAR UI: uploads the photo folder, starts the run, then polls /api/status for progress.
(function () {
  'use strict';

  var PHOTO = /\.(jpe?g|png)$/i;
  var SHEETS_URL = 'https://docs.google.com/spreadsheets/u/0/';
  var $ = function (id) { return document.getElementById(id); };
  var st = { job: null, uploading: false, uploaded: false, state: 'idle', step: 0, detail: '', steps: [], logLength: 0, results: null, canOpen: false };
  var stepsKey = '';  // last rendered progress list, so the spinner is not restarted by unrelated updates

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function api(method, url, body) {
    return fetch(url, { method: method, headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined })
      .then(function (r) { return r.json().then(function (d) { if (!r.ok) throw new Error(d.error || r.statusText); return d; }); });
  }

  function setPct(p) {
    $('bar').setAttribute('aria-valuenow', p);
    $('barFill').style.width = p + '%';
    $('pct').textContent = 'Upload ' + p + '%';
  }

  // Errors appear in the section they belong to: photoError (upload), goError (run), resError (results).
  function showError(msg, where) {
    var el = $(where || 'goError');
    el.textContent = msg || '';
    el.hidden = !msg;
  }

  // Step icons. Colours come from the stylesheet (.ok green, .bad red); every icon carries alt text.
  var ICONS = {
    done: function (alt) { return '<svg class="ok" width="28" height="28" viewBox="0 0 28 28" fill="none" role="img" aria-label="' + alt + '"><circle cx="14" cy="14" r="13" stroke="currentColor" stroke-width="2"></circle><path d="M8 14.5l4 4 8-9" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"></path></svg>'; },
    active: function (alt) { return '<span class="spin" role="img" aria-label="' + alt + '"></span>'; },
    failed: function (alt) { return '<svg class="bad" width="28" height="28" viewBox="0 0 28 28" fill="none" role="img" aria-label="' + alt + '"><circle cx="14" cy="14" r="13" stroke="currentColor" stroke-width="2"></circle><path d="M9.5 9.5l9 9M18.5 9.5l-9 9" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"></path></svg>'; },
    pending: function (alt) { return '<span class="dot" role="img" aria-label="' + alt + '"></span>'; }
  };
  var WORDS = { done: 'done', active: 'in progress', failed: 'failed', pending: 'waiting' };

  function renderSteps() {
    var running = st.state === 'running', failed = st.state === 'failed';
    var key = [st.state, st.step, st.detail, st.steps.join('|')].join('~');
    if (key === stepsKey) return;
    stepsKey = key;
    $('steps').innerHTML = st.steps.map(function (label, i) {
      var kind = i < st.step ? 'done' : (i === st.step && running ? 'active' : (i === st.step && failed ? 'failed' : 'pending'));
      var text = esc(label) + (kind === 'active' && st.detail ? ' (' + esc(st.detail) + ')' : '');
      return '<li class="step ' + kind + '">' +
        '<span class="step-icon">' + ICONS[kind](esc(label + ': ' + WORDS[kind])) + '</span>' +
        '<span class="step-text">' + text + '</span></li>';
    }).join('');
  }

  function render() {
    var running = st.state === 'running';
    var canGo = st.uploaded && !st.uploading && !running && $('car').value.trim() !== '';
    $('go').disabled = !canGo;
    $('pick').disabled = st.uploading || running;
    renderSteps();
    var r = st.results, done = st.state === 'done' && r;
    $('dlXlsx').disabled = !done;
    $('openXlsx').disabled = !done;
    $('reveal').hidden = !st.canOpen;
    $('reveal').disabled = !done;
    if (done) {
      var parts = [r.photos + (r.photos === 1 ? ' photo: ' : ' photos: ') + r.priced + ' priced, ' + r.failed + ' not priced'];
      if (r.nulls) parts.push(r.nulls + ' NULL skipped');
      if (r.cost != null) parts.push('cost $' + r.cost.toFixed(4));
      $('resLabel').textContent = 'results.xlsx is ready. ' + parts.join(', ') + '.';
    } else if (st.state === 'failed') {
      $('resLabel').textContent = 'The run failed. Check the BEAR server output for details.';
    } else {
      $('resLabel').textContent = running ? 'Working on it...' : 'Available when the run finishes';
    }
  }

  function poll() {
    api('GET', '/api/status?since=' + st.logLength).then(function (d) {
      (d.models || []).forEach(function (m, i) {
        var el = document.querySelector('.model[data-agent="' + i + '"]');
        if (el) { el.textContent = m.split('/').pop(); el.parentNode.parentNode.title = 'Agent ' + (i + 1) + ' uses ' + m + '. Choosing models is coming later.'; }
      });
      if (d.version) $('version').textContent = 'Version ' + d.version.replace(/\.0$/, '');
      st.logLength = d.logLength;  // tells the server how much log we have already seen; the page no longer shows it
      st.state = d.state; st.step = d.step; st.detail = d.detail; st.steps = d.steps;
      st.results = d.results; st.canOpen = d.canOpen;
      if (d.job && d.job !== st.job && !st.uploading) {  // page reloaded: pick the server's folder back up
        st.job = d.job; st.uploaded = true; setPct(100);
        $('folderLabel').textContent = d.folder + ' uploaded';
      }
      render();
    }).catch(function () { /* server restarting or stopped; keep trying */ })
      .then(function () { setTimeout(poll, st.state === 'running' || st.uploading ? 500 : 1500); });
  }

  function putFile(job, file, onProgress) {
    return new Promise(function (resolve, reject) {
      var x = new XMLHttpRequest();
      x.open('PUT', '/api/upload/' + job + '/' + encodeURIComponent(file.name));
      x.upload.onprogress = function (e) { onProgress(e.loaded); };
      x.onload = function () {
        if (x.status === 200) { onProgress(file.size); resolve(); }
        else { var m = 'Upload failed'; try { m = JSON.parse(x.responseText).error; } catch (e) {} reject(new Error(file.name + ': ' + m)); }
      };
      x.onerror = function () { reject(new Error(file.name + ': upload failed')); };
      x.send(file);
    });
  }

  function upload(files) {
    // Same rule as the bear command: photos directly inside the chosen folder only.
    var all = Array.prototype.slice.call(files);
    var name = all.length ? (all[0].webkitRelativePath || '').split('/')[0] : '';
    var photos = all.filter(function (f) { return PHOTO.test(f.name) && (f.webkitRelativePath || '').split('/').length === 2; });
    if (!photos.length) { showError('No .jpg/.jpeg/.png photos found directly inside that folder.', 'photoError'); return; }
    showError('', 'photoError');
    var total = photos.reduce(function (a, f) { return a + f.size; }, 0) || 1;
    var loaded = photos.map(function () { return 0; });
    st.uploading = true; st.uploaded = false; setPct(0);
    $('folderLabel').textContent = 'Uploading ' + name;
    render();
    api('POST', '/api/folder', { name: name }).then(function (d) {
      st.job = d.job;
      var next = 0;
      function worker() {
        if (next >= photos.length) return Promise.resolve();
        var i = next++;
        return putFile(d.job, photos[i], function (n) {
          loaded[i] = n;
          setPct(Math.floor(100 * loaded.reduce(function (a, b) { return a + b; }, 0) / total));
        }).then(worker);
      }
      return Promise.all([worker(), worker(), worker()]).then(function () { return api('POST', '/api/uploaded', { job: d.job }); });
    }).then(function () {
      setPct(100);
      st.uploaded = true;
      $('folderLabel').textContent = name + ' uploaded (' + photos.length + ' photos)';
    }).catch(function (e) {
      $('folderLabel').textContent = 'Upload failed';
      showError(e.message, 'photoError');
    }).then(function () { st.uploading = false; render(); });
  }

  function download(url) {
    var a = document.createElement('a');
    a.href = url; a.download = '';
    document.body.appendChild(a); a.click(); a.remove();
  }

  $('pick').addEventListener('click', function () { $('folder').value = ''; $('folder').click(); });
  $('folder').addEventListener('change', function (e) { if (e.target.files.length) upload(e.target.files); });
  $('car').addEventListener('input', render);
  $('car').addEventListener('keydown', function (e) { if (e.key === 'Enter' && !$('go').disabled) $('go').click(); });
  $('go').addEventListener('click', function () {
    showError('');
    st.state = 'running'; st.step = 0; st.detail = ''; st.results = null; render();
    api('POST', '/api/run', { job: st.job, vehicle: $('car').value.trim() })
      .catch(function (e) { st.state = 'idle'; showError(e.message); render(); });
  });
  $('dlXlsx').addEventListener('click', function () { download('/api/results.xlsx'); });
  $('openXlsx').addEventListener('click', function () { window.open(SHEETS_URL, '_blank', 'noopener'); });
  $('reveal').addEventListener('click', function () { showError('', 'resError'); api('POST', '/api/reveal').catch(function (e) { showError(e.message, 'resError'); }); });

  poll();
})();
