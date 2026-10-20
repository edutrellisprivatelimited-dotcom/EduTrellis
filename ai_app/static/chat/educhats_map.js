/* EduChats → Maps tab: everyone on EduChats across India as coloured pins.
   Opens full screen over the app; "Add me to the map" saves your spot and what
   others may see (⋮ sheet #mapMeSheet). Server side: ai_app/educhats_map.py. */
(function () {
  'use strict';
  var view = document.getElementById('mapsView'), cfgEl = document.getElementById('maps-config');
  if (!view || !cfgEl || !window.SupportChat) return;
  var cfg = JSON.parse(cfgEl.textContent);
  if (!cfg) return;
  var REGIONS = {
    north: ['North India', '#f43f5e'], west: ['West India', '#f59e0b'], south: ['South India', '#10b981'],
    east: ['East India', '#3b82f6'], northeast: ['North-East', '#a855f7'], central: ['Central India', '#06b6d4']
  };
  var STYLES = {
    // CARTO basemaps: OpenStreetMap's own tile servers refuse apps (403 "Access blocked").
    dark: ['https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>'],
    light: ['https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>'],
    sat: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', 'Imagery &copy; Esri']
  };
  var $ = function (id) { return document.getElementById(id); };
  var L = null, map = null, tiles = null, pinLayer = null, hereMarker = null, data = null, filter = null, style = 'dark';
  try { style = localStorage.getItem('educhats-map-style') || 'dark'; } catch (e) {}
  if (!STYLES[style]) style = 'dark';

  function esc(s) { var d = document.createElement('div'); d.textContent = s == null ? '' : String(s); return d.innerHTML; }
  function post(url, body) {
    return fetch(url, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': SupportChat.csrf() }, body: JSON.stringify(body || {}) })
      .then(function (r) { return r.json().catch(function () { return { ok: false, error: 'Something went wrong. Please try again.' }; }); });
  }
  function toast(o) { if (window.eduToast) window.eduToast(o); }

  // ── open / close ──
  function open() {
    view.hidden = false;
    requestAnimationFrame(function () { view.classList.add('open'); });
    document.addEventListener('keydown', onKey);
    $('mpLoad').hidden = false;
    SupportChat.loadLeaflet().then(function (lib) {
      L = lib;
      if (!map) build();
      setTimeout(function () { map.invalidateSize(); }, 60);
      return load();
    }).catch(function () {
      $('mpLoad').innerHTML = '<i class="fas fa-triangle-exclamation"></i> Couldn\'t load the map. Check your internet and try again.';
    });
  }
  function close() {
    view.classList.remove('open');
    document.removeEventListener('keydown', onKey);
    setTimeout(function () { view.hidden = true; }, 280);
  }
  function onKey(e) { if (e.key === 'Escape' && !document.querySelector('.sheet.open')) close(); }

  function build() {
    var phone = window.innerWidth < 600;
    map = L.map('mpMap', { zoomControl: false, minZoom: 4, maxZoom: 18, worldCopyJump: false,
      maxBounds: [[-2, 58], [42, 108]], maxBoundsViscosity: 0.8 }).setView(phone ? [22.5, 81] : [22.8, 80.5], phone ? 4 : 5);
    L.control.zoom({ position: 'bottomright' }).addTo(map);
    pinLayer = L.layerGroup().addTo(map);
    setStyle(style);
  }
  function setStyle(k) {
    style = k;
    try { localStorage.setItem('educhats-map-style', k); } catch (e) {}
    if (tiles) map.removeLayer(tiles);
    tiles = L.tileLayer(STYLES[k][0], { maxZoom: 19, subdomains: 'abcd', attribution: STYLES[k][1] }).addTo(map);
    var el = $('mpMap');
    el.classList.toggle('mp-dark', k === 'dark'); el.classList.toggle('mp-light', k === 'light');
    view.querySelectorAll('.mp-seg button').forEach(function (b) { b.classList.toggle('on', b.dataset.style === k); });
  }

  // ── pins ──
  function load() {
    return fetch(cfg.api, { credentials: 'same-origin', cache: 'no-store' }).then(function (r) { return r.json(); }).then(function (res) {
      $('mpLoad').hidden = true;
      if (!res || !res.ok) { toast({ kind: 'error', icon: 'fa-triangle-exclamation', title: 'Map not available', text: (res && res.error) || 'Please try again.' }); return; }
      data = res;
      draw(); stats(); joinButton();
    });
  }
  function pinIcon(p, i) {
    var c = REGIONS[p.r] ? REGIONS[p.r][1] : '#06b6d4', size = p.me ? 30 : 14;
    return L.divIcon({ className: 'mp-pin-wrap', iconSize: [size, size], iconAnchor: [size / 2, size / 2], popupAnchor: [0, -size / 2],
      html: '<span class="mp-pin' + (p.me ? ' me' : '') + (p.on ? ' on' : '') + '" style="--c:' + c + ';animation-delay:' + (i % 80) * 9 + 'ms">' + (p.me ? '<i class="fas fa-user"></i>' : '') + '</span>' });
  }
  function popup(p) {
    var reg = REGIONS[p.r] || REGIONS.central, d = p.d || {};
    var title = d.name || (d.username ? '@' + d.username : 'User ' + p.n);
    var initial = (d.name || d.username || 'U').charAt(0).toUpperCase();
    var html = '<div style="--c:' + reg[1] + '"><div class="pp-head"><span class="pp-ava">' + (d.photo ? '<img src="' + esc(d.photo) + '" alt="">' : esc(p.d ? initial : p.n)) + '</span>' +
      '<div><b>' + esc(title) + (p.me ? '<span class="pp-you">You</span>' : '') + '</b><small><i></i>' + (p.on ? 'Online now' : 'EduChats member') + '</small></div></div>';
    var rows = [];
    if (d.name && d.username) rows.push(['fa-at', '@' + d.username]);
    if (d.city) rows.push(['fa-location-dot', d.city]);
    if (d.email) rows.push(['fa-envelope', d.email]);
    if (d.bio) rows.push(['fa-quote-left', d.bio]);
    if (rows.length) html += '<div class="pp-rows">' + rows.map(function (r) { return '<span><i class="fas ' + r[0] + '"></i>' + esc(r[1]) + '</span>'; }).join('') + '</div>';
    return html + '</div>';
  }
  function draw() {
    pinLayer.clearLayers();
    var shown = 0;
    data.pins.forEach(function (p) {
      if (filter && p.r !== filter && !p.me) return;
      L.marker([p.lat, p.lng], { icon: pinIcon(p, shown++), riseOnHover: true, zIndexOffset: p.me ? 1000 : 0, keyboard: false })
        .bindPopup(popup(p), { className: 'mp-pop', closeButton: false })
        .addTo(pinLayer);
    });
  }
  function count(el, to) {   // numbers roll up when the map opens
    var from = +el.textContent || 0, t0 = performance.now();
    (function step(t) {
      var k = Math.min(1, (t - t0) / 900), v = Math.round(from + (to - from) * (1 - Math.pow(1 - k, 3)));
      el.textContent = v.toLocaleString('en-IN');
      if (k < 1) requestAnimationFrame(step);
    })(t0);
  }
  function stats() {
    count($('mpTotal'), data.pins.length); count($('mpStates'), data.states); count($('mpCities'), data.cities);
    var by = {};
    data.pins.forEach(function (p) { by[p.r] = (by[p.r] || 0) + 1; });
    var legend = $('mpLegend'); legend.textContent = '';
    Object.keys(REGIONS).forEach(function (k) {
      if (!by[k]) return;
      var b = document.createElement('button'); b.type = 'button'; b.className = 'mp-chip' + (filter === k ? ' on' : ''); b.style.setProperty('--c', REGIONS[k][1]);
      b.innerHTML = '<i></i>' + esc(REGIONS[k][0]) + ' <em>' + by[k] + '</em>';
      b.addEventListener('click', function () { filter = filter === k ? null : k; stats(); draw(); });
      legend.appendChild(b);
    });
    legend.classList.toggle('filtering', !!filter);
    var demo = $('mpDemo');
    demo.hidden = !data.demo;
    if (data.demo) $('mpDemoN').textContent = data.demo;
  }
  function joinButton() {
    var b = $('mpJoin'), on = !!(data && data.mine);
    b.classList.toggle('on', on);
    $('mpJoinLabel').textContent = !data || !data.can_join ? 'Log in to add yourself' : on ? (data.mine.visible ? "You're on the map · Edit" : 'Hidden from the map · Edit') : 'Add me to the map';
  }

  // ── "where am I" (not saved) ──
  function locate() {
    if (!navigator.geolocation) { toast({ kind: 'error', icon: 'fa-location-crosshairs', title: 'Location not available', text: 'This browser can\'t share your location.' }); return; }
    navigator.geolocation.getCurrentPosition(function (pos) {
      var ll = [pos.coords.latitude, pos.coords.longitude];
      if (hereMarker) hereMarker.setLatLng(ll);
      else hereMarker = L.marker(ll, { icon: L.divIcon({ className: 'mp-pin-wrap', iconSize: [18, 18], iconAnchor: [9, 9], html: '<span class="mp-here"></span>' }), zIndexOffset: 2000 }).addTo(map);
      map.flyTo(ll, Math.max(map.getZoom(), 11), { duration: 1.2 });
    }, function () {
      toast({ kind: 'error', icon: 'fa-location-crosshairs', title: 'Location is off', text: 'Allow location for EduChats in your browser settings.' });
    }, { enableHighAccuracy: true, timeout: 12000, maximumAge: 60000 });
  }

  // ── "You on the map" sheet ──
  var sheet = $('mapMeSheet'), fix = null;
  function openMe() {
    if (!data || !data.can_join) { var login = $('openLogin'); if (login) { close(); login.click(); } return; }
    var mine = data.mine;
    fix = null;
    sheet.querySelectorAll('[data-mm]').forEach(function (i) {
      var k = i.dataset.mm;
      i.checked = mine ? !!mine[k] : (k === 'visible' || k === 'show_city');
    });
    $('mmLocate').classList.toggle('done', !!mine);
    $('mmLocTitle').textContent = mine ? 'Update my location' : 'Use my current location';
    $('mmLocSub').textContent = mine ? 'Saved near ' + (mine.city || 'your area') + ' · tap to refresh' : 'Allow location when your browser asks';
    $('mmRemove').hidden = !mine;
    $('mmErr').hidden = true;
    $('mmSave').textContent = mine ? 'Save' : 'Add me';
    sheet.classList.add('open');
  }
  function err(msg) { var e = $('mmErr'); e.textContent = msg; e.hidden = !msg; }
  $('mmLocate').addEventListener('click', function () {
    if (!navigator.geolocation) { err('This browser can\'t share your location.'); return; }
    $('mmLocTitle').textContent = 'Finding you…'; err('');
    navigator.geolocation.getCurrentPosition(function (pos) {
      fix = { lat: pos.coords.latitude, lng: pos.coords.longitude };
      $('mmLocate').classList.add('done');
      $('mmLocTitle').textContent = 'Location found';
      $('mmLocSub').textContent = 'Accurate to about ' + Math.max(1, Math.round(pos.coords.accuracy)) + ' m · shown rounded to ~1 km';
    }, function () {
      $('mmLocTitle').textContent = 'Use my current location';
      err('Location is off. Allow location for EduChats in your browser settings, then try again.');
    }, { enableHighAccuracy: true, timeout: 15000, maximumAge: 30000 });
  });
  $('mmSave').addEventListener('click', function () {
    if (!fix && !data.mine) { err('Tap "Use my current location" first.'); return; }
    var body = { action: 'save' };
    if (fix) { body.lat = fix.lat; body.lng = fix.lng; }
    sheet.querySelectorAll('[data-mm]').forEach(function (i) { body[i.dataset.mm] = i.checked; });
    var btn = this; btn.disabled = true;
    post(cfg.me, body).then(function (res) {
      btn.disabled = false;
      if (!res.ok) { err(res.error || 'Couldn\'t save. Please try again.'); return; }
      sheet.classList.remove('open');
      toast({ kind: 'success', icon: 'fa-map-pin', title: body.visible ? "You're on the map" : 'Saved — your pin is hidden', text: body.visible ? 'Others see only what you picked.' : 'Turn "Show me on the map" on any time.', ms: 3200 });
      load().then(function () { if (res.mine && body.visible) map.flyTo([res.mine.lat, res.mine.lng], Math.max(map.getZoom(), 10), { duration: 1.2 }); });
    }).catch(function () { btn.disabled = false; err('No internet connection. Please try again.'); });
  });
  $('mmRemove').addEventListener('click', function () {
    post(cfg.me, { action: 'remove' }).then(function (res) {
      if (!res.ok) { err(res.error || 'Couldn\'t remove. Please try again.'); return; }
      sheet.classList.remove('open');
      toast({ icon: 'fa-map-pin', title: 'Removed from the map', ms: 2600 });
      load();
    });
  });

  // ── wiring ──
  $('mpBack').addEventListener('click', close);
  $('mpLocate').addEventListener('click', locate);
  $('mpJoin').addEventListener('click', openMe);
  view.querySelectorAll('.mp-seg button').forEach(function (b) { b.addEventListener('click', function () { if (map) setStyle(b.dataset.style); }); });
  $('mpDemoDel').addEventListener('click', function () {
    if (!confirm('Remove all ' + data.demo + ' demo users (example1@gmail.com … ) and their pins? This can\'t be undone.')) return;
    post(cfg.demo).then(function (res) {
      if (!res.ok) { toast({ kind: 'error', icon: 'fa-triangle-exclamation', title: res.error || 'Couldn\'t remove them' }); return; }
      toast({ kind: 'success', icon: 'fa-broom', title: res.deleted + ' demo users removed', ms: 3000 });
      load();
    });
  });
  window.EduMaps = { open: open, close: close };
})();
