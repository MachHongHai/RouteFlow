"use strict";
let activeGeneration=null, generationSnapshot=null, systemFlow=null, selectedStep='raw';
let generationPolling=false, generationVersion=0, generationRequest=crypto.randomUUID();
let generationSubmitting=false, generationOptionsReady=false;
let generationSubmitError='';
const phaseLabels={waiting:'Chờ xử lý',running:'Đang xử lý',success:'Đã xử lý',failed:'Lỗi',skipped:'Chưa chạy',unknown:'Chưa có số liệu'};
const phaseClass=value=>({success:'running',running:'starting',failed:'failed'}[value]||'');

function syncGenerationControls() {
  const required=['source','warehouse','pubsub','api','relay','consumer'];
  const ready=required.every(id=>state.overview?.services.some(s=>s.id===id && s.state==='running' && !/unhealthy|starting/.test(s.status||'')));
  $('#generate-submit').disabled=!generationOptionsReady || !ready || state.busy || state.generating || generationSubmitting || state.overview?.storage.pinned_to_e===false;
  $('#generate-submit').textContent=generationSubmitting ? 'Đang gửi…' : state.generating ? 'Đang chạy một đợt…' : 'Tạo dữ liệu';
  const reason=!state.overview ? 'Đang chờ trạng thái dịch vụ.' : state.overview.storage.pinned_to_e!==true ? 'Kiểm tra cấu hình Docker trên E trước khi tạo dữ liệu.' : !ready ? 'Bật đủ Source, Warehouse, Pub/Sub, API, Relay và Consumer để tạo dữ liệu.' : '';
  $('#generation-readiness').hidden=!reason; $('#generation-readiness').textContent=reason;
}

async function generationView() {
  if(!generationOptionsReady) {
    try {
      const options=await api('/api/generation/options');
      $('#generation-date').value=options.default_date;
      $('#generation-date').min=options.min_date; $('#generation-date').max=options.max_date;
      $('#generation-orders').max=options.max_orders; generationOptionsReady=true;
    } catch(error) {showGenerationError(error.message);}
  }
  syncGenerationControls(); await pollGeneration();
}

function showGenerationError(message) {
  $('#generation-error').hidden=!message;
  $('#generation-error').textContent=message||'';
}

async function pollGeneration() {
  if(generationPolling) return;
  generationPolling=true; const version=generationVersion;
  try {
    const [runs,flow]=await Promise.all([api('/api/generation'),api('/api/flow')]);
    if(version!==generationVersion)return;
    if(activeGeneration===null) activeGeneration=runs[0]?.id||'';
    const options='<option value="">Toàn bộ pipeline</option>'+runs.map(run=>`<option value="${run.id}">${date(run.started_at,true)} · ${number(run.options.orders)} đơn · ${run.id.slice(0,8)}</option>`).join('');
    if($('#generation-runs').innerHTML!==options) {$('#generation-runs').innerHTML=options;$('#generation-runs').value=activeGeneration;}
    state.generating=runs.some(run=>run.status==='running');
    systemFlow=flow;
    const current=activeGeneration ? await api(`/api/generation/${encodeURIComponent(activeGeneration)}`) : null;
    if(version!==generationVersion)return;
    generationSnapshot=current; renderGeneration(); syncControls(); syncGenerationControls();
  } catch(error) {showGenerationError(`Chưa cập nhật được luồng: ${error.message}`);}
  finally {generationPolling=false;}
}

function renderGeneration() {
  const focusedStep=document.activeElement?.dataset.pipelineStep;
  const job=generationSnapshot, progress=job?.progress, source=progress?.source??(job?null:systemFlow?.source), warehouse=progress?.warehouse??(job?null:systemFlow?.warehouse);
  const expected=source?.events, generated=source?.orders, target=job?.options.orders??generated;
  const eventsKnown=source!=null, rawKnown=warehouse!=null;
  const publishState=!eventsKnown?'unknown':expected>0&&source.published===expected?'success':job?.phases.publish||'waiting';
  const rawState=!rawKnown?'unknown':expected>0&&warehouse.events===expected?'success':job?.phases.raw||'waiting';
  const dbt=systemFlow?.runs.find(run=>run.pipeline_name==='dbt');
  const dbtState=job?.phases.dbt||(!dbt?'unknown':dbt.status==='RUNNING'?'running':dbt.status==='FAILED'?'failed':warehouse?.facts===source?.orders&&source?.orders>0?'success':'waiting');
  const nodes=[
    ['generate',job?'Generate':'Nghiệp vụ',job?`${number(generated)} / ${number(target)} đơn`:`${number(generated)} đơn`,job?.phases.generate||(eventsKnown?'success':'unknown')],
    ['outbox','Source / Outbox',`${number(expected)} sự kiện`,eventsKnown&&expected>0?'success':job?.phases.generate||'unknown'],
    ['publish','Pub/Sub',`${number(source?.published)} / ${number(expected)} đã publish`,publishState],
    ['raw','Consumer → RAW',`${number(warehouse?.events)} / ${number(expected)} đã nhận`,rawState],
    ['dbt','dbt → Mart',`${number(warehouse?.facts)} / ${number(target)} đơn`,dbtState]
  ];
  $('#pipeline-track').innerHTML=nodes.map(([key,label,count,status],index)=>`<li><button type="button" class="pipeline-step ${phaseClass(status)}" data-pipeline-step="${key}" aria-pressed="${key===selectedStep}"><span class="step-number">${index+1}</span><span class="step-title">${label}</span><span class="step-count">${count}</span><span class="step-state">${phaseLabels[status]||status}</span></button></li>`).join('');
  if(focusedStep) $('#pipeline-track').querySelector(`[data-pipeline-step="${focusedStep}"]`)?.focus({preventScroll:true});
  const status=job ? {running:job.phase==='generate'?'Đang tạo đơn':job.phase==='dbt'?'Đang chạy dbt':'Đang chờ publish / ingest',success:job.options.transform?'Hoàn thành · đã kiểm tra mart':'Hoàn thành đến RAW · không chạy dbt',failed:'Đợt chạy có lỗi',interrupted:'Theo dõi đã bị ngắt'}[job.status] : 'Toàn bộ dữ liệu hiện có';
  $('#generation-status').textContent=status;
  $('#generation-id').hidden=!job;
  $('#generation-id').textContent=job ? `Mã đợt: ${job.id} · ngày UTC ${job.options.business_date} · seed ${job.options.seed}` : '';
  showGenerationError(job?.error||generationSubmitError);
  $('#ingestion-bar').hidden=!job||!expected;
  $('#ingestion-count').textContent=`Ingest: ${number(warehouse?.events)} / ${number(expected)} sự kiện`;
  $('#flow-updated').textContent=`Cập nhật ${date(job?.checked_at||systemFlow?.checked_at)}`;
  $('#ingestion-progress').max=Math.max(1,expected||1); $('#ingestion-progress').value=warehouse?.events||0;
  const dlq=progress?.dlq;
  const descriptions={
    generate:`Bộ sinh tạo đơn mẫu và diễn biến giao hàng qua nghiệp vụ của dự án. Đây là dữ liệu được thêm vào Source, không phải số HTTP request đến Delivery API. ${job?`Kết quả đợt: ${Object.entries(job.outcome||{}).map(([name,value])=>`${name}: ${number(value)}`).join(', ')||'chưa hoàn tất'}.`:''}`,
    outbox:`Source đã ghi ${number(expected)} sự kiện vào transactional outbox. ${eventsKnown?number(expected-source.published):'—'} sự kiện chưa đánh dấu publish; ${number(source?.retrying)} đang có lỗi retry.`,
    publish:`${number(source?.published)} / ${number(expected)} sự kiện đã có published_at sau xác nhận của broker. Đây không phải số message đang nằm trong hàng đợi Pub/Sub.`,
    raw:`${number(warehouse?.events)} / ${number(expected)} sự kiện đã ghi RAW. Consumer ghi archive trước RAW. ${job?`DLQ của riêng đợt: ${number(dlq)}.`:'Chọn một đợt để xem tiến độ theo mã tương quan.'}`,
    dbt:`Mart hiện có ${number(warehouse?.facts)} / ${number(target)} đơn ${job?'thuộc đợt này':'trong hệ thống'}. ${job&&!job.options.transform?'Đợt này không yêu cầu chạy dbt; một lần dbt sau đó vẫn có thể đưa dữ liệu này vào mart.':dbt?`dbt gần nhất: ${dbt.status}, ${date(dbt.created_at,true)}.`:'Chưa có bản ghi chạy dbt.'}`
  };
  $('#step-detail-title').textContent=nodes.find(row=>row[0]===selectedStep)?.[1]||'Luồng xử lý';
  $('#step-detail-body').textContent=descriptions[selectedStep];
  const spark=systemFlow?.runs.find(run=>run.pipeline_name==='spark_gps');
  $('#gps-flow').innerHTML=`<div><span class="meta">Archive · GPS đã vào RAW ${job?'của đợt':''}</span><strong>${number(warehouse?.gps)} điểm</strong></div><span class="flow-arrow" aria-hidden="true">→</span><div><span class="meta">Spark gần nhất</span><strong>${spark?escape({SUCCESS:'Thành công',FAILED:'Thất bại',RUNNING:'Đang chạy'}[spark.status]||spark.status):'Chưa chạy'}</strong><small>${spark?date(spark.created_at,true):'Job độc lập'}</small></div><span class="flow-arrow" aria-hidden="true">→</span><div><span class="meta">Parquet → GPS marts</span><strong>${number(systemFlow?.warehouse?.gps_summary)} điểm tổng hợp</strong><small>Toàn bộ hệ thống</small></div>`;
  $('#generation-events').hidden=!job;
  $('#generation-events-body').innerHTML=(progress?.events||[]).map(event=>`<tr><td>${escape(event.event_type)}</td><td title="${escape(event.event_id)}"><code>${escape(event.event_id.slice(0,8))}</code></td><td>${event.published_at?'Đã publish':'Chờ publish'}</td><td>${event.received===true?'Đã nhận':event.received===false?'Chưa nhận':'Chưa đọc được'}</td></tr>`).join('')||'<tr><td colspan="4">Chưa ghi nhận sự kiện của đợt.</td></tr>';
}

$('#generation-form').addEventListener('submit',async event=>{
  event.preventDefault(); if(generationSubmitting||state.generating)return;
  generationSubmitting=true; generationSubmitError=''; showGenerationError(''); syncGenerationControls();
  try {
    const body={request_id:generationRequest,orders:Number($('#generation-orders').value),seed:Number($('#generation-seed').value),business_date:$('#generation-date').value,transform:$('#generation-transform').checked};
    const job=await api('/api/generation',{method:'POST',body:JSON.stringify(body)});
    activeGeneration=job.id; generationVersion++; generationRequest=crypto.randomUUID();
    state.generating=job.status==='running'; await pollGeneration();
  } catch(error) {generationSubmitError=`Chưa tạo được đợt: ${error.message}`;showGenerationError(generationSubmitError);}
  finally {generationSubmitting=false;syncControls();syncGenerationControls();}
});
$('#generation-form').addEventListener('input',()=>{if(!generationSubmitting)generationRequest=crypto.randomUUID();});
$('#generation-runs').addEventListener('change',event=>{activeGeneration=event.target.value;generationVersion++;pollGeneration();});
$('#pipeline-track').addEventListener('click',event=>{const button=event.target.closest('[data-pipeline-step]');if(button){selectedStep=button.dataset.pipelineStep;renderGeneration();$('#pipeline-track').querySelector(`[data-pipeline-step="${selectedStep}"]`)?.focus({preventScroll:true});}});
if(state.view==='generate')generationView();
setInterval(()=>{if(state.view==='generate'&&!document.hidden)pollGeneration();},2000);
