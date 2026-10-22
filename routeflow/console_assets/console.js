"use strict";
const $ = (selector) => document.querySelector(selector);
const token = $('meta[name="console-token"]').content;
const state = {overview:null, busy:false, refreshing:false, table:"orders", page:1, log:"", view:"services", logService:"api"};
const locale = new Intl.NumberFormat("vi-VN");
const number = (value) => value == null ? "—" : locale.format(Number(value));
const escape = (value) => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const date = (value, full=false) => value ? new Intl.DateTimeFormat("vi-VN", full ? {dateStyle:"short",timeStyle:"short"} : {hour:"2-digit",minute:"2-digit",second:"2-digit"}).format(new Date(value)) : "—";
const bytes = (value) => value == null ? "—" : `${new Intl.NumberFormat("vi-VN",{maximumFractionDigits:1}).format(value / 1024 ** 3)} GiB`;
const sleep = (ms) => new Promise(resolve => setTimeout(resolve,ms));
async function api(path, options={}) {
  const response = await fetch(path, {cache:"no-store", ...options, headers:{"Content-Type":"application/json","X-Console-Token":token,...options.headers}});
  let payload; try { payload = await response.json(); } catch { throw Error("Máy chủ trả về phản hồi không hợp lệ."); }
  if (!response.ok) throw Error(typeof payload.detail === "string" ? payload.detail : "Không thực hiện được yêu cầu.");
  return payload;
}
let toastTimer;
function toast(message) { $('#toast').textContent=message; $('#toast').hidden=false; clearTimeout(toastTimer); toastTimer=setTimeout(()=>$('#toast').hidden=true,5500); }
function serviceStatus(service) {
  if (service.state === "running") {
    if ((service.status||"").includes("unhealthy")) return ["failed","Lỗi healthcheck"];
    if ((service.status||"").includes("starting")) return ["starting","Đang khởi động"];
    return ["running","Đang chạy"];
  }
  if (service.state === "restarting") return ["starting","Đang khởi động"];
  return ["", service.state === "missing" ? "Chưa tạo" : service.state === "unknown" ? "Chưa kết nối" : "Đã dừng"];
}
const badge = (label, kind="") => `<span class="status ${kind}"><span class="tiny-dot"></span>${escape(label)}</span>`;
function syncControls() {
  const locked=state.busy || !state.overview?.docker.available || state.overview?.storage.pinned_to_e === false;
  document.querySelectorAll('[data-target="stack"]').forEach(button=>{
    const anyRunning=state.overview?.services.some(service=>['running','restarting'].includes(service.state));
    const allRunning=state.overview?.services.every(service=>service.state==='running');
    button.disabled=locked || (button.dataset.action==='start' ? allRunning : !anyRunning);
  });
  document.querySelectorAll('[data-action]').forEach(button=>{
    if(button.dataset.target==='docker') button.disabled=state.busy;
    else if(button.dataset.target!=='stack') button.disabled=locked;
  });
}
function serviceRow(service) {
  const [kind,label]=serviceStatus(service);
  const running=["running","restarting"].includes(service.state);
  const disabled=state.busy || !state.overview?.docker.available || state.overview?.storage.pinned_to_e === false ? "disabled" : "";
  return `<div class="service-row" role="row"><div class="service-info" role="cell"><div class="service-name" title="${escape(service.detail)}">${escape(service.name)}${service.url ? `<a href="${service.url}" target="_blank" rel="noopener" aria-label="Mở ${escape(service.name)}">Mở</a>` : ""}</div><p>${escape(service.id)}${service.port ? ` · <span class="service-port">:${service.port}</span>` : ""}</p></div><div role="cell">${badge(label,kind)}</div><div class="service-actions" role="cell"><button class="text-button" data-logs="${service.id}" aria-label="Nhật ký ${escape(service.name)}">Nhật ký</button>${running ? `<button class="text-button" data-target="${service.id}" data-action="restart" ${disabled} aria-label="Khởi động lại ${escape(service.name)}">Khởi động lại</button>` : ""}<button class="text-button ${running ? "stop" : ""}" data-target="${service.id}" data-action="${running ? "stop" : "start"}" ${disabled} aria-label="${running ? "Dừng" : "Bật"} ${escape(service.name)}">${running ? "Dừng" : "Bật"}</button></div></div>`;
}
function renderServices() {
  const data=state.overview; if(!data) return;
  const search=$('#service-search').value.trim().toLocaleLowerCase("vi-VN"), filter=$('#service-filter').value;
  const rows=data.services.filter(s=>(`${s.name} ${s.id} ${s.detail}`).toLocaleLowerCase("vi-VN").includes(search) && (filter === "all" || (filter === "running" ? s.state === "running" : !["running","restarting"].includes(s.state))));
  const list=$('#all-services');
  // Preserve keyboard focus across automatic refreshes of service states.
  const focus=list.contains(document.activeElement) ? document.activeElement : null;
  const focusKey=focus ? ['target','action','logs'].map(key=>[key,focus.dataset[key]]).filter(([,value])=>value) : [];
  const focusLabel=focus?.getAttribute('aria-label');
  list.innerHTML=rows.length ? rows.map(serviceRow).join("") : '<p class="empty-text">Không có dịch vụ phù hợp.</p>';
  if(focus) {
    const replacement=[...list.querySelectorAll('button,a')].find(element=>element.getAttribute('aria-label')===focusLabel && focusKey.every(([key,value])=>element.dataset[key]===value));
    replacement?.focus({preventScroll:true});
  }
  $('#other-containers').innerHTML=data.others.length ? data.others.map(row=>`<div class="other-row"><div>${escape(row.name)}<small>${escape(row.ports || "Không mở cổng trên máy")}</small></div>${badge(row.state === "running" ? "Đang chạy" : "Đã dừng",row.state === "running" ? "running" : "")}</div>`).join("") : '<p class="meta">Không có container khác.</p>';
  syncControls();
}
function renderMetrics() {
  const {data,services,docker}=state.overview;
  const metrics=[
    ["Dịch vụ đang chạy",docker.available ? services.filter(s=>s.state === 'running').length : null,"/ 8"],
    ["Đơn hàng",data.source?.orders,""],
    ["Sự kiện RAW",data.warehouse?.events,""],
    ["Điểm GPS",data.warehouse?.gps_points,""]
  ];
  $('#metrics').innerHTML=metrics.map(([label,value,unit])=>`<div><dt>${label}</dt><dd>${number(value)}${unit ? `<small>${unit}</small>` : ""}</dd></div>`).join('');
}
function renderStorage() {
  const storage=state.overview.storage;
  $('#storage-observed').hidden=!storage.observed_at;
  $('#storage-observed').textContent=storage.observed_at ? `Dung lượng VHD được ghi nhận lúc ${date(storage.observed_at,true)}.${storage.disk_snapshot_at ? ' Số đo dung lượng ổ đĩa cũng lấy từ thời điểm này.' : ' Dung lượng trống các ổ được đọc trực tiếp.'}` : '';
  const roles={"C:":"Windows, ứng dụng và log máy chủ","D:":"Mã nguồn, cache, backup","E:":"Docker và volume"};
  $('#storage-disks').innerHTML=storage.disks.map(disk=>`<div class="disk-row"><div><strong>Ổ ${disk.drive}</strong><p>${roles[disk.drive] || "Ổ đĩa local"}</p></div><progress value="${disk.used}" max="${disk.total}" aria-label="Dung lượng đã dùng ổ ${disk.drive}"></progress><div class="disk-free">Trống ${bytes(disk.free)}<p>/ ${bytes(disk.total)}</p></div></div>`).join('');
  $('#storage-details').innerHTML=`<div class="storage-row"><div><strong>Ổ đĩa Docker · ${bytes(storage.docker_bytes)}</strong><p>${escape(storage.docker_path)}</p></div>${badge(storage.pinned_to_e ? "Đã ghim trên E" : "Cần kiểm tra",storage.pinned_to_e ? "running" : "failed")}</div><div class="storage-row"><div><strong>Bản sao đã kiểm tra phục hồi</strong><p>${escape(storage.backup?.path || "Chưa tìm thấy bản ghi backup.")}</p><p>${storage.backup ? `Kiểm tra lúc ${date(storage.backup.checked_at,true)}. Kết quả được lưu từ lần đó; chưa kiểm tra lại file hiện tại.` : "Tạo backup và chạy verify để kiểm tra phục hồi."}</p></div>${badge(storage.backup?.verified ? "Đã thử phục hồi" : "Chưa xác minh",storage.backup?.verified ? "running" : "")}</div>`;
}
function renderNotice() {
  const data=state.overview; if(!data)return;
  const messages=[];
  if(!data.docker.available) messages.push(data.docker.message);
  if(data.storage.pinned_to_e === false) messages.push("Cấu hình WSL chưa ghim trên E. Kiểm tra trước khi bật dịch vụ.");
  if(['services','data'].includes(state.view) && data.data.source?.dlq) messages.push(`DLQ: ${number(data.data.source.dlq)} sự kiện chưa xử lý. Xem bảng Dead-letter queue trong Dữ liệu.`);
  $('#connection-error').hidden=!messages.length;
  $('#connection-error').textContent=messages.join(" ");
  if(!data.docker.available && data.storage.pinned_to_e !== false) {
    const button=document.createElement('button'); button.className='button secondary'; button.dataset.target='docker'; button.dataset.action='start'; button.textContent='Mở Docker Desktop'; $('#connection-error').append(button);
  }
  syncControls();
}
async function refresh(showFeedback=false) {
  if(state.refreshing) return;
  state.refreshing=true; $('#refresh').disabled=true;
  try {
    state.overview=await api('/api/overview');
    const data=state.overview;
    $('#engine-status').textContent=data.docker.available ? `Docker Engine ${data.docker.version}` : "Docker chưa kết nối";
    $('#updated-at').textContent=`Cập nhật lúc ${date(data.checked_at)}`;
    renderNotice();
    renderServices(); renderMetrics(); renderStorage();
    if(showFeedback) toast("Đã cập nhật trạng thái mới nhất.");
  } catch(error) {
    state.overview=null;syncControls();
    $('#connection-error').hidden=false; $('#connection-error').textContent=`Không kết nối được Console: ${error.message} Dữ liệu phía dưới có thể đã cũ.`;
  } finally { state.refreshing=false; $('#refresh').disabled=false; }
}
const views={services:"Dịch vụ",data:"Dữ liệu",logs:"Nhật ký",storage:"Lưu trữ"};
function navigate() {
  if(location.hash==='#content' && state.overview) return;
  let view=location.hash.slice(1); if(!views[view]) view="services";
  state.view=view;
  document.querySelectorAll('.view').forEach(element=>element.hidden=element.id!==`view-${view}`);
  document.querySelectorAll('nav a').forEach(element=>{const active=element.dataset.view===view;element.classList.toggle('active',active);if(active) element.setAttribute('aria-current','page'); else element.removeAttribute('aria-current');});
  $('#page-title').textContent=views[view]; document.title=`RouteFlow · ${views[view]}`;
  $('#start-stack').hidden=view!=='services';
  renderNotice();
  if(view==='data') loadTable(); if(view==='logs') loadLogs();
}
let tableRequest=0, logRequest=0;
async function loadTable() {
  const request=++tableRequest, table=state.table, page=state.page;
  $('#data-state').textContent='Đang đọc dữ liệu…'; $('#data-table thead').replaceChildren(); $('#data-table tbody').replaceChildren();
  $('#previous-page').disabled=true; $('#next-page').disabled=true;
  try {
    const data=await api(`/api/tables/${encodeURIComponent(table)}?page=${page}`);
    if(request!==tableRequest) return;
    const columns=Object.keys(data.rows[0] || {});
    const header=document.createElement('tr');
    for(const column of columns) {const cell=document.createElement('th');cell.textContent=column;header.append(cell);}
    $('#data-table thead').append(header);
    for(const row of data.rows) {const tr=document.createElement('tr');for(const key of columns){const cell=document.createElement('td');const value=row[key];const text=typeof value==='object'&&value!==null ? JSON.stringify(value) : String(value??'—'); cell.textContent=text;cell.title=text;tr.append(cell);}$('#data-table tbody').append(tr);}
    $('#data-state').textContent=columns.length ? '' : 'Bảng hiện chưa có dữ liệu.';
    $('#data-caption').textContent=`${data.name} · ${number(data.total)} dòng · chỉ đọc`;
    $('#page-label').textContent=`Trang ${state.page}`;
    $('#previous-page').disabled=state.page<=1; $('#next-page').disabled=state.page*20>=data.total;
  } catch(error) {if(request!==tableRequest)return;$('#data-state').textContent=error.message;$('#data-caption').textContent='Không đọc được bảng.';}
}
function renderLogs() {
  const search=$('#log-search').value.toLowerCase();
  $('#log-output').textContent=state.log.split('\n').filter(line=>line.toLowerCase().includes(search)).join('\n') || 'Không có dòng phù hợp.';
}
async function loadLogs(background=false) {
  const request=++logRequest, output=$('#log-output'), scroll=output.scrollTop;
  const following=output.scrollHeight-output.clientHeight-scroll<24;
  $('#load-logs').disabled=true;
  if(background!==true) output.textContent='Đang tải nhật ký…';
  try {const result=await api(`/api/logs/${encodeURIComponent(state.logService)}`);if(request!==logRequest)return;state.log=result.content;renderLogs();output.scrollTop=background===true && !following ? scroll : output.scrollHeight;}
  catch(error) {if(request!==logRequest)return;state.log=error.message;renderLogs();}
  finally {if(request===logRequest)$('#load-logs').disabled=false;}
}
async function runAction(target, action) {
  if(state.busy) return;
  const label=target==='stack' ? 'toàn bộ RouteFlow' : target==='docker' ? 'Docker Desktop' : state.overview?.services.find(s=>s.id===target)?.name || target;
  const verb={start:'Bật',stop:'Dừng',restart:'Khởi động lại'}[action];
  state.busy=true;renderServices();$('#start-stack').disabled=true;
  const banner=$('#job-banner');banner.hidden=false;banner.className='job-banner';banner.textContent=`${verb} ${label}… Đang thực hiện, có thể mất vài phút.`;
  try {
    let job=await api(`/api/actions/${encodeURIComponent(target)}`,{method:'POST',body:JSON.stringify({action})});
    const started=Date.now();
    while(job.status==='running') {await sleep(1200);job=await api(`/api/jobs/${job.id}`);banner.textContent=`${verb} ${label}… ${Math.floor((Date.now()-started)/1000)} giây. Trạng thái sẽ cập nhật khi hoàn tất.`;}
    banner.className=`job-banner ${job.status}`;
    banner.textContent=job.status==='success' ? `${verb} ${label} thành công.` : `Không hoàn tất thao tác: ${job.output}`;
    if(job.status==='success') {setTimeout(()=>{if(!state.busy)banner.hidden=true;},5000);}
  } catch(error) {banner.className='job-banner failed';banner.textContent=error.message;}
  finally {state.busy=false;await refresh();if(state.view==='logs') await loadLogs();}
}
let pendingAction;
document.addEventListener('click',event=>{
  const logButton=event.target.closest('[data-logs]');if(logButton){state.logService=logButton.dataset.logs;$('#log-select').value=state.logService;if(location.hash==='#logs')loadLogs();else location.hash='logs';return;}
  const button=event.target.closest('[data-action]');if(!button || button.disabled || state.busy)return;
  const {target,action}=button.dataset;
  if(action==='stop' || action==='restart') {
    pendingAction={target,action};const label=target==='stack'?'toàn bộ RouteFlow':state.overview?.services.find(s=>s.id===target)?.name||target;
    $('#confirm-title').textContent=`${action==='stop'?'Dừng':'Khởi động lại'} ${label}?`;
    $('#confirm-description').textContent='Dịch vụ có thể tạm thời không truy cập được. Volume và dữ liệu đã lưu sẽ được giữ nguyên.';
    $('#accept-confirm').textContent=action==='stop'?'Dừng dịch vụ':'Khởi động lại';$('#confirm-dialog').showModal();
  } else runAction(target,action);
});
$('#cancel-confirm').addEventListener('click',()=>$('#confirm-dialog').close());
$('#accept-confirm').addEventListener('click',()=>{const action=pendingAction;$('#confirm-dialog').close();if(action)runAction(action.target,action.action);});
$('#refresh').addEventListener('click',()=>refresh(true));
$('#service-search').addEventListener('input',renderServices);$('#service-filter').addEventListener('change',renderServices);
$('#table-select').addEventListener('change',event=>{state.table=event.target.value;state.page=1;loadTable();});
$('#load-table').addEventListener('click',loadTable);
$('#previous-page').addEventListener('click',()=>{state.page--;loadTable();});$('#next-page').addEventListener('click',()=>{state.page++;loadTable();});
$('#log-select').addEventListener('change',event=>{state.logService=event.target.value;loadLogs();});
$('#load-logs').addEventListener('click',loadLogs);$('#log-search').addEventListener('input',renderLogs);
$('#copy-logs').addEventListener('click',async()=>{try{await navigator.clipboard.writeText($('#log-output').textContent);toast('Đã sao chép log.');}catch{toast('Không sao chép được. Bạn có thể chọn và sao chép nội dung trong khung log.');}});
window.addEventListener('hashchange',navigate);
async function init() {
  try {
    const tables=await api('/api/tables');
    $('#table-select').innerHTML=tables.map(table=>`<option value="${table.id}">${escape(table.name)} · ${table.database}</option>`).join('');
    const services=[['api','Delivery API'],['source','Source PostgreSQL'],['warehouse','Analytics Warehouse'],['pubsub','Pub/Sub Emulator'],['relay','Outbox Relay'],['consumer','Event Consumer'],['spark-master','Spark Master'],['spark-worker','Spark Worker']];
    $('#log-select').innerHTML=services.map(([id,name])=>`<option value="${id}">${name}</option>`).join('');
    navigate();await refresh();
  } catch(error) {$('#connection-error').hidden=false;$('#connection-error').textContent=`Không mở được Console: ${error.message}`;}
}
init();
setInterval(()=>{if(!document.hidden){refresh();if(state.view==='logs')loadLogs(true);}},15000);
