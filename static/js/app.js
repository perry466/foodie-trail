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
  async del(url){ const r=await fetch(url,{method:'DELETE'}); if(!r.ok) throw await err(r); return r.json(); },
};
async function err(r){ try{ const j=await r.json(); return new Error(j.detail||j.msg||r.statusText); }catch{ return new Error(r.statusText); } }
const $ = s => document.querySelector(s);
const $$ = s => Array.from(document.querySelectorAll(s));
function toast(msg){ const t=$('#toast'); t.textContent=msg; t.classList.remove('hidden'); clearTimeout(t._t); t._t=setTimeout(()=>t.classList.add('hidden'),2200); }
function esc(s){ return (s||'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
function ratingColor(r){ return r<=2?'#9aa0a6':r===3?'#2f80ed':'#f0502f'; }
function pinHTML(r){ return `<div style="background:${ratingColor(r)};box-sizing:border-box;width:34px;height:34px;border:2.5px solid #fff;border-radius:50% 50% 50% 0;transform:rotate(-45deg);display:flex;align-items:center;justify-content:center;box-shadow:0 3px 8px rgba(0,0,0,.35)"><span style="transform:rotate(45deg);display:flex;align-items:center;justify-content:center"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 2v7c0 1.1.9 2 2 2h4a2 2 0 0 0 2-2V2"/><path d="M7 2v20"/><path d="M21 15V2a5 5 0 0 0-5 5v6c0 1.1.9 2 2 2h3Zm0 0v7"/></svg></span></div>`; }
function clusterHTML(n){ const size = n>=100?46:(n>=10?40:34); return `<div class="fm-cluster" style="width:${size}px;height:${size}px">${n}</div>`; }
const MAP_LIMIT = 600; // 地图单次加载图钉上限（按视野取，缩到全中国也不超量）

/* ---------------- 地图适配 ---------------- */
const MapView = {
  impl:null, map:null, cluster:null, _plain:null, _records:[], _drawing:false, _dt:null,
  async init(){
    const cfg = await API.get('/api/config/amap');
    this.cfg = cfg;
    if(cfg.configured && cfg.key) await this.initAMap(cfg);
    else await this.initLeaflet();
    this.render(window.__APP__ ? window.__APP__.records : []);
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
      m.on('click',()=>window.__APP__ && window.__APP__.showDetail(r.id));
      m.on('mouseover',()=>{ this._iw.setContent(prev); this._iw.open(this.map, m.getPosition()); });
      m.on('mouseout',()=>this._iw.close());
      return {_amap:m};
    }else{
      const icon=L.divIcon({html:pinHTML(r.rating),className:'',iconSize:[34,34],iconAnchor:[17,34]});
      const m=L.marker([r.lat,r.lng],{icon});
      m.bindTooltip(prev,{direction:'top',offset:[0,-38],className:'pin-tip-box',opacity:1});
      m.on('click',()=>window.__APP__ && window.__APP__.showDetail(r.id));
      return {_leaf:m};
    }
  },
  // 点击聚合气泡：弹出该区域美食清单，点条目打开详情卡片
  _openCluster(items, pos){
    const app = window.__APP__;
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
  tempMarker(lng,lat){
    if(this.impl==='amap'){ if(window.__APP__ && window.__APP__._tempMarker) this.map.remove(window.__APP__._tempMarker); window.__APP__._tempMarker=new AMap.Marker({position:[lng,lat]}); this.map.add(window.__APP__._tempMarker); this.map.setZoomAndCenter(15,[lng,lat]); }
    else{ if(window.__APP__ && window.__APP__._tempMarker) this.map.removeLayer(window.__APP__._tempMarker); const ic=L.divIcon({className:'',html:'<div style="width:16px;height:16px;border-radius:50%;background:#2f80ed;border:2.5px solid #fff;box-shadow:0 1px 5px rgba(0,0,0,.45)"></div>',iconSize:[16,16],iconAnchor:[8,8]}); window.__APP__._tempMarker=L.marker([lat,lng],{icon:ic}).addTo(this.map); this.map.flyTo([lat,lng],15); }
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
      records:[], page:1, pageSize:100, listTotal:0,
      filters:{ keyword:'', sort:'updatedAt:desc', tags:[], rating:0, checkin:'', viewOnly:false },
      viewBounds:null,
      allTags:[],
      detail:null,
      form:{ id:null, name:'', rating:3, price:'', checkin:'', note:'', draft:false, lat:null, lng:null, address:'' },
      formTags:[], formPhotos:[], formNewPhotos:[], formRemoved:[], hours:null, locLabel:'未选点（在地图上点选）', formMsg:'', tagInput:'',
      settings:{ key:'', security:'', webKey:'', connMsg:'', realKey:'' },
      dash:null,
      importPreview:'', importReady:false, importFile:null,
      pickMode:false, pickCb:null, _tempMarker:null,
      mapConfig:{ configured:false },
      _mapSeq:0, _mmT:null,
    };
  },
  computed:{
    pagedRecords(){
      const size=this.pageSize||100;
      const pages=Math.max(1,Math.ceil(this.records.length/size));
      const p=Math.min(Math.max(1,this.page),pages);
      return this.records.slice((p-1)*size,p*size);
    },
    pages(){ const size=this.pageSize||100; return Math.max(1,Math.ceil(this.records.length/size)); },
  },
  methods:{
    statusOf(r){ return {want:'想去',visited:'去过',favorite:'收藏'}[r.checkinStatus]||''; },
    photoURL(f){ return URL.createObjectURL(f); },
    fmtHours(s){ return fmtHoursRaw(s); },

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
    closePanel(){ this.panel='none'; },
    fitChina(){ MapView.fitChina(); this.moreOpen=false; },

    /* 数据加载 */
    async loadRecords(){
      const f=this.filters;
      let url=`/api/records?${this._filterQuery()}`;
      if(f.viewOnly && this.viewBounds){ const b=this.viewBounds; url+=`&swLng=${b.swLng}&swLat=${b.swLat}&neLng=${b.neLng}&neLat=${b.neLat}`; }
      try{
        const recs=await API.get(url);
        this.records=recs; this.listTotal=recs.length; this.page=1;
        const cnt={}; recs.forEach(r=>(r.tags||[]).forEach(t=>cnt[t]=(cnt[t]||0)+1));
        this.allTags=Object.entries(cnt).sort((a,b)=>b[1]-a[1]).slice(0,24).map(([t,c])=>({t,c}));
        await this.reloadMap();   // 地图按视野动态加载，不再全量渲染
      }catch(e){ toast('加载失败：'+e.message); }
    },
    onSearch(){ clearTimeout(this._st); this._st=setTimeout(()=>this.loadRecords(),250); },
    goto(p){ this.page=p; },
    /* 筛选条件拼成查询串（列表与地图共用） */
    _filterQuery(){
      const f=this.filters;
      let q=`keyword=${encodeURIComponent(f.keyword)}&sort=${f.sort}&checkinStatus=${f.checkin}`;
      if(f.rating) q+=`&ratingMin=${f.rating}&ratingMax=${f.rating}`;
      if(f.tags.length) q+=`&tags=${encodeURIComponent(f.tags.join(','))}`;
      return q;
    },
    /* 地图按当前可视区+上限取数并渲染（根治大规模卡顿） */
    async reloadMap(){
      if(!MapView.map) return;
      if(!this.showMarkers){ MapView.render([]); return; }
      const seq = ++this._mapSeq;
      const b = MapView.getBounds();
      const url = `/api/records?${this._filterQuery()}&swLng=${b.swLng}&swLat=${b.swLat}&neLng=${b.neLng}&neLat=${b.neLat}&limit=${MAP_LIMIT}`;
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
      if(!confirm('确认删除「'+this.detail.name+'」？')) return;
      try{ await API.del('/api/records/'+this.detail.id); toast('已删除'); this.detailOpen=false; this.detail=null; await this.loadRecords(); }
      catch(e){ toast('删除失败：'+e.message); }
    },

    /* 筛选 */
    toggleStar(n){ this.filters.rating = this.filters.rating===n?0:n; this.loadRecords(); },
    setStar(n){ this.filters.rating=n; this.loadRecords(); },
    toggleTag(t){ const i=this.filters.tags.indexOf(t); if(i>=0)this.filters.tags.splice(i,1); else this.filters.tags.push(t); this.loadRecords(); },
    setCheckin(c){ this.filters.checkin=c; this.loadRecords(); },
    onViewOnly(e){ this.filters.viewOnly=e.target.checked; if(this.filters.viewOnly) this.viewBounds=MapView.getBounds(); else this.viewBounds=null; this.loadRecords(); },
    resetFilter(){ this.filters={keyword:'',sort:'updatedAt:desc',tags:[],rating:0,checkin:'',viewOnly:false}; this.viewBounds=null; this.loadRecords(); },

    /* 看板 */
    async openDash(){ try{ this.dash=await API.get('/api/dashboard'); this.dashOpen=true; }catch(e){ toast('看板加载失败：'+e.message); } },

    /* 设置 */
    async openSettings(){
      this.moreOpen=false;
      try{
        const cfg=await API.get('/api/config/amap');
        this.mapConfig=cfg; this.settings.realKey=cfg.key;
        this.settings.key=cfg.configured?this.maskKey(cfg.key):'';
        this.settings.security=''; this.settings.webKey=''; this.settings.connMsg='';
        this.settingsOpen=true;
      }catch(e){ toast('设置加载失败：'+e.message); }
    },
    maskKey(k){ if(!k) return ''; return '••••••'+k.slice(-4); },
    async saveKey(){
      let key=this.settings.key.trim(); const sec=this.settings.security.trim(); const web=this.settings.webKey.trim();
      if(this.mapConfig.configured && key===this.maskKey(this.settings.realKey)) key=this.settings.realKey;
      if(!key){ toast('请输入 JS API Key'); return; }
      const body={key,security:sec||null};
      if(web) body.web_key=web;
      try{ await API.sendForm('/api/settings/amap','PUT',body); toast('已保存（加密存储）'); await MapView.init(); await this.loadRecords(); }
      catch(e){ toast('保存失败：'+e.message); }
    },
    async testConn(){
      try{ const r=await API.sendForm('/api/settings/test-connection','POST',{}); this.settings.connMsg=r.ok?'✅ '+r.msg:'❌ '+r.msg; }
      catch(e){ this.settings.connMsg='❌ '+e.message; }
    },
    async clearKey(){
      try{ await API.del('/api/settings/amap'); toast('已清除'); await this.openSettings(); await MapView.init(); await this.loadRecords(); }
      catch(e){ toast('清除失败：'+e.message); }
    },

    /* 表单 */
    openForm(rec){ this.moreOpen=false; this.panel='none';
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
      this.locLabel=rec?`已选点 (${rec.lat.toFixed(4)}, ${rec.lng.toFixed(4)})`:'未选点（在地图上点选）';
      this.formMsg=''; this.tagInput='';
      this.formOpen=true;
      this.$nextTick(()=>this.renderHoursEditor());
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
      if(!this.form.lat||!this.form.lng){ /* 无预设也可选 */ }
      this.pickMode=true; toast('在地图上点选位置');
      this.formOpen=false;
      this.pickCb=(lng,lat)=>{
        this.form.lng=lng; this.form.lat=lat;
        this.locLabel=`已选点 (${lat.toFixed(4)}, ${lng.toFixed(4)})`;
        MapView.tempMarker(lng,lat);
        this.pickMode=false; this.pickCb=null; this.formOpen=true;
        this.$nextTick(()=>this.renderHoursEditor());
      };
    },
    async locateMe(){
      if(!navigator.geolocation){ toast('浏览器不支持定位'); return; }
      navigator.geolocation.getCurrentPosition(async pos=>{
        const {longitude:lng,latitude:lat}=pos.coords;
        const gc=await API.sendForm('/api/coords/convert','POST',{lng,lat});
        this.form.lng=gc.lng; this.form.lat=gc.lat;
        this.locLabel=`当前定位 (${gc.lat.toFixed(4)}, ${gc.lng.toFixed(4)})`;
        MapView.tempMarker(gc.lng,gc.lat);
      },()=>toast('定位被拒，请手动选点'),{enableHighAccuracy:true,timeout:8000});
    },
    async geocode(){
      const addr=this.form.address.trim(); if(!addr) return;
      if(!this.mapConfig.configured){ toast('未配置高德 Key，无法搜索地址'); return; }
      try{
        const data=await API.get('/api/amap/geocode?address='+encodeURIComponent(addr));
        const g=data.geocodes&&data.geocodes[0];
        if(!g){ toast('未找到地址'); return; }
        const [lng,lat]=g.location.split(',').map(Number);
        this.form.lng=lng; this.form.lat=lat;
        this.locLabel=`${g.formatted_address} (${lat.toFixed(4)}, ${lng.toFixed(4)})`;
        MapView.tempMarker(lng,lat);
      }catch(e){ toast('地理编码失败：'+e.message); }
    },
    searchPOI(){
      const kw=this.form.address.trim(); if(!kw) return;
      if(!this.mapConfig.configured){ $('#poiResult').innerHTML='<div class="hint">未配置高德 Key，无法搜索 POI</div>'; return; }
      clearTimeout(this._poi);
      this._poi=setTimeout(async()=>{
        try{
          const data=await API.get('/api/amap/poi?keywords='+encodeURIComponent(kw));
          const tips=(data.tips||[]).filter(t=>t.location);
          $('#poiResult').innerHTML = tips.map((t,i)=>`<div class="poi-item" data-i="${i}" data-lng="${t.location.split(',')[0]}" data-lat="${t.location.split(',')[1]}">${esc(t.name)}<small>${esc(t.district||'')} ${esc(t.address||'')}</small></div>`).join('') || '<div class="hint">无结果</div>';
          $$('#poiResult .poi-item').forEach(el=>el.onclick=()=>{ const lng=+el.dataset.lng,lat=+el.dataset.lat; this.form.lng=lng; this.form.lat=lat; this.locLabel=`${el.childNodes[0].textContent} (${lat.toFixed(4)}, ${lng.toFixed(4)})`; MapView.tempMarker(lng,lat); $('#poiResult').innerHTML=''; });
        }catch(e){ toast('POI 搜索失败：'+e.message); }
      },400);
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
      try{
        let rec;
        if(this.form.id) rec=await API.sendForm('/api/records/'+this.form.id,'PUT',body);
        else rec=await API.sendForm('/api/records','POST',body);
        for(const f of this.formNewPhotos) await API.upload('/api/records/'+rec.id+'/photos',f);
        for(const pid of this.formRemoved) await API.del('/api/photos/'+pid);
        toast('已保存'); this.formOpen=false; await this.loadRecords();
        if(this.detailOpen && this.detail && this.detail.id===rec.id) this.detail=rec;
      }catch(e){ this.formMsg='保存失败：'+e.message; }
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
      const f=this.filters; let url=`/api/export?mode=full&keyword=${encodeURIComponent(f.keyword)}&checkinStatus=${f.checkin}`;
      if(f.rating) url+=`&ratingMin=${f.rating}&ratingMax=${f.rating}`;
      if(f.tags.length) url+=`&tags=${encodeURIComponent(f.tags.join(','))}`;
      window.location.href=url;
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
      else if(e.key==='Escape'){ this.panel='none'; this.moreOpen=false; this.settingsOpen=this.formOpen=this.detailOpen=this.dashOpen=this.importOpen=false; }
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
