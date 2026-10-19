/* 前端逻辑回归：不启动浏览器，直接加载真实的 static/js/app.js，
   用桩替换 Vue / fetch / localStorage / MapView，断言“点一下会发生什么”。

   覆盖：草稿三态与地图同步、重复点击不重复请求、导出含草稿、照片删除失败可重试。
   运行：node tests/front-check.js
*/
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const APP_JS = path.join(__dirname, '..', 'static', 'js', 'app.js');
const src = fs.readFileSync(APP_JS, 'utf8');

const ALL = [
  { id: 'a', name: '正式店', draft: false, tags: ['火锅'], rating: 4 },
  { id: 'b', name: '草稿店', draft: true, tags: [], rating: 3 },
];

let lastUrl = '';
let rendered = null;
const exported = { href: '' };

const fakeEl = () => ({
  textContent: '',
  classList: { add() {}, remove() {} },
  appendChild() {},
  remove() {},
});

const ctx = {
  console,
  setTimeout,
  clearTimeout,
  Vue: { createApp: () => ({ mount: () => ({}) }) },
  document: {
    querySelector: () => fakeEl(),
    querySelectorAll: () => [],
    documentElement: { getAttribute: () => null, setAttribute: () => {} },
    addEventListener: () => {},
    createElement: () => fakeEl(),
  },
  window: { location: exported, __APP__: null },
  localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  FormData: class { append() {} },
  URL: { createObjectURL: () => '' },
  fetch: async (url) => {
    lastUrl = url;
    let rows = ALL;
    if (/draftsOnly=1/.test(url)) rows = ALL.filter((r) => r.draft);
    else if (!/includeDrafts=1/.test(url)) rows = ALL.filter((r) => !r.draft);
    return { ok: true, json: async () => rows };
  },
};

vm.createContext(ctx);
vm.runInContext(
  src + ';globalThis.__App=App;globalThis.__MapView=MapView;globalThis.__API=API;',
  ctx
);

const MapView = ctx.__MapView;
MapView.map = {};
MapView.getBounds = () => ({ swLng: 100, swLat: 20, neLng: 120, neLat: 45 });
MapView.render = (recs) => { rendered = recs; };

const app = Object.assign({}, ctx.__App.data(), ctx.__App.methods);
Object.defineProperty(app, 'visibleRecords', { get() { return this._visible(this.records); } });
app.records = ALL.slice();
app.loadRecords = async () => {};
app._mapSeq = 0;

const pass = [];
const fail = [];
const check = (name, cond, extra) => (cond ? pass : fail).push(name + (extra ? ' :: ' + extra : ''));
const tick = () => new Promise((r) => setTimeout(r, 30));
const ids = (rows) => (rows || []).map((r) => r.id).join(',');

(async () => {
  // ---- 草稿三态：地图必须与列表同范围，且切换后立即重取 ----
  lastUrl = ''; rendered = null;
  app.setDrafts('only');
  await tick();
  check('仅草稿：地图请求带 draftsOnly=1', /draftsOnly=1/.test(lastUrl), lastUrl);
  check('仅草稿：地图立即重渲染', Array.isArray(rendered));
  check('仅草稿：地图只含草稿', ids(rendered) === 'b', ids(rendered));

  lastUrl = ''; rendered = null;
  app.setDrafts('hide');
  await tick();
  check('不含草稿：请求不带 includeDrafts', !/includeDrafts=1/.test(lastUrl), lastUrl);
  check('不含草稿：地图只有正式记录', ids(rendered) === 'a', ids(rendered));

  lastUrl = ''; rendered = null;
  app.setDrafts('all');
  await tick();
  check('含草稿：请求带 includeDrafts=1', /includeDrafts=1/.test(lastUrl) && !/draftsOnly=1/.test(lastUrl), lastUrl);
  check('含草稿：地图两条都在', (rendered || []).length === 2, (rendered || []).length);

  const before = lastUrl;
  app.setDrafts('all');
  await tick();
  check('重复点同一项不发请求', lastUrl === before);

  // ---- 导出始终含草稿，其余筛选保留 ----
  app.filters.keyword = '火 锅';
  app.filters.tags = ['火锅'];
  app.doExport();
  check('导出带 includeDrafts=1', /includeDrafts=1/.test(exported.href), exported.href);
  check(
    '导出保留关键词与标签筛选',
    /keyword=%E7%81%AB%20%E9%94%85/.test(exported.href) && /tags=%E7%81%AB%E9%94%85/.test(exported.href),
    exported.href
  );

  // ---- 照片删除失败不能被当作成功 ----
  ctx.__API.sendForm = async () => ({ id: 'r1', name: 'x' });
  ctx.__API.upload = async () => ({ ok: true });
  ctx.__API.del = async (url) => {
    if (url.includes('bad')) throw new Error('500');
    return { ok: true };
  };
  app.form = { id: 'r1', name: 'x', rating: 3, price: '', checkin: '', note: '', draft: false, lat: 39.9, lng: 116.4, address: '' };
  app.formTags = [];
  app.formNewPhotos = [];
  app.formRemoved = ['bad', 'good'];
  app.hours = {};
  app.saving = false;
  app.formOpen = true;
  app.formMsg = '';
  await app.saveForm();
  check('删除失败项被保留', app.formRemoved.length === 1 && app.formRemoved[0] === 'bad', JSON.stringify(app.formRemoved));
  check('删除失败时表单不关闭', app.formOpen === true);
  check('删除失败有明确提示', /删除失败/.test(app.formMsg), app.formMsg);

  ctx.__API.del = async () => ({ ok: true });
  app.formRemoved = ['p1'];
  app.formNewPhotos = [];
  app.formMsg = '';
  app.form.id = 'r1';
  app.formOpen = true;
  await app.saveForm();
  check('全部成功时清空待删除', app.formRemoved.length === 0);
  check('全部成功时表单关闭', app.formOpen === false);

  console.log('通过 ' + pass.length + ' 项');
  pass.forEach((n) => console.log('  ok  ' + n));
  if (fail.length) {
    console.log('失败 ' + fail.length + ' 项');
    fail.forEach((n) => console.log('  FAIL ' + n));
    process.exit(1);
  }
})();
