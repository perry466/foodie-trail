/* ============================================================
   美食地图 · Vue 3（无构建）前端
   地图实例由 MapView 管理，挂载在 Vue 管控之外的 #map 上；
   UI 层（工具栏 / 抽屉 / 模态）由 Vue 接管。
   ============================================================ */
const { createApp } = Vue;

/* ---------------- 基础工具 ---------------- */
const API = {
  async get(url){ const r = await fetch(url); if(!r.ok) throw await err(r); return r.json(); },
  async sendForm(url, method, body){ const r = await fetch(url,{method, headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)}); if(!r.ok) throw await err(r); return r.json(); },
  async upload(url, file){ const fd=new FormData(); fd.append('file',file); const r=await fetch(url,{method:'POST',body:fd}); if(!r.ok) throw await err(r); return r.json(); },
  async del(url, body){ const opt={method:'DELETE'}; if(body!==undefined){ opt.headers={'Content-Type':'application/json'}; opt.body=JSON.stringify(body); } const r=await fetch(url,opt); if(!r.ok) throw await err(r); return r.json(); },
};
/* 把 FastAPI 的错误体转成一句人话。
   Pydantic 422 的 detail 是数组：[{loc:['body','avgPrice'], msg:'Value error, 人均须为 …'}]，
   直接塞进 Error 会变成 "[object Object]"，用户根本看不懂。 */
function fmtDetail(d){
  if(d==null) return '';
  if(typeof d==='string') return d;
  if(Array.isArray(d)){
    return d.map(x=>String((x&&x.msg)||'输入不合法').replace(/^Value error,\s*/,'')).join('；');
  }
  if(typeof d==='object') return String(d.msg||JSON.stringify(d));
  return String(d);
}
async function err(r){
  const base=r.statusText||('HTTP '+r.status);
  try{
    const j=await r.json();
    const e=new Error(fmtDetail(j.detail!==undefined?j.detail:j.msg)||base);
    e.status=r.status; return e;
  }catch{ const e=new Error(base); e.status=r.status; return e; }
}

/* ---------------- 版本号比较 ----------------
   和 backend 一样必须按数字元组比：字符串比较下 "1.0.10" < "1.0.9"，
   会让「刚更新完」的判断永远不成立。 */
function verNum(v){
  const m=String(v||'').match(/(\d+)(?:\.(\d+))?(?:\.(\d+))?/);
  return m ? [+m[1], +(m[2]||0), +(m[3]||0)] : [0,0,0];
}
function verCmp(a,b){
  const x=verNum(a), y=verNum(b);
  for(let i=0;i<3;i++){ if(x[i]!==y[i]) return x[i]>y[i]?1:-1; }
  return 0;
}

/* ---------------- 开屏动画 ----------------
   纯 DOM 操作、不依赖 Vue：首屏数据（地图 + 记录）到位后才淡出，最少停留
   900ms（否则一闪而过像故障），最多 2.8s 强制让开（否则接口卡住就是一片白）。 */
const SPLASH_MIN_MS=1600, SPLASH_MAX_MS=3800, _splashAt=Date.now();
let _splashDone=false;
/* 先把「已更新到 vX」写上去、再等数据：这两件事必须分开。
   合在一起写的话，首屏慢（地图/接口 2–4 秒）时文案是在淡出前一瞬间才换上去的，
   用户根本看不到——那正是最需要它的时候。 */
function splashNote(note){
  const el=document.getElementById('splash');
  if(!el || !note) return;
  el.classList.add('updated');
  el.dataset.noted='1';
  const sub=document.getElementById('splashSub');
  if(sub) sub.textContent=note;
}
function splashReady(note){
  if(_splashDone) return;
  _splashDone=true;
  const el=document.getElementById('splash');
  if(!el) return;
  if(note) splashNote(note);
  // 更新提示要留够阅读时间；普通启动最少停留 1.6s——开屏是节奏的一部分，不是故障页
  const floor = el.dataset.noted==='1' ? 1800 : SPLASH_MIN_MS;
  const wait=Math.max(0, floor-(Date.now()-_splashAt));
  setTimeout(()=>{
    el.classList.add('out');
    setTimeout(()=>{ if(el.parentNode) el.remove(); }, 800);
  }, wait);
}
setTimeout(()=>splashReady(), SPLASH_MAX_MS);
/* 带上传进度 + 响应流读取的 POST：导入大文件时用（fetch 拿不到上传进度） */
/* 上传文件并读取响应；响应是 NDJSON 时逐行触发 onEvent（导入写入进度）。
   不用 XHR：实测 Chrome 对这种小分块流式响应，onprogress 会停发且 load 不触发；
   fetch 的 ReadableStream 每一块都能读到。fetch 拿不到上传进度，
   上传阶段由调用方用"不确定进度条"表示。 */
async function streamUpload(url, file, { onEvent } = {}){
  const fd = new FormData();
  fd.append('file', file);
  const r = await fetch(url, { method:'POST', body:fd });
  if(!r.ok){
    let msg = r.statusText || ('HTTP ' + r.status);
    try{ const j = await r.json(); msg = fmtDetail(j.detail!==undefined?j.detail:j.msg) || msg; }catch{}
    throw new Error(msg);
  }
  const ct = r.headers.get('content-type') || '';
  if(ct.indexOf('ndjson') < 0){
    const j = await r.json();
    if(onEvent) onEvent(j);
    return j;
  }
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = '', last = null;
  while(true){
    const { value, done } = await reader.read();
    if(done) break;
    buf += dec.decode(value, { stream:true });
    let nl;
    while((nl = buf.indexOf('\n')) >= 0){
      const line = buf.slice(0, nl).trim();
      buf = buf.slice(nl + 1);
      if(!line) continue;
      try{ last = JSON.parse(line); if(onEvent) onEvent(last); }catch{}
    }
  }
  const rest = buf.trim();
  if(rest){ try{ last = JSON.parse(rest); if(onEvent) onEvent(last); }catch{} }
  return last;
}

const $ = s => document.querySelector(s);
const $$ = s => Array.from(document.querySelectorAll(s));
/* 记录/照片 id 拼进 URL 前必须编码：id 里出现 / ? # & 会让路径错位，详情直接 404 */
const recPath = id => '/api/records/' + encodeURIComponent(id);
const photoPath = id => '/api/photos/' + encodeURIComponent(id);
/* 外部链接：Android WebView 不支持 window.open 新窗口，交给原生桥用系统浏览器打开；
   桌面/普通浏览器仍走 window.open。 */
function openExternalUrl(url){
  const s=String(url||'');
  if(!/^https?:\/\//i.test(s)) return;
  try{
    if(window.Android && typeof window.Android.openExternal==='function'){
      window.Android.openExternal(s);
      return;
    }
  }catch(e){ /* 没桥接就走下面的兜底 */ }
  window.open(s,'_blank','noopener');
}
function toast(msg, action){
  const t=$('#toast');
  if(!t) return;
  // 带动作的 toast 需要真实 DOM；测试桩里没有 querySelector，退化成纯文本
  if(action && typeof t.querySelector==='function'){
    t.innerHTML=`<span>${esc(msg)}</span><button type="button" class="toast-act">${esc(action.label)}</button>`;
    const b=t.querySelector('.toast-act');
    if(b) b.onclick=()=>{ try{ action.fn(); }finally{ t.classList.add('hidden'); } };
  }else{
    t.textContent=msg;
  }
  t.classList.remove('hidden');
  clearTimeout(t._t);
  t._t=setTimeout(()=>t.classList.add('hidden'), action?4500:2200);
}
function esc(s){ return (s||'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
function ratingColor(r){ return r<=2?'#9aa0a6':r===3?'#2f80ed':'#f0502f'; }
function pinHTML(r){ return `<div style="background:${ratingColor(r)};box-sizing:border-box;width:34px;height:34px;border:2.5px solid #fff;border-radius:50% 50% 50% 0;transform:rotate(-45deg);display:flex;align-items:center;justify-content:center;box-shadow:0 3px 8px rgba(0,0,0,.35)"><span style="transform:rotate(45deg);display:flex;align-items:center;justify-content:center"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 2v7c0 1.1.9 2 2 2h4a2 2 0 0 0 2-2V2"/><path d="M7 2v20"/><path d="M21 15V2a5 5 0 0 0-5 5v6c0 1.1.9 2 2 2h3Zm0 0v7"/></svg></span></div>`; }
function clusterHTML(n){ const size = n>=100?46:(n>=10?40:34); return `<div class="fm-cluster" style="width:${size}px;height:${size}px">${n}</div>`; }
const MAP_LIMIT = 600; // 地图单次加载图钉上限（按视野取，缩到全中国也不超量）
const DRAFT_KEY = 'fm-form-draft-v1';   // 添加表单的本地草稿（未提交内容）
/* 人均档位：与看板 /api/dashboard 的价位分桶保持一致，下钻时能正确回填 */
const PRICE_BUCKETS = [
  { label:'<30',      min:0,   max:30 },
  { label:'30–60',    min:30,  max:60 },
  { label:'60–100',   min:60,  max:100 },
  { label:'100–200',  min:100, max:200 },
  { label:'≥200',     min:200, max:null },
];

/* ---------------- 地图适配 ---------------- */
const MapView = {
  impl:null, map:null, cluster:null, _plain:null, _records:[], _drawing:false, _dt:null,
  /* 销毁当前地图实例：切换地图实现（Leaflet ↔ 高德）或重设 Key 时必须先清场，
     否则旧实例的 DOM、事件监听、InfoWindow 会残留，出现叠加或点击错乱 */
  destroy(){
    try{ if(this.map && this.impl==='amap' && typeof this.map.destroy==='function') this.map.destroy(); }catch(e){}
    try{ if(this.map && this.impl==='leaflet' && typeof this.map.remove==='function') this.map.remove(); }catch(e){}
    try{ if(this._iw && this._iw.close) this._iw.close(); }catch(e){}
    try{ if(this._cw && this._cw.close) this._cw.close(); }catch(e){}
    this.impl=null; this.map=null; this.cluster=null; this._plain=null; this._records=[];
    this._iw=null; this._cw=null; this._hoverPopup=null; this._drawing=false; this._dt=null;
    const el=document.getElementById('map');
    if(el) el.innerHTML='';       // Leaflet 会往容器塞 DOM，直接清空最保险
  },
  async init(){
    this.destroy();
    const cfg = await API.get('/api/config/amap');
    this.cfg = cfg;
    if(cfg.configured && cfg.key){
      try{
        await this.initAMap(cfg);
      }catch(e){
        // 配了 Key 也可能失败：脚本被墙、CDN 抖动、Key 失效。
        // 必须退回本地 Leaflet，否则地图整块空白，用户只能看到一个空容器。
        console.warn('[map] 高德加载失败，回退本地底图：', e && e.message);
        try{ this.destroy(); }catch(_){}
        await this.initLeaflet();
        this._amapFailed = true;
        try{ toast('高德地图加载失败，已切到本地底图'); }catch(_){}
      }
    } else {
      await this.initLeaflet();
    }
    this.render(window.__APP__ ? window.__APP__.records.slice() : []);
  },
  async initAMap(cfg){
    if($('#mapBanner')) $('#mapBanner').remove();
    await loadScript(`https://webapi.amap.com/maps?v=2.0&key=${cfg.key}`, cfg.security);
    this.impl='amap';
    // 注意：高德使用 [经度, 纬度] 顺序，中心取中国疆域中心
    this.map = new AMap.Map('map',{zoom:4,center:[104.2,35.5],viewMode:'2D'});
    this._iw = new AMap.InfoWindow({offset:new AMap.Pixel(0,-30)});
    this._cw = new AMap.InfoWindow({offset:new AMap.Pixel(0,-12)});  // 聚合气泡的清单弹窗（与 hover 提示分开，避免移开即关）
    this.map.on('click', e=>{
      const app=window.__APP__;
      if(app && app.pickMode && app.pickCb){ app.pickCb(e.lnglat.getLng(), e.lnglat.getLat()); return; }
      // 空白点击统一由 document 层处理（带拖动判定），这里不重复关闭
    });
    // 缩放后网格聚合需要重算（平移不影响地理坐标，无需重算）
    this.map.on('zoomend', ()=>this._scheduleDraw());
    this.map.on('moveend', ()=>{ const a=window.__APP__; if(a && a.onMapMoveEnd) a.onMapMoveEnd(); });
    // 右键（高德桌面端的长按等价操作）：带上坐标直接新增
    this.map.on('rightclick', e=>{
      const app=window.__APP__;
      const lng=e.lnglat.getLng(), lat=e.lnglat.getLat();
      if(app && app.pickMode && app.pickCb){ app.pickCb(lng,lat); return; }
      if(app && app.onMapLongPress) app.onMapLongPress(lng,lat);
    });
  },
  async initLeaflet(){
    await loadCSS('/lib/leaflet/leaflet.css');
    await loadScript('/lib/leaflet/leaflet.js');
    await loadScript('/lib/leaflet.markercluster/leaflet.markercluster.js');
    await loadCSS('/lib/leaflet.markercluster/MarkerCluster.css');
    await loadCSS('/lib/leaflet.markercluster/MarkerCluster.Default.css');
    this.impl='leaflet';
    this.map = L.map('map',{attributionControl:true}).setView([35,104],4);
    L.tileLayer('https://wprd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=7&x={x}&y={y}&z={z}',{maxZoom:18,subdomains:'1234',attribution:'© 高德地图（兜底图层）'}).addTo(this.map);
    this.map.on('click', e=>{
      const app=window.__APP__;
      if(app && app.pickMode && app.pickCb){ app.pickCb(e.latlng.lng, e.latlng.lat); return; }
      // 空白点击统一由 document 层处理（带拖动判定），这里不重复关闭
    });
    this.map.on('moveend', ()=>{ const a=window.__APP__; if(a && a.onMapMoveEnd) a.onMapMoveEnd(); });
    // 右键/长按地图：带上坐标直接新增
    this.map.on('contextmenu', e=>{
      const app=window.__APP__;
      if(app && app.pickMode && app.pickCb){ app.pickCb(e.latlng.lng, e.latlng.lat); return; }
      if(app && app.onMapLongPress) app.onMapLongPress(e.latlng.lng, e.latlng.lat);
    });
    this.showFallbackBanner();
  },
  showFallbackBanner(){
    try{ if(localStorage.getItem('fm_amap_banner_dismissed')==='1') return; }catch(_){}
    let b=$('#mapBanner'); if(!b){ b=document.createElement('div'); b.id='mapBanner'; $('#map').appendChild(b); }
    b.className='map-banner';
    b.textContent='';
    const text=document.createElement('span');
    text.textContent='未配置高德 Key：当前使用兜底地图（可正常显示、打点、查看记录）。POI 搜索 / 地址定位 / 驾车路线需配置 Key 后启用。';
    const close=document.createElement('button');
    close.type='button';
    close.className='map-banner-x';
    close.setAttribute('aria-label','关闭提示');
    close.textContent='✕';
    close.addEventListener('click', ()=>{
      try{ localStorage.setItem('fm_amap_banner_dismissed','1'); }catch(_){}
      b.remove();
    });
    b.append(text, close);
  },
  render(records){
    // 尊重"显示描点"开关：关闭时清空标记，仅保留底图
    const app = window.__APP__;
    const show = !app || app.showMarkers !== false;
    this._records = show ? (records || []) : [];
    if(this.impl==='amap') this.drawAMap();
    else if(this.impl==='leaflet') this.drawLeaflet();
  },
  // 视野变化（缩放）后重算聚合，做防抖 + 重入保护
  _scheduleDraw(){
    if(this._drawing) return;
    clearTimeout(this._dt);
    this._dt = setTimeout(()=>{
      this._drawing = true;
      try{ this.drawAMap(); }catch(e){ console.error(e); }finally{ this._drawing = false; }
    }, 60);
  },
  /* 高德：官方 AMap.MarkerCluster 插件在本项目环境下不渲染任何标记，
     改用原生 Marker 自建网格聚合（可靠、可控、样式统一）。 */
  drawAMap(){
    const map = this.map; if(!map) return;
    if(this._plain && this._plain.length){ map.remove(this._plain); this._plain = null; }
    if(this._iw) this._iw.close();
    const recs = this._records || [];
    if(!recs.length) return;
    const grid = 64;                 // 聚合网格边长（像素），越大聚合越强
    const buckets = new Map();
    recs.forEach(r=>{
      let p; try{ p = map.lngLatToContainer(new AMap.LngLat(r.lng, r.lat)); }catch(e){ p = null; }
      if(!p) return;
      const k = Math.floor(p.getX()/grid) + '_' + Math.floor(p.getY()/grid);
      let b = buckets.get(k); if(!b){ b = {x:0,y:0,n:0,items:[]}; buckets.set(k,b); }
      b.x += p.getX(); b.y += p.getY(); b.n++; b.items.push(r);
    });
    const out = [];
    buckets.forEach(b=>{
      if(b.n === 1){ out.push(this.mk(b.items[0])._amap); return; }
      let c; try{ c = map.containerToLngLat(new AMap.Pixel(b.x/b.n, b.y/b.n)); }catch(e){ return; }
      const pos = [c.getLng(), c.getLat()];
      const items = b.items;
      const m = new AMap.Marker({ position:pos, content:clusterHTML(b.n), anchor:'center', zIndex:120 });
      // 点击聚合气泡 → 弹出该区域美食清单（点清单条目打开详情卡片）
      m.on('click', ()=>this._openCluster(items, pos));
      // hover 显示轻提示
      m.on('mouseover', ()=>{ this._iw.setContent(`<div class="fm-cluster-tip">本区域 <b>${items.length}</b> 家美食<br><span>点击查看列表</span></div>`); this._iw.open(this.map, pos); });
      m.on('mouseout', ()=>this._iw.close());
      out.push(m);
    });
    this._plain = out;
    if(out.length) map.add(out);
  },
  drawLeaflet(){
    const map = this.map; if(!map) return;
    if(this.cluster){ map.removeLayer(this.cluster); this.cluster = null; }
    const recs = this._records || [];
    if(!recs.length) return;
    this.cluster = L.markerClusterGroup({chunkedLoading:true,chunkInterval:60,chunkDelay:15});
    recs.forEach(r=>this.cluster.addLayer(this.mk(r)._leaf));
    map.addLayer(this.cluster);
  },
  mk(r){
    const prev = previewHTML(r);
    if(this.impl==='amap'){
      const m=new AMap.Marker({position:[r.lng,r.lat],content:pinHTML(r.rating),anchor:'bottom-center'});
      m.on('click',()=>{ const a=window.__APP__; if(a && a.pickMode) return a.pickCb && a.pickCb(r.lng,r.lat); a && a.showDetail(r.id); });
      m.on('mouseover',()=>{ this._iw.setContent(prev); this._iw.open(this.map, m.getPosition()); });
      m.on('mouseout',()=>this._iw.close());
      return {_amap:m};
    }else{
      const icon=L.divIcon({html:pinHTML(r.rating),className:'',iconSize:[34,34],iconAnchor:[17,34]});
      const m=L.marker([r.lat,r.lng],{icon});
      m.bindTooltip(prev,{direction:'top',offset:[0,-38],className:'pin-tip-box',opacity:1});
      m.on('click',()=>{ const a=window.__APP__; if(a && a.pickMode) return a.pickCb && a.pickCb(r.lng,r.lat); a && a.showDetail(r.id); });
      return {_leaf:m};
    }
  },
  // 点击聚合气泡：弹出该区域美食清单，点条目打开详情卡片
  _openCluster(items, pos){
    const app = window.__APP__;
    // 选点态下点聚合气泡应视为"选这个位置"，而不是打开清单
    if(app && app.pickMode){ if(app.pickCb) app.pickCb(pos[0], pos[1]); return; }
    const wrap = document.createElement('div');
    wrap.className = 'fm-cluster-list';
    const head = document.createElement('div'); head.className = 'fm-cl-head';
    head.textContent = `本区域 ${items.length} 家美食${items.length>60?'（显示前 60）':''}`;
    wrap.appendChild(head);
    const body = document.createElement('div'); body.className = 'fm-cl-body';
    items.slice(0, 60).forEach(r=>{
      const row = document.createElement('div'); row.className = 'fm-cl-item';
      const name = document.createElement('span'); name.className = 'fm-cl-name'; name.textContent = r.name || '未命名';
      const st = ({want:'想去',visited:'去过',favorite:'收藏'})[r.checkinStatus] || '';
      const meta = document.createElement('span'); meta.className = 'fm-cl-meta';
      meta.innerHTML = `<span class="fm-cl-star">${'★'.repeat(r.rating)}${'☆'.repeat(5-r.rating)}</span>${st?`<span class="fm-cl-status">${st}</span>`:''}`;
      row.appendChild(name); row.appendChild(meta);
      row.addEventListener('click', ()=>{ this._cw.close(); if(app && app.showDetail) app.showDetail(r.id); });
      body.appendChild(row);
    });
    wrap.appendChild(body);
    const foot = document.createElement('div'); foot.className = 'fm-cl-foot'; foot.textContent = '点击条目查看详情';
    wrap.appendChild(foot);
    this._cw.setContent(wrap);
    this._cw.open(this.map, pos);
  },
  /* 列表 hover → 地图上弹出该店的预览气泡（不移动地图，避免跟着鼠标乱飞） */
  hoverRecord(r){
    if(!this.map || !r) return;
    const html=previewHTML(r);
    try{
      if(this.impl==='amap'){
        this._iw.setContent(html); this._iw.open(this.map,[r.lng,r.lat]);
      }else{
        if(!this._hoverPopup){
          this._hoverPopup=L.popup({closeButton:false,offset:[0,-34],className:'pin-tip-box',autoPan:false});
        }
        this._hoverPopup.setLatLng([r.lat,r.lng]).setContent(html).openOn(this.map);
      }
    }catch(e){}
  },
  hoverEnd(){
    try{
      if(this.impl==='amap'){ if(this._iw) this._iw.close(); }
      else if(this._hoverPopup && this.map) this.map.closePopup(this._hoverPopup);
    }catch(e){}
  },
  flyTo(r){ if(this.impl==='amap') this.map.setZoomAndCenter(16,[r.lng,r.lat]); else this.map.flyTo([r.lat,r.lng],16); },
  fitChina(){ if(this.impl==='amap') this.map.setZoomAndCenter(4,[104.2,35.5]); else this.map.setView([35.5,104.2],4); },
  getBounds(){
    if(this.impl==='amap'){ const b=this.map.getBounds(); return {swLng:b.getSouthWest().getLng(),swLat:b.getSouthWest().getLat(),neLng:b.getNorthEast().getLng(),neLat:b.getNorthEast().getLat()}; }
    const b=this.map.getBounds(); return {swLng:b.getWest(),swLat:b.getSouth(),neLng:b.getEast(),neLat:b.getNorth()};
  },
  /* 选点临时标记。
     注意：不能存在 Vue 的响应式对象（app._tempMarker）上——数据里的对象会被 reactive()
     深度代理，而 AMap 内部按引用管理覆盖物，代理对象会使 remove/add 抛异常，
     异常会中断调用方后续代码（表现为"选完点表单没回来"）。因此存在 MapView 自身。
     另外整段加 try/catch：地图操作失败也绝不能影响表单状态。*/
  _tempMarker:null,
  _clearTempMarker(){
    const m=this._tempMarker; this._tempMarker=null;
    if(!m) return;
    try{ this.impl==='amap' ? this.map.remove(m) : this.map.removeLayer(m); }
    catch(e){ try{ if(m.setMap) m.setMap(null); }catch(e2){} }   // AMap 兼容写法
  },
  tempMarker(lng,lat){
    try{
      this._clearTempMarker();
      if(this.impl==='amap'){
        this._tempMarker=new AMap.Marker({position:[lng,lat],zIndex:200});
        this.map.add(this._tempMarker);
        this.map.setZoomAndCenter(15,[lng,lat]);
      }else{
        const ic=L.divIcon({className:'',html:'<div style="width:16px;height:16px;border-radius:50%;background:#2f80ed;border:2.5px solid #fff;box-shadow:0 1px 5px rgba(0,0,0,.45)"></div>',iconSize:[16,16],iconAnchor:[8,8]});
        this._tempMarker=L.marker([lat,lng],{icon:ic}).addTo(this.map);
        this.map.flyTo([lat,lng],15);
      }
    }catch(e){ console.warn('tempMarker 失败（不影响选点结果）', e); }
  },
};
function loadScript(src, security){
  return new Promise((res,rej)=>{
    if(security) window._AMapSecurityConfig={securityJsCode:security};
    if([...document.scripts].some(s=>s.src===src)) return res();
    const s=document.createElement('script'); s.src=src; s.onload=res; s.onerror=()=>rej(new Error('脚本加载失败: '+src)); document.head.appendChild(s);
  });
}
function loadCSS(href){ return new Promise(res=>{ if([...document.querySelectorAll('link')].some(l=>l.href===href)) return res(); const l=document.createElement('link'); l.rel='stylesheet'; l.href=href; l.onload=res; l.onerror=res; document.head.appendChild(l); }); }

/* ---------------- 营业时间（每周排班） ---------------- */
const WEEKDAYS=[['mon','周一'],['tue','周二'],['wed','周三'],['thu','周四'],['fri','周五'],['sat','周六'],['sun','周日']];
function emptySchedule(){ const o={}; WEEKDAYS.forEach(([k])=>o[k]=[]); return o; }
function normTime(t){ const m=String(t||'').match(/^(\d{1,2}):(\d{2})$/); return m?`${String(m[1]).padStart(2,'0')}:${m[2]}`:''; }
function parseHours(str){
  const sched=emptySchedule(); if(!str) return sched;
  try{ const j=JSON.parse(str); if(j&&typeof j==='object'){ WEEKDAYS.forEach(([k])=>sched[k]=(j[k]||[]).map(x=>({s:normTime(x.s),e:normTime(x.e)}))); return sched; } }catch{}
  const m=String(str).match(/(\d{1,2}:\d{2})\s*[-~—至到]\s*(\d{1,2}:\d{2})/);
  if(m) WEEKDAYS.forEach(([k])=>sched[k]=[{s:normTime(m[1]),e:normTime(m[2])}]);
  return sched;
}
function serializeHours(sched){
  const any=WEEKDAYS.some(([k])=>sched[k]&&sched[k].length);
  if(!any) return null;
  const out={}; WEEKDAYS.forEach(([k])=>out[k]=sched[k]||[]);
  return JSON.stringify(out);
}
function fmtHoursRaw(str){
  if(!str) return '';
  let isJson=false; try{ const j=JSON.parse(str); isJson=!!j&&typeof j==='object'; }catch{}
  if(!isJson) return String(str);
  const sched=parseHours(str);
  const sig=k=>(sched[k]||[]).length?sched[k].map(x=>x.s+'~'+x.e).join('、'):'REST';
  const parts=[]; let i=0;
  while(i<7){ let j=i; while(j+1<7 && sig(WEEKDAYS[j+1][0])===sig(WEEKDAYS[i][0])) j++;
    const s=sig(WEEKDAYS[i][0]);
    const range=(i===j)?WEEKDAYS[i][1]:(j===i+1?WEEKDAYS[i][1]+'、'+WEEKDAYS[j][1]:WEEKDAYS[i][1]+'至'+WEEKDAYS[j][1]);
    parts.push(s==='REST'?range+' 休息':range+' '+s); i=j+1; }
  return parts.join('；');
}
function previewHTML(r){
  const st={want:'想去',visited:'去过',favorite:'收藏'}[r.checkinStatus];
  const tags=(r.tags||[]).slice(0,3).map(t=>`<span class="tip-tag">${esc(t)}</span>`).join('');
  return `<div class="tip-name">${esc(r.name)}</div><div class="tip-meta"><span class="tip-star">${'★'.repeat(r.rating)}</span>${st?`<span class="tip-status">${st}</span>`:''}${r.avgPrice!=null?`<span class="tip-price">¥${r.avgPrice}/人</span>`:''}</div>${tags?`<div class="tip-tags">${tags}</div>`:''}`;
}

/* ---------------- 图片大图预览（独立于 Vue） ---------------- */
function openLightbox(photos, i){
  window.__LB__={photos,i};
  $('#lbImg').src=photoPath(photos[i].id);
  $('#lbCounter').textContent=`${i+1} / ${photos.length}`;
  const multi=photos.length>1;
  $('#lbPrev').classList.toggle('hidden',!multi);
  $('#lbNext').classList.toggle('hidden',!multi);
  $('#lbCounter').classList.toggle('hidden',!multi);
  $('#lightbox').classList.remove('hidden');
}
function closeLightbox(){ $('#lightbox').classList.add('hidden'); window.__LB__=null; }
function lbNav(d){
  if(!window.__LB__) return;
  const p=window.__LB__.photos,n=p.length;
  window.__LB__.i=((window.__LB__.i+d)%n+n)%n;
  $('#lbImg').src=photoPath(p[window.__LB__.i].id);
  $('#lbCounter').textContent=`${window.__LB__.i+1} / ${n}`;
}
function bindLightbox(){
  $('#lbClose').onclick=closeLightbox;
  $('#lbPrev').onclick=()=>lbNav(-1);
  $('#lbNext').onclick=()=>lbNav(1);
  $('#lightbox').onclick=e=>{ if(e.target.id==='lightbox') closeLightbox(); };
}

/* ============================================================
   Vue 应用
   ============================================================ */
const App = {
  data(){
    return {
      panel:'none',
      showMarkers:true,
      moreOpen:false,
      searchOpen:false,
      /* 筛选面板：草稿态。改动只更新 filterDraft，点「应用」才写回 filters */
      filterOpen:false,
      filterDraft:{ ratingMin:0, ratingMax:null, priceMin:null, priceMax:null, tags:[], tagsMode:'all', drafts:'all', viewOnly:false },
      tagQuery:'',
      facetRecords:[], facetReady:false,
      themeName:'浅色',
      priceBuckets:PRICE_BUCKETS,
      settingsOpen:false, formOpen:false, detailOpen:false, dashOpen:false, importOpen:false,
      confirmBox:{ open:false, title:'', message:'', ok:'确认', danger:false, busy:false, onlyOk:false },
      records:[], renderCount:60, listTotal:0, activeIdx:-1,
      selectMode:false, selectedIds:[],
      filters:{ keyword:'', sort:'updatedAt:desc', tags:[], tagsMode:'all', ratingMin:0, ratingMax:null, checkin:'', viewOnly:false, priceMin:null, priceMax:null, drafts:'all' },
      viewBounds:null,
      allTags:[],
      detail:null,
      form:{ id:null, name:'', rating:3, price:'', checkin:'', note:'', draft:false, lat:null, lng:null, address:'' },
      formTags:[], formPhotos:[], formNewPhotos:[], formRemoved:[], hours:null, formMsg:'', tagInput:'',
      formMore:false, formErr:{ name:'', loc:'' },
      /* 位置状态：locName 是地点名，locCoord 是"纬度, 经度"字符串，两者都空表示未选点 */
      locName:'', locCoord:'',
      /* 地址联想：输入即搜（无需回车），poiActive 是键盘当前高亮项 */
      poiList:[], poiOpen:false, poiLoading:false, poiActive:-1, poiMsg:'', poiNeedKey:false,
      settings:{ key:'', security:'', webKey:'', connMsg:'', realKey:'' },
      /* 版本与更新：模板里要用，所以全部用普通名字（下划线开头 Vue 3 不代理） */
      appVersion:'', appMode:'', autoUpdateCheck:true,
      updateInfo:{}, updateMsg:'', updateBusy:false, updateBanner:false, updateBannerLow:false,
      dl:{ state:'idle', percent:0, received:0, total:0, error:'' },
      /* 安装阶段（2.0）：旧进程一退出，页面就再也拿不到数据，所以整块界面
         换成进度卡。phase: '' | closing | installing | done | timeout */
      installOpen:false, installPhase:'', installPercent:0, installTarget:'',
      installError:'', installCountdown:0, installDead:false,
      dash:null,
      importPreview:'', importReady:false, importFile:null,
      importBusy:false, importIndet:false, importPercent:0, importText:'',
      pickMode:false, pickCb:null, pickingMap:false, _pickedAt:0,
      mapConfig:{ configured:false },
      draftNotice:'', draftSaved:false, _suppressDraft:false,
      /* 内部状态：下划线开头，Vue 3 不会代理到实例，只能在 JS 方法里用 this._xxx 访问，
         严禁出现在模板表达式中（生产版会抛 ReferenceError，整个组件渲染失败） */
      _mapSeq:0, _mmT:null, _poiSeq:0, _dlTimer:null, _lastCheckAt:0,
      _installTimer:null, _watchTimer:null, _reloadTimer:null, _installT0:0, _installSeenDeath:false,
      /* 保存中标志：模板要用（禁用按钮 + 文案切换），所以必须用普通名字 */
      saving:false,
    };
  },
  computed:{
    /* 按草稿可见范围过滤后的记录（分页与计数都基于它） */
    visibleRecords(){ return this._visible(this.records); },
    draftCount(){ return this.records.filter(r=>r.draft).length; },
    /* 滚动加载：只渲染前 N 条，滚动到底前再追加，避免 1000 条一次性进 DOM */
    pagedRecords(){
      const n=Math.max(60, this.renderCount||60);
      return this.visibleRecords.slice(0,n);
    },
    /* 运行形态：设置面板里显示「安装版 / 绿色版 / 源码版」 */
    modeText(){ return this.appMode==='android' ? '安卓版' : (this.appMode==='installer' ? '安装版' : (this.appMode==='portable' ? '绿色版' : '源码版')); },

    /* 更新说明是 GitHub Release 的 markdown 原文，直接显示会露出
       **Full Changelog** 这种标记（用户截图踩过）；这里只做无害清洗，
       把加粗标记去掉，其余原样保留。 */
    updateNotes(){
      return (this.updateInfo.notes||'').replace(/\*\*/g,'').trim();
    },
    /* 不能自动安装时，按「用户此刻真的能点哪个按钮」给指令。
       源码版没 exe 可替换，让它去"替换 _internal"是错的；
       额度耗尽的降级结果里没有资产地址，「复制下载链接」按钮根本不渲染，
       此时再让用户点它就是死路，只能引导去 Release 页面。 */
    updateModeHint(){
      if(this.updateInfo && this.updateInfo.canAutoInstall) return '';
      if(this.appMode==='source') return '源码版：git pull 后重启服务即可。';
      if(this.appMode==='portable') return '绿色版：下载后替换 exe 与 _internal，别覆盖 data。';
      if(!this.updateInfo || !this.updateInfo.downloadUrl)
        return '去 Release 页面下载安装包，覆盖安装即可。';
      return '点「复制下载链接」用浏览器下载后覆盖安装。';
    },
    /* ---------- 安装遮罩的文案与步骤（模板直接取用，别在模板里写逻辑） ---------- */
    installTitle(){
      const v=this.installTarget?'v'+this.installTarget:'';
      if(this.installPhase==='done') return '已更新到 '+v;
      if(this.installPhase==='timeout') return '安装可能没有完成';
      if(this.installPhase==='closing') return '正在准备安装';
      return v ? ('正在安装 '+v) : '正在安装新版本';
    },
    installSub(){
      if(this.installPhase==='done') return (this.installCountdown>0)
        ? (this.installCountdown+' 秒后自动打开新版本…')
        : '正在打开新版本…';
      if(this.installPhase==='timeout') return this.installError || '没有检测到新版本启动，可手动打开安装包再装一次。';
      if(this.installPhase==='closing') return '正在关闭当前版本，马上开始安装。';
      return '安装期间界面不可用，通常需要 10–30 秒，请不要关闭这个窗口。';
    },
    installSteps(){
      const p=this.installPhase;
      const ok = p==='done';
      const s1 = p==='closing' ? 'run' : (ok||p==='installing'||p==='timeout' ? 'done' : 'wait');
      const s2 = p==='closing' ? 'wait'
               : p==='installing' ? 'run'
               : p==='timeout' ? 'fail' : 'done';
      const s3 = ok ? 'done' : 'wait';
      return [
        { k:'close',   label:'关闭当前版本', state:s1 },
        { k:'install', label:'安装新版本'+(this.installTarget?' v'+this.installTarget:''), state:s2 },
        { k:'restart', label:'重新启动', state:s3 },
      ];
    },
    /* 当前生效的筛选条件数（不含关键词与排序） */
    activeFilterCount(){
      const f=this.filters;
      let n=0;
      if(f.ratingMin||f.ratingMax) n++;
      if(f.priceMin!=null||f.priceMax!=null) n++;
      n+=f.tags.length;
      if(f.drafts!=='all') n++;
      if(f.viewOnly) n++;
      return n;
    },
    hasActiveFilters(){ return this.activeFilterCount>0 || !!this.filters.keyword.trim(); },
    /* 已选条件 chips：单个可移除，避免"忘了哪个条件没关" */
    activeChips(){
      const f=this.filters, out=[];
      if(f.ratingMin||f.ratingMax){
        const lo=f.ratingMin||1, hi=f.ratingMax;
        const t=(hi&&hi===lo)?`${lo} 星`:(hi?`${lo}–${hi} 星`:`≥${lo} 星`);
        out.push({k:'rating', t});
      }
      if(f.priceMin!=null||f.priceMax!=null) out.push({k:'price', t:'人均 '+this._priceLabel(f.priceMin,f.priceMax)});
      f.tags.forEach((t,i)=>out.push({k:'tag'+i, t:'标签 · '+t}));
      if(f.tags.length>1 && f.tagsMode==='any') out.push({k:'tagsMode', t:'标签：任一'});
      if(f.drafts==='hide') out.push({k:'drafts', t:'不含草稿'});
      if(f.drafts==='only') out.push({k:'drafts', t:'仅草稿'});
      if(f.viewOnly) out.push({k:'viewOnly', t:'仅看当前视野'});
      return out;
    },
    filteredTags(){
      const q=(this.tagQuery||'').trim().toLowerCase();
      return q ? this.allTags.filter(t=>t.t.toLowerCase().includes(q)) : this.allTags;
    },
    /* 面板里的「符合 N 家」：纯本地估算，不发请求 */
    filterDraftCount(){
      if(!this.facetReady) return '…';
      const f=this.filterDraft;
      return this.facetRecords.filter(r=>this._matchFilters(r,f)).length;
    },
    /* 看板图表用的最大值（决定柱子相对高度） */
    dashRatingMax(){ return this.dash ? Math.max(1, ...this.dash.rating.dist.map(d=>d.count)) : 1; },
    dashPriceMax(){ return this.dash ? Math.max(1, ...this.dash.price.buckets.map(b=>b.count)) : 1; },
    dashTagMax(){ return this.dash ? Math.max(1, ...this.dash.tags.top.map(t=>t.count)) : 1; },
    dashMonthMax(){ return this.dash ? Math.max(1, this.dash.monthPeak||0) : 1; },
  },
  watch:{
    form:{ handler(){ this.scheduleDraft(); }, deep:true },
    formTags:{ handler(){ this.scheduleDraft(); }, deep:true },
    hours:{ handler(){ this.scheduleDraft(); }, deep:true },
    locName(){ this.scheduleDraft(); },
    locCoord(){ this.scheduleDraft(); },
    /* 清单打开时给 body 打个标记：地图兜底提示条要避开左侧面板 */
    panel(v){ document.body.classList.toggle('fm-list-open', v==='list'); },
  },
  methods:{
    statusOf(r){ return {want:'想去',visited:'去过',favorite:'收藏'}[r.checkinStatus]||''; },
    photoSrc(id){ return photoPath(id); },
    photoURL(f){
      if(!f) return '';
      let u=this._photoURLs.get(f);
      if(!u){ u=URL.createObjectURL(f); this._photoURLs.set(f,u); }   // 每个 File 只建一次
      return u;
    },
    releasePhotoURL(f){
      if(!this._photoURLs) return;
      const u=f&&this._photoURLs.get(f);
      if(u){ URL.revokeObjectURL(u); this._photoURLs.delete(f); }
    },
    releaseAllPhotoURLs(){
      if(!this._photoURLs) return;
      for(const u of this._photoURLs.values()) URL.revokeObjectURL(u);
      this._photoURLs.clear();
    },
    fmtHours(s){ return fmtHoursRaw(s); },

    /* 应用内确认弹窗（替代浏览器原生 confirm） */
    askConfirm(opts){
      return new Promise(resolve=>{
        this._confirmResolve=resolve;
        this.confirmBox={
          open:true,
          title:opts.title||'请确认',
          message:opts.message||'',
          ok:opts.ok||'确认',
          danger:!!opts.danger,
          busy:false,
          onlyOk:!!opts.onlyOk,
        };
      });
    },
    closeConfirm(v){
      const r=this._confirmResolve;
      this._confirmResolve=null;
      this.confirmBox={...this.confirmBox, open:false, busy:false};
      if(r) r(!!v);
    },
    setConfirmBusy(v){ this.confirmBox={...this.confirmBox, busy:!!v}; },
    showError(title, msg){
      return this.askConfirm({ title, message:msg, ok:'知道了', onlyOk:true });
    },

    /* 批量删除的请求层：批量接口不可用（旧版服务）时退化为逐条删除 */
    async removeRecords(ids){
      try{
        const r=await API.del('/api/records/batch',{ids});
        return (r&&r.deleted!=null)?r.deleted:ids.length;
      }catch(e){
        const fallback=[404,405,422,501].includes(e.status);
        if(!fallback) throw e;
        let n=0;
        for(const id of ids){ await API.del(recPath(id)); n++; }
        return n;
      }
    },

    /* 主题 */
    toggleTheme(){
      const cur=document.documentElement.getAttribute('data-theme');
      const next=cur==='dark'?'light':'dark';
      document.documentElement.setAttribute('data-theme',next);
      try{ localStorage.setItem('fm-theme',next); }catch{}
      this.themeName = next==='dark' ? '深色' : '浅色';
      this.moreOpen=false;
    },

    /* 显示选项：地图描点开关 */
    setShowMarkers(v){
      this.showMarkers = !!v;
      try{ localStorage.setItem('fm-show-markers', this.showMarkers?'1':'0'); }catch{}
      this.reloadMap();
      toast(this.showMarkers?'已显示描点':'已隐藏描点');
    },

    /* 视图切换：地图 / 清单 / 看板 */
    goHome(){ this.moreOpen=false; this.panel='none'; this.dashOpen=false; this.filterOpen=false; this.fitChina(); this._syncURL(); },
    goMap(){ this.moreOpen=false; this.panel='none'; this.dashOpen=false; this.filterOpen=false; this.closeDetail(); this._syncURL(); },
    openList(){
      this.moreOpen=false; this.dashOpen=false; this.panel='list';
      this._syncURL();
      // 「仅看当前视野」在打开清单时按此刻地图范围重取，避免用的是上次的 bounds
      if(this.filters.viewOnly){ this.viewBounds=MapView.getBounds(); this.loadRecords(); }
    },
    /* 面板开关（保留旧调用点） */
    togglePanel(name){ this.moreOpen=false; this.panel = this.panel===name ? 'none' : name; },
    closePanel(){ this.panel='none'; this.filterOpen=false; this.exitSelect(); this._syncURL(); },
    fitChina(){ MapView.fitChina(); this.moreOpen=false; },

    /* 数据加载 */
    async loadRecords(){
      const f=this.filters;
      // 序列号防竞态：快速切筛选/搜索时，先发出的请求可能后返回，把新结果盖回去。
      // 地图有 _mapSeq，列表之前没有——补上同一套保护。
      const seq=(this._recSeq=(this._recSeq||0)+1);
      // 列表始终把草稿取回来（否则勾选"存为草稿"的记录会从列表和地图上彻底消失），
      // 再由前端按 filters.drafts 决定显示范围
      let url=`/api/records?${this._filterQuery(true)}`;
      if(f.viewOnly && this.viewBounds){ const b=this.viewBounds; url+=`&swLng=${b.swLng}&swLat=${b.swLat}&neLng=${b.neLng}&neLat=${b.neLat}`; }
      try{
        const recs=await API.get(url);
        if(seq!==this._recSeq) return;   // 已有更新的请求在路上，这份旧响应作废
        this.records=recs; this.listTotal=this._visible(recs).length;
        // 清除已不存在于当前结果里的选中项（如被筛掉或已删除），避免误删
        if(this.selectedIds.length){
          const alive=new Set(this._visible(recs).map(r=>r.id));
          this.selectedIds=this.selectedIds.filter(id=>alive.has(id));
        }
        const cnt={}; recs.forEach(r=>(r.tags||[]).forEach(t=>cnt[t]=(cnt[t]||0)+1));
        // 不再截断到 24 个：标签多了以后长尾标签也要能筛到（面板里可搜索）
        this.allTags=Object.entries(cnt).sort((a,b)=>b[1]-a[1]).map(([t,c])=>({t,c}));
        await this.reloadMap();   // 地图按视野动态加载，不再全量渲染
        this._syncURL();
      }catch(e){ toast('加载失败：'+e.message); }
    },
    onSearch(){ clearTimeout(this._st); this._st=setTimeout(()=>this.loadRecords(),250); },
    /* 窄屏（≤980px）顶栏只留搜索图标，点开后用浮层输入；宽屏直接聚焦原输入框 */
    onSearchTap(e){
      if(!window.matchMedia || !window.matchMedia('(max-width:980px)').matches) return;
      e.preventDefault();
      this.openMobileSearch();
    },
    openMobileSearch(){
      this.moreOpen=false;
      this.searchOpen=true;
      this.$nextTick(()=>{ const el=this.$refs.mobileSearch; if(el) el.focus(); });
    },
    closeMobileSearch(){ this.searchOpen=false; },
    /* 列表滚动到底部前 240px，追加 60 条 */
    onListScroll(e){
      const el=e.target;
      if(this._moreLock) return;
      if(el.scrollTop+el.clientHeight < el.scrollHeight-240) return;
      if(this.renderCount>=this.visibleRecords.length) return;
      this._moreLock=true;
      this.renderCount=Math.min(this.visibleRecords.length, this.renderCount+60);
      this.$nextTick(()=>{ this._moreLock=false; });
    },
    /* 把某条记录滚进视野；若它还没渲染，先把 renderCount 扩到它之后 */
    _revealRecord(id){
      const idx=this.visibleRecords.findIndex(r=>r.id===id);
      if(idx<0) return;
      if(idx>=this.renderCount) this.renderCount=Math.min(this.visibleRecords.length, idx+20);
      this.$nextTick(()=>{
        // 不用选择器拼 id：旧数据里可能有引号/空格，直接按 dataset 比对更稳
        const el=$$('.rec-card').find(x=>x.dataset.rid===String(id));
        if(el) el.scrollIntoView({block:'nearest', behavior:'smooth'});
      });
    },
    /* 筛选条件拼成查询串（列表与地图共用）
       withDrafts=true 时把草稿一并取回（列表用）；
       draftsOnly=true 时只取草稿（地图在"仅草稿"下必须与列表同范围，否则会混入非草稿） */
    _filterQuery(withDrafts, draftsOnly){
      const f=this.filters;
      let q=`keyword=${encodeURIComponent(f.keyword)}&sort=${f.sort}&checkinStatus=${f.checkin}`;
      // 星级是「下限」语义：只看 ≥N 星，不再写死区间
      if(f.ratingMin) q+=`&ratingMin=${f.ratingMin}`;
      if(f.ratingMax) q+=`&ratingMax=${f.ratingMax}`;
      if(f.tags.length){
        // 重复参数（?tags=a&tags=b），不按逗号拼——标签本身可以含逗号
        q+=f.tags.map(t=>`&tags=${encodeURIComponent(t)}`).join('');
        if(f.tagsMode==='any') q+='&tagsAny=1';
      }
      if(f.priceMin!=null) q+=`&avgPriceMin=${f.priceMin}`;
      if(f.priceMax!=null) q+=`&avgPriceMax=${f.priceMax}`;
      if(draftsOnly) q+='&includeDrafts=1&draftsOnly=1';
      else if(withDrafts) q+='&includeDrafts=1';
      return q;
    },
    /* 草稿可见范围：all 全部 / hide 不含 / only 仅草稿 */
    _visible(list){
      const ds=this.filters.drafts;
      if(ds==='hide') return list.filter(r=>!r.draft);
      if(ds==='only') return list.filter(r=>r.draft);
      return list;
    },
    /* 地图按当前可视区+上限取数并渲染（根治大规模卡顿） */
    async reloadMap(){
      if(!MapView.map) return;
      if(!this.showMarkers){ MapView.render([]); return; }
      const seq = ++this._mapSeq;
      const b = MapView.getBounds();
      // 地图与列表使用同一草稿范围：含草稿=全取 / 仅草稿=只取草稿 / 不含草稿=后端默认排除
      const ds = this.filters.drafts;
      const url = `/api/records?${this._filterQuery(ds!=='hide', ds==='only')}&swLng=${b.swLng}&swLat=${b.swLat}&neLng=${b.neLng}&neLat=${b.neLat}&limit=${MAP_LIMIT}`;
      try{
        const recs = await API.get(url);
        if(seq !== this._mapSeq) return;            // 已有更新的请求，丢弃过期结果
        MapView.render(recs);
      }catch(e){ /* 视野加载失败不影响列表，忽略 */ }
    },
    onMapMoveEnd(){
      clearTimeout(this._mmT);
      this._mmT=setTimeout(()=>{
        if(this.filters.viewOnly && this.panel==='list'){
          this.viewBounds=MapView.getBounds();
          this.loadRecords();            // loadRecords 内部会 reloadMap，不重复请求
        }else{
          this.reloadMap();
        }
      }, 380);
    },

    /* 详情 */
    async showDetail(id){
      const token=(this._detailReq=(this._detailReq||0)+1);   // 竞态守卫：仅最新的点击生效
      try{
        const r=await API.get(recPath(id));
        if(token!==this._detailReq) return;                   // 已有更新的请求，丢弃本次旧结果
        this.detail=r; this.detailOpen=true;
        MapView.flyTo(r);
        if(this.panel==='list') this._revealRecord(r.id);
      }catch(e){ if(token===this._detailReq) toast('打开失败：'+e.message); }
    },
    closeDetail(){ this.detailOpen=false; this.activeIdx=-1; },
    /* 点击空白：按「详情 → 筛选 → 清单」逐层返回。
       snap 是按下瞬间的快照，避免同一次点击被多个处理器各关一层。 */
    onMapBlankClick(snap){
      snap = snap || { detail:this.detailOpen, filter:this.filterOpen, panel:this.panel, form:this.formOpen };
      if(snap.form) return;              // 表单开着时点空白不应悄悄关掉背后的清单
      if(snap.filter){ this.filterOpen=false; return; }
      if(snap.detail){ this.closeDetail(); return; }
      if(snap.panel==='list'){ this.closePanel(); }
    },

    /* ---------- 列表卡片 / 详情的快捷操作 ---------- */
    /* PUT 是全量替换，所以要把未改动的字段一起带上；照片不在此接口内，不会被误删 */
    _recordBody(r, extra){
      return Object.assign({
        name:r.name, lng:r.lng, lat:r.lat, rating:r.rating,
        tags:r.tags||[], businessHours:r.businessHours||null,
        avgPrice:r.avgPrice!=null?r.avgPrice:null,
        checkinStatus:r.checkinStatus||null, note:r.note||null, draft:!!r.draft,
      }, extra||{});
    },
    locateRecord(r){ MapView.flyTo(r); toast('已定位：'+r.name); },
    async markVisited(r){
      if(r.checkinStatus==='visited') return;
      try{
        await API.sendForm(recPath(r.id),'PUT',this._recordBody(r,{checkinStatus:'visited'}));
        toast(`「${r.name}」已标记为去过`);
        if(this.detail && this.detail.id===r.id) this.detail={...this.detail, checkinStatus:'visited'};
        await this.loadRecords();
      }catch(e){ toast('修改失败：'+e.message); }
    },
    /* 列表接口不带照片，编辑前先取完整记录，避免打开表单后照片"消失" */
    async editRecord(r){
      try{ const full=await API.get(recPath(r.id)); this.openForm(full); }
      catch(e){ toast('打开失败：'+e.message); }
    },
    navTo(r){
      const url='https://uri.amap.com/marker?position='+r.lng+','+r.lat
        +'&name='+encodeURIComponent(r.name||'美食')+'&src=foodmap&coordinate=gaode&callnative=0';
      openExternalUrl(url);
    },
    async setDetailStatus(s){
      const d=this.detail;
      if(!d || d.checkinStatus===s) return;
      const prev=d.checkinStatus;
      this.detail={...d, checkinStatus:s};        // 乐观更新，失败回滚
      try{
        const rec=await API.sendForm(recPath(d.id),'PUT',this._recordBody(d,{checkinStatus:s}));
        this.detail=rec;
        toast('已标记为'+({want:'想去',visited:'去过',favorite:'收藏'}[s]||s));
        await this.loadRecords();
      }catch(e){
        this.detail={...this.detail, checkinStatus:prev};
        toast('修改失败：'+e.message);
      }
    },
    async deleteDetail(){
      if(!this.detail) return;
      const id=this.detail.id, name=this.detail.name;
      const ok=await this.askConfirm({
        title:'删除这条记录？',
        message:`「${name}」及其照片会被永久删除，此操作不可撤销。`,
        ok:'删除', danger:true,
      });
      if(!ok) return;
      this.setConfirmBusy(true);
      try{
        await API.del(recPath(id));
        this.closeConfirm(true);
        toast('已删除');
        this.detailOpen=false; this.detail=null;
        await this.loadRecords();
      }catch(e){
        this.closeConfirm(true);
        await this.showError('删除失败', e.message||'未知错误');
      }
    },

    /* 批量选择 / 批量删除（列表抽屉内） */
    enterSelect(){ this.moreOpen=false; this.filterOpen=false; this.panel='list'; this.selectMode=true; this._syncURL(); },
    exitSelect(){ this.selectMode=false; this.selectedIds=[]; },
    isSelected(id){ return this.selectedIds.includes(id); },
    toggleSelect(id){
      const i=this.selectedIds.indexOf(id);
      if(i>=0) this.selectedIds.splice(i,1); else this.selectedIds.push(id);
    },
    /* 全选：作用于当前筛选后的全部结果（不限于当前页；也不含被草稿筛选隐藏的记录） */
    selectAll(){ this.selectedIds=this.visibleRecords.map(r=>r.id); },
    /* 反选：当前结果集中未选中的变为选中，已选中的取消 */
    invertSelect(){
      const sel=new Set(this.selectedIds);
      this.selectedIds=this.visibleRecords.filter(r=>!sel.has(r.id)).map(r=>r.id);
    },
    clearSelect(){ this.selectedIds=[]; },
    async batchDelete(){
      const ids=[...this.selectedIds];
      if(!ids.length) return;
      const ok=await this.askConfirm({
        title:`删除 ${ids.length} 条记录？`,
        message:'所选记录及其照片会被永久删除，此操作不可撤销。',
        ok:`删除 ${ids.length} 条`, danger:true,
      });
      if(!ok) return;
      this.setConfirmBusy(true);
      try{
        const n=await this.removeRecords(ids);
        this.closeConfirm(true);
        toast(`已删除 ${n} 条`);
        if(this.detail && ids.includes(this.detail.id)){ this.detailOpen=false; this.detail=null; }
        this.exitSelect();
        await this.loadRecords();
      }catch(e){
        this.closeConfirm(true);
        await this.loadRecords();          // 可能已部分删除，先让列表回到真实状态
        await this.showError('删除失败', `${e.message||'未知错误'}。若问题持续，请关闭窗口重新运行 start.bat 后再试。`);
      }
    },

    /* ---------- 筛选：筛选栏即时生效，面板内是草稿态 ---------- */
    setCheckin(c){ this.filters.checkin=c; this.renderCount=60; this.loadRecords(); },
    _priceLabel(min,max){
      const b=PRICE_BUCKETS.find(x=>x.min===min && x.max===max);
      if(b) return '¥'+b.label;
      if(min!=null && max!=null) return `¥${min}–${max}`;
      if(min!=null) return `≥¥${min}`;
      return `低于 ¥${max}`;    // 上限是开区间（< max），写 ≤ 会差一块钱
    },
    /* 本地匹配：与后端 list() 的条件保持一致，用于面板里的结果预估 */
    _matchFilters(r,f){
      const kw=(this.filters.keyword||'').trim().toLowerCase();
      if(kw){
        const hay=((r.name||'')+' '+(r.note||'')+' '+(r.tags||[]).join(' ')).toLowerCase();
        if(!hay.includes(kw)) return false;
      }
      if(this.filters.checkin && r.checkinStatus!==this.filters.checkin) return false;
      if(f.ratingMin && r.rating<f.ratingMin) return false;
      if(f.ratingMax && r.rating>f.ratingMax) return false;
      if(f.priceMin!=null || f.priceMax!=null){
        if(r.avgPrice==null) return false;
        if(f.priceMin!=null && r.avgPrice<f.priceMin) return false;
        if(f.priceMax!=null && r.avgPrice>=f.priceMax) return false;
      }
      if(f.tags.length){
        const has=(r.tags||[]);
        const ok=f.tagsMode==='any' ? f.tags.some(t=>has.includes(t)) : f.tags.every(t=>has.includes(t));
        if(!ok) return false;
      }
      if(f.drafts==='hide' && r.draft) return false;
      if(f.drafts==='only' && !r.draft) return false;
      return true;
    },
    async toggleFilter(){
      if(this.filterOpen){ this.filterOpen=false; return; }
      // 打开时把已生效条件复制成草稿；面板内改动不发请求
      this.filterDraft={
        ratingMin:this.filters.ratingMin, ratingMax:this.filters.ratingMax,
        priceMin:this.filters.priceMin, priceMax:this.filters.priceMax,
        tags:[...this.filters.tags], tagsMode:this.filters.tagsMode,
        drafts:this.filters.drafts, viewOnly:this.filters.viewOnly,
      };
      this.tagQuery='';
      this.filterOpen=true;
      this.facetReady=false;
      try{
        const recs=await API.get('/api/records?includeDrafts=1&sort='+encodeURIComponent(this.filters.sort));
        this.facetRecords=recs;
      }catch(e){ this.facetRecords=[]; }
      this.facetReady=true;
    },
    setDraftPrice(i){
      if(i==null){ this.filterDraft.priceMin=null; this.filterDraft.priceMax=null; return; }
      const b=PRICE_BUCKETS[i];
      this.filterDraft.priceMin=b.min; this.filterDraft.priceMax=b.max;
    },
    toggleDraftTag(t){
      const i=this.filterDraft.tags.indexOf(t);
      if(i>=0) this.filterDraft.tags.splice(i,1); else this.filterDraft.tags.push(t);
    },
    resetDraftFilter(){
      this.filterDraft={ ratingMin:0, ratingMax:null, priceMin:null, priceMax:null, tags:[], tagsMode:'all', drafts:'all', viewOnly:false };
    },
    applyFilter(){
      const d=this.filterDraft;
      this.filters.ratingMin=d.ratingMin;
      this.filters.ratingMax=d.ratingMax||null;
      this.filters.priceMin=d.priceMin;
      this.filters.priceMax=d.priceMax;
      this.filters.tags=[...d.tags];
      this.filters.tagsMode=d.tagsMode||'all';
      this.filters.drafts=d.drafts;
      // 「仅看当前视野」是模式不是阈值：打开时锁定当前视野，关闭时清掉 bounds
      if(d.viewOnly && !this.filters.viewOnly) this.viewBounds=MapView.getBounds();
      if(!d.viewOnly) this.viewBounds=null;
      this.filters.viewOnly=d.viewOnly;
      this.filterOpen=false;
      this.renderCount=60;
      const n=((d.ratingMin||d.ratingMax)?1:0)+((d.priceMin!=null||d.priceMax!=null)?1:0)+d.tags.length+(d.drafts!=='all'?1:0);
      this.loadRecords();
      toast(n?`已应用筛选 · ${n} 个条件`:'已清除筛选');
    },
    removeChip(k){
      const f=this.filters;
      if(k==='rating'){ f.ratingMin=0; f.ratingMax=null; }
      else if(k==='price'){ f.priceMin=null; f.priceMax=null; }
      else if(k==='drafts') f.drafts='all';
      else if(k==='tagsMode') f.tagsMode='all';
      else if(k==='viewOnly'){ f.viewOnly=false; this.viewBounds=null; }
      else if(k.indexOf('tag')===0) f.tags.splice(+k.slice(3),1);
      this.renderCount=60; this.loadRecords();
    },
    clearFilters(){
      Object.assign(this.filters,{
        keyword:'', tags:[], tagsMode:'all', ratingMin:0, ratingMax:null, checkin:'', viewOnly:false,
        priceMin:null, priceMax:null, drafts:'all',
      });
      this.viewBounds=null; this.tagQuery='';
      this.filterDraft={ ratingMin:0, ratingMax:null, priceMin:null, priceMax:null, tags:[], drafts:'all', viewOnly:false };
      this.filterOpen=false; this.renderCount=60;
      this.loadRecords();
    },
    /* 旧接口保留：草稿范围仍要保证列表与地图同源 */
    setDrafts(v){
      if(this.filters.drafts===v) return;
      this.filters.drafts=v; this.renderCount=60; this.listTotal=this.visibleRecords.length;
      this.reloadMap();
    },
    onViewOnly(e){ this.filters.viewOnly=e.target.checked; if(this.filters.viewOnly) this.viewBounds=MapView.getBounds(); else this.viewBounds=null; this.loadRecords(); },
    resetFilter(){ this.clearFilters(); },

    /* ---------- URL 状态：刷新、分享、前进后退都不丢筛选 ---------- */
    _syncURL(){
      const f=this.filters, q=new URLSearchParams();
      if(this.panel==='list') q.set('view','list');
      if(f.checkin) q.set('status',f.checkin);
      if(f.ratingMin) q.set('rating',String(f.ratingMin));
      if(f.ratingMax) q.set('ratingMax',String(f.ratingMax));
      if(f.priceMin!=null||f.priceMax!=null) q.set('price',`${f.priceMin==null?'':f.priceMin}-${f.priceMax==null?'':f.priceMax}`);
      f.tags.forEach(t=>q.append('tags',t));   // 重复参数，标签含逗号也不拆
      if(f.tags.length>1 && f.tagsMode==='any') q.set('tagsMode','any');
      if(f.drafts!=='all') q.set('drafts',f.drafts);
      if(f.viewOnly) q.set('viewOnly','1');
      if(f.keyword.trim()) q.set('q',f.keyword.trim());
      if(f.sort!=='updatedAt:desc') q.set('sort',f.sort);
      const s=q.toString();
      try{ history.replaceState(null,'',location.pathname+(s?'?'+s:'')); }catch(e){}
    },
    _readURL(){
      const q=new URLSearchParams(location.search);
      // 先把筛选恢复默认：URL 是完整的状态源，不带某个参数就表示「这一项没有筛选」。
      // 只在参数存在时赋值，会让「后退」到更早的 URL 时残留上一次的筛选条件。
      Object.assign(this.filters, {
        keyword:'', sort:'updatedAt:desc', tags:[], tagsMode:'all',
        ratingMin:0, ratingMax:null, checkin:'', viewOnly:false,
        priceMin:null, priceMax:null, drafts:'all',
      });
      if(q.get('view')==='list') this.panel='list';
      const st=q.get('status');
      if(['want','visited','favorite'].indexOf(st)>=0) this.filters.checkin=st;
      const rt=parseInt(q.get('rating'),10);
      if(rt>=1&&rt<=5) this.filters.ratingMin=rt;
      const rMax=parseInt(q.get('ratingMax'),10);
      if(rMax>=1&&rMax<=5) this.filters.ratingMax=rMax;
      const pr=q.get('price');
      if(pr){
        const parts=pr.split('-');
        if(parts[0]) this.filters.priceMin=parseInt(parts[0],10);
        if(parts[1]) this.filters.priceMax=parseInt(parts[1],10);
      }
      const tg=q.getAll('tags');               // 新格式是重复参数；旧分享链接（tags=a,b）不再按逗号拆
      if(tg.length) this.filters.tags=tg.filter(Boolean);
      if(q.get('tagsMode')==='any') this.filters.tagsMode='any';
      const df=q.get('drafts');
      if(df==='hide'||df==='only') this.filters.drafts=df;
      if(q.get('viewOnly')==='1') this.filters.viewOnly=true;
      const kw=q.get('q'); if(kw) this.filters.keyword=kw;
      const so=q.get('sort'); if(so) this.filters.sort=so;
      this.filterDraft={
        ratingMin:this.filters.ratingMin, ratingMax:this.filters.ratingMax,
        priceMin:this.filters.priceMin, priceMax:this.filters.priceMax,
        tags:[...this.filters.tags], tagsMode:this.filters.tagsMode,
        drafts:this.filters.drafts, viewOnly:this.filters.viewOnly,
      };
    },
    mapHover(r){ MapView.hoverRecord(r); },
    mapLeave(){ MapView.hoverEnd(); },
    /* 键盘：↑↓ 在列表内移动，Enter 打开 */
    _moveActive(d){
      const list=this.pagedRecords;
      if(!list.length) return;
      let i=this.activeIdx;
      i = i<0 ? (d>0?0:list.length-1) : Math.min(list.length-1, Math.max(0,i+d));
      this.activeIdx=i;
      this.$nextTick(()=>{
        const el=document.querySelectorAll('.rec-card')[i];
        if(el) el.scrollIntoView({block:'nearest'});
      });
      MapView.hoverRecord(list[i]);
    },
    _openActive(){
      const r=this.pagedRecords[this.activeIdx];
      if(r) this.showDetail(r.id);
    },

    /* 看板：加载 + 图表下钻（点图表即筛到列表） */
    async openDash(){
      this.moreOpen=false;
      this.panel='none'; this.filterOpen=false;
      try{ this.dash=await API.get('/api/dashboard'); this.dashOpen=true; }
      catch(e){ toast('看板加载失败：'+e.message); }
    },
    dashDrill(kind, val){
      /* 看板统计的是「全部非草稿」，所以下钻必须把其它遗留条件一起清掉：
         否则之前开着「仅草稿」或搜索词时，点图表会得到空列表、数量也对不上。
         草稿范围也设成 hide——图表里的数字本来就不含草稿，否则点「4★ 42」
         会得到 44 条（多出草稿），数字对不上。 */
      const f={
        keyword:'', sort:'updatedAt:desc', checkin:'',
        ratingMin:0, ratingMax:null, priceMin:null, priceMax:null,
        tags:[], tagsMode:'all', drafts:'hide', viewOnly:false,
      };
      let label='';
      if(kind==='checkin'){ f.checkin=val; label={visited:'去过',want:'想去',favorite:'收藏'}[val]||'全部'; }
      // 柱状图是「精确星级」：4 星就只筛 4 星，不能把 5 星也算进来
      else if(kind==='star'){ f.ratingMin=val; f.ratingMax=val; label=val+' 星'; }
      else if(kind==='price'){ const b=this.dash.price.buckets[val]; f.priceMin=b.min; f.priceMax=b.max; label='人均 '+b.label; }
      else if(kind==='tag'){ f.tags=[val]; label=val; }
      this.dashOpen=false;
      this.viewBounds=null;
      Object.assign(this.filters, f);
      this.filterDraft={
        ratingMin:f.ratingMin, ratingMax:f.ratingMax, priceMin:null, priceMax:null,
        tags:[...f.tags], tagsMode:'all', drafts:f.drafts, viewOnly:false,
      };
      this.renderCount=60;
      this.panel='list';                 // 下钻直接打开清单，条件以 chips 回显
      this.filterOpen=false;
      this.loadRecords();
      toast('已筛选：'+label);
    },
    dashOpenRecord(id){ this.dashOpen=false; this.showDetail(id); },
    barH(n, max){ return (n && max ? Math.max(4, Math.round(n*100/max)) : 0) + '%'; },

    /* 设置 */
    async openSettings(){
      this.moreOpen=false;
      try{
        const cfg=await API.get('/api/config/amap');
        this.mapConfig=cfg; this.settings.realKey=cfg.key;
        this.settings.key=cfg.configured?this.maskKey(cfg.key):'';
        // 已存的安全密钥用掩码回显；用户不改动则原样回传，避免"只改 Web Key 却把 securityJsCode 抹掉"
        this.settings.security=cfg.security?this.maskKey(cfg.security):'';
        this.settings.webKey=''; this.settings.connMsg='';
        this.settingsOpen=true;
      }catch(e){
        // 高德配置读失败也要能打开设置：更新检查与地图 Key 无关，
        // 否则这个接口一报错，用户就永远进不到「检查更新」。
        this.settingsOpen=true;
        toast('地图 Key 读取失败：'+e.message);
      }
      this.loadVersion();
      this._syncDownload();
    },
    /* ---------- 版本与更新 ---------- */
    async loadVersion(){
      try{ const r=await API.get('/api/app/version'); this.appVersion=r.version||''; this.appMode=r.mode||''; }
      catch(e){ /* 版本号读不到不影响主流程，静默 */ }
    },
    /* 刚更新完的判断：安装前写了 fm-updating=<目标版本>，这里只在新版本真的
       起来（本地版本 ≥ 目标）时才消费掉它，并让开屏显示「已更新到 vX」。
       安装失败时标记留着不动——把一次失败显示成「已更新」比不显示更糟。 */
    _updatedNote(){
      let target='';
      try{ target=localStorage.getItem('fm-updating')||''; }catch(e){ return ''; }
      if(!target || !this.appVersion) return '';
      if(target!=='1' && verCmp(this.appVersion, target)<0) return '';
      try{ localStorage.removeItem('fm-updating'); }catch(e){}
      return '已更新到 v'+this.appVersion;
    },
    fmtDate(s){ try{ return new Date(s).toLocaleDateString('zh-CN'); }catch(e){ return ''; } },
    /* force=true 跳过后端 30 分钟缓存；启动时用 false，几乎不产生网络开销 */
    async checkUpdate(force){
      if(this.updateBusy) return;
      // 手动检查加 20 秒防抖：GitHub 对短时间内的突发请求会直接回 403（次级限流），
      // 连点「检查更新」正好踩中，而且响应里看不出原因，只会显示一句 HTTP 403。
      if(force && this._lastCheckAt && Date.now()-this._lastCheckAt < 20000){
        this.updateMsg='刚检查过，请等十几秒再试（GitHub 会限制过密的请求）';
        return;
      }
      this.updateBusy=true;
      if(force){ this.updateMsg='正在检查…'; this._lastCheckAt=Date.now(); }
      try{
        const r=await API.get('/api/update/check'+(force?'?force=1':''));
        this.updateInfo=r||{};
        if(!r || r.ok===false){
          // 后端的 reason 已经是给人看的完整句子（原因+等多久+去哪看），直接展示
          this.updateMsg=(r&&r.reason)||'暂时无法检查更新，请稍后再试';
        }else if(r.hasUpdate){
          let m = r.degraded
            ? ('发现新版本 v'+r.latest+'，GitHub 接口额度已用完，只能手动下载')
            : ('发现新版本 v'+r.latest);
          this.updateMsg=m+this._cacheNote(r);
          // 「忽略此版本」在启动路径上已判断；手动点「检查更新」也应该一致——
          // 用户刚点过 ✕，再主动查一次却把横幅弹回来，会让他以为 ✕ 没生效。
          const skip=(()=>{ try{ return localStorage.getItem('fm-skip-version')||''; }catch(e){ return ''; } })();
          if(!skip || r.latest!==skip) this._showUpdateBanner();
        }else if(r.stale){
          // 联网失败兜底：此时「已是最新版本」这个断言根本不成立——根本没查成。
          // 必须明说失败 + 显示的是多久之前的结果，否则刚发布的新版会被旧缓存挡住。
          const mins=r.checkedAt?Math.max(1,Math.round((Date.now()/1000-r.checkedAt)/60)):0;
          const when=mins>0?mins+' 分钟前':'';
          this.updateMsg='检查更新失败：'+((r.reason||'网络问题').replace(/。$/,''))+
            '。下面是 '+when+'的缓存结果（当前 v'+r.current+'）。点「检查更新」重试';
          this.updateBanner=false;
        }else{
          this.updateMsg='已是最新版本（v'+r.current+'）'+this._cacheNote(r);
          this.updateBanner=false;
        }
      }catch(e){
        // 走到这里多是本机网络断了，e.message 是英文异常名，不给人看
        this.updateMsg='暂时无法连接 GitHub，请检查网络后重试';
      }finally{
        this.updateBusy=false;
      }
    },
    openUpdateFromBanner(){ this.updateBanner=false; this.openSettings(); },
    /* 结果来自缓存或联网失败兜底时必须说明，否则刚发布的新版会被旧缓存挡住，
       用户看着「发现新版本 v1.0.7」会以为就是最新的（2026-10-22 用户真踩过）。 */
    _cacheNote(r){
      if(!r) return '';
      if(r.stale) return '（注意：刚才联网失败，这是上一次检查的结果，点「检查更新」重试）';
      if(r.cached && r.checkedAt){
        const mins=Math.max(1,Math.round((Date.now()/1000-r.checkedAt)/60));
        return '（缓存：'+mins+' 分钟前检查的结果，点「检查更新」立即刷新）';
      }
      return '';
    },
    /* 未配置高德 Key 时底部红条也占 top:74px（.map-banner），两条会叠在一起。
       红条在 #map 层、更新条在 #ui 层，后者必然盖住前者，所以这里错开一行。 */
    _showUpdateBanner(){
      this.updateBannerLow=!!document.querySelector('.map-banner');
      this.updateBanner=true;
    },
    dismissUpdate(){
      this.updateBanner=false;
      try{ localStorage.setItem('fm-skip-version', (this.updateInfo&&this.updateInfo.latest)||''); }catch(e){}
      toast('已忽略该版本，下次有新版本再提醒');
    },
    setAutoUpdateCheck(v){
      this.autoUpdateCheck=!!v;
      try{ localStorage.setItem('fm-auto-update', v?'1':'0'); }catch(e){}
      toast(v?'已开启启动时检查更新':'已关闭启动时检查更新');
    },
    openReleasePage(){
      const url=(this.updateInfo&&this.updateInfo.htmlUrl)||'https://github.com/perry466/foodie-trail/releases';
      openExternalUrl(url);
    },
    /* 应用内下载走的是 release-assets.githubusercontent.com，有些网络到不了那里，
       httpx 会连接超时。给一条「复制链接」的出路：丢进浏览器或下载工具往往能成。 */
    async copyUpdateUrl(){
      const url=(this.updateInfo&&this.updateInfo.downloadUrl)||'';
      if(!url){ toast('没有可用的安装包链接，请先检查更新'); return; }
      try{
        await navigator.clipboard.writeText(url);
        toast('下载链接已复制，可用浏览器或下载工具获取');
        return;
      }catch(e){ /* 老浏览器 / 无剪贴板权限：走下面的兜底 */ }
      try{
        const ta=document.createElement('textarea');
        ta.value=url; ta.style.position='fixed'; ta.style.opacity='0';
        document.body.appendChild(ta); ta.select();
        document.execCommand('copy'); ta.remove();
        toast('下载链接已复制');
      }catch(e){
        this.showError('复制失败', '请手动复制这个地址：\n'+url);
      }
    },
    async startUpdate(){
      if(this.dl.state==='downloading'||this.dl.state==='cancelling') return;
      this.updateBusy=true; this.updateMsg='正在下载安装包…';
      try{
        this.dl=await API.sendForm('/api/update/download','POST',{});
        this._pollDownload();
      }catch(e){
        this.updateBusy=false;
        this.updateMsg='下载失败：'+e.message+'。可点「复制下载链接」用浏览器或下载工具获取';
      }
    },
    /* 取消下载：后端是协作式的（点下即把 state 切成 cancelling，
       worker 收到标志位后自己删 .part），所以这里不立刻假定成功，
       继续轮询直到看到 cancelled —— 否则按钮会先显示「已取消」再跳回「下载中」。 */
    async cancelUpdate(){
      if(this.dl.state!=='downloading') return;
      this.updateMsg='正在取消下载…';
      try{
        this.dl=await API.sendForm('/api/update/cancel','POST',{});
        this._pollDownload();
      }catch(e){
        toast('取消失败：'+(e.message||'未知原因'));
      }
    },
    _pollDownload(){
      clearInterval(this._dlTimer);
      this._dlTimer=setInterval(async()=>{
        try{
          const d=await API.get('/api/update/download');
          this.dl=d;
          if(d.state==='done'){
            clearInterval(this._dlTimer); this._dlTimer=null;
            this.updateBusy=false; this.updateMsg='下载完成，可以安装了';
          }else if(d.state==='cancelled'){
            clearInterval(this._dlTimer); this._dlTimer=null;
            this.updateBusy=false; this.updateMsg='已取消下载，没有留下半截安装包';
          }else if(d.state==='cancelling'){
            this.updateMsg='正在取消下载…';
          }else if(d.state==='error'){
            clearInterval(this._dlTimer); this._dlTimer=null;
            this.updateBusy=false;
            this.updateMsg='下载失败：'+(d.error||'未知错误')+'。可点「复制下载链接」用浏览器或下载工具获取';
          }
        }catch(e){ /* 轮询失败不打断，下一轮继续 */ }
      },800);
    },
    /* 打开设置时同步一次下载进度：设置面板关掉再打开、或者刷新过页面之后，
       前端内存里的 dl 可能还停在 idle，那样就没有「取消下载」按钮可点。 */
    async _syncDownload(){
      try{
        const d=await API.get('/api/update/download');
        if(!d||!d.state) return;
        this.dl=d;
        if(d.state==='downloading'){ this.updateBusy=true; this._pollDownload(); }
        else if(d.state==='cancelling'||d.state==='verifying'){ this._pollDownload(); }
      }catch(e){ /* 同步失败不影响其它功能，静默 */ }
    },
    async installOrDownload(){
      if(this.dl.state==='done'){ this.doInstall(); return; }
      await this.startUpdate();
    },
    /* 自动安装的兜底出口：打开下载目录，用户自己双击安装包。
       v1.0.2–v1.0.7 因为 cmd 链转义 bug 全都装不上，当时没有任何手动出口。 */
    async revealDownload(){
      try{
        await API.sendForm('/api/update/reveal','POST',{});
      }catch(e){
        toast('打开文件夹失败：'+(e.message||'未知原因'));
      }
    },
    /* 点「立即安装并重启」之后的三段式流程：
       ① closing    —— 调 /api/update/install，旧进程 1.2 秒后退出
       ② installing —— 接口开始连不上，说明旧进程已死、安装器在跑
       ③ done        —— 接口又通了，说明新版本已经起来；同端口下直接 reload 复用本标签页
       旧版（1.0.x）在这里只改一行文字，用户看着一个半死的界面，不知道到底装没装。 */
    async doInstall(){
      const ok=await this.askConfirm({
        title:'立即升级？',
        message:'程序会退出并启动安装程序，装完自动重新打开。data 目录（记录、照片、密钥）不会被删除。',
        ok:'开始升级',
      });
      if(!ok) return;
      this.installTarget=(this.updateInfo&&this.updateInfo.latest)||'';
      // 先把「正在更新到哪个版本」落盘：新标签页起来时靠它判断要不要显示「已更新」
      try{ localStorage.setItem('fm-updating', this.installTarget||'1'); }catch(e){}
      // 关掉原来的界面：设置面板、提示条、更多菜单全收起来，只留安装进度卡
      this.settingsOpen=false; this.moreOpen=false; this.updateBanner=false;
      this.installOpen=true; this.installError=''; this.installCountdown=0; this.installDead=false;
      this.updateBusy=true;
      this._setInstallPhase('closing');
      this._startInstallTicker();
      try{
        const r=await API.sendForm('/api/update/install','POST',{});
        if(r&&r.version) this.installTarget=r.version;
        this._setInstallPhase('installing');
      }catch(e){
        // 进程正在退出，fetch 可能先断——这不是失败，继续按「安装中」观察
        if(/Failed to fetch|NetworkError|load failed|aborted|network/i.test(e.message||'')){
          this._setInstallPhase('installing');
        }else{
          this._setInstallPhase('timeout', '启动安装程序失败：'+(e.message||'未知原因'));
          this._stopInstallWatchers();
          return;
        }
      }
      this._watchRestart();
    },
    _setInstallPhase(p, msg){
      this.installPhase=p;
      if(msg!==undefined) this.installError=msg;
      if(p==='closing'&&this.installPercent<6) this.installPercent=6;
      if(p==='installing'&&this.installPercent<14) this.installPercent=14;
      if(p==='done'){ this.installPercent=100; this.updateBusy=false; }
      // 服务已经没了的时候，「打开安装包位置」这个接口也调不通，别给它留按钮
      if(p==='timeout') this.installDead=!!this._installSeenDeath;
    },
    /* 进度条靠两条信息拼出来：前端能确定的「阶段」+ 对服务存活状态的探测。
       不假装知道安装器的真实百分比——Inno 静默模式没有可读进度，编一个精确
       数字反而会在 99% 卡住，比不确定更难受。 */
    _startInstallTicker(){
      clearInterval(this._installTimer);
      this._installTimer=setInterval(()=>{
        if(!this.installOpen) return;
        // 上限按阶段递进：安装中最多走到 88%，剩下的留到「检测到新版本」那一下
        const cap = this.installPhase==='installing' ? 88
                  : this.installPhase==='closing' ? 12
                  : this.installPhase==='done' ? 100 : this.installPercent;
        if(this.installPercent<cap){
          // 0.03 是「每 450ms 吃掉剩余距离的 3%」：约 10 秒到 30%，20 秒到 70%，
          // 真装完再跳到 100%。比线性好——不会在前 5 秒就冲到 90% 然后干等。
          const step=this.installPhase==='installing'
            ? Math.max(0.3, (cap-this.installPercent)*0.03)
            : 3;
          this.installPercent=Math.min(cap, +(this.installPercent+step).toFixed(1));
        }
      },450);
    },
    _stopInstallWatchers(){
      clearInterval(this._watchTimer); this._watchTimer=null;
      clearInterval(this._installTimer); this._installTimer=null;
      clearTimeout(this._reloadTimer); this._reloadTimer=null;
    },
    /* 每 900ms 探一次 /api/app/version：
       失败 = 旧进程已退出（进入安装中）；再次成功 = 新版本起来了（进入完成）。
       全程 150 秒上限，超时给手动出口，绝不让用户对着一个永远转圈的界面。 */
    _watchRestart(){
      clearInterval(this._watchTimer);
      const t0=Date.now(); this._installT0=t0; this._installSeenDeath=false;
      this._watchTimer=setInterval(async()=>{
        if(!this.installOpen){ clearInterval(this._watchTimer); this._watchTimer=null; return; }
        if(Date.now()-t0>150000){
          this._setInstallPhase('timeout','等了 2 分半还没检测到新版本启动。可点「打开安装包位置」手动装一次。');
          this._stopInstallWatchers();
          return;
        }
        try{
          const r=await API.get('/api/app/version');
          if(this._installSeenDeath && r && r.version){
            clearInterval(this._watchTimer); this._watchTimer=null;
            this._finishInstall(r.version);
          }
        }catch(e){
          // 连不上 = 旧进程已经退出，安装器正在跑
          if(!this._installSeenDeath){
            this._installSeenDeath=true;
            this._setInstallPhase('installing');
          }
        }
      },900);
    },
    _finishInstall(version){
      this.appVersion=version||this.installTarget||this.appVersion;
      try{ localStorage.setItem('fm-updating', this.installTarget||this.appVersion||'1'); }catch(e){}
      this._setInstallPhase('done');
      clearInterval(this._installTimer); this._installTimer=null;
      // 倒计时 3 秒后自动 reload：同端口下本标签页直接变成新版界面，
      // 用户即使关掉启动器新开的标签页也不会停在一个过期的遮罩上。
      this.installCountdown=3;
      clearInterval(this._reloadTimer);
      this._reloadTimer=setInterval(()=>{
        this.installCountdown-=1;
        if(this.installCountdown<=0){ this._stopInstallWatchers(); this.reloadApp(); }
      },1000);
    },
    reloadApp(){
      this._stopInstallWatchers();
      try{ location.reload(); }catch(e){ /* 极端情况下 reload 被拦，用户还能手动刷新 */ }
    },
    /* 安装没成功、但服务还活着（比如 409/500）：必须留一条退回应用的路，
       否则用户被一张报错卡片钉死在界面上，只能手动刷新。 */
    closeInstall(){
      this._stopInstallWatchers();
      this.installOpen=false; this.updateBusy=false;
      this._syncDownload();
    },
    _initUpdate(){
      // 安卓版由 APK 安装包更新，不查 GitHub、也不显示 Windows 的更新入口
      if(this.appMode==='android') return;
      try{ this.autoUpdateCheck=localStorage.getItem('fm-auto-update')!=='0'; }catch(e){ this.autoUpdateCheck=true; }
      if(!this.autoUpdateCheck) return;
      let skip='';
      try{ skip=localStorage.getItem('fm-skip-version')||''; }catch(e){}
      // 延迟 2 秒：先让地图和清单把首屏请求跑完，不跟启动抢带宽
      setTimeout(async()=>{
        if(this.appMode==='android') return;
        await this.checkUpdate(false);
        const info=this.updateInfo||{};
        if(info.ok && info.hasUpdate && info.latest && info.latest!==skip) this._showUpdateBanner();
      },2000);
    },
    maskKey(k){ if(!k) return ''; return '••••••'+k.slice(-4); },
    async saveKey(){
      let key=this.settings.key.trim(); let sec=this.settings.security.trim(); const web=this.settings.webKey.trim();
      if(this.mapConfig.configured && key===this.maskKey(this.settings.realKey)) key=this.settings.realKey;
      if(this.mapConfig.security && sec===this.maskKey(this.mapConfig.security)) sec=this.mapConfig.security;
      if(!key){ toast('请输入 JS API Key'); return; }
      // security 留空表示"保持原值"，后端不再删除已有安全密钥；清除走单独的明确操作
      const body={key,security:sec||null};
      if(web) body.web_key=web;
      try{
        await API.sendForm('/api/settings/amap','PUT',body);
        toast('已保存，正在重新加载地图');
        // 换 Key 必须重建高德脚本与地图实例，整页刷新最干净（MapView.init 只清实例，清不掉已加载的 AMap）
        setTimeout(()=>location.reload(), 500);
      }
      catch(e){ toast('保存失败：'+e.message); }
    },
    async testConn(){
      try{ const r=await API.sendForm('/api/settings/test-connection','POST',{}); this.settings.connMsg=r.ok?'✅ '+r.msg:'❌ '+r.msg; }
      catch(e){ this.settings.connMsg='❌ '+e.message; }
    },
    async clearKey(){
      const ok=await this.askConfirm({
        title:'清除全部高德 Key？',
        message:'JS API Key、安全密钥与 Web 服务 Key 都会被删除，地图与地址搜索随即不可用，需要重新填写。',
        ok:'全部清除', danger:true,
      });
      if(!ok) return;
      try{ await API.del('/api/settings/amap'); toast('已清除，正在重新加载地图'); setTimeout(()=>location.reload(), 500); }
      catch(e){ toast('清除失败：'+e.message); }
    },
    async clearSecurity(){
      const ok=await this.askConfirm({
        title:'清除安全密钥？',
        message:'只删除 securityJsCode，JS API Key 与 Web 服务 Key 保持不变。',
        ok:'清除安全密钥', danger:true,
      });
      if(!ok) return;
      try{ await API.del('/api/settings/amap/security'); toast('已清除安全密钥，正在重新加载地图'); setTimeout(()=>location.reload(), 500); }
      catch(e){ toast('清除失败：'+e.message); }
    },

    /* 表单 */
    /* 添加表单草稿：不小心关掉弹窗后，已填内容不丢（localStorage，仅本机） */
    scheduleDraft(){ clearTimeout(this._draftT); this._draftT=setTimeout(()=>this._saveDraft(),400); },
    _hasDraftContent(){
      const f=this.form;
      return !!(f.name.trim()||f.address.trim()||f.note.trim()||f.lat!=null||this.formTags.length);
    },
    _saveDraft(){
      if(this._suppressDraft || this.form.id) return;   // 编辑既有记录不存草稿
      if(!this._hasDraftContent()){ this.clearDraft(); return; }
      try{
        localStorage.setItem(DRAFT_KEY, JSON.stringify({
          form:{...this.form}, tags:[...this.formTags], hours:this.hours,
          locName:this.locName, locCoord:this.locCoord, photoCount:this.formNewPhotos.length, savedAt:Date.now(),
        }));
        this.draftSaved=true;
      }catch{}
    },
    _restoreDraft(){
      let d=null;
      try{ d=JSON.parse(localStorage.getItem(DRAFT_KEY)||'null'); }catch{}
      if(!d||!d.form) return false;
      const f=d.form;
      const has=(f.name&&f.name.trim())||(f.address&&f.address.trim())||(f.note&&f.note.trim())||f.lat!=null||(d.tags&&d.tags.length);
      if(!has) return false;
      this.form={...this.form,...f,id:null};
      this.formTags=[...(d.tags||[])];
      this.hours=d.hours||parseHours(null);
      this.locName=d.locName||'';
      this.locCoord=d.locCoord||'';
      this.draftNotice='已恢复上次未保存的内容';
      if(d.photoCount) this.draftNotice+=`，其中 ${d.photoCount} 张照片需重新选择`;
      this.draftSaved=true;
      return true;
    },
    clearDraft(){
      try{ localStorage.removeItem(DRAFT_KEY); }catch{}
      this.draftSaved=false; this.draftNotice='';
    },
    resetFormDraft(){
      this.clearDraft();
      this.form={ id:null, name:'', rating:3, price:'', checkin:'', note:'', draft:false, lat:null, lng:null, address:'' };
      this.releaseAllPhotoURLs();      // 恢复过的草稿可能带新选照片，清空时要一起回收
      this.formTags=[]; this.formPhotos=[]; this.formNewPhotos=[]; this.formRemoved=[];
      this.hours=parseHours(null); this.locName=''; this.locCoord=''; this.formMsg=''; this.tagInput='';
      this.$nextTick(()=>this.renderHoursEditor());
    },
    openForm(rec){ this.moreOpen=false; this.filterOpen=false;
      this.releaseAllPhotoURLs();      // 上一次没关干净时，先回收 Object URL
      this.pickMode=false; this.pickCb=null; this.pickingMap=false;   // 清掉可能残留的选点态
      this._suppressDraft=true;          // 初始化字段期间不要覆盖已有草稿
      this.formMore=!!rec;               // 新建时只露必填三项，补充信息折叠
      this.formErr={ name:'', loc:'' };
      this.form.id=rec?rec.id:null;
      this.form.name=rec?rec.name:'';
      this.form.rating=rec?rec.rating:3;
      this.form.price=rec&&rec.avgPrice!=null?rec.avgPrice:'';
      this.form.checkin=rec?(rec.checkinStatus||''):'';
      this.form.note=rec?(rec.note||''):'';
      this.form.draft=rec?!!rec.draft:false;
      this.form.lat=rec?rec.lat:null;
      this.form.lng=rec?rec.lng:null;
      this.form.address='';
      this.formTags=rec?[...(rec.tags||[])]:[];
      this.formPhotos=rec?(rec.photos||[]).map(p=>({id:p.id,url:photoPath(p.id)})):[];
      this.formNewPhotos=[]; this.formRemoved=[];
      this.hours=parseHours(rec?rec.businessHours:null);
      this.locName=rec?(rec.name||'已选点'):'';
      this.locCoord=rec?`${rec.lat.toFixed(4)}, ${rec.lng.toFixed(4)}`:'';
      this._resetPOI();
      this.formMsg=''; this.tagInput='';
      this.draftNotice=''; this.draftSaved=false;
      if(!rec) this._restoreDraft();     // 新建时自动恢复未提交的草稿
      this.formOpen=true;
      this.$nextTick(()=>{ this.renderHoursEditor(); this._suppressDraft=false; });
    },
    toggleFormMore(){
      this.formMore=!this.formMore;
      // 营业时间编辑器是手动渲染的，展开后要补一次
      if(this.formMore) this.$nextTick(()=>this.renderHoursEditor());
    },
    /* 右键/长按地图：带上坐标进入新增，填个店名就能存 */
    onMapLongPress(lng,lat){
      if(this.formOpen || this.pickMode) return;
      this.openForm(null);
      this.form.lng=lng; this.form.lat=lat;
      this.locName='地图选点';
      this.locCoord=`${lat.toFixed(4)}, ${lng.toFixed(4)}`;
      this.formErr.loc='';
      try{ MapView.tempMarker(lng,lat); }catch(e){}
      toast('已带上位置，填个店名就能保存');
    },
    addTag(){
      const v=this.tagInput.trim();
      if(!v){ this.tagInput=''; return; }
      // 与后端 validate.normalize_tags 的上限保持一致（MAX_TAG_LEN=24 / MAX_TAGS=32）。
      // 后端超限是静默丢弃（导入老备份时要兼容），所以前端必须先把住——
      // 否则用户输完标签、保存后又消失，会以为程序吃掉了数据。
      if(v.length>24){ toast('标签最多 24 个字'); return; }
      if(this.formTags.length>=32 && !this.formTags.includes(v)){ toast('最多 32 个标签'); return; }
      if(!this.formTags.includes(v)) this.formTags.push(v);
      this.tagInput='';
    },
    removeTag(i){ this.formTags.splice(i,1); },
    pickPhotos(e){ for(const f of e.target.files){ if(this.formPhotos.length+this.formNewPhotos.length<9) this.formNewPhotos.push(f); } e.target.value=''; },
    removePhoto(i,isNew){
      if(isNew){ this.releasePhotoURL(this.formNewPhotos[i]); this.formNewPhotos.splice(i,1); }
      else { this.formRemoved.push(this.formPhotos[i].id); this.formPhotos.splice(i,1); }
    },
    pickOnMap(){
      // 进入选点态：表单不销毁，只收起成一条提示条（遮罩透明可穿透），
      // 这样用户始终知道"还在添加流程里"，也不会因为地图操作异常而丢掉整张表单。
      // 提示由 pick-bar 承担，不再弹 toast（toast 也在底部，会盖住提示条的取消按钮）。
      // 清单会被收起：点选需要尽量大的地图可视区。
      this.panel='none'; this.filterOpen=false;
      this.pickMode=true; this.pickingMap=true;
      this.pickCb=(lng,lat)=>{
        // 顺序很关键：先恢复表单状态，再动地图。地图调用即使失败也不影响表单。
        this.pickMode=false; this.pickCb=null; this.pickingMap=false;
        this.form.lng=lng; this.form.lat=lat;
        this.locName='地图选点';
        this.locCoord=`${lat.toFixed(4)}, ${lng.toFixed(4)}`;
        this._pickedAt=Date.now();          // 供遮罩误触保护使用
        try{ MapView.tempMarker(lng,lat); }catch(e){ console.warn('标注选点失败', e); }
        this.$nextTick(()=>this.renderHoursEditor());
      };
    },
    cancelPick(){ this.pickMode=false; this.pickCb=null; this.pickingMap=false; },
    /* 关闭表单（按钮/取消/稍后再填）统一走这里，确保退出选点态 */
    closeForm(){ if(this.pickingMap) this.cancelPick(); this.formOpen=false; this.releaseAllPhotoURLs(); },
    /* 点遮罩关闭：选点态下不关；刚选完点的 500ms 内忽略（防误触、防双击）
       另外本方法也可以关闭编辑/新增表单以外的模态，由调用处决定 */
    backdropClose(){
      if(this.pickingMap) return;
      if(Date.now()-(this._pickedAt||0) < 500) return;
      this.formOpen=false;
      this.releaseAllPhotoURLs();
    },
    async locateMe(){
      if(!navigator.geolocation){ toast('浏览器不支持定位'); return; }
      navigator.geolocation.getCurrentPosition(async pos=>{
        // 回调是 async：不加 try 的话坐标转换失败会变成未处理的 Promise 异常，
        // 界面毫无反应，用户只看到「点了没动静」
        try{
          const {longitude:lng,latitude:lat}=pos.coords;
          const gc=await API.sendForm('/api/coords/convert','POST',{lng,lat});
          this.form.lng=gc.lng; this.form.lat=gc.lat;
          this.locName='当前位置';
          this.locCoord=`${gc.lat.toFixed(4)}, ${gc.lng.toFixed(4)}`;
          MapView.tempMarker(gc.lng,gc.lat);
        }catch(e){
          toast('定位转换失败：'+(e.message||'网络异常')+'，请手动选点');
        }
      },()=>toast('定位被拒，请手动选点'),{enableHighAccuracy:true,timeout:8000});
    },
    /* ---------- 位置搜索：输入即联想，不需要按回车 ---------- */
    _resetPOI(){
      clearTimeout(this._poiT);
      this._poiSeq=(this._poiSeq||0)+1;      // 让在途请求作废，避免旧结果盖掉新结果
      this.poiList=[]; this.poiOpen=false; this.poiLoading=false;
      this.poiActive=-1; this.poiMsg=''; this.poiNeedKey=false;
    },
    _addrBlockReason(){
      // 搜索走后端代理，只依赖「Web 服务」Key；与前端地图用哪种底图无关，
      // 所以这里不检查 mapConfig.configured，否则只配了 Web 服务 Key 时会被误拦。
      if(!this.mapConfig.webConfigured) return '搜索地点需要「Web 服务」类型的 Key（与地图 Key 不是同一个）。';
      return '';
    },
    onAddressFocus(){
      if(this.form.address.trim().length>=2 && (this.poiList.length||this.poiMsg)){
        this.poiOpen=true; this._revealPOI();
      }
    },
    /* 联想面板长在表单滚动区里，展开后若被底部工具栏挡住就点不到。
       这里只做「最小必要滚动」：优先让面板露出来，但不能把输入框顶出可视区。 */
    _revealPOI(){
      this.$nextTick(()=>{
        const body=document.querySelector('.modal-body');
        const box=document.querySelector('.addr-box');
        const panel=$('#poiPanel');
        if(!body||!box||!panel) return;
        const br=body.getBoundingClientRect(), pr=panel.getBoundingClientRect();
        const overflow=pr.bottom-br.bottom;              // 面板底部越界多少
        if(overflow<=2) return;
        const room=box.getBoundingClientRect().top-br.top;  // 输入框上方还有多少可牺牲
        body.scrollTop += Math.min(overflow, Math.max(0, room-8));
      });
    },
    onAddressInput(){
      const kw=this.form.address.trim();
      this.poiMsg=''; this.poiNeedKey=false;
      if(!kw){ this._resetPOI(); return; }
      const why=this._addrBlockReason();
      if(why){ this.poiList=[]; this.poiLoading=false; this.poiMsg=why; this.poiNeedKey=true; this.poiOpen=true; this._revealPOI(); return; }
      if(kw.length<2){ this._resetPOI(); return; }   // 单个字的噪音太大，从第 2 个字开始联想
      clearTimeout(this._poiT);
      this.poiLoading=true; this.poiOpen=true;
      this._poiT=setTimeout(()=>this.fetchPOI(kw), 200);
    },
    async fetchPOI(kw){
      const seq=++this._poiSeq;
      try{
        const near=(this.form.lng!=null&&this.form.lat!=null)?`&location=${this.form.lng},${this.form.lat}`:'';
        const data=await API.get('/api/amap/poi?keywords='+encodeURIComponent(kw)+near);
        if(seq!==this._poiSeq) return;              // 用户又输入了，丢弃这个过期响应
        this.poiList=data.tips||[];
        this.poiActive=this.poiList.length?0:-1;
        if(!this.poiList.length) this.poiMsg=`没有找到「${kw}」，换个说法或直接在地图上点选。`;
        this._revealPOI();
      }catch(e){
        if(seq!==this._poiSeq) return;
        this.poiList=[]; this.poiMsg=e.message; this.poiNeedKey=/Key/i.test(e.message);
        this._revealPOI();
      }finally{
        if(seq===this._poiSeq) this.poiLoading=false;
      }
    },
    onAddrKey(e){
      if(e.key==='ArrowDown'||e.key==='ArrowUp'){
        if(!this.poiOpen||!this.poiList.length) return;
        e.preventDefault();
        const n=this.poiList.length;
        this.poiActive=e.key==='ArrowDown' ? (this.poiActive+1)%n : (this.poiActive-1+n)%n;
        this.$nextTick(()=>this._scrollPOIActive());
        return;
      }
      if(e.key==='Enter'){
        e.preventDefault();
        if(this.poiOpen && this.poiList.length) this.pickPOI(this.poiActive<0?0:this.poiActive);
        else if(this.form.address.trim()) this.geocode();   // 没有联想项时，回车退回地理编码
        return;
      }
      if(e.key==='Escape' && this.poiOpen){ e.stopPropagation(); this.poiOpen=false; }
    },
    _scrollPOIActive(){
      const box=$('#poiPanel'); if(!box) return;
      const el=box.querySelector('.poi-row.active'); if(!el) return;
      if(el.offsetTop<box.scrollTop) box.scrollTop=el.offsetTop;
      else if(el.offsetTop+el.offsetHeight>box.scrollTop+box.clientHeight)
        box.scrollTop=el.offsetTop+el.offsetHeight-box.clientHeight;
    },
    /* 高亮匹配到的关键词（先转义再包 <em>，避免 XSS） */
    hl(s){
      const safe=esc(s||''); const kw=(this.form.address||'').trim();
      if(!kw) return safe;
      const pat=esc(kw).replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
      try{ return safe.replace(new RegExp(pat,'gi'), m=>`<em class="poi-hl">${m}</em>`); }catch{ return safe; }
    },
    poiSub(t){ return [t.district,t.address].filter(Boolean).join(' · '); },
    pickPOI(i){
      const t=this.poiList[i]; if(!t) return;
      this.form.lng=t.lng; this.form.lat=t.lat;
      this.form.address=t.name;
      this.locName=t.name;
      this.locCoord=`${t.lat.toFixed(4)}, ${t.lng.toFixed(4)}`;
      this._resetPOI();                          // 收起面板并作废在途请求
      try{ MapView.tempMarker(t.lng,t.lat); }catch(e){ console.warn('选点标注失败', e); }
      toast('已选：'+t.name);
    },
    clearAddress(){ this.form.address=''; this._resetPOI(); },
    /* 撤销已选位置（与"清空搜索词"分开：清词不清点，清点才清坐标） */
    clearLocation(){
      this.form.lat=null; this.form.lng=null;
      this.locName=''; this.locCoord='';
      this.clearAddress();
    },
    /* 兜底：回车但无联想结果时做地址解析 */
    async geocode(){
      const addr=this.form.address.trim(); if(!addr) return;
      const why=this._addrBlockReason();
      if(why){ this.poiMsg=why; this.poiNeedKey=true; this.poiOpen=true; return; }
      this.poiLoading=true;
      try{
        const data=await API.get('/api/amap/geocode?address='+encodeURIComponent(addr));
        const g=(data.geocodes||[])[0];
        if(!g){ this.poiMsg='没有解析出这个地址，换个写法或直接在地图上点选。'; this.poiOpen=true; return; }
        this.form.lng=g.lng; this.form.lat=g.lat;
        this.locName=g.formatted_address;
        this.locCoord=`${g.lat.toFixed(4)}, ${g.lng.toFixed(4)}`;
        this.poiOpen=false; this.poiList=[]; this.poiMsg='';
        try{ MapView.tempMarker(g.lng,g.lat); }catch(e){ console.warn('选点标注失败', e); }
        toast('已定位：'+g.formatted_address);
      }catch(e){
        this.poiMsg=e.message; this.poiNeedKey=/Key/i.test(e.message); this.poiOpen=true;
      }finally{ this.poiLoading=false; }
    },
    renderHoursEditor(){
      const box=$('#hoursEditor'); if(!box) return;
      box.innerHTML='';
      WEEKDAYS.forEach(([k,label])=>{
        const day=document.createElement('div'); day.className='day-row'; day.dataset.day=k;
        const lb=document.createElement('span'); lb.className='day-label'; lb.textContent=label; day.appendChild(lb);
        const slots=document.createElement('div'); slots.className='day-slots';
        if(!(this.hours[k]||[]).length){ const rest=document.createElement('span'); rest.className='day-rest'; rest.textContent='休息'; slots.appendChild(rest); }
        (this.hours[k]||[]).forEach((sl,idx)=>{
          const sr=document.createElement('span'); sr.className='slot-row';
          sr.innerHTML=`<input type="time" value="${sl.s}"><em>至</em><input type="time" value="${sl.e}"><button type="button" class="slot-del" aria-label="删除该时段" title="删除该时段">✕</button>`;
          const ins=sr.querySelectorAll('input');
          ins[0].onchange=()=>{ this.hours[k][idx].s=normTime(ins[0].value); };
          ins[1].onchange=()=>{ this.hours[k][idx].e=normTime(ins[1].value); };
          sr.querySelector('.slot-del').onclick=()=>{ this.hours[k].splice(idx,1); this.renderHoursEditor(); };
          slots.appendChild(sr);
        });
        day.appendChild(slots);
        const add=document.createElement('button'); add.type='button'; add.className='slot-add'; add.textContent='+ 时段'; add.title='添加营业时段';
        add.onclick=()=>{ this.hours[k]=(this.hours[k]||[]); this.hours[k].push({s:'09:00',e:'22:00'}); this.renderHoursEditor(); };
        day.appendChild(add);
        box.appendChild(day);
      });
    },
    async saveForm(){
      if(this.saving) return;                     // 防重复提交：连点两次不会再建一条重复记录
      this.formErr={ name:'', loc:'' };
      const name=this.form.name.trim();
      if(!name){ this.formErr.name='给这家店起个名字'; this.formMsg=''; return; }
      if((this.formPhotos.length+this.formNewPhotos.length)>9){ this.formMsg='照片最多 9 张'; return; }
      // 坐标允许为 0：不能用 !lat||!lng（经度/纬度 0 是合法位置，会被误判成"没选点"）
      const hasLoc=Number.isFinite(+this.form.lat) && Number.isFinite(+this.form.lng)
                   && this.form.lat!=null && this.form.lng!=null;
      if(!hasLoc){ this.formErr.loc='先选个位置：地图点选或搜索地点'; this.formMsg=''; return; }
      const body={
        name, rating:this.form.rating, lng:this.form.lng, lat:this.form.lat,
        tags:this.formTags, businessHours:serializeHours(this.hours),
        // 0 元是有效价格（免费），不能用 truthy 判断，否则会被当成「没填」存成 null
        avgPrice:(this.form.price===''||this.form.price==null)?null:+this.form.price,
        checkinStatus:this.form.checkin||null, note:this.form.note.trim()||null, draft:this.form.draft,
      };
      this.saving=true;
      this.formMsg='';
      try{
        let rec;
        if(this.form.id) rec=await API.sendForm(recPath(this.form.id),'PUT',body);
        else{
          rec=await API.sendForm('/api/records','POST',body);
          // 立刻回填 id：记录已落库，之后任何重试都会走更新而不是新建，
          // 避免"照片上传失败→用户再点保存→产生重复记录"
          this.form.id=rec.id;
        }
        // 顺序很重要：**先删后加**。
        // 库里已有 9 张（上限）时，先上传会被"最多 9 张"直接 400 拒绝，
        // 「删 1 张加 1 张」就得点两次保存才成功（第一次还提示上传失败）。
        // 删除只动本机文件、几乎不会失败；上传才可能因图片本身失败，把风险大的放后面。
        const delFailed=[];
        for(const pid of this.formRemoved){
          try{ await API.del(photoPath(pid)); }
          catch(e){ delFailed.push(pid); }   // 删除失败要保留，否则照片仍留在库里、下次打开又冒出来
        }
        this.formRemoved=delFailed;
        // 照片逐张上传，失败的不丢弃，留在列表里等用户重试
        const failed=[];
        for(const f of this.formNewPhotos){
          try{ await API.upload(recPath(rec.id)+'/photos',f); }
          catch(e){ failed.push(f); }
        }
        this.formNewPhotos=failed;
        if(failed.length||delFailed.length){
          const parts=[];
          if(failed.length) parts.push(`${failed.length} 张照片上传失败`);
          if(delFailed.length) parts.push(`${delFailed.length} 张照片删除失败`);
          this.formMsg=`记录已保存，但有 ${parts.join('、')}，可再点保存重试`;
          await this.loadRecords();
          return;                                   // 保留表单与未完成项，便于重试
        }
        toast('已保存', { label:'再记一家', fn:()=>this.openForm(null) });
        this.clearDraft(); this.formOpen=false; this.releaseAllPhotoURLs(); await this.loadRecords();
        if(this.detailOpen && this.detail && this.detail.id===rec.id) this.detail=rec;
      }catch(e){ this.formMsg='保存失败：'+e.message; }
      finally{ this.saving=false; }
    },

    /* 导入 / 导出 */
    openImport(){
      this.moreOpen=false; this.importPreview=''; this.importReady=false; this.importFile=null;
      this.importBusy=false; this.importPercent=0; this.importText='';
      this.importOpen=true;
    },
    async onImportFile(e){
      const file=e.target.files[0]; if(!file) return;
      this.importBusy=true; this.importIndet=true; this.importPercent=0;
      this.importText='正在上传备份文件…';
      this.importPreview=''; this.importReady=false; this.importFile=null;
      try{
        const j=await streamUpload('/api/import', file);
        this.importIndet=false; this.importText='解析完成，确认后开始写入';
        this.importFile=file;
        const bad=(j.invalidDetails&&j.invalidDetails.length)?`；无效 ${j.invalid} 条`:'';
        this.importPreview=`预览：新增 ${j.append}，更新 ${j.update}，无效 ${j.invalid}${bad}`;
        this.importReady=true;
      }catch(err){
        this.importIndet=false; this.importText='';
        this.importPreview='❌ '+err.message;
      }finally{
        this.importBusy=false;
      }
    },
    async doImport(){
      if(!this.importFile || this.importBusy) return;
      this.importBusy=true; this.importIndet=true; this.importPercent=0;
      this.importText='正在上传备份文件…';
      try{
        const j=await streamUpload('/api/import?confirm=true&progress=1', this.importFile, {
          onEvent:(ev)=>{
            if(ev.type==='start'){
              this.importIndet=false; this.importPercent=60;
              this.importText=`开始写入 ${ev.total} 条…`;
            }else if(ev.type==='progress'){
              this.importPercent=60+Math.round(ev.done/Math.max(1,ev.total)*40);
              this.importText=`写入 ${ev.done} / ${ev.total} 条`;
            }
          },
        });
        this.importIndet=false; this.importPercent=100;
        const skipped=j.photosSkipped?`，跳过异常照片 ${j.photosSkipped} 张`:'';
        const kept=j.photosKept?`，${j.photosKept} 条记录保留了原有照片`:'';
        const renamed=j.idsRenamed?`，${j.idsRenamed} 条 id 含非法字符已重建`:'';
        // 「写入 0 条」单独出现会被当成失败：把按时间戳跳过（已是最新）的条数说清楚
        const same=j.unchanged?`，${j.unchanged} 条已是最新未覆盖`:'';
        this.importText=`完成：写入 ${j.written} 条${same}${j.failed?`，失败 ${j.failed}`:''}${j.invalid?`，无效 ${j.invalid}`:''}${skipped}${kept}${renamed}`;
        toast(`导入完成：写入 ${j.written}${same}${j.invalid?`，无效 ${j.invalid}`:''}${skipped}${kept}${renamed}`);
        this.importOpen=false; this.importFile=null;
        await this.loadRecords();
      }catch(e){
        this.importIndet=false;
        this.importText='导入失败：'+e.message;
        this.importPreview='❌ '+e.message;
      }finally{
        this.importBusy=false;
      }
    },
    doExport(){
      this.moreOpen=false;
      // 备份始终包含草稿：草稿同样是用户数据，静默遗漏会让恢复后的数据不完整
      window.location.href=`/api/export?mode=full&includeDrafts=1&${this._filterQuery(false)}`;
    },

    /* Android 实体返回键：按「最上层浮层先关」的顺序退，全部关完返回 false 让原生退出。
       与键盘 Escape 的行为保持一致，但不把浏览器历史当成浮层栈。 */
    handleBack(){
      const lb=$('#lightbox');
      if(lb && !lb.classList.contains('hidden')){ closeLightbox(); return true; }
      if(this.searchOpen){ this.closeMobileSearch(); return true; }
      if(this.confirmBox.open){ this.closeConfirm(false); return true; }
      if(this.pickingMap){ this.cancelPick(); return true; }
      if(this.selectMode){ this.exitSelect(); return true; }
      if(this.filterOpen){ this.filterOpen=false; return true; }
      if(this.detailOpen){ this.closeDetail(); this._syncURL(); return true; }
      if(this.moreOpen){ this.moreOpen=false; return true; }
      if(this.settingsOpen||this.formOpen||this.dashOpen||this.importOpen){
        this.settingsOpen=this.formOpen=this.dashOpen=this.importOpen=false;
        this._syncURL();
        return true;
      }
      if(this.panel!=='none'){ this.panel='none'; this._syncURL(); return true; }
      return false;
    },

    /* lightbox 桥接 */
    openLightbox(photos,i){ openLightbox(photos,i); },
  },
  created(){
    /* File -> ObjectURL 缓存。模板每次重渲染都会调 photoURL(f)，
       每次都 createObjectURL 会持续泄漏（且 <img> 反复重新加载）。
       放在 created 里而不是 data()：Map 不需要响应式，Vue 代理只会增加开销。 */
    this._photoURLs=new Map();
  },
  mounted(){
    const t=localStorage.getItem('fm-theme'); if(t) document.documentElement.setAttribute('data-theme',t);
    this.themeName = t==='dark' ? '深色' : '浅色';
    document.body.classList.toggle('fm-list-open', this.panel==='list');
    this._readURL();   // 支持 ?view=list&rating=4&tags=火锅 这样的深链接
    if(localStorage.getItem('fm-show-markers')==='0') this.showMarkers=false;
    bindLightbox();
    /* 供 Android 壳的返回键调用；返回 true 表示这次返回被页面消费 */
    window.__fmBack = () => this.handleBack();
    // 全局快捷键 & 点击外部关闭浮层
    document.addEventListener('keydown',e=>{
      if(/INPUT|TEXTAREA|SELECT/.test(e.target.tagName)) return;
      // 安装遮罩期间屏蔽所有快捷键：这时后端已经没了，任何操作都只会报错
      if(this.installOpen) return;
      if($('#lightbox') && !$('#lightbox').classList.contains('hidden')){
        if(e.key==='Escape') closeLightbox();
        else if(e.key==='ArrowLeft') lbNav(-1);
        else if(e.key==='ArrowRight') lbNav(1);
        return;
      }
      const modalOpen=this.formOpen||this.settingsOpen||this.dashOpen||this.importOpen||this.confirmBox.open;
      if(this.searchOpen && e.key==='Escape'){ this.closeMobileSearch(); return; }
      if(!modalOpen && this.panel==='list' && (e.key==='ArrowDown'||e.key==='ArrowUp')){
        e.preventDefault(); this._moveActive(e.key==='ArrowDown'?1:-1); return;
      }
      if(!modalOpen && e.key==='Enter' && this.panel==='list' && this.activeIdx>=0){
        e.preventDefault(); this._openActive(); return;
      }
      if(e.key==='n'||e.key==='N'){ if(!modalOpen) this.openForm(null); }
      else if(e.key==='/'){ e.preventDefault(); const el=$('.tb-search input'); if(el) el.focus(); }
      else if((e.key==='f'||e.key==='F') && !modalOpen){
        if(this.panel!=='list') this.openList();
        this.$nextTick(()=>{ if(!this.filterOpen) this.toggleFilter(); });
      }
      else if(e.key==='Escape'){
        if(this.confirmBox.open){ this.closeConfirm(false); return; }
        if(this.pickingMap){ this.cancelPick(); return; }
        if(this.selectMode){ this.exitSelect(); return; }
        if(this.filterOpen){ this.filterOpen=false; return; }
        if(this.detailOpen){ this.closeDetail(); this._syncURL(); return; }
        this.panel='none'; this.moreOpen=false;
        this.settingsOpen=this.formOpen=this.dashOpen=this.importOpen=false;
        this._syncURL();          // 否则地址栏还留着 ?view=list，刷新后又跳回清单
      }
    });
    /* 空白点击：任何不在交互容器里的点击都算「点空白」。
       用 pointerdown 的位置/时间判断，拖动地图、长按都不会误触发。 */
    let downX=0, downY=0, downAt=0, downSnap=null;
    document.addEventListener('pointerdown',e=>{
      downX=e.clientX; downY=e.clientY; downAt=Date.now();
      downSnap={ detail:this.detailOpen, filter:this.filterOpen, panel:this.panel, form:this.formOpen };
    },true);
    document.addEventListener('click',e=>{
      if(this.moreOpen && !e.target.closest('.menubar')) this.moreOpen=false;
      if(this.filterOpen && !e.target.closest('.fpop') && !e.target.closest('.fb-filter')
         && e.target.closest('.drawer,.menubar')) this.filterOpen=false;
      // 拖动超过 6px 或按住超过 700ms（长按）不算点击
      if(Math.abs(e.clientX-downX)>6 || Math.abs(e.clientY-downY)>6) return;
      if(downAt && Date.now()-downAt>700) return;
      const t=e.target;
      if(!t || !t.closest) return;
      if(t.closest('.menubar,.drawer,.modal-wrap,.fpop,.more-menu,#lightbox,.toast,' +
                  '.leaflet-marker-icon,.leaflet-control,.marker-cluster,.amap-marker,.fm-cluster,.amap-control')) return;
      this.onMapBlankClick(downSnap);
    });
    // 前进/后退：按 URL 还原条件并重查
    window.addEventListener('popstate',()=>{ this._readURL(); this.loadRecords(); });
    // 启动
    (async()=>{
      // 版本号先取：开屏要靠它判断「是不是刚更新完」，本地接口很快，不拖首屏
      await this.loadVersion();
      const note=this._updatedNote();
      splashNote(note);          // 先换文案，再等地图和记录
      try{ await MapView.init(); }catch(e){ console.error(e); toast('地图加载失败：'+e.message); }
      if(MapView.cfg) this.mapConfig = MapView.cfg;
      // URL 里带 viewOnly 时，等地图就绪后再取一次视野，否则 bounds 是空的
      if(this.filters.viewOnly) this.viewBounds=MapView.getBounds();
      await this.loadRecords();
      splashReady(note);
      if(note) setTimeout(()=>toast(note), 900);
    })();
    // 检查更新：内部延迟 2 秒、失败静默，绝不阻塞首屏
    this._initUpdate();
  },
};

const vm = createApp(App).mount('#ui');
window.__APP__ = vm;
