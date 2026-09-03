/* eslint-disable no-console */
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

class Element {
  constructor(tagName) {
    this.tagName = tagName;
    this.nodeType = 1;
    this.style = {};
    this.children = [];
    this.attributes = {};
    this.parentNode = null;
    this.innerHTML = '';
    this.textContent = '';
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }

  appendChild(child) {
    child.parentNode = this;
    this.children.push(child);
    if (child.tagName === 'iframe') {
      process.nextTick(function () {
        if (typeof child.onload === 'function') child.onload();
      });
    }
    return child;
  }

  removeChild(child) {
    this.children = this.children.filter(function (item) { return item !== child; });
    child.parentNode = null;
  }
}

function response(payload, status) {
  return {
    ok: status === undefined || status < 300,
    status: status || 200,
    json: function () { return Promise.resolve(payload); }
  };
}

function loadSdk(fetchImpl) {
  const document = {
    currentScript: {src: 'https://peis.example.com/dbquery/static/js/dbquery-embed.js'},
    getElementsByTagName: function () { return [this.currentScript]; },
    createElement: function (tagName) { return new Element(tagName); },
    querySelector: function () { return null; }
  };
  const sandbox = {
    window: {},
    document: document,
    fetch: fetchImpl,
    Promise: Promise,
    setTimeout: setTimeout
  };
  vm.runInNewContext(
    fs.readFileSync('static/js/dbquery-embed.js', 'utf8'),
    sandbox,
    {filename: 'dbquery-embed.js'}
  );
  return sandbox.window.DBQueryEmbed;
}

async function testLoginThenHome() {
  const calls = [];
  const sdk = loadSdk(function (url, options) {
    calls.push({url: url, options: options});
    if (calls.length === 1) return Promise.resolve(response({
      authenticated: true,
      embed_path: '/embed-session/embed-token/?embed=1&hide_header=1&sidebar=0',
      embed_session: 'embed-token'
    }));
    throw new Error('Unexpected request');
  });
  const container = new Element('div');
  const result = await sdk.mount({
    el: container,
    username: 'tester',
    password: 'secret',
    apiBase: '/dbquery'
  });
  assert.strictEqual(calls.length, 1);
  assert.strictEqual(calls[0].url, '/dbquery/api/integration/frontend-login');
  assert.strictEqual(calls[0].options.method, 'POST');
  assert.strictEqual(calls[0].options.credentials, 'include');
  assert.strictEqual(
    result.iframe.src,
    '/dbquery/embed-session/embed-token/?embed=1&hide_header=1&sidebar=0'
  );
  assert.strictEqual(result.iframe.style.width, '100%');
  assert.strictEqual(result.iframe.style.height, '100%');
  assert.strictEqual(result.iframe.style.border, '0');
  assert.strictEqual(result.iframe.style.display, 'block');
  assert.strictEqual(result.iframe.title, 'DBQuery');
  assert.strictEqual(result.iframe.src.includes('tester'), false);
  assert.strictEqual(result.iframe.src.includes('secret'), false);
  assert.strictEqual(result.iframe.src.includes('form'), false);
  assert.strictEqual(result.iframe.src.includes('params'), false);
}

async function testExistingSessionAndTrailingSlash() {
  const calls = [];
  const sdk = loadSdk(function (url, options) {
    calls.push({url: url, options: options});
    return Promise.resolve(response({authenticated: true}));
  });
  const container = new Element('div');
  const result = await sdk.mount({
    el: container,
    apiBase: '/dbquery/'
  });
  assert.strictEqual(calls.length, 1);
  assert.strictEqual(calls[0].url, '/dbquery/api/integration/session');
  assert.strictEqual(result.iframe.src, '/dbquery/');
}

async function testDefaultBaseAndLogout() {
  const calls = [];
  const sdk = loadSdk(function (url, options) {
    calls.push({url: url, options: options});
    if (url === '/api/integration/frontend-login') return Promise.resolve(response({
      authenticated: true,
      embed_path: '/embed-session/token-2/',
      embed_session: 'token-2'
    }));
    if (url === '/api/integration/logout') return Promise.resolve(response({success: true}));
    throw new Error('Unexpected request: ' + url);
  });
  const container = new Element('div');
  const result = await sdk.mount({el: container, username: 'tester', password: 'secret', apiBase: '/'});
  assert.strictEqual(result.iframe.src, '/embed-session/token-2/');
  await sdk.logout();
  assert.strictEqual(calls[1].url, '/api/integration/logout');
  assert.strictEqual(calls[1].options.method, 'POST');
  assert.deepStrictEqual(JSON.parse(calls[1].options.body), {embed_session: 'token-2'});
}

async function testMissingCredentialsUsesSessionProbe() {
  const calls = [];
  const sdk = loadSdk(function (url, options) {
    calls.push({url: url, options: options});
    return Promise.resolve(response({authenticated: true}));
  });
  const container = new Element('div');
  const result = await sdk.mount({el: container, apiBase: '/dbquery'});
  assert.strictEqual(calls.length, 1);
  assert.strictEqual(calls[0].url, '/dbquery/api/integration/session');
  assert.strictEqual(calls[0].options.method, 'GET');
  assert.strictEqual(result.iframe.src, '/dbquery/');
}

Promise.resolve()
  .then(testLoginThenHome)
  .then(testExistingSessionAndTrailingSlash)
  .then(testDefaultBaseAndLogout)
  .then(testMissingCredentialsUsesSessionProbe)
  .then(function () { console.log('DBQueryEmbed SDK tests passed'); })
  .catch(function (error) {
    console.error(error && error.stack ? error.stack : error);
    process.exit(1);
  });
