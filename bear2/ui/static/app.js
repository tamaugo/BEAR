// BEAR UI: uploads the photo folder, starts the run, then polls /api/status for progress
// and shows the run's questions (first-line check, failed name model) for the operator to answer.
(function () {
  'use strict';

  var PHOTO = /\.(jpe?g|png)$/i;
  var SHEETS_URL = 'https://docs.google.com/spreadsheets/u/0/';
  var $ = function (id) { return document.getElementById(id); };
  var st = { job: null, uploading: false, uploaded: false, state: 'idle', step: 0, detail: '', steps: [], logLength: 0, results: null, canOpen: false,
    question: null, error: null, canFinish: false };
  var stepsKey = '';  // last rendered progress list, so the spinner is not restarted by unrelated updates
  var configs = {}, configsKey = '';  // model setups from the server, by id; the page always opens on the first (default)
  var namesKey = '', serverName = '';  // name model drop-down, and the server's kept model it last showed
  var askKey = '', answered = 0;       // last rendered question, and the id of the last one answered here
  var names = {};                      // name model id -> label
  var bannerKey = '', closedKey = '';  // error shown in the banner, and the one the operator closed
  var check = { line: '', note: '', model: '', rejected: {}, pick: '' };  // first-line check shown above GO

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

  // Model setups: one drop-down of whole setups (bear2/configs.py), never one model per agent.
  function renderConfigs(list, current) {
    var key = JSON.stringify(list);
    if (key !== configsKey) {
      configsKey = key;
      configs = {};
      list.forEach(function (c) { configs[c.id] = c; });
      var keep = $('config').value;
      $('config').innerHTML = list.map(function (c) {
        return '<option value="' + esc(c.id) + '">' + esc(c.label) + ' (' + esc(c.tag) + ')</option>';
      }).join('');
      $('config').value = configs[keep] ? keep : list[0].id;
    }
    if (st.state === 'running' && configs[current]) $('config').value = current;  // show what the run is using
    showConfig();
  }

  function showConfig() {
    var c = configs[$('config').value];
    if (!c) return;
    $('configTag').textContent = c.tag;
    $('configTag').className = 'tag ' + c.tag.toLowerCase();
    $('configAbout').textContent = c.about;
    var names = $('nameModel').value ? [['Agent 3 cleans part names', $('nameModel').value]] : [];
    $('configModels').innerHTML = c.models.concat(names).map(function (m) {
      return '<dt>' + esc(m[0]) + '</dt><dd>' + esc(m[1]) + '</dd>';
    }).join('');
  }

  // Name model (Agent 3): the server keeps the one that last worked until `bear ui` closes, so
  // the drop-down follows it whenever it changes there (a model approved at the first-line check).
  function renderNames(list, current) {
    var key = JSON.stringify(list);
    if (key !== namesKey) {
      namesKey = key;
      names = {};
      list.forEach(function (m) { names[m[0]] = m[1].replace(/ \(Default\)$/, ''); });
      $('nameModel').innerHTML = list.map(function (m) {
        return '<option value="' + esc(m[0]) + '">' + esc(m[1]) + '</option>';
      }).join('');
      serverName = '';
    }
    if (current !== serverName) { serverName = current; $('nameModel').value = current; }
  }

  function modelOf(label) {
    for (var id in names) if (names[id] === label) return id;
    return '';
  }

  function pending(kind) {
    var q = st.question;
    return q && q.id !== answered && q.kind === kind ? q : null;
  }

  // The name model failed (try again / switch / stop): answered from the banner and the model drop-down.
  function failing() {
    var e = st.error;
    return e && e.ask && e.ask !== answered ? e : null;
  }

  // Run errors drop down from the top: a code, what to do, and the full error under Info.
  function renderBanner() {
    var e = st.error && (!st.error.ask || failing()) ? st.error : null;
    var key = e ? e.code + e.title + (e.ask || '') : '';
    if (key !== bannerKey) {
      bannerKey = key;
      if (e) {
        $('bannerCode').textContent = e.code;
        $('bannerTitle').textContent = e.title;
        $('bannerDetail').textContent = e.detail;
        $('bannerActions').hidden = !e.ask;
        $('banner').querySelector('details').open = false;
      }
    }
    var open = !!e && key !== closedKey;
    $('banner').classList.toggle('open', open);
  }

  // The first-line check: the finished line shows in the output field above GO. GO approves it;
  // picking another model in the drop-down rejects it and checks again with that model.
  function renderCheck() {
    var q = pending('check');
    if (q) {
      var m = /names by (.+)\):/.exec(q.ask);
      check.model = m ? modelOf(m[1]) : '';
      check.line = (q.ask.split('\n')[1] || '').trim().split(' | ')[0];
      check.note = '';
    }
    var out = $('checkLine');
    out.textContent = check.line || check.note || 'Output name (part name, number with car name)';
    out.className = 'input output' + (check.line ? '' : ' placeholder');
    Array.prototype.forEach.call($('nameModel').options, function (o) { o.disabled = !!(q && check.rejected[o.value]); });
    if (q && check.model) $('nameModel').value = check.model;
    var left = Object.keys(names).filter(function (id) { return id !== check.model && !check.rejected[id]; });
    $('checkHint').innerHTML = !q ? '' : left.length
      ? 'Looks right? Press GO. Wrong? Pick another model.'
      : 'Looks right? Press GO. Every other model has been tried. <button type="button" id="noneRight" class="link">None look right</button>';
    $('checkHint').hidden = !q;
  }

  // A question from the run. Lines after the first are the finished results line to check.
  function renderAsk() {
    var q = st.question && st.question.id !== answered && st.question.kind !== 'check' &&
      !(st.error && st.error.ask === st.question.id) ? st.question : null;
    var key = q ? JSON.stringify(q) : '';
    if (key === askKey) return;
    askKey = key;
    if (q && q.kind === 'model' && check.pick) {  // the model was already picked above GO
      var c = q.choices.filter(function (c) { return c[1] === names[check.pick]; })[0];
      check.pick = '';
      if (c) { answer(c[0], q.id); return; }
    }
    $('ask').hidden = !q;
    if (!q) { $('ask').innerHTML = ''; return; }
    var lines = q.ask.split('\n'), title = lines.shift();
    var shown = lines.map(function (l) { return l.trim(); }).filter(Boolean).map(function (l) {
      var f = l.split(' | ');  // info | price | url | image
      return '<div class="listing"><span>' + esc(f[0]) + '</span>' +
        (f.length >= 4 ? '<span class="small">£' + esc(f[1]) + ' · ' + esc(f[f.length - 1]) + '</span>' : '') + '</div>';
    }).join('');
    var stop = q.choices.filter(function (c) { return c[0] === 'q'; });
    var rest = q.choices.filter(function (c) { return c[0] !== 'q'; });
    var buttons = function (list, first) {
      return list.map(function (c, i) {
        return '<button type="button" class="btn' + (i || !first ? ' quiet' : '') + '" data-key="' + esc(c[0]) + '">' + esc(c[1]) + '</button>';
      }).join('');
    };
    var body = q.kind === 'model'
      ? '<select id="askModel" class="input select">' +
          rest.map(function (c) { return '<option value="' + esc(c[0]) + '">' + esc(c[1]) + '</option>'; }).join('') +
        '</select><div class="row"><button type="button" class="btn" data-pick="1">Check with this model</button>' + buttons(stop, false) + '</div>'
      : '<div class="row">' + buttons(rest.concat(stop), true) + '</div>';
    var head = q.kind === 'model' ? '<label id="askTitle" for="askModel" class="ask-title">' + esc(title) + '</label>'
      : '<span id="askTitle" class="ask-title">' + esc(title) + '</span>';
    $('ask').innerHTML = head + shown + body;
    var focus = $('ask').querySelector('select, button');
    if (focus) focus.focus();
  }

  function answer(key, id) {
    id = id || (st.question && st.question.id);
    answered = id;
    renderAsk();
    renderCheck();
    renderBanner();
    api('POST', '/api/answer', { id: id, key: key }).catch(function (e) { showError(e.message); });
  }

  function render() {
    var running = st.state === 'running';
    $('config').disabled = running;
    var checking = !!pending('check') || !!failing();
    $('nameModel').disabled = running && !checking;
    var canGo = checking || (st.uploaded && !st.uploading && !running && $('car').value.trim() !== '');
    $('go').disabled = !canGo;
    $('pick').disabled = st.uploading || running;
    renderSteps();
    renderAsk();
    renderCheck();
    renderBanner();
    $('finishNames').hidden = !st.canFinish;
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
    } else if (st.canFinish) {
      $('resLabel').textContent = 'The photo reads and eBay results are saved. Pick a name model above, then finish the names.';
    } else if (st.state === 'failed') {
      $('resLabel').textContent = 'The run stopped.';
    } else {
      $('resLabel').textContent = running ? 'Working on it...' : 'Available when the run finishes';
    }
  }

  function poll() {
    api('GET', '/api/status?since=' + st.logLength).then(function (d) {
      if (d.version) $('version').textContent = 'Version ' + d.version.replace(/\.0$/, '');
      st.logLength = d.logLength;  // tells the server how much log we have already seen; the page no longer shows it
      st.state = d.state; st.step = d.step; st.detail = d.detail; st.steps = d.steps;
      st.results = d.results; st.canOpen = d.canOpen;
      st.question = d.question; st.error = d.error; st.canFinish = d.canFinish;
      if (d.nameModels && d.nameModels.length) renderNames(d.nameModels, d.nameModel);
      if (d.configs && d.configs.length) renderConfigs(d.configs, d.config);
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
  $('config').addEventListener('change', showConfig);
  $('nameModel').addEventListener('change', function () {
    if (failing()) {  // the name model failed: switch to the one picked (its line is checked first)
      check.pick = $('nameModel').value;
      check.line = '';
      check.note = 'Checking with ' + names[check.pick] + '...';
      answer('m', failing().ask);
    } else if (pending('check')) {  // wrong line: reject this model and check again with the one picked
      check.rejected[check.model] = true;
      check.pick = $('nameModel').value;
      check.line = '';
      check.note = 'Checking with ' + names[check.pick] + '...';
      answer('n');
    }
    showConfig();
  });
  $('bannerClose').addEventListener('click', function () { closedKey = bannerKey; renderBanner(); });
  $('bannerRetry').addEventListener('click', function () { if (failing()) answer('r', failing().ask); render(); });
  $('bannerStop').addEventListener('click', function () { if (failing()) answer('q', failing().ask); render(); });
  $('bannerModel').addEventListener('click', function () {
    $('nameModel').scrollIntoView({ block: 'center', behavior: 'smooth' });
    $('nameModel').focus();
  });
  $('checkHint').addEventListener('click', function (e) {
    if (e.target.id === 'noneRight') { check.rejected[check.model] = true; answer('n'); }
  });
  $('ask').addEventListener('click', function (e) {
    var b = e.target.closest('button');
    if (b) answer(b.hasAttribute('data-pick') ? $('askModel').value : b.getAttribute('data-key'));
  });
  $('car').addEventListener('keydown', function (e) { if (e.key === 'Enter' && !$('go').disabled) $('go').click(); });
  $('go').addEventListener('click', function () {
    if (pending('check')) { answer('y'); render(); return; }  // the line looks right
    showError('');
    check = { line: '', note: '', model: '', rejected: {}, pick: '' };
    st.state = 'running'; st.step = 0; st.detail = ''; st.results = null; st.error = null; st.canFinish = false; render();
    api('POST', '/api/run', { job: st.job, vehicle: $('car').value.trim(), config: $('config').value, nameModel: $('nameModel').value })
      .catch(function (e) { st.state = 'idle'; showError(e.message); render(); });
  });
  $('finishNames').addEventListener('click', function () {
    showError('', 'resError');
    check = { line: '', note: '', model: '', rejected: {}, pick: '' };
    st.state = 'running'; st.step = 0; st.detail = ''; st.error = null; st.canFinish = false; render();
    api('POST', '/api/finish', { job: st.job, nameModel: $('nameModel').value })
      .catch(function (e) { st.state = 'failed'; showError(e.message, 'resError'); render(); });
  });
  $('dlXlsx').addEventListener('click', function () { download('/api/results.xlsx'); });
  $('openXlsx').addEventListener('click', function () { window.open(SHEETS_URL, '_blank', 'noopener'); });
  $('reveal').addEventListener('click', function () { showError('', 'resError'); api('POST', '/api/reveal').catch(function (e) { showError(e.message, 'resError'); }); });

  poll();
})();
