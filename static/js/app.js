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
async function err(r){ const base=r.statusText; try{ const j=await r.json(); const e=new Error(j.detail||j.msg||base); e.status=r.status; return e; }catch{ const e=new Error(base); e.status=r.status; return e; } }
const $ = s => document.querySelector(s);
const $$ = s => Array.from(document.querySelectorAll(s));
function toast(msg){ const t=$('#toast'); t.textContent=msg; t.classList.remove('hidden'); clearTimeout(t._t); t._t=setTimeout(()=>t.classList.add('hidden'),2200); }
function esc(s){ return (s||'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
function ratingColor(r){ return r<=2?'#9aa0a6':r===3?'#2f80ed':'#f0502f'; }
function pinHTML(r){ return `<div style="background:${ratingColor(r)};box-sizing:border-box;width:34px;height:34px;border:2.5px solid #fff;border-radius:50% 50% 50% 0;transform:rotate(-45deg);display:flex;align-items:center;justify-content:center;box-shadow:0 3px 8px rgba(0,0,0,.35)"><span style="transform:rotate(45deg);display:flex;align-items:center;justify-content:center"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 2v7c0 1.1.9 2 2 2h4a2 2 0 0 0 2-2V2"/><path d="M7 2v20"/><path d="M21 15V2a5 5 0 0 0-5 5v6c0 1.1.9 2 2 2h3Zm0 0v7"/></svg></span></div>`; }
function clusterHTML(n){ const size = n>=100?46:(n>=10?40:34); return `<div class="fm-cluster" style="width:${size}px;height:${size}px">${n}</div>`; }
const MAP_LIMIT = 600; // 地图单次加载图钉上限（按视野取，缩到全中国也不超量）
const DRAFT_KEY = 'fm-form-draft-v1';   // 添加表单的本地草稿（未提交内容）

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
    this._iw=null; this._cw=null; this._drawing=false; this._dt=null;
    const el=document.getElementById('map');
    if(el) el.innerHTML='';       // Leaflet 会往容器塞 DOM，直接清空最保险
  },
  async init(){
    this.destroy();
    const cfg = await API.get('/api/config/amap');
    this.cfg = cfg;
    if(cfg.configured && cfg.key) await this.initAMap(cfg);
    else await this.initLeaflet();
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
      if(app) app.closeDetail();   // 点击地图空白处收起详情卡片
    });
    // 缩放后网格聚合需要重算（平移不影响地理坐标，无需重算）
    this.map.on('zoomend', ()=>this._scheduleDraw());
    this.map.on('moveend', ()=>{ const a=window.__APP__; if(a && a.onMapMoveEnd) a.onMapMoveEnd(); });
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
      if(app) app.closeDetail();   // 点击地图空白处收起详情卡片
    });
    this.map.on('moveend', ()=>{ const a=window.__APP__; if(a && a.onMapMoveEnd) a.onMapMoveEnd(); });
    this.showFallbackBanner();
  },
  showFallbackBanner(){
    let b=$('#mapBanner'); if(!b){ b=document.createElement('div'); b.id='mapBanner'; $('#map').appendChild(b); }
    b.className='map-banner';
    b.textContent='未配置高德 Key：当前使用兜底地图（可正常显示、打点、查看记录）。POI 搜索 / 地址定位 / 驾车路线需配置 Key 后启用。';
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
  $('#lbImg').src='/api/photos/'+photos[i].id;
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
  $('#lbImg').src='/api/photos/'+p[window.__LB__.i].id;
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
      settingsOpen:false, formOpen:false, detailOpen:false, dashOpen:false, importOpen:false,
      confirmBox:{ open:false, title:'', message:'', ok:'确认', danger:false, busy:false, onlyOk:false },
      records:[], page:1, pageSize:100, listTotal:0,
      selectMode:false, selectedIds:[],
      filters:{ keyword:'', sort:'updatedAt:desc', tags:[], rating:0, checkin:'', viewOnly:false, priceMin:null, priceMax:null, drafts:'all' },
      viewBounds:null,
      allTags:[],
      detail:null,
      form:{ id:null, name:'', rating:3, price:'', checkin:'', note:'', draft:false, lat:null, lng:null, address:'' },
      formTags:[], formPhotos:[], formNewPhotos:[], formRemoved:[], hours:null, formMsg:'', tagInput:'',
      /* 位置状态：locName 是地点名，locCoord 是"纬度, 经度"字符串，两者都空表示未选点 */
      locName:'', locCoord:'',
      /* 地址联想：输入即搜（无需回车），poiActive 是键盘当前高亮项 */
      poiList:[], poiOpen:false, poiLoading:false, poiActive:-1, poiMsg:'', poiNeedKey:false,
      settings:{ key:'', security:'', webKey:'', connMsg:'', realKey:'' },
      dash:null,
      importPreview:'', importReady:false, importFile:null,
      pickMode:false, pickCb:null, pickingMap:false, _pickedAt:0,
      mapConfig:{ configured:false },
      draftNotice:'', draftSaved:false, _suppressDraft:false,
      /* 内部状态：下划线开头，Vue 3 不会代理到实例，只能在 JS 方法里用 this._xxx 访问，
         严禁出现在模板表达式中（生产版会抛 ReferenceError，整个组件渲染失败） */
      _mapSeq:0, _mmT:null, _poiSeq:0,
      /* 保存中标志：模板要用（禁用按钮 + 文案切换），所以必须用普通名字 */
      saving:false,
    };
  },
  computed:{
    /* 按草稿可见范围过滤后的记录（分页与计数都基于它） */
    visibleRecords(){ return this._visible(this.records); },
    draftCount(){ return this.records.filter(r=>r.draft).length; },
    pagedRecords(){
      const size=this.pageSize||100;
      const list=this.visibleRecords;
      const pages=Math.max(1,Math.ceil(list.length/size));
      const p=Math.min(Math.max(1,this.page),pages);
      return list.slice((p-1)*size,p*size);
    },
    pages(){ const size=this.pageSize||100; return Math.max(1,Math.ceil(this.visibleRecords.length/size)); },
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
  },
  methods:{
    statusOf(r){ return {want:'想去',visited:'去过',favorite:'收藏'}[r.checkinStatus]||''; },
    photoURL(f){ return URL.createObjectURL(f); },
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
        for(const id of ids){ await API.del('/api/records/'+id); n++; }
        return n;
      }
    },

    /* 主题 */
    toggleTheme(){
      const cur=document.documentElement.getAttribute('data-theme');
      const next=cur==='dark'?'light':'dark';
      document.documentElement.setAttribute('data-theme',next);
      try{ localStorage.setItem('fm-theme',next); }catch{}
      this.moreOpen=false;
    },

    /* 显示选项：地图描点开关 */
    setShowMarkers(v){
      this.showMarkers = !!v;
      try{ localStorage.setItem('fm-show-markers', this.showMarkers?'1':'0'); }catch{}
      this.reloadMap();
      toast(this.showMarkers?'已显示描点':'已隐藏描点');
    },

    /* 面板开关 */
    togglePanel(name){ this.moreOpen=false; this.panel = this.panel===name ? 'none' : name; },
    closePanel(){ this.panel='none'; this.exitSelect(); },
    fitChina(){ MapView.fitChina(); this.moreOpen=false; },

    /* 数据加载 */
    async loadRecords(){
      const f=this.filters;
      // 列表始终把草稿取回来（否则勾选"存为草稿"的记录会从列表和地图上彻底消失），
      // 再由前端按 filters.drafts 决定显示范围
      let url=`/api/records?${this._filterQuery(true)}`;
      if(f.viewOnly && this.viewBounds){ const b=this.viewBounds; url+=`&swLng=${b.swLng}&swLat=${b.swLat}&neLng=${b.neLng}&neLat=${b.neLat}`; }
      try{
        const recs=await API.get(url);
        this.records=recs; this.listTotal=this._visible(recs).length; this.page=1;
        // 清除已不存在于当前结果里的选中项（如被筛掉或已删除），避免误删
        if(this.selectedIds.length){
          const alive=new Set(this._visible(recs).map(r=>r.id));
          this.selectedIds=this.selectedIds.filter(id=>alive.has(id));
        }
        const cnt={}; recs.forEach(r=>(r.tags||[]).forEach(t=>cnt[t]=(cnt[t]||0)+1));
        this.allTags=Object.entries(cnt).sort((a,b)=>b[1]-a[1]).slice(0,24).map(([t,c])=>({t,c}));
        await this.reloadMap();   // 地图按视野动态加载，不再全量渲染
      }catch(e){ toast('加载失败：'+e.message); }
    },
    onSearch(){ clearTimeout(this._st); this._st=setTimeout(()=>this.loadRecords(),250); },
    goto(p){ this.page=p; },
    /* 筛选条件拼成查询串（列表与地图共用）
       withDrafts=true 时把草稿一并取回（列表用）；
       draftsOnly=true 时只取草稿（地图在"仅草稿"下必须与列表同范围，否则会混入非草稿） */
    _filterQuery(withDrafts, draftsOnly){
      const f=this.filters;
      let q=`keyword=${encodeURIComponent(f.keyword)}&sort=${f.sort}&checkinStatus=${f.checkin}`;
      if(f.rating) q+=`&ratingMin=${f.rating}&ratingMax=${f.rating}`;
      if(f.tags.length) q+=`&tags=${encodeURIComponent(f.tags.join(','))}`;
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
    onMapMoveEnd(){ clearTimeout(this._mmT); this._mmT = setTimeout(()=>this.reloadMap(), 350); },

    /* 详情 */
    async showDetail(id){
      const token=(this._detailReq=(this._detailReq||0)+1);   // 竞态守卫：仅最新的点击生效
      try{
        const r=await API.get('/api/records/'+id);
        if(token!==this._detailReq) return;                   // 已有更新的请求，丢弃本次旧结果
        this.detail=r; this.detailOpen=true;
        MapView.flyTo(r);
      }catch(e){ if(token===this._detailReq) toast('打开失败：'+e.message); }
    },
    closeDetail(){ this.detailOpen=false; },
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
        await API.del('/api/records/'+id);
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
    enterSelect(){ this.moreOpen=false; this.panel='list'; this.selectMode=true; },
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

    /* 筛选 */
    toggleStar(n){ this.filters.rating = this.filters.rating===n?0:n; this.loadRecords(); },
    setStar(n){ this.filters.rating=n; this.loadRecords(); },
    toggleTag(t){ const i=this.filters.tags.indexOf(t); if(i>=0)this.filters.tags.splice(i,1); else this.filters.tags.push(t); this.loadRecords(); },
    setCheckin(c){ this.filters.checkin=c; this.loadRecords(); },
    setDrafts(v){
      if(this.filters.drafts===v) return;
      this.filters.drafts=v; this.page=1; this.listTotal=this.visibleRecords.length;
      this.reloadMap();          // 草稿范围变了，地图立即按同一范围重取，不必等拖动地图
    },
    onViewOnly(e){ this.filters.viewOnly=e.target.checked; if(this.filters.viewOnly) this.viewBounds=MapView.getBounds(); else this.viewBounds=null; this.loadRecords(); },
    resetFilter(){ this.filters={keyword:'',sort:'updatedAt:desc',tags:[],rating:0,checkin:'',viewOnly:false,priceMin:null,priceMax:null,drafts:'all'}; this.viewBounds=null; this.loadRecords(); },

    /* 看板：加载 + 图表下钻（点图表即筛到列表） */
    async openDash(){
      this.moreOpen=false;
      try{ this.dash=await API.get('/api/dashboard'); this.dashOpen=true; }
      catch(e){ toast('看板加载失败：'+e.message); }
    },
    dashDrill(kind, val){
      const f={ rating:0, priceMin:null, priceMax:null, checkin:'', tags:[] };
      let label='';
      if(kind==='checkin'){ f.checkin=val; label={visited:'去过',want:'想去',favorite:'收藏'}[val]||'全部'; }
      else if(kind==='star'){ f.rating=val; label=val+' 星'; }
      else if(kind==='price'){ const b=this.dash.price.buckets[val]; f.priceMin=b.min; f.priceMax=b.max; label='人均 '+b.label; }
      else if(kind==='tag'){ f.tags=[val]; label=val; }
      this.dashOpen=false;
      Object.assign(this.filters, f);
      this.panel='list';                 // 直接打开列表抽屉，让筛选结果可见
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
      }catch(e){ toast('设置加载失败：'+e.message); }
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
      this.formTags=[]; this.formPhotos=[]; this.formNewPhotos=[]; this.formRemoved=[];
      this.hours=parseHours(null); this.locName=''; this.locCoord=''; this.formMsg=''; this.tagInput='';
      this.$nextTick(()=>this.renderHoursEditor());
    },
    openForm(rec){ this.moreOpen=false; this.panel='none';
      this.pickMode=false; this.pickCb=null; this.pickingMap=false;   // 清掉可能残留的选点态
      this._suppressDraft=true;          // 初始化字段期间不要覆盖已有草稿
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
      this.formPhotos=rec?(rec.photos||[]).map(p=>({id:p.id,url:'/api/photos/'+p.id})):[];
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
    addTag(){
      const v=this.tagInput.trim();
      if(v && !this.formTags.includes(v)) this.formTags.push(v);
      this.tagInput='';
    },
    removeTag(i){ this.formTags.splice(i,1); },
    pickPhotos(e){ for(const f of e.target.files){ if(this.formPhotos.length+this.formNewPhotos.length<9) this.formNewPhotos.push(f); } e.target.value=''; },
    removePhoto(i,isNew){ if(isNew) this.formNewPhotos.splice(i,1); else { this.formRemoved.push(this.formPhotos[i].id); this.formPhotos.splice(i,1); } },
    pickOnMap(){
      // 进入选点态：表单不销毁，只收起成一条提示条（遮罩透明可穿透），
      // 这样用户始终知道"还在添加流程里"，也不会因为地图操作异常而丢掉整张表单。
      // 提示由 pick-bar 承担，不再弹 toast（toast 也在底部，会盖住提示条的取消按钮）。
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
    closeForm(){ if(this.pickingMap) this.cancelPick(); this.formOpen=false; },
    /* 点遮罩关闭：选点态下不关；刚选完点的 500ms 内忽略（防误触、防双击）
       另外本方法也可以关闭编辑/新增表单以外的模态，由调用处决定 */
    backdropClose(){
      if(this.pickingMap) return;
      if(Date.now()-(this._pickedAt||0) < 500) return;
      this.formOpen=false;
    },
    async locateMe(){
      if(!navigator.geolocation){ toast('浏览器不支持定位'); return; }
      navigator.geolocation.getCurrentPosition(async pos=>{
        const {longitude:lng,latitude:lat}=pos.coords;
        const gc=await API.sendForm('/api/coords/convert','POST',{lng,lat});
        this.form.lng=gc.lng; this.form.lat=gc.lat;
        this.locName='当前位置';
        this.locCoord=`${gc.lat.toFixed(4)}, ${gc.lng.toFixed(4)}`;
        MapView.tempMarker(gc.lng,gc.lat);
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
          sr.innerHTML=`<input type="time" value="${sl.s}"><em>至</em><input type="time" value="${sl.e}"><button type="button" class="slot-del" title="删除该时段">✕</button>`;
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
      const name=this.form.name.trim();
      if(!name){ this.formMsg='店名必填'; return; }
      if((this.formPhotos.length+this.formNewPhotos.length)>9){ this.formMsg='照片最多 9 张'; return; }
      if(!this.form.lat||!this.form.lng){ this.formMsg='请先在地图上点选位置'; return; }
      const body={
        name, rating:this.form.rating, lng:this.form.lng, lat:this.form.lat,
        tags:this.formTags, businessHours:serializeHours(this.hours),
        avgPrice:this.form.price?+this.form.price:null,
        checkinStatus:this.form.checkin||null, note:this.form.note.trim()||null, draft:this.form.draft,
      };
      this.saving=true;
      this.formMsg='';
      try{
        let rec;
        if(this.form.id) rec=await API.sendForm('/api/records/'+this.form.id,'PUT',body);
        else{
          rec=await API.sendForm('/api/records','POST',body);
          // 立刻回填 id：记录已落库，之后任何重试都会走更新而不是新建，
          // 避免"照片上传失败→用户再点保存→产生重复记录"
          this.form.id=rec.id;
        }
        // 照片逐张上传/删除，失败的不丢弃，留在列表里等用户重试
        const failed=[];
        for(const f of this.formNewPhotos){
          try{ await API.upload('/api/records/'+rec.id+'/photos',f); }
          catch(e){ failed.push(f); }
        }
        this.formNewPhotos=failed;
        const delFailed=[];
        for(const pid of this.formRemoved){
          try{ await API.del('/api/photos/'+pid); }
          catch(e){ delFailed.push(pid); }   // 删除失败要保留，否则照片仍留在库里、下次打开又冒出来
        }
        this.formRemoved=delFailed;
        if(failed.length||delFailed.length){
          const parts=[];
          if(failed.length) parts.push(`${failed.length} 张照片上传失败`);
          if(delFailed.length) parts.push(`${delFailed.length} 张照片删除失败`);
          this.formMsg=`记录已保存，但有 ${parts.join('、')}，可再点保存重试`;
          await this.loadRecords();
          return;                                   // 保留表单与未完成项，便于重试
        }
        toast('已保存'); this.clearDraft(); this.formOpen=false; await this.loadRecords();
        if(this.detailOpen && this.detail && this.detail.id===rec.id) this.detail=rec;
      }catch(e){ this.formMsg='保存失败：'+e.message; }
      finally{ this.saving=false; }
    },

    /* 导入 / 导出 */
    openImport(){ this.moreOpen=false; this.importPreview=''; this.importReady=false; this.importFile=null; this.importOpen=true; },
    async onImportFile(e){
      const file=e.target.files[0]; if(!file) return;
      const fd=new FormData(); fd.append('file',file);
      try{
        const r=await fetch('/api/import',{method:'POST',body:fd}); const j=await r.json();
        if(j.detail){ this.importPreview='❌ '+j.detail; this.importReady=false; return; }
        this.importFile=file;
        const bad=(j.invalidDetails&&j.invalidDetails.length)?`；无效 ${j.invalid} 条`:'';
        this.importPreview=`预览：新增 ${j.append}，更新 ${j.update}，无效 ${j.invalid}${bad}`;
        this.importReady=true;
      }catch(err){ this.importPreview='❌ '+err.message; this.importReady=false; }
    },
    async doImport(){
      if(!this.importFile) return;
      const fd=new FormData(); fd.append('file',this.importFile);
      try{
        const r=await fetch('/api/import?confirm=true',{method:'POST',body:fd}); const j=await r.json();
        toast(`导入完成：写入 ${j.written}，无效 ${j.invalid}`);
        this.importOpen=false; this.importFile=null; await this.loadRecords();
      }catch(e){ toast('导入失败：'+e.message); }
    },
    doExport(){
      this.moreOpen=false;
      // 备份始终包含草稿：草稿同样是用户数据，静默遗漏会让恢复后的数据不完整
      window.location.href=`/api/export?mode=full&includeDrafts=1&${this._filterQuery(false)}`;
    },

    /* lightbox 桥接 */
    openLightbox(photos,i){ openLightbox(photos,i); },
  },
  mounted(){
    const t=localStorage.getItem('fm-theme'); if(t) document.documentElement.setAttribute('data-theme',t);
    if(localStorage.getItem('fm-show-markers')==='0') this.showMarkers=false;
    bindLightbox();
    // 全局快捷键 & 点击外部关闭更多
    document.addEventListener('keydown',e=>{
      if(/INPUT|TEXTAREA|SELECT/.test(e.target.tagName)) return;
      if($('#lightbox') && !$('#lightbox').classList.contains('hidden')){
        if(e.key==='Escape') closeLightbox();
        else if(e.key==='ArrowLeft') lbNav(-1);
        else if(e.key==='ArrowRight') lbNav(1);
        return;
      }
      if(e.key==='n'||e.key==='N'){ this.openForm(null); }
      else if(e.key==='/'){ e.preventDefault(); const el=$('.drawer-search input'); if(el) el.focus(); }
      else if(e.key==='Escape'){ if(this.confirmBox.open){ this.closeConfirm(false); return; } if(this.pickingMap){ this.cancelPick(); return; } if(this.selectMode){ this.exitSelect(); return; } this.panel='none'; this.moreOpen=false; this.settingsOpen=this.formOpen=this.detailOpen=this.dashOpen=this.importOpen=false; }
    });
    document.addEventListener('click',e=>{ if(this.moreOpen && !e.target.closest('.menubar')) this.moreOpen=false; });
    // 启动
    (async()=>{
      try{ await MapView.init(); }catch(e){ console.error(e); toast('地图加载失败：'+e.message); }
      if(MapView.cfg) this.mapConfig = MapView.cfg;
      await this.loadRecords();
    })();
  },
};

const vm = createApp(App).mount('#ui');
window.__APP__ = vm;
