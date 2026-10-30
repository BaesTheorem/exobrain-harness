"use strict";
/* MIST TV Agent service. Runs on the TV. HTTP on the LAN, port 8099, token in
 * the query string. Installs and removes packages through the TV's own
 * developer bridge on 127.0.0.1:26101 (the restricted `shell 0` command set),
 * launches apps, and reads or writes TizenBrew's module config and the module
 * name the Criterion tile launches. Old-Node JavaScript on purpose. */
module.exports.onStart = function () {
  var http = require('http'), fs = require('fs'), url = require('url');
  var adbhost = require('./adbhost/index.js');
  var cfg = require('./config.js');
  var PORT = 8099;
  var TMP = '/home/owner/share/tmp/sdk_tools/tmp/';
  var TB_CONFIG = '/home/owner/share/tizenbrewConfig.json';
  var STATE = '/home/owner/share/mist-tv-agent.json';
  var SAFE_NAME = /^[A-Za-z0-9._-]+$/, SAFE_PKG = /^[A-Za-z0-9]{10}$/, SAFE_APP = /^[A-Za-z0-9._-]+$/;
  var SAFE_CMD = /^(applist|capability|vd_[a-z]+)( [A-Za-z0-9._\/:-]+)*$/;

  // The bridge never closes a `shell 0` stream on its own, so the call ends
  // when the output has been quiet for a moment (longer while an install
  // is still printing progress), and the connection is dropped at once:
  // TizenBrew needs the same bridge to relaunch itself.
  function sdb(cmd, cb) {
    var chunks = [], done = false, client, quiet = null, hard;
    function finish(err) {
      if (done) return;
      done = true; clearTimeout(hard); clearTimeout(quiet);
      try { client._stream.destroy(); } catch (e) {}
      cb(err, Buffer.concat(chunks).toString());
    }
    function armQuiet(ms) { clearTimeout(quiet); quiet = setTimeout(function () { finish(null); }, ms); }
    hard = setTimeout(function () { finish(chunks.length ? null : 'no answer from the bridge in 180 s'); }, 180000);
    try { client = adbhost.createConnection({ host: '127.0.0.1', port: 26101 }); }
    catch (e) { return finish('bridge connect failed: ' + e.message); }
    client._stream.on('error', function (e) { finish('bridge error: ' + e.message); });
    client._stream.on('close', function () { finish(null); });
    armQuiet(15000);  // nothing at all for 15 s: give up with what we have
    var s = client.createStream('shell:0 ' + cmd);
    s.on('data', function (d) {
      chunks.push(d);
      var text = d.toString();
      armQuiet(/installing\[|install start|package_path/.test(text) ? 20000 : 1500);
    });
    s.on('end', function () { finish(null); });
    s.on('error', function (e) { finish('stream error: ' + e.message); });
  }

  function send(res, code, body, type) {
    res.writeHead(code, { 'Content-Type': type || 'text/plain; charset=utf-8', 'Access-Control-Allow-Origin': '*' });
    res.end(body);
  }
  function json(res, code, obj) { send(res, code, JSON.stringify(obj), 'application/json'); }
  function readState() { try { return JSON.parse(fs.readFileSync(STATE, 'utf8')); } catch (e) { return {}; } }
  function isLoopback(req) {
    var a = (req.socket && req.socket.remoteAddress) || '';
    return a === '127.0.0.1' || a === '::1' || a === '::ffff:127.0.0.1';
  }
  function body(req, cb) {
    var chunks = [], size = 0;
    req.on('data', function (d) { size += d.length; if (size > 60 * 1024 * 1024) { req.destroy(); return; } chunks.push(d); });
    req.on('end', function () { cb(Buffer.concat(chunks)); });
  }


  // ---- TizenBrew module launch ----------------------------------------
  // TizenBrew launches a module cleanly on one path only: its auto-launch
  // entry, read when its debugger attaches. So: write the entry, make
  // TizenBrew (re)start, clear the entry a little later.
  var TB_APP = 'xvvl3S1bvH.TizenBrewStandalone', TB_WS_PORT = 8081, RELAUNCH = 3;  // Events.ReLaunchInDebug
  function readTb() { try { return JSON.parse(fs.readFileSync(TB_CONFIG, 'utf8')); } catch (e) { return { modules: [], autoLaunchServiceList: [], autoLaunchModule: '' }; } }
  function writeTb(c) { fs.writeFileSync(TB_CONFIG, JSON.stringify(c, null, 4)); }

  // Minimal WebSocket client (Node 4 has none): handshake, one masked text frame, close.
  function wsSend(port, text, cb, host) {
    var net = require('net'), crypto = require('crypto'), done = false, sock;
    function fin(err) { if (done) return; done = true; try { sock.destroy(); } catch (e) {} cb(err); }
    sock = net.connect(port, host || '127.0.0.1');
    var t = setTimeout(function () { fin('ws timeout'); }, 4000);
    sock.on('error', function (e) { clearTimeout(t); fin('ws error: ' + e.message); });
    sock.on('connect', function () {
      var key = crypto.randomBytes(16).toString('base64');
      sock.write('GET / HTTP/1.1\r\nHost: 127.0.0.1:' + port + '\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: ' + key + '\r\nSec-WebSocket-Version: 13\r\n\r\n');
    });
    var buf = '';
    sock.on('data', function (d) {
      buf += d.toString('binary');
      if (buf.indexOf('\r\n\r\n') < 0) return;
      if (buf.indexOf(' 101 ') < 0) { clearTimeout(t); return fin('ws handshake refused'); }
      var payload = new Buffer(text, 'utf8'), mask = crypto.randomBytes(4), head;
      if (payload.length < 126) { head = new Buffer(2); head[1] = 0x80 | payload.length; }
      else { head = new Buffer(4); head[1] = 0x80 | 126; head.writeUInt16BE(payload.length, 2); }
      head[0] = 0x81;
      var masked = new Buffer(payload.length);
      for (var i = 0; i < payload.length; i++) masked[i] = payload[i] ^ mask[i % 4];
      sock.write(Buffer.concat([head, mask, masked]));
      setTimeout(function () { clearTimeout(t); fin(null); }, 300);
    });
  }

  function launchApp(appId, cb) {
    try { tizen.application.launch(appId, function () { cb(null); }, function (e) { cb('launch failed: ' + e.message); }); }
    catch (e) { cb('launch failed: ' + e.message); }
  }

  function launchModule(fullName, cb) {
    var c = readTb();
    if (c.modules.indexOf(fullName) < 0) return cb('module not registered in TizenBrew: ' + fullName);
    c.autoLaunchModule = fullName; writeTb(c);
    setTimeout(function () { var c2 = readTb(); if (c2.autoLaunchModule === fullName) { c2.autoLaunchModule = ''; writeTb(c2); } }, 60000);
    // TizenBrew service up: ask it to restart TizenBrew under its debugger (the auto-launch path).
    var msg = JSON.stringify({ type: RELAUNCH, payload: { tvIP: '127.0.0.1' } });
    wsSend(TB_WS_PORT, msg, function (err) {
      if (!err) return cb(null, 'relaunch requested through TizenBrew service');
      wsSend(TB_WS_PORT, msg, function (err2) {
        if (!err2) return cb(null, 'relaunch requested through TizenBrew service (localhost)');
        launchApp(TB_APP, function (err3) { cb(err3, err3 ? '' : 'TizenBrew launched (service was down: ' + err + ')'); });
      }, 'localhost');
    });
  }

  var server = http.createServer(function (req, res) {
    var u = url.parse(req.url, true), q = u.query || {}, p = u.pathname;
    if (p === '/ping') return json(res, 200, { ok: true, agent: 'mist-tv-agent', node: process.version, time: new Date().toISOString() });
    if (p === '/module' && req.method === 'GET' && isLoopback(req)) { var st = readState(); return json(res, 200, { moduleName: st.moduleName || '', moduleType: st.moduleType || 'gh' }); }
    if (p === '/launch-module' && req.method === 'POST' && (isLoopback(req) || q.token === cfg.token)) {
      var st2 = readState(), full = q.name || ((st2.moduleType || 'gh') + '/' + (st2.moduleName || ''));
      return launchModule(full, function (err, msg) { send(res, err ? 500 : 200, err ? err : msg); });
    }
    if (q.token !== cfg.token) return send(res, 403, 'forbidden');

    if (p === '/sysinfo') {
      var out = { node: process.version };
      try { out.totalMemory = tizen.systeminfo.getTotalMemory(); out.availableMemory = tizen.systeminfo.getAvailableMemory(); } catch (e) { out.memoryError = e.message; }
      var pending = 2;
      function done() { if (--pending === 0) json(res, 200, out); }
      try {
        tizen.systeminfo.getPropertyValue('STORAGE', function (st) {
          out.storage = (st.units || []).map(function (u) { return { type: u.type, capacity: u.capacity, available: u.availableCapacity, removable: u.isRemovable }; }); done();
        }, function (e) { out.storageError = e.message; done(); });
      } catch (e) { out.storageError = e.message; done(); }
      try {
        tizen.systeminfo.getPropertyValue('BUILD', function (b) { out.build = { model: b.model, manufacturer: b.manufacturer, buildVersion: b.buildVersion }; done(); },
          function (e) { out.buildError = e.message; done(); });
      } catch (e) { out.buildError = e.message; done(); }
      return;
    }
    if (p === '/meminfo') {
      var mi = {};
      try {
        fs.readFileSync('/proc/meminfo', 'utf8').split('\n').forEach(function (line) {
          var m = line.match(/^(\w+):\s+(\d+)\s*kB/);
          if (m) mi[m[1]] = parseInt(m[2], 10) * 1024;
        });
      } catch (e) { mi.error = e.message; }
      var procs = [], readable = 0, total = 0;
      try {
        fs.readdirSync('/proc').forEach(function (d) {
          if (!/^\d+$/.test(d)) return;
          total++;
          try {
            var st = fs.readFileSync('/proc/' + d + '/status', 'utf8');
            var nm = (st.match(/^Name:\s*(.+)$/m) || [])[1];
            var rss = (st.match(/^VmRSS:\s*(\d+)/m) || [])[1];
            if (nm && rss) { procs.push({ pid: +d, name: nm, rssBytes: parseInt(rss, 10) * 1024 }); readable++; }
          } catch (e) { /* sandbox hides other users' processes */ }
        });
      } catch (e) { mi.procError = e.message; }
      procs.sort(function (a, b) { return b.rssBytes - a.rssBytes; });
      return json(res, 200, { meminfo: mi, processes_total: total, processes_readable: readable, top: procs.slice(0, 40) });
    }
    if (p === '/apps') return sdb('vd_applist', function (err, out) { send(res, err ? 500 : 200, err ? err : out); });
    if (p === '/sdb' && req.method === 'POST') {
      if (!SAFE_CMD.test(q.cmd || '')) return send(res, 400, 'command not allowed');
      return sdb(q.cmd, function (err, out) { send(res, err ? 500 : 200, err ? err : out); });
    }
    if (p === '/install' && req.method === 'POST') {
      if (!SAFE_PKG.test(q.pkg || '') || !SAFE_NAME.test(q.name || '')) return send(res, 400, 'bad pkg or name');
      return body(req, function (buf) {
        var file = TMP + q.name;
        try { fs.writeFileSync(file, buf); } catch (e) { return send(res, 500, 'write failed: ' + e.message); }
        sdb('vd_appinstall ' + q.pkg + ' ' + file, function (err, out) {
          try { fs.unlinkSync(file); } catch (e) {}
          send(res, err ? 500 : 200, err ? err : out);
        });
      });
    }
    if (p === '/uninstall' && req.method === 'POST') {
      if (!SAFE_PKG.test(q.pkg || '')) return send(res, 400, 'bad pkg');
      return sdb('vd_appuninstall ' + q.pkg, function (err, out) { send(res, err ? 500 : 200, err ? err : out); });
    }
    if (p === '/launch' && req.method === 'POST') {
      if (!SAFE_APP.test(q.app || '')) return send(res, 400, 'bad app id');
      return launchApp(q.app, function (err) { send(res, err ? 500 : 200, err ? err : 'launched ' + q.app); });
    }
    if (p === '/tizenbrew-config') {
      if (req.method === 'GET') { try { return send(res, 200, fs.readFileSync(TB_CONFIG, 'utf8'), 'application/json'); } catch (e) { return send(res, 404, 'no config: ' + e.message); } }
      if (req.method === 'PUT') return body(req, function (buf) {
        try { JSON.parse(buf.toString()); fs.writeFileSync(TB_CONFIG, buf); send(res, 200, 'written'); } catch (e) { send(res, 400, 'bad json or write failed: ' + e.message); }
      });
    }
    if (p === '/module') {
      if (req.method === 'GET') return json(res, 200, readState());
      if (req.method === 'PUT') return body(req, function (buf) {
        try { var m = JSON.parse(buf.toString()); fs.writeFileSync(STATE, JSON.stringify({ moduleName: m.moduleName, moduleType: m.moduleType || 'gh' })); send(res, 200, 'written'); }
        catch (e) { send(res, 400, 'bad json or write failed: ' + e.message); }
      });
    }
    send(res, 404, 'no such route');
  });
  server.on('error', function (e) { console.log('mist-tv-agent server error: ' + e.message); });
  server.listen(PORT, '0.0.0.0', function () { console.log('mist-tv-agent listening on ' + PORT); });
};
module.exports.onRequest = function () {};
module.exports.onExit = function () {};
