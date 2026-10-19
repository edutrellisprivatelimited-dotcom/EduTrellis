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

  function liveLabel(loc) {
    if (!loc.live_until) return 'Location';
    if (!loc.live) return 'Live location ended';
    var mins = Math.max(1, Math.round((new Date(loc.live_until) - new Date()) / 60000));
    return 'Live location · ' + (mins >= 60 ? Math.round(mins / 60) + ' h' : mins + ' min') + ' left';
  }

  // Fills a bubble's content area for message m.
  function renderBody(box, m) {
    box.textContent = '';
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
      var frame = el('iframe', 'att-map');
      frame.src = mapSrc(m.lat, m.lng); frame.loading = 'lazy'; frame.title = 'Map';
      frame.setAttribute('referrerpolicy', 'no-referrer');
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
      wrap._loc = { lat: m.lat, lng: m.lng };
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
      if (!wrap._loc || wrap._loc.lat !== loc.lat || wrap._loc.lng !== loc.lng) {
        wrap._loc = { lat: loc.lat, lng: loc.lng };
        wrap.querySelector('.att-map').src = mapSrc(loc.lat, loc.lng);
        wrap.querySelector('.att-loc-open').href = 'https://www.google.com/maps?q=' + loc.lat + ',' + loc.lng;
      }
    });
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
  // opts: { url, side: 'user'|'admin'|<chat user id>, peerName, csrf, onError(text), keep, photo }
  // keep: leave other call screens on the page (EduChats has one per chat)
  function Calls(opts) {
    var self = this;
    var pc = null, local = null, call = null, iceSeen = 0, fast = null, timer = null, ringTone = null;
    var pendingIce = [];
    var ui = buildUi();

    function buildUi() {
      // The dashboard swaps pages in place, so an earlier page's (idle) call
      // screen may still be here.
      if (!opts.keep) document.querySelectorAll('.call-overlay:not(.open)').forEach(function (old) { old.remove(); });
      var o = el('div', 'call-overlay');
      o.innerHTML =
        '<video class="call-remote" autoplay playsinline></video>' +
        '<video class="call-local" autoplay playsinline muted></video>' +
        '<div class="call-info"><div class="call-avatar"><i class="fas fa-user"></i></div>' +
        '<div class="call-name"></div><div class="call-state"></div></div>' +
        '<div class="call-bar">' +
        '<button class="call-btn mute" title="Mute"><i class="fas fa-microphone"></i></button>' +
        '<button class="call-btn cam" title="Camera"><i class="fas fa-video"></i></button>' +
        '<button class="call-btn accept" title="Answer"><i class="fas fa-phone"></i></button>' +
        '<button class="call-btn end" title="End"><i class="fas fa-phone-slash"></i></button></div>';
      document.body.appendChild(o);
      o.querySelector('.call-name').textContent = opts.peerName;
      if (opts.photo) {
        var av = o.querySelector('.call-avatar'), pic = el('img'); pic.src = opts.photo; pic.alt = '';
        pic.style.cssText = 'width:100%;height:100%;object-fit:cover;border-radius:50%';
        pic.onerror = function () { pic.remove(); av.innerHTML = '<i class="fas fa-user"></i>'; };
        av.textContent = ''; av.appendChild(pic);
      }
      o.querySelector('.end').addEventListener('click', function () { self.hangUp(); });
      o.querySelector('.accept').addEventListener('click', function () { self.answer(); });
      o.querySelector('.mute').addEventListener('click', function () {
        if (!local) return;
        var t = local.getAudioTracks()[0]; if (!t) return;
        t.enabled = !t.enabled; this.classList.toggle('off', !t.enabled);
      });
      o.querySelector('.cam').addEventListener('click', function () {
        if (!local) return;
        var t = local.getVideoTracks()[0]; if (!t) return;
        t.enabled = !t.enabled; this.classList.toggle('off', !t.enabled);
      });
      return o;
    }

    function show(state, text) {
      ui.className = 'call-overlay open ' + state + ' ' + (call && call.kind === 'video' ? 'is-video' : 'is-audio');
      ui.querySelector('.call-state').textContent = text;
    }

    function send(data) {
      return fetch(opts.url, {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': opts.csrf }, body: JSON.stringify(data)
      }).then(function (r) { return r.json(); });
    }

    function media(kind) {
      if (!navigator.mediaDevices || !window.RTCPeerConnection) {
        return Promise.reject(new Error('Calls need a modern browser on a secure (https) page.'));
      }
      return navigator.mediaDevices.getUserMedia({ audio: true, video: kind === 'video' ? { facingMode: 'user' } : false })
        .catch(function () { throw new Error('Allow microphone' + (kind === 'video' ? ' and camera' : '') + ' access to call.'); });
    }

    function makePeer(servers) {
      pc = new RTCPeerConnection({ iceServers: servers });
      local.getTracks().forEach(function (t) { pc.addTrack(t, local); });
      ui.querySelector('.call-local').srcObject = local;
      pc.ontrack = function (e) { ui.querySelector('.call-remote').srcObject = e.streams[0]; };
      pc.onicecandidate = function (e) {
        if (e.candidate && call) send({ action: 'ice', id: call.id, candidate: e.candidate.toJSON() });
      };
      pc.onconnectionstatechange = function () {
        if (pc && pc.connectionState === 'connected') startTimer();
        if (pc && pc.connectionState === 'failed') { opts.onError('The call could not connect on this network.'); self.hangUp(); }
      };
    }

    function startTimer() {
      if (timer) return;
      var t0 = Date.now();
      show('active', '0:00');
      timer = setInterval(function () {
        var s = Math.floor((Date.now() - t0) / 1000);
        ui.querySelector('.call-state').textContent = Math.floor(s / 60) + ':' + ('0' + (s % 60)).slice(-2);
      }, 1000);
    }

    function addIce(list) {
      (list || []).slice(iceSeen).forEach(function (c) {
        if (pc && pc.remoteDescription) pc.addIceCandidate(c).catch(function () {});
        else pendingIce.push(c);
      });
      iceSeen = Math.max(iceSeen, (list || []).length);
    }

    function flushIce() {
      pendingIce.splice(0).forEach(function (c) { pc.addIceCandidate(c).catch(function () {}); });
    }

    function pollFast() {
      if (fast) return;
      fast = setInterval(function () {
        fetch(opts.url, { credentials: 'same-origin' }).then(function (r) { return r.json(); })
          .then(function (res) { if (res.ok) self.sync(res.call, res.ice_servers); }).catch(function () {});
      }, 1000);
    }

    function ring(on) {
      try {
        if (on && !ringTone) {
          var ctx = new (window.AudioContext || window.webkitAudioContext)();
          var osc = ctx.createOscillator(), gain = ctx.createGain();
          osc.frequency.value = 440; gain.gain.value = 0;
          osc.connect(gain); gain.connect(ctx.destination); osc.start();
          var beat = setInterval(function () {
            gain.gain.setValueAtTime(0.08, ctx.currentTime);
            gain.gain.setValueAtTime(0, ctx.currentTime + 0.4);
          }, 1500);
          ringTone = { ctx: ctx, beat: beat };
        } else if (!on && ringTone) {
          clearInterval(ringTone.beat); ringTone.ctx.close(); ringTone = null;
        }
      } catch (e) {}
    }

    function cleanup(text) {
      ring(false);
      clearInterval(fast); fast = null;
      clearInterval(timer); timer = null;
      if (pc) { pc.close(); pc = null; }
      if (local) { local.getTracks().forEach(function (t) { t.stop(); }); local = null; }
      ui.querySelector('.call-remote').srcObject = null;
      iceSeen = 0; pendingIce = [];
      if (text) { show('ended', text); setTimeout(function () { ui.className = 'call-overlay'; }, 1800); }
      else ui.className = 'call-overlay';
      call = null;
    }

    this.start = function (kind) {
      if (call) return;
      call = { kind: kind };
      show('calling', 'Calling…');
      media(kind).then(function (stream) {
        local = stream;
        return fetch(opts.url, { credentials: 'same-origin' }).then(function (r) { return r.json(); });
      }).then(function (res) {
        makePeer(res.ice_servers);
        return pc.createOffer().then(function (offer) { return pc.setLocalDescription(offer).then(function () { return offer; }); });
      }).then(function (offer) {
        return send({ action: 'start', kind: kind, offer: { type: offer.type, sdp: offer.sdp } });
      }).then(function (res) {
        if (!res.ok) throw new Error(res.error || 'Could not start the call.');
        call = res.call; show('calling', 'Ringing…'); pollFast();
      }).catch(function (err) { cleanup(); opts.onError(err.message); });
    };

    this.answer = function () {
      if (!call || !call.offer) return;
      ring(false);
      show('connecting', 'Connecting…');
      media(call.kind).then(function (stream) {
        local = stream;
        return fetch(opts.url, { credentials: 'same-origin' }).then(function (r) { return r.json(); });
      }).then(function (res) {
        makePeer(res.ice_servers);
        return pc.setRemoteDescription(call.offer);
      }).then(function () {
        flushIce();
        return pc.createAnswer();
      }).then(function (answer) {
        return pc.setLocalDescription(answer).then(function () {
          return send({ action: 'answer', id: call.id, answer: { type: answer.type, sdp: answer.sdp } });
        });
      }).then(function (res) {
        if (!res.ok) throw new Error(res.error || 'Could not answer.');
        pollFast();
      }).catch(function (err) {
        if (call) send({ action: 'decline', id: call.id });
        cleanup(); opts.onError(err.message);
      });
    };

    this.busy = function () { return !!call; };
    this.hangUp = function () {
      if (call && call.id) send({ action: call.status === 'ringing' && call.caller !== opts.side ? 'decline' : 'end', id: call.id });
      cleanup('Call ended');
    };

    // Called with the server's view of the call on every poll.
    this.sync = function (state) {
      if (!state || state.status === 'ended') {
        if (call && call.id && (!state || state.id === call.id)) {
          var reason = state && state.reason;
          cleanup(reason === 'declined' ? 'Call declined' : reason === 'missed' ? 'No answer' : 'Call ended');
        }
        return;
      }
      if (!call) {
        if (state.status === 'ringing' && state.caller !== opts.side) {
          call = state;
          show('incoming', 'Incoming ' + (state.kind === 'video' ? 'video' : 'voice') + ' call…');
          ring(true);
          pollFast();
        }
        return;
      }
      if (call.id && call.id !== state.id) return;
      var wasRinging = call.status === 'ringing';
      call = Object.assign(call, state);
      if (state.answer && pc && !pc.currentRemoteDescription && state.caller === opts.side) {
        pc.setRemoteDescription(state.answer).then(flushIce).catch(function () {});
        show('connecting', 'Connecting…');
      }
      if (wasRinging && state.status === 'active' && state.caller !== opts.side && !pc) cleanup();   // answered elsewhere
      addIce(state.ice);
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
    voiceRecorder: voiceRecorder, fmtTime: fmtTime };
})();
