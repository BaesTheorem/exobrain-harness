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

  function sdb(cmd, cb) {
    var chunks = [], done = false, client;
    function finish(err) {
      if (done) return;
      done = true; clearTimeout(timer);
      try { client._stream.end(); } catch (e) {}
      cb(err, Buffer.concat(chunks).toString());
    }
    var timer = setTimeout(function () { finish('timeout after 180 s'); }, 180000);
    try { client = adbhost.createConnection({ host: '127.0.0.1', port: 26101 }); }
    catch (e) { return finish('bridge connect failed: ' + e.message); }
    client._stream.on('error', function (e) { finish('bridge error: ' + e.message); });
    client._stream.on('close', function () { setTimeout(function () { finish(null); }, 200); });
    var s = client.createStream('shell:0 ' + cmd);
    s.on('data', function (d) { chunks.push(d); });
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

  var server = http.createServer(function (req, res) {
    var u = url.parse(req.url, true), q = u.query || {}, p = u.pathname;
    if (p === '/ping') return json(res, 200, { ok: true, agent: 'mist-tv-agent', node: process.version, time: new Date().toISOString() });
    if (p === '/module' && req.method === 'GET' && isLoopback(req)) { var st = readState(); return json(res, 200, { moduleName: st.moduleName || '', moduleType: st.moduleType || 'gh' }); }
    if (q.token !== cfg.token) return send(res, 403, 'forbidden');

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
      try {
        tizen.application.launch(q.app, function () { send(res, 200, 'launched ' + q.app); }, function (e) { send(res, 500, 'launch failed: ' + e.message); });
      } catch (e) { send(res, 500, 'launch failed: ' + e.message); }
      return;
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
