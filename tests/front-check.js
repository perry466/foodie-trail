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
    getElementById: () => null,          // 开屏层在真实页面里才有，这里返回 null 走「没有就跳过」
    documentElement: { getAttribute: () => null, setAttribute: () => {} },
    addEventListener: () => {},
    createElement: () => fakeEl(),
  },
  window: { location: exported, __APP__: null },
  localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  FormData: class { append() {} },
  URL: { createObjectURL: () => '' },
  URLSearchParams,
  history: { replaceState() {} },
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
  src + ';globalThis.__App=App;globalThis.__MapView=MapView;globalThis.__API=API;globalThis.__recPath=recPath;globalThis.__serializeHours=serializeHours;globalThis.__verCmp=verCmp;',
  ctx
);

const MapView = ctx.__MapView;
MapView.map = {};
MapView.getBounds = () => ({ swLng: 100, swLat: 20, neLng: 120, neLat: 45 });
MapView.render = (recs) => { rendered = recs; };

const app = Object.assign({}, ctx.__App.data(), ctx.__App.methods);
if (ctx.__App.created) ctx.__App.created.call(app);   // 真实的 Object URL 缓存初始化
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

  // ---- 人均价位：预览与后端同为 [下限, 上限) ----
  app.filters.keyword = '';
  const priceFilter = (min, max) => ({
    priceMin: min, priceMax: max, tags: [], tagsMode: 'all', ratingMin: 0, checkin: '', drafts: 'all',
  });
  const f3060 = priceFilter(30, 60);
  check('30–60 含 30（下限闭）', app._matchFilters({ avgPrice: 30 }, f3060));
  check('30–60 含 59', app._matchFilters({ avgPrice: 59 }, f3060));
  check('30–60 不含 60（上限开）', !app._matchFilters({ avgPrice: 60 }, f3060));
  check('30–60 不含 29', !app._matchFilters({ avgPrice: 29 }, f3060));
  const f200 = priceFilter(200, null);
  check('≥200 含 200', app._matchFilters({ avgPrice: 200 }, f200));
  check('无人价不参与', !app._matchFilters({ avgPrice: null }, f3060));

  // ---- 照片 Object URL：同一 File 只建一次，关闭表单时释放 ----
  let created = 0;
  const revoked = [];
  ctx.URL.createObjectURL = () => 'blob:' + ++created;
  ctx.URL.revokeObjectURL = (u) => revoked.push(u);
  app._photoURLs = new Map();
  const file1 = {};
  const url1 = app.photoURL(file1);
  const url2 = app.photoURL(file1);
  check('photoURL 同一个 File 复用', url1 === url2 && created === 1, `created=${created}`);
  app.releasePhotoURL(file1);
  check('移除待上传照片后 revoke', revoked.includes(url1), JSON.stringify(revoked));
  const file2 = {};
  app.formNewPhotos = [file2];
  app.photoURL(file2);
  app.closeForm();
  check('关闭表单释放剩余 Object URL', revoked.includes('blob:' + created) && app._photoURLs.size === 0,
    JSON.stringify(revoked));

  // ---- 经纬度为 0 是合法位置，不能被当成"没选点" ----
  ctx.__API.sendForm = async () => ({ id: 'r0', name: '赤道店', lat: 0, lng: 0, photos: [] });
  app.form = { id: null, name: '赤道店', rating: 3, price: '', checkin: '', note: '', draft: false, lat: 0, lng: 0, address: '' };
  app.formErr = { name: '', loc: '' };
  app.formPhotos = [];
  app.formNewPhotos = [];
  app.formRemoved = [];
  app.hours = {};
  app.saving = false;
  app.formMsg = '';
  app.formOpen = true;
  await app.saveForm();
  check('经纬度 0 允许保存', app.formErr.loc === '', app.formErr.loc);

  // ---- 看板下钻：清掉遗留条件 + 星级是精确区间 ----
  app.dash = { price: { buckets: [{ label: '<30', min: 0, max: 30, count: 1 }] } };
  app.filters.keyword = '火锅';
  app.filters.drafts = 'only';
  app.filters.viewOnly = true;
  app.filters.tags = ['老店'];
  app.loadRecords = async () => {};
  app.dashDrill('star', 4);
  check('下钻清空关键词', app.filters.keyword === '', app.filters.keyword);
  check('下钻改为不含草稿（与看板数字同口径）', app.filters.drafts === 'hide', app.filters.drafts);
  check('下钻关闭仅看视野', app.filters.viewOnly === false);
  check('下钻清空标签', app.filters.tags.length === 0);
  check('星级下钻是精确区间', app.filters.ratingMin === 4 && app.filters.ratingMax === 4,
    `${app.filters.ratingMin}-${app.filters.ratingMax}`);
  const chips = ctx.__App.computed.activeChips.call(app);   // computed 不在 methods 里
  const ratingChip = chips.find((c) => c.k === 'rating');
  check('星级 chip 文案为精确值', ratingChip && ratingChip.t === '4 星', ratingChip && ratingChip.t);
  check('星级下钻带 ratingMax 查询参数', /ratingMax=4/.test(app._filterQuery(true, false)),
    app._filterQuery(true, false));
  const f44 = Object.assign({}, app.filters);
  check('精确星级只匹配该星级', app._matchFilters({ rating: 4, tags: [], avgPrice: null }, f44)
    && !app._matchFilters({ rating: 5, tags: [], avgPrice: null }, f44));

  // ---- 记录 id 必须编码后再拼 URL ----
  app.filters.ratingMin = 0; app.filters.ratingMax = null;
  check('recPath 编码斜杠', ctx.__recPath('a/b') === '/api/records/a%2Fb', ctx.__recPath('a/b'));

  // ---- 0 元是有效价格，不能当成「没填」 ----
  let lastBody = null;
  ctx.__API.sendForm = async (url, method, body) => {
    lastBody = body;
    return { id: 'r0', name: 'x', photos: [], avgPrice: body.avgPrice };
  };
  app.form = { id: null, name: '免费店', rating: 3, price: 0, checkin: '', note: '', draft: false, lat: 39.9, lng: 116.4, address: '' };
  app.formErr = { name: '', loc: '' };
  app.formPhotos = []; app.formNewPhotos = []; app.formRemoved = [];
  app.hours = {}; app.saving = false; app.formMsg = ''; app.formOpen = true;
  await app.saveForm();
  check('0 元不会被当成空值', lastBody && lastBody.avgPrice === 0, String(lastBody && lastBody.avgPrice));

  // ---- 七天排班序列化后的长度（后端必须能接受，不能按 120 字卡） ----
  const weekTwo = {};
  ['mon','tue','wed','thu','fri','sat','sun'].forEach((k) => {
    weekTwo[k] = [{ s: '11:00', e: '14:00' }, { s: '17:00', e: '21:00' }];
  });
  const hoursJson = ctx.__serializeHours(weekTwo);
  check('七天两段排班 JSON 超过 120 字', hoursJson.length > 400, String(hoursJson.length));

  // ---- 导入结果：写入 0 条但全是「已是最新」时，必须说清楚而不是像失败 ----
  let importFetch = null;
  ctx.fetch = async (url) => {
    lastUrl = url;
    if (importFetch) return importFetch;
    return { ok: true, json: async () => ALL };
  };
  importFetch = {
    ok: true,
    headers: { get: () => 'application/json' },
    json: async () => ({ written: 0, unchanged: 3, invalid: 0, failed: 0, photosSkipped: 0, photosKept: 0, idsRenamed: 0 }),
  };
  app.importFile = {};
  app.importBusy = false;
  app.importText = '';
  app.loadRecords = async () => {};
  await app.doImport();
  check('导入 0 写入时提示"已是最新"', /3 条已是最新/.test(app.importText), app.importText);

  // ---- 关闭/进入批量时的 URL 同步（Esc 后刷新不能又跳回清单） ----
  let synced = 0;
  const realSync = app._syncURL;
  app._syncURL = function () { synced++; return realSync.call(this); };
  app.panel = 'none';
  app.enterSelect();
  check('进入批量选择会同步 URL', synced === 1 && app.panel === 'list', `synced=${synced}`);
  app._syncURL = realSync;

  // ---- 2.0：版本比较、安装步骤状态机、「刚更新完」的判断 ----
  check('版本按数字元组比较（2.0.0 > 1.0.9）', ctx.__verCmp('2.0.0', '1.0.9') === 1, ctx.__verCmp('2.0.0', '1.0.9'));
  check('补丁位两位数不比字符串（1.0.10 > 1.0.9）', ctx.__verCmp('1.0.10', '1.0.9') === 1);
  check('同版本比较为 0', ctx.__verCmp('2.0.0', '2.0.0') === 0);

  const steps = (phase, target) => {
    app.installPhase = phase;
    app.installTarget = target || '';
    return ctx.__App.computed.installSteps.call(app);
  };
  const st1 = steps('installing', '2.0.0');
  check('安装中：已关闭 + 安装进行中 + 待重启',
    st1[0].state === 'done' && st1[1].state === 'run' && st1[2].state === 'wait',
    st1.map((s) => s.state).join(','));
  check('安装中步骤带目标版本号', /2\.0\.0/.test(st1[1].label), st1[1].label);
  check('安装完成：三步全完成', steps('done', '2.0.0').every((s) => s.state === 'done'));
  check('安装超时：安装步骤标失败', steps('timeout', '2.0.0')[1].state === 'fail');

  // localStorage 桩换成可写字典：标记只能在新版本真正起来后才被消费
  const store = {};
  ctx.localStorage = {
    getItem: (k) => (k in store ? store[k] : null),
    setItem: (k, v) => { store[k] = v; },
    removeItem: (k) => { delete store[k]; },
  };
  ctx.localStorage.setItem('fm-updating', '2.0.0');
  app.appVersion = '1.0.9';
  check('旧版本启动不消费更新标记', app._updatedNote() === '' && store['fm-updating'] === '2.0.0');
  app.appVersion = '2.0.0';
  check('新版本启动显示已更新到 v2.0.0', app._updatedNote() === '已更新到 v2.0.0', app._updatedNote());
  check('更新标记消费后清空', !('fm-updating' in store));

  // ---- 不能自动安装时，提示必须指向「屏幕上真的存在的按钮」 ----
  // 额度耗尽的降级结果没有资产地址，「复制下载链接」按钮不渲染，
  // 再让用户去点它就是死路（2026-10-23 用户截图实踩）。
  app.appMode = 'installer';
  const hint = () => ctx.__App.computed.updateModeHint.call(app);
  app.updateInfo = { canAutoInstall: false, downloadUrl: '' };
  check('降级时提示去 Release 页面，不指向不存在的复制按钮',
    /Release 页面/.test(hint()) && !/复制下载链接/.test(hint()), hint());
  app.updateInfo = { canAutoInstall: false, downloadUrl: 'https://example.invalid/s.exe' };
  check('有下载地址时才提示复制链接', /复制下载链接/.test(hint()), hint());
  app.updateInfo = { canAutoInstall: true, downloadUrl: 'https://example.invalid/s.exe' };
  check('可自动安装时不显示兜底提示', hint() === '');

  console.log('通过 ' + pass.length + ' 项');
  pass.forEach((n) => console.log('  ok  ' + n));
  if (fail.length) {
    console.log('失败 ' + fail.length + ' 项');
    fail.forEach((n) => console.log('  FAIL ' + n));
    process.exit(1);
  }
})();
