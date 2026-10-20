/* Shared by /chats and the dashboard's chat page: drawing rich messages
   (photos, videos, files, locations, calls) and voice/video calls (WebRTC).
   Everything is built with DOM methods — message text is never parsed as HTML. */
(function () {
  'use strict';

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function mapSrc(lat, lng) {
    var d = 0.006;
    return 'https://www.openstreetmap.org/export/embed.html?bbox=' + (lng - d) + ',' + (lat - d) + ',' +
      (lng + d) + ',' + (lat + d) + '&layer=mapnik&marker=' + lat + ',' + lng;
  }

  // A clean little map for a chat bubble: CARTO (OpenStreetMap data) tiles around the point and a pin
  // (no embedded page, so no buttons or credits cluttering it, and nothing to load but pictures).
  function staticMap(box, lat, lng) {
    var z = 15, n = Math.pow(2, z), r = lat * Math.PI / 180;
    var px = (lng + 180) / 360 * n * 256, py = (1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2 * n * 256;
    var cx = Math.floor(px / 256), cy = Math.floor(py / 256);
    box.textContent = '';
    var layer = el('div', 'sm-layer');
    for (var dx = -1; dx <= 1; dx++) for (var dy = -1; dy <= 1; dy++) {
      var tx = cx + dx, ty = cy + dy;
      if (ty < 0 || ty >= n) continue;
      var t = el('img', 'sm-tile'); t.alt = ''; t.draggable = false; t.loading = 'lazy';
      t.src = 'https://a.basemaps.cartocdn.com/rastertiles/voyager/' + z + '/' + ((tx % n) + n) % n + '/' + ty + '.png';
      t.style.left = Math.round(tx * 256 - px) + 'px'; t.style.top = Math.round(ty * 256 - py) + 'px';
      layer.appendChild(t);
    }
    box.appendChild(layer);
    var pin = el('span', 'sm-pin'); pin.innerHTML = '<i class="fas fa-location-dot"></i>'; box.appendChild(pin);
    box.appendChild(el('span', 'sm-credit', '© OpenStreetMap © CARTO'));
  }

  function liveLabel(loc) {
    if (!loc.live_until) return 'Location';
    if (!loc.live) return 'Live location ended';
    var mins = Math.max(1, Math.round((new Date(loc.live_until) - new Date()) / 60000));
    return 'Live location · ' + (mins >= 60 ? Math.round(mins / 60) + ' h' : mins + ' min') + ' left';
  }

  // Fills a bubble's content area for message m.
  function renderBody(box, m) {
    box.textContent = '';
    if (m.once) { box.appendChild(onceBubble(m)); return; }
    if (m.kind === 'image' && m.url) {
      var img = el('img', 'att-img');
      img.src = m.url; img.alt = m.name || 'Photo'; img.loading = 'lazy'; img.draggable = false;
      img.addEventListener('click', function () { openViewer(m.url, m.name); });
      img.addEventListener('contextmenu', function (e) { if (!api.canSave) e.preventDefault(); });
      box.appendChild(img);
      if (api.canSave) box.appendChild(saveButton(m.url, m.name || 'photo'));
    } else if (m.kind === 'video' && m.url) {
      var v = el('video', 'att-video');
      v.src = m.url; v.controls = true; v.preload = 'metadata'; v.playsInline = true;
      v.setAttribute('controlsList', 'nodownload noplaybackrate'); v.disablePictureInPicture = true;
      v.addEventListener('contextmenu', function (e) { if (!api.canSave) e.preventDefault(); });
      box.appendChild(v);
      if (api.canSave) box.appendChild(saveButton(m.url, m.name || 'video'));
    } else if (m.kind === 'file' && m.url) {
      var a = el('a', 'att-file');
      a.href = m.url; a.target = '_blank'; a.rel = 'noopener';
      var ic = el('i', 'fas fa-file-lines'); a.appendChild(ic);
      a.appendChild(el('span', 'att-file-name', m.name || 'File'));
      a.appendChild(el('i', 'fas fa-download att-file-dl'));
      box.appendChild(a);
    } else if (m.kind === 'location' && m.lat != null) {
      var wrap = el('div', 'att-loc');
      wrap.dataset.locId = m.id;
      var frame = el('div', 'att-map');
      staticMap(frame, m.lat, m.lng);
      wrap.appendChild(frame);
      var row = el('div', 'att-loc-row');
      var label = el('span', 'att-loc-label' + (m.live ? ' live' : ''));
      label.textContent = liveLabel(m);
      row.appendChild(label);
      var open = el('a', 'att-loc-open', 'Open in Maps');
      open.href = 'https://www.google.com/maps?q=' + m.lat + ',' + m.lng; open.target = '_blank'; open.rel = 'noopener';
      row.appendChild(open);
      wrap.appendChild(row);
      box.appendChild(wrap);
      wrap._loc = { lat: m.lat, lng: m.lng, live: !!m.live, live_until: m.live_until, updated: m.updated, who: m.name || '' };
      wrap.title = 'Open the map';
      wrap.addEventListener('click', function (e) { if (!e.target.closest('.att-loc-open')) openMap(wrap); });
    } else if (m.kind === 'sticker' && /^[0-9a-f_]+$/.test(m.body || '')) {
      box.classList.add('is-sticker');
      var st = el('img', 'att-sticker');
      st.src = 'https://fonts.gstatic.com/s/e/notoemoji/latest/' + m.body + '/512.webp';
      st.alt = 'Sticker'; st.loading = 'lazy'; st.draggable = false;
      box.appendChild(st);
      return;
    } else if (m.kind === 'gif' && /^https:\/\/(media\d?\.giphy\.com|i\.giphy\.com|media\.tenor\.com)\//.test(m.body || '')) {
      box.classList.add('is-gif');
      var gw = el('a', 'att-gif'); gw.href = m.body; gw.target = '_blank'; gw.rel = 'noopener noreferrer';
      var gi = el('img'); gi.src = m.body; gi.alt = 'GIF'; gi.loading = 'lazy'; gi.draggable = false;
      gi.onerror = function () { gw.classList.add('broken'); gw.removeAttribute('href'); gw.textContent = ''; gw.appendChild(el('i', 'fas fa-film')); gw.appendChild(el('span', '', 'GIF unavailable')); };
      gw.appendChild(gi); gw.appendChild(el('span', 'att-gif-tag', 'GIF'));
      box.appendChild(gw);
      return;
    } else if (m.kind === 'voice' && m.url) {
      box.appendChild(voicePlayer(m));
      return;
    } else if (m.kind === 'call') {
      var call = el('div', 'att-call');
      var missed = /missed|declined/i.test(m.body);
      call.appendChild(el('i', 'fas ' + (/video/i.test(m.body) ? 'fa-video' : 'fa-phone') + (missed ? ' missed' : '')));
      call.appendChild(el('span', '', m.body));
      box.appendChild(call);
      return;
    }
    if (m.body && m.kind !== 'location') box.appendChild(el('div', 'msg-text', m.body));
  }

  // ── voice messages ──────────────────────────────────────────────────────────
  // A WhatsApp-style player: play / pause, a waveform you can tap to jump, the
  // length, and 1× / 1.5× / 2× speed. Only one plays at a time. Recordings from
  // Chrome don't carry their length, so the "m:ss" saved with the message is used.
  var playingVoice = null;
  function fmtTime(s) { s = Math.max(0, Math.round(s || 0)); return Math.floor(s / 60) + ':' + ('0' + s % 60).slice(-2); }
  function parseTime(t) { var m = /^(\d+):(\d\d)$/.exec(t || ''); return m ? +m[1] * 60 + +m[2] : 0; }
  function voicePlayer(m) {
    var wrap = el('div', 'att-voice'), known = parseTime(m.body);
    var play = el('button', 'vn-play'); play.type = 'button'; play.setAttribute('aria-label', 'Play voice message');
    play.innerHTML = '<i class="fas fa-play"></i>';
    var main = el('div', 'vn-main'), wave = el('div', 'vn-wave'), meta = el('div', 'vn-meta');
    var time = el('span', 'vn-time', fmtTime(known)), speed = el('button', 'vn-speed', '1×');
    speed.type = 'button'; speed.title = 'Playback speed';
    var seed = 0, key = String(m.id || m.url || '');
    for (var i = 0; i < key.length; i++) seed = (seed * 31 + key.charCodeAt(i)) >>> 0;
    var bars = [];
    for (var b = 0; b < 32; b++) {
      seed = (seed * 1103515245 + 12345) >>> 0;
      var h = 22 + (seed % 70) * (0.55 + 0.45 * Math.sin(b / 3));
      var bar = el('i'); bar.style.height = Math.max(14, Math.min(100, Math.round(h))) + '%';
      wave.appendChild(bar); bars.push(bar);
    }
    meta.appendChild(time); meta.appendChild(speed);
    main.appendChild(wave); main.appendChild(meta);
    wrap.appendChild(play); wrap.appendChild(main);
    wrap.appendChild(el('span', 'vn-mic')).innerHTML = '<i class="fas fa-microphone"></i>';
    var audio = null, rate = 1;
    function length() { return audio && isFinite(audio.duration) && audio.duration > 0 ? audio.duration : known || 1; }
    function paint() {
      var at = audio ? audio.currentTime : 0, frac = Math.min(1, at / length());
      bars.forEach(function (bar, n) { bar.classList.toggle('on', n / bars.length < frac); });
      time.textContent = audio && (at > 0 || !audio.paused) ? fmtTime(at) : fmtTime(length());
    }
    function ensure() {
      if (audio) return audio;
      audio = new Audio(); audio.preload = 'metadata'; audio.src = m.url;
      audio.addEventListener('timeupdate', paint);
      audio.addEventListener('loadedmetadata', function () {
        // Chrome's webm recordings report Infinity until it has seen the end once
        if (audio.duration === Infinity) { audio.currentTime = 1e7; audio.addEventListener('durationchange', function once() { audio.removeEventListener('durationchange', once); audio.currentTime = 0; paint(); }); }
        paint();
      });
      audio.addEventListener('play', function () { play.innerHTML = '<i class="fas fa-pause"></i>'; wrap.classList.add('playing'); });
      audio.addEventListener('pause', function () { play.innerHTML = '<i class="fas fa-play"></i>'; wrap.classList.remove('playing'); });
      audio.addEventListener('ended', function () { audio.currentTime = 0; paint(); });
      audio.addEventListener('error', function () { wrap.classList.add('broken'); time.textContent = 'Not available'; });
      return audio;
    }
    play.addEventListener('click', function (e) {
      e.stopPropagation();
      var a = ensure();
      if (a.paused) {
        if (playingVoice && playingVoice !== a) playingVoice.pause();
        playingVoice = a; a.playbackRate = rate;
        var p = a.play(); if (p && p.catch) p.catch(function () {});
      } else a.pause();
    });
    wave.addEventListener('click', function (e) {
      e.stopPropagation();
      var r = wave.getBoundingClientRect(), a = ensure(), frac = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
      try { a.currentTime = frac * length(); } catch (err) {}
      paint();
    });
    speed.addEventListener('click', function (e) {
      e.stopPropagation();
      rate = rate === 1 ? 1.5 : rate === 1.5 ? 2 : 1;
      speed.textContent = rate + '×';
      if (audio) audio.playbackRate = rate;
    });
    return wrap;
  }

  // The microphone button in a composer. Tap it to record; the bar that opens
  // has delete, pause / resume, and send. opts: { form, textarea, onSend(file, seconds), onError(text), canRecord() }
  var MAX_VOICE_SECONDS = 15 * 60;
  function voiceRecorder(opts) {
    var form = opts.form, area = opts.textarea, sendBtn = form.querySelector('button[type=submit]');
    var mic = el('button', 'round send vn-micbtn'); mic.type = 'button';
    mic.title = 'Record a voice message'; mic.setAttribute('aria-label', 'Record a voice message');
    mic.innerHTML = '<i class="fas fa-microphone"></i>';
    form.insertBefore(mic, sendBtn);
    var bar = el('div', 'vn-rec');
    bar.innerHTML = '<button type="button" class="vn-x" title="Delete" aria-label="Delete recording"><i class="fas fa-trash-can"></i></button>'
      + '<span class="vn-dot"></span><span class="vn-clock">0:00</span><span class="vn-level"></span>'
      + '<button type="button" class="vn-pause" title="Pause" aria-label="Pause recording"><i class="fas fa-pause"></i></button>'
      + '<button type="button" class="round send vn-go" title="Send" aria-label="Send voice message"><i class="fas fa-paper-plane"></i></button>';
    form.appendChild(bar);
    var clock = bar.querySelector('.vn-clock'), levelBox = bar.querySelector('.vn-level'), pauseBtn = bar.querySelector('.vn-pause');
    var levels = [];
    for (var i = 0; i < 28; i++) { var lv = el('i'); levelBox.appendChild(lv); levels.push(lv); }
    function sync() { form.classList.toggle('has-text', !!area.value.trim()); }
    area.addEventListener('input', sync);
    form.addEventListener('submit', function () { setTimeout(sync, 0); });
    sync();

    var rec = null, stream = null, chunks = [], started = 0, elapsed = 0, timer = null, sendIt = false, paused = false;
    var audioCtx = null, analyser = null, raf = null, history = [];
    function pickType() {
      var types = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4;codecs=mp4a.40.2', 'audio/mp4', 'audio/aac'];
      for (var n = 0; n < types.length; n++) { try { if (MediaRecorder.isTypeSupported(types[n])) return types[n]; } catch (e) {} }
      return '';
    }
    function seconds() { return elapsed + (paused || !started ? 0 : (Date.now() - started) / 1000); }
    function tick() { var sec = seconds(); clock.textContent = fmtTime(sec); if (sec >= MAX_VOICE_SECONDS) stop(true); }
    function meter() {
      if (!analyser) return;
      var data = new Uint8Array(analyser.fftSize); analyser.getByteTimeDomainData(data);
      var peak = 0;
      for (var n = 0; n < data.length; n++) peak = Math.max(peak, Math.abs(data[n] - 128));
      history.push(paused ? 0 : Math.min(1, peak / 64)); if (history.length > levels.length) history.shift();
      levels.forEach(function (lv, n) { var v = history[n - (levels.length - history.length)] || 0; lv.style.height = Math.max(12, Math.round(v * 100)) + '%'; });
      raf = requestAnimationFrame(meter);
    }
    function start() {
      if (rec) return;
      if (opts.canRecord && !opts.canRecord()) return;
      if (!window.MediaRecorder || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        return opts.onError(window.isSecureContext === false ? 'Voice messages need the secure (https) EduChats site.' : 'Voice messages are not supported in this browser.');
      }
      navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } }).then(function (s) {
        stream = s; chunks = []; sendIt = false; paused = false; elapsed = 0; history = [];
        var type = pickType();
        try { rec = new MediaRecorder(s, type ? { mimeType: type, audioBitsPerSecond: 32000 } : undefined); }
        catch (e) { rec = new MediaRecorder(s); }
        rec.ondataavailable = function (e) { if (e.data && e.data.size) chunks.push(e.data); };
        rec.onstop = finish;
        rec.start(500);
        started = Date.now();
        form.classList.add('recording'); form.classList.remove('paused');
        pauseBtn.innerHTML = '<i class="fas fa-pause"></i>'; pauseBtn.title = 'Pause';
        tick(); timer = setInterval(tick, 250);
        try {
          var AC = window.AudioContext || window.webkitAudioContext;
          audioCtx = new AC(); analyser = audioCtx.createAnalyser(); analyser.fftSize = 512;
          audioCtx.createMediaStreamSource(s).connect(analyser); meter();
        } catch (e) { analyser = null; }
      }).catch(function (err) {
        opts.onError(err && (err.name === 'NotAllowedError' || err.name === 'SecurityError')
          ? 'Allow the microphone for EduChats to record voice messages (🔒 in the address bar → Microphone).'
          : err && err.name === 'NotFoundError' ? 'No microphone was found on this device.' : 'Could not start the microphone.');
      });
    }
    function stop(send) {
      if (!rec) return;
      sendIt = send;
      clearInterval(timer); cancelAnimationFrame(raf);
      if (!paused) elapsed += (Date.now() - started) / 1000;
      started = 0;
      if (rec.state !== 'inactive') { try { rec.requestData(); } catch (e) {} rec.stop(); } else finish();
    }
    function finish() {
      var type = (rec && rec.mimeType) || 'audio/webm', secs = elapsed;
      if (stream) stream.getTracks().forEach(function (t) { t.stop(); });
      if (audioCtx) { try { audioCtx.close(); } catch (e) {} }
      stream = null; audioCtx = null; analyser = null; rec = null;
      form.classList.remove('recording', 'paused');
      if (!sendIt || !chunks.length) return;
      if (secs < 1) return opts.onError('That voice message was too short.');
      var mime = type.split(';')[0], ext = /ogg/.test(mime) ? '.ogg' : /mp4|aac|m4a/.test(mime) ? '.m4a' : '.webm';
      var blob = new Blob(chunks, { type: mime });
      var file;
      try { file = new File([blob], 'voice' + ext, { type: mime }); } catch (e) { file = blob; file.name = 'voice' + ext; }
      opts.onSend(file, Math.max(1, Math.round(secs)));
    }
    mic.addEventListener('click', start);
    bar.querySelector('.vn-x').addEventListener('click', function () { stop(false); });
    bar.querySelector('.vn-go').addEventListener('click', function () { stop(true); });
    pauseBtn.addEventListener('click', function () {
      if (!rec) return;
      if (!paused && rec.state === 'recording') {
        rec.pause(); elapsed += (Date.now() - started) / 1000; paused = true;
        form.classList.add('paused'); pauseBtn.innerHTML = '<i class="fas fa-microphone"></i>'; pauseBtn.title = 'Resume';
      } else if (paused) {
        rec.resume(); started = Date.now(); paused = false;
        form.classList.remove('paused'); pauseBtn.innerHTML = '<i class="fas fa-pause"></i>'; pauseBtn.title = 'Pause';
      }
    });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && rec) stop(false); });
    return { busy: function () { return !!rec; }, cancel: function () { stop(false); } };
  }

  // Moves live-location pins already on screen.
  function updateLocations(root, locations) {
    (locations || []).forEach(function (loc) {
      var wrap = root.querySelector('.att-loc[data-loc-id="' + loc.id + '"]');
      if (!wrap) return;
      var label = wrap.querySelector('.att-loc-label');
      label.textContent = liveLabel(loc);
      label.classList.toggle('live', !!loc.live);
      var old = wrap._loc || {};
      var moved = old.lat !== loc.lat || old.lng !== loc.lng;
      wrap._loc = { lat: loc.lat, lng: loc.lng, live: !!loc.live, live_until: loc.live_until, updated: loc.updated, who: old.who || '' };
      if (moved) {
        staticMap(wrap.querySelector('.att-map'), loc.lat, loc.lng);
        wrap.querySelector('.att-loc-open').href = 'https://www.google.com/maps?q=' + loc.lat + ',' + loc.lng;
      }
      if (mapView && mapView.wrap === wrap) mapView.update();
    });
  }

  function csrfToken() {
    if (typeof api.csrf === 'function') return api.csrf();
    if (api.csrf) return api.csrf;
    var c = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    if (c) return decodeURIComponent(c[1]);
    var i = document.querySelector('[name=csrfmiddlewaretoken]');
    return i ? i.value : '';
  }

  // ── view once ──────────────────────────────────────────────────────────────
  // The bubble shows ① Photo / ① Video; the person it was sent to taps it once to
  // see it full screen. After that (and for the sender) it only says "Opened".
  function onceMine(node, m) {
    if (typeof m.mine === 'boolean') return m.mine;
    var b = node.closest('.msg, .th-msg');
    if (!b) return false;
    return b.classList.contains('th-msg') ? b.classList.contains('admin') : b.classList.contains('user');
  }
  function onceBubble(m) {
    var b = el('button', 'att-once'); b.type = 'button';
    var ic = el('span', 'once-ic'), txt = el('span', 'once-txt'), sub = el('small', 'once-sub');
    var label = m.kind === 'video' ? 'Video' : 'Photo';
    function paint(opened) {
      b.classList.toggle('opened', !!opened);
      ic.innerHTML = opened ? '<i class="fas fa-eye-slash"></i>' : '<b>1</b>';
      txt.textContent = opened ? 'Opened' : label;
      sub.textContent = opened ? 'View once ' + label.toLowerCase() : 'View once';
    }
    paint(m.opened);
    var words = el('span', 'once-words'); words.appendChild(txt); words.appendChild(sub);
    b.appendChild(ic); b.appendChild(words);
    setTimeout(function () { if (b.isConnected && onceMine(b, m)) b.classList.add('mine'); }, 0);
    b.addEventListener('click', function () {
      if (b.classList.contains('opened') || b.classList.contains('busy')) return;
      if (onceMine(b, m)) { flashTip(b, 'Only the person you sent it to can open it — one time.'); return; }
      if (!m.open_url) return;
      b.classList.add('busy');
      fetch(m.open_url, { method: 'POST', credentials: 'same-origin', headers: { 'X-CSRFToken': csrfToken() } })
        .then(function (r) { return r.json().catch(function () { return { ok: false, error: 'Could not open it. Please try again.' }; }).then(function (j) { j.status = r.status; return j; }); })
        .then(function (res) {
          b.classList.remove('busy');
          if (res.status === 410) { paint(true); return; }
          if (!res.ok) { flashTip(b, res.error || 'Could not open it.'); return; }
          showOnce(res, function () { paint(true); });
        })
        .catch(function () { b.classList.remove('busy'); flashTip(b, 'Could not reach the server.'); });
    });
    return b;
  }
  function flashTip(anchor, text) {
    var t = el('div', 'once-tip', text);
    document.body.appendChild(t);
    var r = anchor.getBoundingClientRect();
    t.style.left = Math.max(8, Math.min(r.left, window.innerWidth - t.offsetWidth - 8)) + 'px';
    t.style.top = Math.max(8, r.top - t.offsetHeight - 8) + 'px';
    setTimeout(function () { t.classList.add('gone'); setTimeout(function () { t.remove(); }, 300); }, 2200);
  }
  function showOnce(res, done) {
    var v = el('div', 'once-viewer');
    var top = el('div', 'once-top');
    var badge = el('span', 'once-badge'); badge.innerHTML = '<b>1</b>';
    top.appendChild(badge);
    top.appendChild(el('span', 'once-title', 'View once ' + (res.kind === 'video' ? 'video' : 'photo')));
    var x = el('button', 'once-x'); x.type = 'button'; x.setAttribute('aria-label', 'Close'); x.innerHTML = '<i class="fas fa-xmark"></i>';
    top.appendChild(x);
    v.appendChild(top);
    var stage = el('div', 'once-stage'), media;
    if (res.kind === 'video') {
      media = el('video'); media.src = res.url; media.controls = true; media.autoplay = true; media.playsInline = true;
      media.setAttribute('controlsList', 'nodownload noplaybackrate noremoteplayback'); media.disablePictureInPicture = true;
    } else {
      media = el('img'); media.src = res.url; media.alt = ''; media.draggable = false;
    }
    stage.appendChild(media);
    v.appendChild(stage);
    if (res.caption) v.appendChild(el('div', 'once-cap', res.caption));
    v.appendChild(el('div', 'once-note', 'This ' + (res.kind === 'video' ? 'video' : 'photo') + ' can only be viewed once. When you close it, it\'s gone.'));
    v.addEventListener('contextmenu', function (e) { e.preventDefault(); });
    document.body.appendChild(v);
    requestAnimationFrame(function () { v.classList.add('open'); });
    function close() {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('visibilitychange', onHide);
      if (media.pause) media.pause();
      media.removeAttribute('src'); if (media.load) try { media.load(); } catch (e) {}
      v.remove(); done();
    }
    function onKey(e) { if (e.key === 'Escape') close(); }
    function onHide() { if (document.hidden) close(); }   // switching away ends it, like WhatsApp
    x.addEventListener('click', close);
    document.addEventListener('keydown', onKey);
    document.addEventListener('visibilitychange', onHide);
  }

  // ── maps (Leaflet + OpenStreetMap, loaded the first time a map opens) ─────────
  var leafletReady = null;
  function loadLeaflet() {
    if (window.L && window.L.map) return Promise.resolve(window.L);
    if (leafletReady) return leafletReady;
    leafletReady = new Promise(function (resolve, reject) {
      var css = document.createElement('link');
      css.rel = 'stylesheet'; css.href = 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css';
      document.head.appendChild(css);
      var js = document.createElement('script');
      js.src = 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js';
      js.onload = function () { resolve(window.L); };
      js.onerror = function () { leafletReady = null; reject(new Error('map')); };
      document.head.appendChild(js);
    });
    return leafletReady;
  }
  var TILES = {
    // CARTO, not tile.openstreetmap.org — OSM's servers block apps with a 403 "Access blocked" tile.
    map: ['https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', '&copy; OpenStreetMap contributors &copy; CARTO', 19],
    sat: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', 'Imagery &copy; Esri', 19]
  };
  function pinIcon(L, live) {
    return L.divIcon({ className: 'mv-pin-wrap', iconSize: [40, 52], iconAnchor: [20, 50],
      html: '<span class="mv-pin' + (live ? ' live' : '') + '"><i class="fas fa-location-dot"></i></span>' });
  }
  function meIcon(L) { return L.divIcon({ className: 'mv-me-wrap', iconSize: [22, 22], iconAnchor: [11, 11], html: '<span class="mv-me"></span>' }); }
  function km(a, b) {
    var R = 6371, toR = Math.PI / 180, dLat = (b.lat - a.lat) * toR, dLng = (b.lng - a.lng) * toR;
    var h = Math.sin(dLat / 2) * Math.sin(dLat / 2) + Math.cos(a.lat * toR) * Math.cos(b.lat * toR) * Math.sin(dLng / 2) * Math.sin(dLng / 2);
    return 2 * R * Math.asin(Math.sqrt(h));
  }
  function distText(d) { return d < 1 ? Math.round(d * 1000) + ' m away' : (d < 10 ? d.toFixed(1) : Math.round(d)) + ' km away'; }
  var placeCache = {};
  function placeName(lat, lng) {
    var key = lat.toFixed(4) + ',' + lng.toFixed(4);
    if (placeCache[key]) return placeCache[key];
    placeCache[key] = fetch('https://nominatim.openstreetmap.org/reverse?format=jsonv2&zoom=18&lat=' + lat + '&lon=' + lng, { headers: { 'Accept-Language': navigator.language || 'en' } })
      .then(function (r) { return r.json(); }).then(function (j) { return (j && j.display_name) || ''; })
      .catch(function () { delete placeCache[key]; return ''; });
    return placeCache[key];
  }
  function agoText(iso) {
    if (!iso) return '';
    var s = Math.max(0, (Date.now() - new Date(iso)) / 1000);
    return s < 60 ? 'Updated just now' : s < 3600 ? 'Updated ' + Math.round(s / 60) + ' min ago'
      : 'Updated ' + new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  }

  // Full-screen map for a location in a chat: pan / zoom, map or satellite, where you
  // are and how far, directions, open in Maps, share — and a live pin keeps moving.
  var mapView = null;
  function openMap(wrap) {
    if (mapView) mapView.close();
    var loc = wrap._loc;
    var v = el('div', 'map-view');
    v.innerHTML = '<div class="mv-head"><button type="button" class="mv-back" aria-label="Close map"><i class="fas fa-arrow-left"></i></button>' +
      '<div class="mv-title"><b></b><small></small></div><button type="button" class="mv-x" aria-label="Close"><i class="fas fa-xmark"></i></button></div>' +
      '<div class="mv-map"><div class="mv-loading"><i class="fas fa-circle-notch fa-spin"></i> Loading map…</div></div>' +
      '<div class="mv-tools"><button type="button" class="mv-tool" data-t="layers" title="Map / Satellite"><i class="fas fa-layer-group"></i></button>' +
      '<button type="button" class="mv-tool" data-t="pin" title="Back to the pin"><i class="fas fa-location-dot"></i></button>' +
      '<button type="button" class="mv-tool" data-t="me" title="Where I am"><i class="fas fa-location-crosshairs"></i></button></div>' +
      '<div class="mv-card"><div class="mv-place"><span class="mv-ic"><i class="fas fa-location-dot"></i></span><div><b class="mv-addr">Finding the address…</b><small class="mv-meta"></small></div></div>' +
      '<div class="mv-acts"><a class="mv-btn primary" target="_blank" rel="noopener" data-a="dir"><i class="fas fa-diamond-turn-right"></i> Directions</a>' +
      '<a class="mv-btn" target="_blank" rel="noopener" data-a="open"><i class="fas fa-map"></i> Open in Maps</a>' +
      '<button type="button" class="mv-btn" data-a="share"><i class="fas fa-share-nodes"></i> Share</button></div></div>';
    document.body.appendChild(v);
    requestAnimationFrame(function () { v.classList.add('open'); });
    var title = v.querySelector('.mv-title b'), sub = v.querySelector('.mv-title small');
    var addr = v.querySelector('.mv-addr'), meta = v.querySelector('.mv-meta');
    var map = null, pin = null, me = null, meRing = null, watch = null, myPos = null, follow = true, layer = null, layerName = 'map', L = null, lastAddrAt = 0, lastAddrPos = null, tick = null;
    function links() {
      var p = wrap._loc;
      v.querySelector('[data-a="dir"]').href = 'https://www.google.com/maps/dir/?api=1&destination=' + p.lat + ',' + p.lng;
      v.querySelector('[data-a="open"]').href = 'https://www.google.com/maps/search/?api=1&query=' + p.lat + ',' + p.lng;
    }
    function texts() {
      var p = wrap._loc, live = p.live, ended = !live && p.live_until;
      title.textContent = (p.who ? p.who + ' · ' : '') + (live ? 'Live location' : ended ? 'Live location ended' : 'Location');
      sub.textContent = live ? liveLabel(p).replace('Live location · ', '') + ' · ' + agoText(p.updated) : ended ? agoText(p.updated) : p.lat.toFixed(5) + ', ' + p.lng.toFixed(5);
      v.classList.toggle('is-live', !!live);
      var bits = [];
      if (myPos) bits.push(distText(km(myPos, p)));
      bits.push(p.lat.toFixed(5) + ', ' + p.lng.toFixed(5));
      meta.textContent = bits.join(' · ');
    }
    var addrLater = null;
    function lookUp() {
      var p = wrap._loc;
      if (lastAddrPos && km(lastAddrPos, p) < 0.05) return;
      var wait = lastAddrPos ? 15000 - (Date.now() - lastAddrAt) : 0;   // gentle on the free address service
      if (wait > 0) { if (!addrLater) addrLater = setTimeout(function () { addrLater = null; if (v.isConnected) lookUp(); }, wait); return; }
      lastAddrAt = Date.now(); lastAddrPos = { lat: p.lat, lng: p.lng };
      placeName(p.lat, p.lng).then(function (name) { if (v.isConnected) addr.textContent = name || 'Dropped pin'; });
    }
    function update() {
      var p = wrap._loc;
      texts(); links(); lookUp();
      if (pin) { pin.setLatLng([p.lat, p.lng]); pin.setIcon(pinIcon(L, p.live)); if (follow) map.panTo([p.lat, p.lng]); }
    }
    function close() {
      if (watch != null && navigator.geolocation) navigator.geolocation.clearWatch(watch);
      clearInterval(tick); clearTimeout(addrLater);
      document.removeEventListener('keydown', onKey);
      if (map) map.remove();
      v.remove();
      if (mapView === api_) mapView = null;
    }
    function onKey(e) { if (e.key === 'Escape') close(); }
    document.addEventListener('keydown', onKey);
    v.querySelector('.mv-back').addEventListener('click', close);
    v.querySelector('.mv-x').addEventListener('click', close);
    v.querySelector('[data-a="share"]').addEventListener('click', function () {
      var p = wrap._loc, url = 'https://www.google.com/maps/search/?api=1&query=' + p.lat + ',' + p.lng;
      if (navigator.share) { navigator.share({ title: 'Location', text: addr.textContent, url: url }).catch(function () {}); return; }
      var btn = this;
      (navigator.clipboard ? navigator.clipboard.writeText(url) : Promise.reject()).then(function () {
        btn.innerHTML = '<i class="fas fa-check"></i> Link copied';
        setTimeout(function () { btn.innerHTML = '<i class="fas fa-share-nodes"></i> Share'; }, 1800);
      }, function () { window.prompt('Copy this link', url); });
    });
    var api_ = { wrap: wrap, close: close, update: update };
    mapView = api_;
    update();
    tick = setInterval(texts, 30000);
    loadLeaflet().then(function (Lf) {
      if (!v.isConnected) return;
      L = Lf;
      var box = v.querySelector('.mv-map'); box.textContent = '';
      var p = wrap._loc;
      map = L.map(box, { zoomControl: false, attributionControl: true }).setView([p.lat, p.lng], 16);
      L.control.zoom({ position: 'topright' }).addTo(map);
      layer = L.tileLayer(TILES.map[0], { attribution: TILES.map[1], maxZoom: TILES.map[2], subdomains: 'abcd' }).addTo(map);
      pin = L.marker([p.lat, p.lng], { icon: pinIcon(L, p.live), zIndexOffset: 1000 }).addTo(map);
      map.on('dragstart', function () { follow = false; });
      setTimeout(function () { map.invalidateSize(); }, 250);
      v.querySelectorAll('.mv-tool').forEach(function (t) {
        t.addEventListener('click', function () {
          if (t.dataset.t === 'layers') {
            layerName = layerName === 'map' ? 'sat' : 'map';
            map.removeLayer(layer);
            layer = L.tileLayer(TILES[layerName][0], { attribution: TILES[layerName][1], maxZoom: TILES[layerName][2], subdomains: layerName === 'map' ? 'abcd' : 'abc' }).addTo(map);
            t.classList.toggle('on', layerName === 'sat');
          } else if (t.dataset.t === 'pin') {
            follow = true; map.flyTo([wrap._loc.lat, wrap._loc.lng], Math.max(map.getZoom(), 16));
          } else if (myPos) {
            follow = false;
            map.flyToBounds(L.latLngBounds([[myPos.lat, myPos.lng], [wrap._loc.lat, wrap._loc.lng]]).pad(0.35), { maxZoom: 17 });
          } else watchMe(true);
        });
      });
      watchMe(false);
    }).catch(function () {
      var box = v.querySelector('.mv-map');
      box.innerHTML = '';
      var f = el('iframe', 'mv-frame'); f.src = mapSrc(wrap._loc.lat, wrap._loc.lng); f.title = 'Map'; box.appendChild(f);
    });
    function watchMe(fly) {
      if (!navigator.geolocation) return;
      var first = true;
      watch = navigator.geolocation.watchPosition(function (pos) {
        myPos = { lat: pos.coords.latitude, lng: pos.coords.longitude };
        if (map) {
          if (!me) {
            meRing = L.circle([myPos.lat, myPos.lng], { radius: pos.coords.accuracy, color: '#2563eb', weight: 1, fillOpacity: .12 }).addTo(map);
            me = L.marker([myPos.lat, myPos.lng], { icon: meIcon(L) }).addTo(map);
          } else { me.setLatLng([myPos.lat, myPos.lng]); meRing.setLatLng([myPos.lat, myPos.lng]).setRadius(pos.coords.accuracy); }
          if (fly && first) map.flyToBounds(L.latLngBounds([[myPos.lat, myPos.lng], [wrap._loc.lat, wrap._loc.lng]]).pad(0.35), { maxZoom: 17 });
        }
        first = false;
        texts();
      }, function () { if (fly) meta.textContent = 'Allow location access to see how far it is.'; }, { enableHighAccuracy: true, maximumAge: 10000, timeout: 20000 });
    }
  }

  // A small map in the "Share location" sheet: your position (blue dot + accuracy),
  // and a pin in the middle you can move to send a different place.
  function pickerMap(box, onPos) {
    var state = { map: null, me: null, ring: null, pos: null, moved: false, watch: null };
    box.innerHTML = '<div class="mv-loading"><i class="fas fa-circle-notch fa-spin"></i> Finding where you are…</div>';
    loadLeaflet().then(function (L) {
      if (!box.isConnected) return;
      box.textContent = '';
      var holder = el('div', 'lp-map'); box.appendChild(holder);
      var center = el('span', 'lp-center'); center.innerHTML = '<i class="fas fa-location-dot"></i>'; box.appendChild(center);
      state.map = L.map(holder, { zoomControl: false, attributionControl: false }).setView([22.6, 79.0], 4);
      L.tileLayer(TILES.map[0], { maxZoom: 19, subdomains: 'abcd' }).addTo(state.map);
      state.map.on('moveend', function () {
        if (!state.dragged || !state.pos) return;
        var c = state.map.getCenter(), far = km(state.pos, { lat: c.lat, lng: c.lng }) * 1000 > Math.max(30, Math.min(state.pos.acc || 0, 150) / 2);
        state.moved = far; box.classList.toggle('moved', far); onPos(state.pos, far);
      });
      state.map.on('dragstart', function () { state.dragged = true; });
      if (!navigator.geolocation) return;
      state.watch = navigator.geolocation.watchPosition(function (p) {
        state.pos = { lat: p.coords.latitude, lng: p.coords.longitude, acc: p.coords.accuracy };
        var ll = [state.pos.lat, state.pos.lng];
        if (!state.me) {
          state.ring = L.circle(ll, { radius: state.pos.acc, color: '#2563eb', weight: 1, opacity: .5, fillOpacity: .07 }).addTo(state.map);
          state.me = L.marker(ll, { icon: meIcon(L) }).addTo(state.map);
          state.map.setView(ll, 17);
        } else { state.me.setLatLng(ll); state.ring.setLatLng(ll).setRadius(state.pos.acc); if (!state.moved) state.map.panTo(ll); }
        onPos(state.pos, state.moved);
      }, function () { onPos(null, false, true); }, { enableHighAccuracy: true, maximumAge: 5000, timeout: 20000 });
      setTimeout(function () { state.map.invalidateSize(); }, 200);
    }).catch(function () { box.innerHTML = '<div class="mv-loading">Map unavailable — you can still send your location.</div>'; });
    return {
      center: function () { var c = state.map && state.map.getCenter(); return c ? { lat: c.lat, lng: c.lng } : null; },
      recenter: function () { state.moved = false; state.dragged = false; box.classList.remove('moved'); if (state.pos && state.map) state.map.flyTo([state.pos.lat, state.pos.lng], 17); onPos(state.pos, false); },
      destroy: function () { if (state.watch != null) navigator.geolocation.clearWatch(state.watch); if (state.map) state.map.remove(); box.textContent = ''; }
    };
  }

  // Staff only: a "Save" button that downloads the original file.
  function downloadUrl(url) { return url + (url.indexOf('?') === -1 ? '?' : '&') + 'download=1'; }
  function saveButton(url, name) {
    var a = el('a', 'att-save');
    a.href = downloadUrl(url); a.download = name; a.title = 'Save to this computer';
    a.appendChild(el('i', 'fas fa-download')); a.appendChild(el('span', '', 'Save'));
    a.addEventListener('click', function (e) { e.stopPropagation(); });
    return a;
  }

  var viewer;
  function openViewer(url, name) {
    if (!viewer) {
      viewer = el('div', 'att-viewer');
      viewer.appendChild(el('img'));
      var close = el('button', 'att-viewer-close'); close.innerHTML = '<i class="fas fa-xmark"></i>';
      close.setAttribute('aria-label', 'Close');
      viewer.appendChild(close);
      viewer.addEventListener('click', function () { viewer.classList.remove('open'); });
      viewer.addEventListener('contextmenu', function (e) { if (!api.canSave) e.preventDefault(); });
      document.body.appendChild(viewer);
    }
    var old = viewer.querySelector('.att-save');
    if (old) old.remove();
    if (api.canSave) { var save = saveButton(url, name || 'photo'); save.classList.add('att-viewer-save'); viewer.appendChild(save); }
    viewer.querySelector('img').src = url;
    viewer.classList.add('open');
  }

  // ── calls ──────────────────────────────────────────────────────────────────
  // opts: { url, side: 'user'|'admin'|<chat user id>, peerName, photo, csrf (or a function returning it),
  //         onError(text), keep,
  //         rooms: { base, thread, contacts() → [{username, name, photo}] }   "Add person" (direct chats)
  //         roomOnly: true   someone added me to their call: no 1:1 link, only the room }
  // keep: leave other call screens on the page (EduChats has one per chat)

  // Sounds: browsers only play audio after a tap, so the audio engine wakes on the first one.
  var audioCtx = null;
  function actx() {
    try {
      if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      if (audioCtx.state === 'suspended') audioCtx.resume().catch(function () {});
    } catch (e) { return null; }
    return audioCtx;
  }
  ['pointerdown', 'keydown'].forEach(function (ev) {
    document.addEventListener(ev, function wake() { actx(); document.removeEventListener(ev, wake, true); }, true);
  });
  function tone(ctx, freq, at, dur, vol, steady) {
    var o = ctx.createOscillator(), g = ctx.createGain();
    o.type = 'sine'; o.frequency.value = freq;
    if (steady) {
      g.gain.setValueAtTime(0, at); g.gain.linearRampToValueAtTime(vol, at + 0.02);
      g.gain.setValueAtTime(vol, at + dur - 0.02); g.gain.linearRampToValueAtTime(0, at + dur);
    } else {   // a struck note (marimba-like)
      g.gain.setValueAtTime(0.0001, at); g.gain.exponentialRampToValueAtTime(vol, at + 0.012);
      g.gain.exponentialRampToValueAtTime(0.0001, at + dur);
    }
    o.connect(g); g.connect(ctx.destination); o.start(at); o.stop(at + dur + 0.05);
  }
  var TONES = {
    // someone is calling me: a bright marimba phrase
    ring: { every: 2000, vibrate: [700, 300, 700], play: function (ctx, t) {
      [[659.25, 0], [830.61, 0.15], [987.77, 0.3], [1318.51, 0.45], [987.77, 0.78], [1318.51, 0.93]].forEach(function (n) {
        tone(ctx, n[0], t + n[1], 0.6, 0.2); tone(ctx, n[0] * 2.01, t + n[1], 0.18, 0.04);
      });
    } },
    // I'm calling: the Indian ring-back "tring-tring" (400 + 450 Hz)
    back: { every: 3000, play: function (ctx, t) {
      [0, 0.6].forEach(function (s) { tone(ctx, 400, t + s, 0.4, 0.045, true); tone(ctx, 450, t + s, 0.4, 0.045, true); });
    } }
  };
  // Incoming-call ringtones: drawn once into a short WAV and played by a looping <audio>,
  // so they keep ringing in a background tab (timers there slow right down) and sound
  // the same on every phone. [name, seconds per ring, sample(t)]
  function sine(f, t) { return Math.sin(6.283185307 * f * t); }
  var RINGTONES = {
    classic: ['Classic phone', 3, function (t) {   // the old bell phone: "trrring-trrring"
      var u = t < 0.42 ? t : (t >= 0.62 && t < 1.04) ? t - 0.62 : -1;
      if (u < 0) return 0;
      var env = Math.min(1, u / 0.012) * Math.min(1, (0.42 - u) / 0.04), hammer = 0.62 + 0.38 * sine(22, u);
      return env * hammer * (0.62 * sine(1046, u) + 0.28 * sine(1568, u) + 0.12 * sine(2637, u));
    }],
    digital: ['Digital', 2.4, function (t) {   // quick two-tone beeps, like most phones
      var k = Math.floor(t / 0.11), u = t - k * 0.11;
      if (k > 7 || u > 0.075) return 0;
      var f = k % 2 ? 1046 : 1397, env = Math.min(1, u / 0.006) * Math.min(1, (0.075 - u) / 0.01);
      return env * (0.8 * sine(f, u) + 0.2 * sine(f * 3, u));
    }],
    marimba: ['Marimba', 2.4, function (t) {
      var out = 0;
      [[659.25, 0], [830.61, 0.15], [987.77, 0.3], [1318.51, 0.45], [987.77, 0.78], [1318.51, 0.93]].forEach(function (n) {
        var u = t - n[1];
        if (u >= 0) out += 0.35 * sine(n[0], u) * Math.exp(-6 * u) + 0.08 * sine(n[0] * 2.01, u) * Math.exp(-20 * u);
      });
      return out;
    }]
  };
  var toneUrls = {};
  function ringtoneUrl(key) {
    if (toneUrls[key]) return toneUrls[key];
    var spec = RINGTONES[key], rate = 22050, n = Math.round(rate * spec[1]), pcm = new Float32Array(n), peak = 0.0001;
    for (var i = 0; i < n; i++) { pcm[i] = spec[2](i / rate); peak = Math.max(peak, Math.abs(pcm[i])); }
    var buf = new ArrayBuffer(44 + n * 2), v = new DataView(buf);
    function str(at, s) { for (var j = 0; j < s.length; j++) v.setUint8(at + j, s.charCodeAt(j)); }
    str(0, 'RIFF'); v.setUint32(4, 36 + n * 2, true); str(8, 'WAVEfmt '); v.setUint32(16, 16, true); v.setUint16(20, 1, true);
    v.setUint16(22, 1, true); v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
    str(36, 'data'); v.setUint32(40, n * 2, true);
    for (i = 0; i < n; i++) v.setInt16(44 + i * 2, Math.max(-1, Math.min(1, pcm[i] / peak * 0.9)) * 32767, true);
    return (toneUrls[key] = URL.createObjectURL(new Blob([buf], { type: 'audio/wav' })));
  }
  function ringtone() { try { var k = localStorage.getItem('educhats-ringtone'); return RINGTONES[k] ? k : 'classic'; } catch (e) { return 'classic'; } }
  var blockedRing = null;   // a ringtone the browser wouldn't start yet: it starts on the next tap
  ['pointerdown', 'keydown'].forEach(function (ev) { document.addEventListener(ev, function () { if (blockedRing) blockedRing(); }, true); });
  function Ringer(name) {
    var spec = TONES[name], timer = null, on = false, audio = null;
    function buzz() { if (spec.vibrate && navigator.vibrate) { try { navigator.vibrate(spec.vibrate); } catch (e) {} } }
    function once() {
      var ctx = actx();
      if (ctx && ctx.state === 'running') spec.play(ctx, ctx.currentTime + 0.05);
      buzz();
    }
    function play() {
      if (!audio) { audio = new Audio(); audio.loop = true; audio.preload = 'auto'; }
      audio.src = ringtoneUrl(ringtone());
      var p = audio.play();
      if (p && p.catch) p.catch(function () { blockedRing = function () { blockedRing = null; if (on) audio.play().catch(function () {}); }; });
    }
    return {
      start: function () {
        if (on) return;
        on = true;
        if (name === 'ring') { play(); buzz(); timer = setInterval(buzz, spec.every); }
        else { once(); timer = setInterval(once, spec.every); }
      },
      stop: function () {
        if (!on) return;
        on = false; blockedRing = null;
        clearInterval(timer); timer = null;
        if (audio) { audio.pause(); try { audio.currentTime = 0; } catch (e) {} }
        if (spec.vibrate && navigator.vibrate) { try { navigator.vibrate(0); } catch (e) {} }
      }
    };
  }
  var preview = null;
  function previewRingtone(key) {
    if (!RINGTONES[key]) return;
    if (preview) preview.pause();
    preview = new Audio(ringtoneUrl(key)); preview.play().catch(function () {});
  }
  // the tab title blinks while someone is calling, so a call shows even from another tab
  var blink = null, plainTitle = '';
  function titleBlink(text) {
    if (blink) { clearInterval(blink); blink = null; document.title = plainTitle; }
    if (!text) return;
    plainTitle = document.title;
    var lit = false;
    blink = setInterval(function () { lit = !lit; document.title = lit ? text : plainTitle; }, 1000);
  }
  function blip(kind) {
    var ctx = actx(); if (!ctx || ctx.state !== 'running') return;
    var t = ctx.currentTime + 0.02;
    if (kind === 'end') { tone(ctx, 660, t, 0.22, 0.12); tone(ctx, 440, t + 0.2, 0.4, 0.12); }
    else if (kind === 'join') { tone(ctx, 523.25, t, 0.2, 0.1); tone(ctx, 783.99, t + 0.14, 0.35, 0.1); }
  }
  var DTMF = { '1': [697, 1209], '2': [697, 1336], '3': [697, 1477], '4': [770, 1209], '5': [770, 1336], '6': [770, 1477],
               '7': [852, 1209], '8': [852, 1336], '9': [852, 1477], '*': [941, 1209], '0': [941, 1336], '#': [941, 1477] };

  // Voice: Opus with forward error correction (fewer dropouts on a weak network),
  // no silence suppression (no clipped first words) and up to 64 kbps mono speech.
  function tuneSdp(sdp) {
    var m = sdp.match(/a=rtpmap:(\d+) opus\/48000/i);
    if (!m) return sdp;
    var pt = m[1], want = { useinbandfec: '1', usedtx: '0', stereo: '0', 'sprop-stereo': '0', maxaveragebitrate: '64000', maxplaybackrate: '48000' };
    var line = new RegExp('a=fmtp:' + pt + ' ([^\\r\\n]*)');
    function join(have) { return Object.keys(have).map(function (k) { return k + '=' + have[k]; }).join(';'); }
    if (line.test(sdp)) {
      return sdp.replace(line, function (all, params) {
        var have = {};
        params.split(';').forEach(function (p) { var kv = p.split('='); if (kv[0].trim()) have[kv[0].trim()] = kv[1]; });
        Object.keys(want).forEach(function (k) { have[k] = want[k]; });
        return 'a=fmtp:' + pt + ' ' + join(have);
      });
    }
    return sdp.replace(m[0], m[0] + '\r\na=fmtp:' + pt + ' ' + join(want));
  }
  // Video up to 720p/30 (less when there are more people), voice sent first when the network is busy.
  function tuneSenders(pc, many) {
    pc.getSenders().forEach(function (s) {
      if (!s.track || !s.getParameters || !s.setParameters) return;
      try {
        var p = s.getParameters();
        if (!p.encodings || !p.encodings.length) return;
        if (s.track.kind === 'audio') { p.encodings[0].maxBitrate = 64000; p.encodings[0].priority = 'high'; p.encodings[0].networkPriority = 'high'; }
        else { p.encodings[0].maxBitrate = many ? 700000 : 1800000; p.encodings[0].maxFramerate = 30; p.degradationPreference = 'balanced'; }
        s.setParameters(p).catch(function () {});
      } catch (e) {}
    });
  }

  function Calls(opts) {
    var self = this;
    var call = null;        // the 1:1 call as the server sees it (or {kind, roomOnly} for an invite)
    var phase = '';         // calling | incoming | connecting | active | ended
    var local = null, servers = null, facing = 'user';
    var peers = {};         // 'main' = the 1:1 link; room members by user id
    var room = null;        // { id, after, members, mySeq, poll }
    var fast = null, timer = null, startedAt = 0, noteTimer = null, rec = null, mainEnded = false;
    var oneCam = false, outputs = [], output = 0;   // sound outputs (loudspeaker / earpiece / Bluetooth) where the browser can switch them
    var ringIn = Ringer('ring'), ringOut = Ringer('back');
    var ui = buildUi(), $ = function (sel) { return ui.querySelector(sel); };
    setWho(opts.peerName, opts.photo);

    function csrf() { return typeof opts.csrf === 'function' ? opts.csrf() : opts.csrf; }
    function post(url, data) {
      return fetch(url, {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() }, body: JSON.stringify(data)
      }).then(function (r) { return r.json().catch(function () { return { ok: false, error: 'Something went wrong.' }; }); });
    }
    function getJ(url) { return fetch(url, { credentials: 'same-origin', cache: 'no-store' }).then(function (r) { return r.json(); }); }
    function send(data) { return post(opts.url, data); }
    function first(name) { return String(name || '').split(' ')[0] || 'Someone'; }

    function avatar(box, name, photo) {
      box.textContent = '';
      var letter = el('span', 'ava-letter', (String(name || '?').trim()[0] || '?').toUpperCase());
      box.appendChild(letter);
      if (photo) {
        var img = el('img'); img.alt = ''; img.src = photo;
        img.onload = function () { letter.remove(); };
        img.onerror = function () { img.remove(); };
        box.appendChild(img);
      }
    }

    function buildUi() {
      // The dashboard swaps pages in place, so an earlier page's (idle) call screen may still be here.
      if (!opts.keep) document.querySelectorAll('.call-overlay:not(.open)').forEach(function (old) { old.remove(); });
      var o = el('div', 'call-overlay');
      o.innerHTML =
        '<div class="call-bg"></div>' +
        '<div class="call-stage"></div>' +
        '<video class="call-local" autoplay playsinline muted></video>' +
        '<div class="call-top"><span class="call-lock"><i class="fas fa-lock"></i> End-to-end encrypted</span>' +
        '<span class="call-rec" hidden><i></i> REC <b>0:00</b></span></div>' +
        '<div class="call-info"><div class="call-ripple"><i></i><i></i><i></i></div><div class="call-avatar"></div><div class="call-name"></div><div class="call-state"></div>' +
        '<div class="call-note" aria-live="polite"></div><div class="call-recnote" hidden></div></div>' +
        '<div class="call-panel call-keys" hidden><button type="button" class="call-x" aria-label="Close"><i class="fas fa-xmark"></i></button>' +
        '<div class="keys-show"></div><div class="keys-grid"></div></div>' +
        '<div class="call-panel call-people" hidden><button type="button" class="call-x" aria-label="Close"><i class="fas fa-xmark"></i></button>' +
        '<b class="people-title">Add to call</b><input type="search" class="people-q" placeholder="Search your chats" autocomplete="off">' +
        '<div class="people-list"></div><small class="people-hint"></small></div>' +
        '<div class="call-bar">' +
        btn('mute', 'fa-microphone', 'Mute') + btn('speaker', 'fa-volume-high', 'Speaker') + btn('cam', 'fa-video', 'Camera') + btn('flip', 'fa-camera-rotate', 'Flip') +
        btn('keypad', 'fa-table-cells', 'Keypad') + btn('rec', 'fa-circle-dot', 'Record') + btn('add', 'fa-user-plus', 'Add') +
        btn('end', 'fa-phone-slash', 'End') + '</div>' +
        '<div class="call-answer">' + btn('decline', 'fa-phone-slash', 'Decline') + btn('accept', 'fa-phone', 'Accept') + '</div>' +
        '<div class="call-kind"></div>';
      document.body.appendChild(o);
      var grid = o.querySelector('.keys-grid');
      '123456789*0#'.split('').forEach(function (d) {
        var k = el('button', 'key', d); k.type = 'button';
        k.addEventListener('click', function () { press(d); });
        grid.appendChild(k);
      });
      function on(cls, fn) { o.querySelector('.call-btn.' + cls).addEventListener('click', fn); }
      on('end', function () { self.hangUp(); });
      on('decline', function () { self.hangUp(); });
      on('accept', function () { self.answer(); });
      on('mute', function () { toggleTrack('audio'); });
      on('speaker', nextOutput);
      on('cam', function () { toggleTrack('video'); });
      on('flip', flip);
      on('keypad', function () { panel('keys'); });
      on('rec', function () { if (rec) stopRec(); else startRec(); });
      on('add', function () { panel('people'); });
      o.querySelectorAll('.call-x').forEach(function (x) { x.addEventListener('click', function () { panel(null); }); });
      o.querySelector('.people-q').addEventListener('input', listPeople);
      return o;
    }
    function btn(cls, icon, label) {
      return '<button type="button" class="call-btn ' + cls + '" aria-label="' + label + '"><span class="ic"><i class="fas ' + icon + '"></i></span><small>' + label + '</small></button>';
    }
    function setWho(name, photo) {
      ui.querySelector('.call-name').textContent = name || 'EduChats call';
      avatar(ui.querySelector('.call-avatar'), name, photo);
      ui.querySelector('.call-bg').style.backgroundImage = photo ? 'url("' + String(photo).replace(/"/g, '%22') + '")' : '';
    }
    function panel(which) {
      $('.call-keys').hidden = which !== 'keys';
      $('.call-people').hidden = which !== 'people';
      if (which === 'people') { $('.people-q').value = ''; listPeople(); }
    }

    function paint() {
      var n = Object.keys(peers).length, group = n > 1 || !!(call && call.roomOnly);
      ui.className = 'call-overlay' + (phase ? ' open ' + phase : '') + (call && call.kind === 'video' ? ' is-video' : ' is-audio') +
        (group ? ' group' : '') + (opts.rooms || opts.roomOnly ? ' can-add' : '') +
        (oneCam ? ' one-cam' : '') + (outputs.length > 1 ? ' can-speaker' : '');
      ui.dataset.n = n;
      var video = call && call.kind === 'video';
      ui.querySelector('.call-kind').innerHTML = '<i class="fas ' + (video ? 'fa-video' : 'fa-phone') + '"></i> EduChats ' + (group ? 'group ' : '') + (video ? 'video' : 'voice') + ' call';
    }
    function state(text) { $('.call-state').textContent = text; }
    function note(text) {
      var box = $('.call-note');
      box.textContent = text; box.classList.add('show');
      clearTimeout(noteTimer); noteTimer = setTimeout(function () { box.classList.remove('show'); }, 3500);
    }
    function show(p, text) {
      phase = p; paint();
      if (text != null) state(text);
      titleBlink(p === 'incoming' ? '📞 ' + $('.call-name').textContent + ' is calling…' : null);
      if (p === 'incoming' && api.autoAnswerUntil > Date.now()) {   // "Answer" was tapped on the notification
        api.autoAnswerUntil = 0;
        setTimeout(function () { if (phase === 'incoming') self.answer(); }, 300);
      }
    }

    // ── people on the call ──
    function addPeer(key, name, photo) {
      if (peers[key]) return peers[key];
      var t = el('div', 'call-tile');
      t.innerHTML = '<video autoplay playsinline></video><div class="tile-ava"></div><div class="tile-state"></div>' +
        '<div class="tile-name"><i class="fas fa-microphone-slash"></i> <span></span></div>';
      avatar(t.querySelector('.tile-ava'), name, photo);
      $('.call-stage').appendChild(t);
      if (outputs[output] && t.querySelector('video').setSinkId) t.querySelector('video').setSinkId(outputs[output].deviceId).catch(function () {});
      peers[key] = { key: key, name: name || 'Someone', photo: photo || '', tile: t, pc: null, stream: null,
                     pending: [], iceSeen: 0, flags: {}, connected: false, invited: false };
      refresh();
      return peers[key];
    }
    function removePeer(key) {
      var p = peers[key];
      if (!p) return;
      if (p.pc) { try { p.pc.close(); } catch (e) {} }
      p.tile.remove();
      delete peers[key];
      refresh();
      if (phase === 'active' && !Object.keys(peers).length) cleanup('Call ended');
    }
    function refresh() {
      var keys = Object.keys(peers);
      keys.forEach(function (k) {
        var p = peers[k], t = p.tile;
        var video = call && call.kind === 'video' && p.stream && !p.flags.camoff &&
          p.stream.getVideoTracks().some(function (tr) { return tr.readyState === 'live'; });
        t.classList.toggle('has-video', !!video);
        t.classList.toggle('muted', !!p.flags.muted);
        t.querySelector('.tile-name span').textContent = p.name;
        t.querySelector('.tile-state').textContent = p.invited ? 'Ringing…' : (p.connected || k === 'main' ? '' : 'Connecting…');
      });
      if (keys.length > 1) $('.call-name').textContent = keys.map(function (k) { return first(peers[k].name); }).join(', ');
      else if (keys.length === 1) $('.call-name').textContent = peers[keys[0]].name;
      var recBy = keys.filter(function (k) { return peers[k].flags.rec; }).map(function (k) { return first(peers[k].name); });
      $('.call-recnote').hidden = !recBy.length;
      $('.call-recnote').textContent = '● ' + recBy.join(', ') + (recBy.length > 1 ? ' are' : ' is') + ' recording this call';
      var mic = local && local.getAudioTracks()[0], cam = local && local.getVideoTracks()[0];
      $('.call-btn.mute').classList.toggle('off', !!(mic && !mic.enabled));
      $('.call-btn.mute i').className = 'fas ' + (mic && !mic.enabled ? 'fa-microphone-slash' : 'fa-microphone');
      $('.call-btn.cam').classList.toggle('off', !!(cam && !cam.enabled));
      $('.call-btn.cam i').className = 'fas ' + (cam && !cam.enabled ? 'fa-video-slash' : 'fa-video');
      $('.call-btn.rec').classList.toggle('on', !!rec);
      $('.call-btn.rec small').textContent = rec ? 'Stop' : 'Record';
      paint();
    }

    function media(kind) {
      if (!navigator.mediaDevices || !window.RTCPeerConnection) {
        return Promise.reject(new Error('Calls need a modern browser on a secure (https) page.'));
      }
      var audio = { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1, sampleRate: 48000 };
      var video = kind === 'video' ? { facingMode: 'user', width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 30, max: 30 } } : false;
      return navigator.mediaDevices.getUserMedia({ audio: audio, video: video }).catch(function (err) {
        if (err && /Overconstrained|ConstraintNotSatisfied/.test(err.name)) return navigator.mediaDevices.getUserMedia({ audio: true, video: kind === 'video' });
        throw err;
      }).then(function (stream) {
        stream.getAudioTracks().forEach(function (t) { if ('contentHint' in t) t.contentHint = 'speech'; });
        stream.getVideoTracks().forEach(function (t) { if ('contentHint' in t) t.contentHint = 'motion'; });
        local = stream; facing = 'user';
        var me = $('.call-local'); me.srcObject = stream; me.classList.remove('back'); me.dataset.live = '1';
        findOutputs();
        if (kind === 'video' && navigator.mediaDevices.enumerateDevices) {
          navigator.mediaDevices.enumerateDevices().then(function (list) {
            oneCam = list.filter(function (d) { return d.kind === 'videoinput'; }).length < 2; paint();
          }).catch(function () {});
        }
        return stream;
      }, function (err) {
        if (api.onMediaBlocked && (!err || /NotAllowed|Security|Permission/.test(err.name))) api.onMediaBlocked(kind);
        throw new Error('Allow microphone' + (kind === 'video' ? ' and camera' : '') + ' access to call.');
      });
    }

    function makePc(p, sendIce) {
      var pc = new RTCPeerConnection({ iceServers: servers || [], iceCandidatePoolSize: 2, bundlePolicy: 'max-bundle' });
      local.getTracks().forEach(function (t) { pc.addTrack(t, local); });
      pc.ontrack = function (e) {
        p.stream = e.streams[0] || p.stream || new MediaStream();
        if (!e.streams[0]) p.stream.addTrack(e.track);
        var v = p.tile.querySelector('video');
        if (v.srcObject !== p.stream) { v.srcObject = p.stream; v.play().catch(function () {}); }
        e.track.onunmute = e.track.onmute = e.track.onended = refresh;
        recAdd(p.stream);
        refresh();
      };
      pc.onicecandidate = function (e) { if (e.candidate) sendIce(e.candidate.toJSON()); };
      pc.onconnectionstatechange = function () {
        var s = pc.connectionState;
        if (s === 'connected') {
          if (!p.connected && p.key !== 'main') { blip('join'); note(first(p.name) + ' joined'); }
          p.connected = true;
          tuneSenders(pc, Object.keys(peers).length > 1);
          if (p.key !== 'main') signal(p.key, 'flag', myFlags());
          startTimer();
          if (phase === 'active') state(clock());
        } else if (s === 'disconnected') {
          if (Object.keys(peers).length === 1) state('Reconnecting…');
        } else if (s === 'failed') {
          if (p.key === 'main' && Object.keys(peers).length === 1) { opts.onError('The call could not connect on this network.'); self.hangUp(); }
          else { note("Couldn't connect to " + first(p.name)); removePeer(p.key); }
        }
        refresh();
      };
      p.pc = pc;
      Object.keys(peers).forEach(function (k) { if (peers[k].pc) tuneSenders(peers[k].pc, Object.keys(peers).length > 1); });
      return pc;
    }
    function addIce(p, c) {
      if (p.pc && p.pc.remoteDescription) p.pc.addIceCandidate(c).catch(function () {});
      else p.pending.push(c);
    }
    function flushIce(p) { p.pending.splice(0).forEach(function (c) { p.pc.addIceCandidate(c).catch(function () {}); }); }
    function allPcs() { return Object.keys(peers).map(function (k) { return peers[k].pc; }).filter(Boolean); }

    function clock() {
      var s = Math.floor((Date.now() - startedAt) / 1000);
      return (s >= 3600 ? Math.floor(s / 3600) + ':' + ('0' + Math.floor(s / 60) % 60).slice(-2) : Math.floor(s / 60)) + ':' + ('0' + (s % 60)).slice(-2);
    }
    var screenLock = null;
    function keepAwake(on) {
      if (!on) { if (screenLock) { screenLock.release().catch(function () {}); screenLock = null; } return; }
      if (screenLock || !navigator.wakeLock) return;
      navigator.wakeLock.request('screen').then(function (l) { screenLock = l; l.addEventListener('release', function () { if (screenLock === l) screenLock = null; }); }).catch(function () {});
    }
    document.addEventListener('visibilitychange', function () { if (!document.hidden && phase === 'active') keepAwake(true); });
    function startTimer() {
      if (timer) return;
      ringOut.stop(); ringIn.stop(); keepAwake(true);
      startedAt = Date.now();
      show('active', '0:00');
      timer = setInterval(function () {
        if (phase === 'active' && $('.call-state').textContent !== 'Reconnecting…') state(clock());
        if (rec) $('.call-rec b').textContent = clockFrom(rec.started);
      }, 1000);
    }
    function clockFrom(t) { var s = Math.floor((Date.now() - t) / 1000); return Math.floor(s / 60) + ':' + ('0' + (s % 60)).slice(-2); }

    // ── mute / camera / flip / keypad ──
    function myFlags() {
      var mic = local && local.getAudioTracks()[0], cam = local && local.getVideoTracks()[0];
      return { muted: !!(mic && !mic.enabled), camoff: !!(cam && !cam.enabled), rec: !!rec };
    }
    function sendFlags() {
      var f = myFlags();
      if (call && call.id && !mainEnded) send({ action: 'flag', id: call.id, flags: f }).catch(function () {});
      Object.keys(peers).forEach(function (k) { if (k !== 'main' && peers[k].connected) signal(k, 'flag', f); });
    }
    function toggleTrack(kind) {
      var t = local && (kind === 'audio' ? local.getAudioTracks() : local.getVideoTracks())[0];
      if (!t) return;
      t.enabled = !t.enabled;
      refresh(); sendFlags();
    }
    function flip() {
      if (!local || !local.getVideoTracks().length) return;
      var want = facing === 'user' ? 'environment' : 'user';
      var size = { width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 30, max: 30 } };
      navigator.mediaDevices.getUserMedia({ video: Object.assign({ facingMode: { exact: want } }, size) })
        .catch(function () { return navigator.mediaDevices.getUserMedia({ video: Object.assign({ facingMode: want }, size) }); })
        .then(function (s) {
          var fresh = s.getVideoTracks()[0], old = local.getVideoTracks()[0];
          if ('contentHint' in fresh) fresh.contentHint = 'motion';
          fresh.enabled = old ? old.enabled : true;
          allPcs().forEach(function (pc) {
            pc.getSenders().forEach(function (snd) { if (snd.track && snd.track.kind === 'video') snd.replaceTrack(fresh).catch(function () {}); });
          });
          if (old) { local.removeTrack(old); old.stop(); }
          local.addTrack(fresh);
          facing = want;
          var me = $('.call-local'); me.srcObject = null; me.srcObject = local; me.classList.toggle('back', want === 'environment');
        }).catch(function () { opts.onError("Couldn't switch the camera."); });
    }
    // Speaker: the microphone keeps working whichever way the sound comes out
    function findOutputs() {
      if (!navigator.mediaDevices.enumerateDevices || !('setSinkId' in HTMLMediaElement.prototype)) return;
      navigator.mediaDevices.enumerateDevices().then(function (list) {
        outputs = list.filter(function (d) { return d.kind === 'audiooutput' && d.deviceId !== 'communications'; });
        output = 0;
        paint();
      }).catch(function () {});
    }
    function outputName(d) {
      var l = (d.label || '').toLowerCase();
      if (/speaker/.test(l)) return 'Speaker';
      if (/earpiece|receiver|handset/.test(l)) return 'Earpiece';
      if (/bluetooth|bt|airpods|buds/.test(l)) return 'Bluetooth';
      if (/headset|headphone|wired/.test(l)) return 'Headphones';
      return d.deviceId === 'default' ? 'Default' : (d.label || 'Output').split('(')[0].trim().slice(0, 14);
    }
    function nextOutput() {
      if (outputs.length < 2) return;
      output = (output + 1) % outputs.length;
      var d = outputs[output];
      Object.keys(peers).forEach(function (k) {
        var v = peers[k].tile.querySelector('video');
        if (v.setSinkId) v.setSinkId(d.deviceId).catch(function () {});
      });
      $('.call-btn.speaker small').textContent = outputName(d);
      $('.call-btn.speaker').classList.toggle('on-alt', output !== 0);
      note('Sound: ' + outputName(d));
    }

    function press(d) {
      var ctx = actx();
      if (ctx && ctx.state === 'running') { var t = ctx.currentTime + 0.01; tone(ctx, DTMF[d][0], t, 0.16, 0.08, true); tone(ctx, DTMF[d][1], t, 0.16, 0.08, true); }
      var typed = $('.keys-show'); typed.textContent = (typed.textContent + d).slice(-24);
      allPcs().forEach(function (pc) {
        pc.getSenders().forEach(function (s) {
          if (s.track && s.track.kind === 'audio' && s.dtmf && s.dtmf.canInsertDTMF !== false) { try { s.dtmf.insertDTMF(d, 120, 70); } catch (e) {} }
        });
      });
    }

    // ── recording (saved to this device; everyone on the call is told) ──
    function startRec() {
      if (!window.MediaRecorder || !local) return opts.onError("Recording isn't supported in this browser.");
      var ctx = actx();
      if (!ctx) return opts.onError("Recording isn't supported in this browser.");
      var dest = ctx.createMediaStreamDestination();
      rec = { ctx: ctx, dest: dest, sources: {}, chunks: [], started: Date.now() };
      recAdd(local);
      Object.keys(peers).forEach(function (k) { recAdd(peers[k].stream); });
      var tracks = dest.stream.getAudioTracks();
      if (call && call.kind === 'video' && HTMLCanvasElement.prototype.captureStream) {
        var canvas = document.createElement('canvas'); canvas.width = 1280; canvas.height = 720;
        var g = canvas.getContext('2d');
        rec.draw = setInterval(function () {
          g.fillStyle = '#0b0d12'; g.fillRect(0, 0, 1280, 720);
          var vids = Object.keys(peers).map(function (k) { return peers[k].tile; })
            .filter(function (t) { return t.classList.contains('has-video'); }).map(function (t) { return t.querySelector('video'); });
          var cols = vids.length > 1 ? 2 : 1, rows = Math.ceil(vids.length / cols) || 1, w = 1280 / cols, h = 720 / rows;
          vids.forEach(function (v, i) { try { g.drawImage(v, (i % cols) * w, Math.floor(i / cols) * h, w, h); } catch (e) {} });
          try { g.drawImage($('.call-local'), 1280 - 260, 720 - 196, 240, 180); } catch (e) {}
        }, 40);
        tracks = tracks.concat(canvas.captureStream(25).getVideoTracks());
      }
      var types = call && call.kind === 'video' ? ['video/webm;codecs=vp8,opus', 'video/webm', 'video/mp4'] : ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4'];
      var type = types.filter(function (t) { return MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(t); })[0];
      try { rec.mr = new MediaRecorder(new MediaStream(tracks), type ? { mimeType: type } : undefined); }
      catch (e) { clearInterval(rec.draw); rec = null; return opts.onError("Recording isn't supported in this browser."); }
      var r = rec;   // the last piece of data arrives after Stop, once rec is already cleared
      rec.mr.ondataavailable = function (e) { if (e.data && e.data.size) r.chunks.push(e.data); };
      rec.mr.onstop = function () { saveRec(r); };
      rec.mr.start(1000);
      $('.call-rec').hidden = false; $('.call-rec b').textContent = '0:00';
      note('Recording — everyone on the call can see this');
      refresh(); sendFlags();
    }
    function recAdd(stream) {
      if (!rec || !stream || rec.sources[stream.id] || !stream.getAudioTracks().length) return;
      try { rec.ctx.createMediaStreamSource(stream).connect(rec.dest); rec.sources[stream.id] = true; } catch (e) {}
    }
    function stopRec() {
      if (!rec) return;
      clearInterval(rec.draw);
      try { rec.mr.stop(); } catch (e) {}
      rec = null;
      $('.call-rec').hidden = true;
      refresh(); sendFlags();
    }
    function saveRec(r) {
      if (!r.chunks.length) return;
      var type = (r.mr && r.mr.mimeType) || 'audio/webm', ext = /mp4/.test(type) ? (/video/.test(type) ? 'mp4' : 'm4a') : 'webm';
      var d = new Date(r.started), pad = function (n) { return ('0' + n).slice(-2); };
      var a = document.createElement('a');
      a.href = URL.createObjectURL(new Blob(r.chunks, { type: type }));
      a.download = 'EduChats call - ' + String(opts.peerName || 'call').replace(/[\\/:*?"<>|]+/g, '') + ' - ' + d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) +
        ' ' + pad(d.getHours()) + '.' + pad(d.getMinutes()) + '.' + ext;
      document.body.appendChild(a); a.click();
      setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 10000);
      note('Recording saved to your downloads');
    }

    // ── more people (rooms) ──
    function roomUrl() { return opts.rooms.base + room.id + '/'; }
    function signal(to, type, data) { if (room) post(roomUrl(), { action: 'signal', to: to, type: type, data: data }).catch(function () {}); }
    function mainUid() { return call && call.callee ? (call.caller === String(opts.side) ? call.callee : call.caller) : null; }
    function startRoom(rid) {
      if (room) return;
      room = { id: rid, after: 0, members: {}, mySeq: 0 };
      room.poll = setInterval(pollRoom, 1000);
      pollRoom();
    }
    function pollRoom() {
      if (!room || room.busy) return;
      room.busy = true;
      getJ(roomUrl() + '?after=' + room.after + (servers ? '' : '&ice=1')).then(function (res) {
        room && (room.busy = false);
        if (!room) return;
        if (!res.ok) { if (!Object.keys(peers).length) cleanup('Call ended'); return; }
        if (res.ice_servers) servers = res.ice_servers;
        roster(res.room);
        (res.inbox || []).forEach(inbox);
      }).catch(function () { if (room) room.busy = false; });
    }
    function roster(r) {
      var me = r.me, main = mainUid();
      r.members.forEach(function (m) {
        if (m.id === me) { room.mySeq = m.seq; return; }
        var before = room.members[m.id];
        room.members[m.id] = m;
        if (m.id === main) return;   // already connected over the 1:1 call
        var p = peers[m.id];
        if (m.state === 'invited') {
          if (!p && phase !== 'incoming') { p = addPeer(m.id, m.name, m.photo); p.invited = true; refresh(); }
        } else if (m.state === 'joined') {
          if (!p) p = addPeer(m.id, m.name, m.photo);
          if (p.invited) { p.invited = false; refresh(); }
          p.name = m.name; if (m.photo && !p.photo) { p.photo = m.photo; avatar(p.tile.querySelector('.tile-ava'), m.name, m.photo); }
          if (!p.pc && local && phase !== 'incoming' && room.mySeq > m.seq) offerTo(p);   // whoever joined later calls
        } else if (p && before && before.state !== m.state) {
          note(first(m.name) + (m.state === 'declined' ? ' declined' : m.state === 'missed' ? " didn't answer" : ' left'));
          removePeer(m.id);
        }
      });
    }
    function offerTo(p) {
      makePc(p, function (c) { signal(p.key, 'ice', c); });
      p.pc.createOffer().then(function (o) {
        o = { type: o.type, sdp: tuneSdp(o.sdp) };
        return p.pc.setLocalDescription(o).then(function () { signal(p.key, 'offer', o); });
      }).catch(function () { note("Couldn't connect to " + first(p.name)); });
    }
    function inbox(msg) {
      room.after = Math.max(room.after, msg.n);
      var from = String(msg.from), m = room.members[from] || {};
      if (msg.type === 'bye') {
        if (peers[from]) { note(first(peers[from].name) + ' left'); removePeer(from); }
        return;
      }
      var p = peers[from] || addPeer(from, m.name, m.photo);
      if (msg.type === 'offer' && local) {
        if (!p.pc) makePc(p, function (c) { signal(from, 'ice', c); });
        p.pc.setRemoteDescription(msg.data).then(function () {
          flushIce(p);
          return p.pc.createAnswer();
        }).then(function (a) {
          a = { type: a.type, sdp: tuneSdp(a.sdp) };
          return p.pc.setLocalDescription(a).then(function () { signal(from, 'answer', a); });
        }).catch(function () {});
      } else if (msg.type === 'answer' && p.pc && !p.pc.currentRemoteDescription) {
        p.pc.setRemoteDescription(msg.data).then(function () { flushIce(p); }).catch(function () {});
      } else if (msg.type === 'ice' && msg.data) {
        addIce(p, msg.data);
      } else if (msg.type === 'flag') {
        p.flags = msg.data || {}; refresh();
      }
    }
    function ensureRoom() {
      if (room) return Promise.resolve();
      return post(opts.rooms.base, { action: 'create', thread: opts.rooms.thread, call: call && call.id }).then(function (res) {
        if (!res.ok) throw new Error(res.error || 'Could not add people right now.');
        startRoom(res.room.id); roster(res.room);
      });
    }
    function listPeople() {
      var list = $('.people-list'), q = $('.people-q').value.trim().toLowerCase().replace(/^@/, '');
      var inCall = {};
      if (room) Object.keys(room.members).forEach(function (k) { var m = room.members[k]; if (m.state === 'joined' || m.state === 'invited') inCall[m.name] = true; });
      inCall[opts.peerName] = true;
      var people = ((opts.rooms && opts.rooms.contacts && opts.rooms.contacts()) || []).filter(function (c) {
        return c.username && !inCall[c.name] && (!q || c.name.toLowerCase().indexOf(q) >= 0 || c.username.indexOf(q) >= 0);
      }).slice(0, 40);
      list.textContent = '';
      var full = Object.keys(peers).length + 1 >= 4;
      $('.people-hint').textContent = full ? 'A call can have up to 4 people.' : 'Up to 4 people · only people you chat with';
      if (!people.length) { list.appendChild(el('p', 'people-empty', q ? 'No one found.' : 'Your chats will show here.')); return; }
      people.forEach(function (c) {
        var row = el('button', 'people-row'); row.type = 'button'; row.disabled = full;
        var av = el('span', 'people-ava'); avatar(av, c.name, c.photo);
        var txt = el('span', 'people-txt'); txt.appendChild(el('b', '', c.name)); txt.appendChild(el('small', '', '@' + c.username));
        row.appendChild(av); row.appendChild(txt); row.appendChild(el('span', 'people-add', 'Add'));
        row.addEventListener('click', function () {
          row.disabled = true;
          ensureRoom().then(function () { return post(roomUrl(), { action: 'invite', username: c.username }); }).then(function (res) {
            if (!res.ok) throw new Error(res.error || 'Could not add ' + first(c.name) + '.');
            roster(res.room); panel(null); note('Calling ' + first(c.name) + '…');
          }).catch(function (err) { row.disabled = false; opts.onError(err.message); });
        });
        list.appendChild(row);
      });
    }

    // ── the 1:1 link ──
    function pollFast() {
      if (fast) return;
      fast = setInterval(function () {
        if (mainEnded) return;
        getJ(opts.url).then(function (res) { if (res.ok) self.sync(res.call, res.ice_servers); }).catch(function () {});
      }, 1000);
    }
    function closeMain() {
      mainEnded = true;
      clearInterval(fast); fast = null;
      removePeer('main');
    }

    function cleanup(text) {
      ringIn.stop(); ringOut.stop(); keepAwake(false); titleBlink(null);
      if (rec) stopRec();
      clearInterval(fast); fast = null;
      clearInterval(timer); timer = null;
      if (room) { clearInterval(room.poll); room = null; }
      Object.keys(peers).forEach(function (k) { var p = peers[k]; if (p.pc) { try { p.pc.close(); } catch (e) {} } p.tile.remove(); });
      peers = {};
      if (local) { local.getTracks().forEach(function (t) { t.stop(); }); local = null; }
      $('.call-local').srcObject = null; delete $('.call-local').dataset.live;
      panel(null);
      $('.keys-show').textContent = '';
      $('.call-rec').hidden = true; $('.call-recnote').hidden = true;
      mainEnded = false;
      var was = phase;
      call = null;
      if (text) {
        if (was === 'active') blip('end');
        show('ended', text);
        setTimeout(function () { if (phase === 'ended') { phase = ''; paint(); setWho(opts.peerName, opts.photo); } }, 1800);
      } else { phase = ''; paint(); setWho(opts.peerName, opts.photo); }
    }

    this.start = function (kind) {
      if (call) return;
      call = { kind: kind };
      setWho(opts.peerName, opts.photo);
      addPeer('main', opts.peerName, opts.photo);
      show('calling', 'Calling…');
      media(kind).then(function () {
        return getJ(opts.url);
      }).then(function (res) {
        servers = res.ice_servers;
        var p = peers.main;
        makePc(p, function (c) { if (call && call.id) send({ action: 'ice', id: call.id, candidate: c }); });
        return p.pc.createOffer().then(function (o) {
          o = { type: o.type, sdp: tuneSdp(o.sdp) };
          return p.pc.setLocalDescription(o).then(function () { return o; });
        });
      }).then(function (offer) {
        return send({ action: 'start', kind: kind, offer: offer });
      }).then(function (res) {
        if (!res.ok) throw new Error(res.error || 'Could not start the call.');
        call = res.call; show('calling', 'Ringing…'); ringOut.start(); pollFast();
      }).catch(function (err) { cleanup(); opts.onError(err.message); });
    };

    // someone added me to their call (chats.html's ring check)
    this.ringRoom = function (info) {
      if (call || !opts.rooms) return;
      call = { kind: info.kind, roomOnly: true };
      opts.peerName = info.name; opts.photo = info.photo || '';
      setWho(info.name, info.photo);
      room = { id: info.room, after: 0, members: {}, mySeq: 0 };
      show('incoming', 'Group ' + (info.kind === 'video' ? 'video' : 'voice') + ' call');
      if (info.others && info.others.length) note('With ' + info.others.join(', '));
      ringIn.start();
      room.poll = setInterval(function () {   // the invite can run out or be cancelled
        getJ(roomUrl()).then(function (res) {
          var mine = res.ok && res.room.members.filter(function (m) { return m.id === res.room.me; })[0];
          if (phase === 'incoming' && (!mine || mine.state !== 'invited')) cleanup('Missed call');
        }).catch(function () {});
      }, 2500);
    };

    this.answer = function () {
      if (!call) return;
      ringIn.stop();
      show('connecting', 'Connecting…');
      if (call.roomOnly) {
        clearInterval(room.poll);
        media(call.kind).then(function () {
          return post(roomUrl(), { action: 'join' });
        }).then(function (res) {
          if (!res.ok) throw new Error(res.error || 'This call has ended.');
          servers = res.ice_servers || servers;
          var rid = room.id; room = null;
          startRoom(rid); roster(res.room);
        }).catch(function (err) {
          if (room) post(roomUrl(), { action: 'decline' }).catch(function () {});
          cleanup(); opts.onError(err.message);
        });
        return;
      }
      if (!call.offer) return;
      media(call.kind).then(function () {
        return getJ(opts.url);
      }).then(function (res) {
        servers = res.ice_servers;
        var p = peers.main || addPeer('main', opts.peerName, opts.photo);
        makePc(p, function (c) { if (call && call.id) send({ action: 'ice', id: call.id, candidate: c }); });
        return p.pc.setRemoteDescription(call.offer);
      }).then(function () {
        flushIce(peers.main);
        return peers.main.pc.createAnswer();
      }).then(function (a) {
        a = { type: a.type, sdp: tuneSdp(a.sdp) };
        return peers.main.pc.setLocalDescription(a).then(function () { return send({ action: 'answer', id: call.id, answer: a }); });
      }).then(function (res) {
        if (!res.ok) throw new Error(res.error || 'Could not answer.');
        pollFast();
      }).catch(function (err) {
        if (call && call.id) send({ action: 'decline', id: call.id });
        cleanup(); opts.onError(err.message);
      });
    };

    this.busy = function () { return !!call; };
    this.hangUp = function () {
      if (room) post(roomUrl(), { action: call && call.roomOnly && phase === 'incoming' ? 'decline' : 'leave' }).catch(function () {});
      if (call && call.id && !mainEnded) send({ action: call.status === 'ringing' && call.caller !== String(opts.side) ? 'decline' : 'end', id: call.id });
      cleanup(phase === 'incoming' ? '' : 'Call ended');
    };

    // Called with the server's view of the 1:1 call on every poll.
    this.sync = function (st) {
      if (mainEnded || (call && call.roomOnly)) return;
      if (!st || st.status === 'ended') {
        if (call && call.id && (!st || st.id === call.id)) {
          var others = Object.keys(peers).filter(function (k) { return k !== 'main' && !peers[k].invited; });
          if (room && others.length) { note(first(opts.peerName) + ' left'); closeMain(); return; }   // the others carry on
          var reason = st && st.reason;
          cleanup(reason === 'declined' ? 'Call declined' : reason === 'missed' ? 'No answer' : 'Call ended');
        }
        return;
      }
      if (!call) {
        if (st.status === 'ringing' && st.caller !== String(opts.side)) {
          call = st;
          setWho(opts.peerName, opts.photo);
          addPeer('main', opts.peerName, opts.photo);
          show('incoming', (st.kind === 'video' ? 'Video' : 'Voice') + ' call');
          ringIn.start();
          pollFast();
        }
        return;
      }
      if (call.id && call.id !== st.id) return;
      var wasRinging = call.status === 'ringing';
      call = Object.assign(call, st);
      var p = peers.main;
      if (st.answer && p && p.pc && !p.pc.currentRemoteDescription && st.caller === String(opts.side)) {
        ringOut.stop();
        p.pc.setRemoteDescription(st.answer).then(function () { flushIce(p); }).catch(function () {});
        show('connecting', 'Connecting…');
      }
      if (wasRinging && st.status === 'active' && st.caller !== String(opts.side) && !(p && p.pc)) { cleanup(); return; }   // answered elsewhere
      if (p) {
        (st.ice || []).slice(p.iceSeen).forEach(function (c) { addIce(p, c); });
        p.iceSeen = Math.max(p.iceSeen, (st.ice || []).length);
        var f = st.peer_flags || {};
        if (JSON.stringify(f) !== JSON.stringify(p.flags)) { p.flags = f; refresh(); }
      }
      if (st.room && !room && opts.rooms && phase !== 'incoming') startRoom(st.room);
    };
  }

  // Emoji · GIF · Stickers panel (WhatsApp-style tabs along the bottom).
  // opts: { onSticker(code), onGif({url, w, h}), gifUrl } — without them it's emoji only.
  var PICKER_SRC = 'https://cdn.jsdelivr.net/npm/emoji-picker-element@1.29.1/index.js';
  var STICKER_PACKS = [["smileys","Smileys",["1f600","1f603","1f604","1f601","1f606","1f605","1f602","1f923","1f62d","1f609","1f60a","1f607","1f970","1f60d","1f929","1f618","1f617","1f61a","1f619","1f972","1f60b","1f61b","1f61c","1f92a","1f61d","1f911","1f917","1f92d","1fae2","1fae3","1f92b","1f914","1fae1","1f910","1f928","1f610","1f611","1f636","1fae5","1f60f","1f612","1f644","1f62c","1f62e_200d_1f4a8","1f925","1f60c","1f614","1f62a","1f924","1f634","1f637","1f912","1f915","1f922","1f92e","1f927","1f975","1f976","1f974","1f635","1f635_200d_1f4ab","1f92f","1f920","1f973","1f978","1f60e","1f913","1f9d0","1f615","1fae4","1f61f","1f641","1f62e","1f62f","1f632","1f633","1f97a","1f979","1f626","1f627","1f628","1f630","1f625","1f622","1f631","1f616","1f623","1f61e","1f613","1f629","1f62b","1f971","1f624","1f621","1f620","1f92c","1f608","1f47f","1f480","1f4a9","1f921","1f47b","1f47d","1f916","1f648","1f649","1f64a"]],["love","Love",["2764_fe0f","1f9e1","1f49b","1f49a","1f499","1f49c","1f90e","1f5a4","1f90d","1fa77","1fa75","1f494","2764_fe0f_200d_1f525","2764_fe0f_200d_1fa79","1f495","1f49e","1f493","1f497","1f496","1f498","1f49d","1f48b","1f48c","1f339","1f490"]],["hands","Hands",["1f44d","1f44e","1f44f","1f64c","1fae6","1f64f","1f44b","1f91d","270c_fe0f","1f91e","1faf0","1f91f","1f918","1f919","1f44c","1f90c","1f448","1f449","1f446","1f447","261d_fe0f","270b","1f590_fe0f","1f596","1faf6","1f4aa","1f9be","1f440","1f441_fe0f","1f9e0","1fac0","1f485","1f933"]],["party","Party",["1f389","1f38a","1f388","1f381","1f382","1f37e","1f942","1f37b","1f525","2728","1f4af","1f31f","2b50","1f308","1f386","1fa94","1f3c6","1f947","1f3af","1f680","1f4a5","1f4ab","1f4ac","1f4a1","1f3b6","1f3b8","26bd","1f3c0"]],["animals","Animals & nature",["1f415","1f429","1f981","1f405","1f984","1f42e","1f416","1f407","1f43f_fe0f","1f994","1f987","1f43b","1f43c","1f9a5","1f998","1f423","1f425","1f426","1f99a","1f989","1f985","1f427","1f438","1f40a","1f422","1f98e","1f40d","1f409","1f433","1f42c","1f988","1f419","1f41f","1f421","1f980","1f40c","1f98b","1f41b","1f41d","1f41e","1f577_fe0f","1f337","1f335","1f340","1f341"]],["food","Food & drink",["1f34e","1f350","1f34a","1f34b","1f349","1f347","1f353","1fad0","1f352","1f96d","1f34d","1f95d","1f345","1f951","1f955","1f33d","1f966","1f9c4","1f344","1f35e","1f968","1f9c0","1f373","1f953","1f354","1f355","1f32d","1f32e","1f37f","1f9c2","1f35c","1f35d","1f366","1f368","1f369","1f36a","1f37c","2615","1f375","1f9cb","1f377","1f379","1f9c3"]],["travel","Travel & places",["1f697","1f695","1f68c","1f3ce_fe0f","1f6b2","2708_fe0f","1f6f8","26f5","1f30d","1f30e","1f30f","1f30b","1f3e0","1f3a1","1f3a2","1f305","1f304","1f307","1f31e","26c5","1f327_fe0f","2744_fe0f","2603_fe0f","1f30a","26a1","1f32a_fe0f"]]];
  var RECENT_KEY = 'educhats-recent-stickers';
  function stickerSrc(code) { return 'https://fonts.gstatic.com/s/e/notoemoji/latest/' + code + '/512.webp'; }
  var pickerReady = null;
  function loadPicker() {
    if (!pickerReady) {
      pickerReady = new Promise(function (resolve, reject) {
        var s = document.createElement('script');
        s.type = 'module'; s.src = PICKER_SRC;
        s.onload = function () { customElements.whenDefined('emoji-picker').then(resolve); };
        s.onerror = function () { pickerReady = null; reject(); };
        document.head.appendChild(s);
      });
    }
    return pickerReady;
  }
  function insertAtCursor(box, text) {
    var start = box.selectionStart == null ? box.value.length : box.selectionStart;
    var end = box.selectionEnd == null ? start : box.selectionEnd;
    if (box.maxLength > 0 && box.value.length - (end - start) + text.length > box.maxLength) return;
    box.value = box.value.slice(0, start) + text + box.value.slice(end);
    box.selectionStart = box.selectionEnd = start + text.length;
    box.dispatchEvent(new Event('input', { bubbles: true }));
  }
  function recentStickers() { try { return JSON.parse(localStorage.getItem(RECENT_KEY) || '[]') || []; } catch (e) { return []; } }
  function rememberSticker(code) {
    var list = recentStickers().filter(function (c) { return c !== code; });
    list.unshift(code);
    try { localStorage.setItem(RECENT_KEY, JSON.stringify(list.slice(0, 24))); } catch (e) {}
  }
  function emojiPicker(button, box, opts) {
    opts = opts || {};
    var rich = !!(opts.onSticker || opts.onGif);
    var pop = null, tab = 'emoji', gifTimer = null, gifSeq = 0, gifsLoaded = false, pack = null;
    function place() {
      var r = button.getBoundingClientRect(), w = Math.min(380, window.innerWidth - 16);
      pop.style.width = w + 'px';
      pop.style.left = Math.max(8, Math.min(r.left, window.innerWidth - w - 8)) + 'px';
      pop.style.bottom = (window.innerHeight - r.top + 10) + 'px';
    }
    function close() { if (pop) pop.classList.remove('open'); button.classList.remove('on'); }
    function show(name) {
      tab = name;
      pop.querySelectorAll('.ep-pane').forEach(function (p) { p.hidden = p.dataset.pane !== name; });
      pop.querySelectorAll('.ep-tabs button').forEach(function (b) { b.classList.toggle('on', b.dataset.tab === name); });
      if (name === 'gif' && !gifsLoaded) searchGifs('');
      if (name === 'sticker') showPack(pack || (recentStickers().length ? 'recent' : STICKER_PACKS[0][0]));
      if (name === 'gif') setTimeout(function () { pop.querySelector('.ep-gifq').focus(); }, 50);
    }
    // ── stickers ──
    function showPack(key) {
      pack = key;
      var grid = pop.querySelector('.ep-stickers'), codes, title;
      pop.querySelectorAll('.ep-cats button').forEach(function (b) { b.classList.toggle('on', b.dataset.pack === key); });
      if (key === 'recent') { codes = recentStickers(); title = 'Recently used'; }
      else { var p = STICKER_PACKS.filter(function (x) { return x[0] === key; })[0]; codes = p[2]; title = p[1]; }
      grid.textContent = '';
      var h = el('div', 'ep-title', title); grid.appendChild(h);
      if (!codes.length) { grid.appendChild(el('p', 'ep-empty', 'Stickers you send show up here.')); return; }
      codes.forEach(function (code) {
        var b = el('button', 'ep-sticker'); b.type = 'button'; b.title = 'Send sticker';
        var img = el('img'); img.src = stickerSrc(code); img.alt = ''; img.loading = 'lazy'; img.draggable = false;
        b.appendChild(img);
        b.addEventListener('click', function () { rememberSticker(code); close(); opts.onSticker(code); });
        grid.appendChild(b);
      });
      grid.scrollTop = 0;
    }
    // ── GIFs ──
    function gifNote(text, icon) {
      var grid = pop.querySelector('.ep-gifs'); grid.textContent = '';
      var p = el('div', 'ep-empty'); p.innerHTML = '<i class="fas ' + (icon || 'fa-film') + '"></i>'; p.appendChild(el('span', '', text));
      grid.appendChild(p);
    }
    function searchGifs(q) {
      var mine = ++gifSeq;
      gifNote(q ? 'Searching GIFs…' : 'Loading trending GIFs…', 'fa-spinner fa-spin');
      fetch(opts.gifUrl + '?q=' + encodeURIComponent(q), { credentials: 'same-origin' })
        .then(function (r) { return r.json(); })
        .then(function (res) {
          if (mine !== gifSeq) return;
          if (!res.ok) return gifNote(res.error || 'GIFs could not be loaded.', res.setup ? 'fa-circle-info' : 'fa-triangle-exclamation');
          gifsLoaded = true;
          pop.querySelector('.ep-attr').textContent = 'Powered by ' + res.provider;
          if (!res.gifs.length) return gifNote('No GIFs found for “' + q + '”.');
          var grid = pop.querySelector('.ep-gifs'); grid.textContent = '';
          res.gifs.forEach(function (g) {
            var b = el('button', 'ep-gif'); b.type = 'button'; b.title = g.title || 'Send GIF';
            b.style.aspectRatio = g.w + ' / ' + g.h;
            var img = el('img'); img.src = g.preview; img.alt = g.title || 'GIF'; img.loading = 'lazy'; img.draggable = false;
            b.appendChild(img);
            b.addEventListener('click', function () { close(); opts.onGif({ url: g.url, w: g.w, h: g.h }); });
            grid.appendChild(b);
          });
        }).catch(function () { if (mine === gifSeq) gifNote('GIFs could not be loaded. Check your connection.', 'fa-triangle-exclamation'); });
    }
    function build() {
      pop = el('div', 'emoji-pop' + (rich ? ' rich' : ''));
      var emojiPane = el('div', 'ep-pane'); emojiPane.dataset.pane = 'emoji';
      var picker = document.createElement('emoji-picker'); picker.className = 'light';
      picker.addEventListener('emoji-click', function (ev) { insertAtCursor(box, ev.detail.unicode); });
      emojiPane.appendChild(picker); pop.appendChild(emojiPane);
      if (rich) {
        var gifPane = el('div', 'ep-pane'); gifPane.dataset.pane = 'gif'; gifPane.hidden = true;
        gifPane.innerHTML = '<label class="ep-search"><i class="fas fa-magnifying-glass"></i><input class="ep-gifq" type="search" placeholder="Search GIFs" maxlength="60" autocomplete="off"></label><div class="ep-gifs"></div><div class="ep-attr"></div>';
        gifPane.querySelector('.ep-gifq').addEventListener('input', function () {
          var q = this.value.trim(); clearTimeout(gifTimer);
          gifTimer = setTimeout(function () { searchGifs(q); }, 400);
        });
        pop.appendChild(gifPane);
        var stPane = el('div', 'ep-pane'); stPane.dataset.pane = 'sticker'; stPane.hidden = true;
        var cats = el('div', 'ep-cats');
        var rec = el('button'); rec.type = 'button'; rec.dataset.pack = 'recent'; rec.title = 'Recently used'; rec.innerHTML = '<i class="fas fa-clock-rotate-left"></i>';
        rec.addEventListener('click', function () { showPack('recent'); }); cats.appendChild(rec);
        STICKER_PACKS.forEach(function (p) {
          var b = el('button'); b.type = 'button'; b.dataset.pack = p[0]; b.title = p[1];
          var img = el('img'); img.src = stickerSrc(p[2][0]); img.alt = ''; img.loading = 'lazy'; b.appendChild(img);
          b.addEventListener('click', function () { showPack(p[0]); });
          cats.appendChild(b);
        });
        stPane.appendChild(cats); stPane.appendChild(el('div', 'ep-stickers')); pop.appendChild(stPane);
        var tabs = el('div', 'ep-tabs');
        [['emoji', '<i class="fa-regular fa-face-smile"></i>', 'Emoji'], ['gif', '<b>GIF</b>', 'GIFs'], ['sticker', '<i class="fas fa-note-sticky"></i>', 'Stickers']].forEach(function (t) {
          var b = el('button'); b.type = 'button'; b.dataset.tab = t[0]; b.title = t[2]; b.innerHTML = t[1];
          b.appendChild(el('span', '', t[2]));
          b.addEventListener('click', function () { show(t[0]); });
          tabs.appendChild(b);
        });
        pop.appendChild(tabs);
      }
      pop.addEventListener('click', function (ev) { ev.stopPropagation(); });
      document.body.appendChild(pop);
      show('emoji');
    }
    button.addEventListener('click', function (e) {
      e.stopPropagation();
      if (pop && pop.classList.contains('open')) return close();
      button.classList.add('on');
      loadPicker().then(function () {
        if (!pop) build();
        place(); pop.classList.add('open');
      }).catch(function () { button.classList.remove('on'); alert('Emojis could not load. Please check your internet and try again.'); });
    });
    document.addEventListener('click', close);
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') close(); });
    window.addEventListener('resize', function () { if (pop && pop.classList.contains('open')) place(); });
  }

  var api = window.SupportChat = { canSave: false, renderBody: renderBody, updateLocations: updateLocations, Calls: Calls, emojiPicker: emojiPicker,
    voiceRecorder: voiceRecorder, fmtTime: fmtTime, openMap: openMap, pickerMap: pickerMap, loadLeaflet: loadLeaflet, csrf: null,
    // ringtone picker (Settings → Permissions & ringtone) and call hooks set by the page
    ringtones: Object.keys(RINGTONES).map(function (k) { return { key: k, name: RINGTONES[k][0] }; }),
    ringtone: ringtone, previewRingtone: previewRingtone,
    setRingtone: function (k) { try { localStorage.setItem('educhats-ringtone', k); } catch (e) {} },
    autoAnswerUntil: 0, onMediaBlocked: null };
})();
