"use strict";
const databaseState={database:'source',catalog:null,table:null,version:0,loading:false,querying:false,tab:'result',drafts:{}};

async function databaseView(force=false) {
  if(databaseState.loading||databaseState.querying)return;
  if(databaseState.catalog&&!force)return;
  databaseState.loading=true;
  const version=++databaseState.version, database=databaseState.database;
  $('#database-select').value=database;
  $('#database-connection').textContent='Đang đọc schema…';
  $('#database-reload').disabled=true;
  $('#database-select').disabled=true;
  try {
    const catalog=await api(`/api/database/${database}/catalog`);
    if(version!==databaseState.version)return;
    databaseState.catalog=catalog;
    $('#database-connection').textContent=`Đã kết nối · ${number(catalog.tables.length)} bảng / view`;
    renderSchema();
    const target=databaseState.table||catalog.tables.find(t=>t.name===(database==='source'?'orders':'fact_order'))||catalog.tables[0];
    if(target) await selectDatabaseTable(target.schema,target.name,!databaseState.drafts[database]);
    else $('#query-status').textContent='Chưa có bảng trong database.';
    if(databaseState.drafts[database])$('#sql-editor').value=databaseState.drafts[database];
  } catch(error) {showQueryError(error.message);$('#database-connection').textContent='Chưa kết nối';}
  finally {databaseState.loading=false;$('#database-reload').disabled=false;$('#database-select').disabled=false;}
}

function renderSchema() {
  const search=$('#database-search').value.toLocaleLowerCase('vi-VN');
  const tables=databaseState.catalog?.tables.filter(table=>`${table.schema}.${table.name}`.toLocaleLowerCase('vi-VN').includes(search))||[];
  const schemas=[...new Set(tables.map(table=>table.schema))];
  $('#database-tables').innerHTML=schemas.map(schema=>`<details open class="schema-group"><summary>${escape(schema)} <span>${tables.filter(t=>t.schema===schema).length}</span></summary>${tables.filter(t=>t.schema===schema).map(table=>`<button class="schema-table" data-schema="${escape(schema)}" data-table="${escape(table.name)}" aria-pressed="${databaseState.table?.schema===schema&&databaseState.table?.name===table.name}"><svg viewBox="0 0 16 16" aria-hidden="true"><rect x="2" y="2" width="12" height="12" rx="1"/><path d="M2 6h12M6 6v8"/></svg><span>${escape(table.name)}</span>${table.kind==='VIEW'?'<small>view</small>':''}</button>`).join('')}</details>`).join('')||'<p class="meta">Không có bảng phù hợp.</p>';
}

async function selectDatabaseTable(schema,name,preview=true) {
  const table=databaseState.catalog?.tables.find(t=>t.schema===schema&&t.name===name);
  if(!table)return;
  databaseState.table=table;
  $('#database-table-name').textContent=`${schema}.${name}`;
  renderSchema();renderColumns();
  if(preview) {
    const quote=value=>'"'+value.replaceAll('"','""')+'"';
    $('#sql-editor').value=`SELECT *\nFROM ${quote(schema)}.${quote(name)}\nLIMIT 100;`;
    await runDatabaseQuery();
  }
}

function renderColumns() {
  const table=databaseState.table;
  const columns=databaseState.catalog?.columns.filter(c=>c.schema===table?.schema&&c.table===table?.name)||[];
  $('#database-columns').innerHTML=columns.map(column=>`<tr><td><code>${escape(column.name)}</code></td><td>${escape(column.type)}</td><td>${column.primary_key?'<span class="key-label">PK</span> ':''}${column.nullable==='NO'?'NOT NULL':'nullable'}</td><td title="${escape(column.default||'')}"><code>${escape(column.default??'—')}</code></td></tr>`).join('')||'<tr><td colspan="4">Chọn bảng để xem cột.</td></tr>';
}

function showQueryError(message='') {$('#query-error').textContent=message;$('#query-error').hidden=!message;}
function resultTab(tab) {
  databaseState.tab=tab;
  $('#result-tab').setAttribute('aria-selected',tab==='result');
  $('#columns-tab').setAttribute('aria-selected',tab==='columns');
  $('#query-result-panel').hidden=tab!=='result';$('#query-columns-panel').hidden=tab!=='columns';
}

async function runDatabaseQuery() {
  if(databaseState.querying)return;
  const statement=$('#sql-editor').value.trim();if(!statement){showQueryError('Nhập truy vấn SELECT hoặc WITH trước khi chạy.');return;}
  const version=databaseState.version,database=databaseState.database;
  databaseState.drafts[database]=statement;
  databaseState.querying=true;$('#query-run').disabled=true;$('#query-run').textContent='Đang truy vấn…';
  $('#database-select').disabled=true;$('#database-reload').disabled=true;
  $('#query-result thead').replaceChildren();$('#query-result tbody').replaceChildren();$('#query-result-note').textContent='';
  $('#query-status').textContent='Đang chạy…';showQueryError();
  try {
    const result=await api(`/api/database/${database}/query`,{method:'POST',body:JSON.stringify({sql:statement,limit:Number($('#query-limit').value)})});
    if(version!==databaseState.version)return;
    $('#query-result thead').replaceChildren();$('#query-result tbody').replaceChildren();
    const header=document.createElement('tr');
    for(const column of result.columns){const th=document.createElement('th');th.textContent=column;header.append(th);}
    $('#query-result thead').append(header);
    for(const row of result.rows){const tr=document.createElement('tr');for(const value of row){const td=document.createElement('td');td.textContent=value===null?'NULL':String(value);td.title=value===null?'NULL':String(value);if(value===null)td.classList.add('null-value');tr.append(td);}$('#query-result tbody').append(tr);}
    $('#query-status').textContent=`${number(result.row_count)} dòng · ${number(result.duration_ms)} ms`;
    $('#query-result-note').textContent=[!result.row_count?'Truy vấn thành công, không có dòng kết quả.':'',result.truncated?`Kết quả được giới hạn; thêm WHERE hoặc LIMIT để thu hẹp truy vấn.`:'',result.clipped?'Một số giá trị dài / kết quả lớn đã được rút gọn.':''].filter(Boolean).join(' ');
    resultTab('result');
  } catch(error) {if(version!==databaseState.version)return;showQueryError(error.message);$('#query-status').textContent='Truy vấn không thành công';}
  finally {databaseState.querying=false;$('#query-run').disabled=false;$('#database-select').disabled=false;$('#database-reload').disabled=false;$('#query-run').innerHTML='Chạy truy vấn <span aria-hidden="true">→</span>';}
}

async function changeDatabase(database,table=null) {
  if(databaseState.querying||databaseState.loading)return;
  databaseState.drafts[databaseState.database]=$('#sql-editor').value;
  if(table)delete databaseState.drafts[database];
  databaseState.database=database;databaseState.catalog=null;databaseState.table=table;
  $('#database-search').value='';$('#query-result thead').replaceChildren();$('#query-result tbody').replaceChildren();
  $('#query-result-note').textContent='';$('#database-tables').replaceChildren();showQueryError();
  await databaseView(true);
}

$('#database-select').addEventListener('change',event=>changeDatabase(event.target.value));
$('#database-reload').addEventListener('click',()=>databaseView(true));
$('#database-search').addEventListener('input',renderSchema);
$('#database-tables').addEventListener('click',event=>{const button=event.target.closest('[data-schema]');if(button&&!databaseState.querying)selectDatabaseTable(button.dataset.schema,button.dataset.table);});
$('#query-run').addEventListener('click',runDatabaseQuery);
$('#sql-editor').addEventListener('keydown',event=>{if((event.ctrlKey||event.metaKey)&&event.key==='Enter'){event.preventDefault();runDatabaseQuery();}});
$('#sql-editor').addEventListener('input',()=>{databaseState.drafts[databaseState.database]=$('#sql-editor').value;});
$('#result-tab').addEventListener('click',()=>resultTab('result'));
$('#columns-tab').addEventListener('click',()=>resultTab('columns'));
document.addEventListener('click',event=>{
  const link=event.target.closest('[data-database-link]');if(!link)return;
  event.preventDefault();
  const [schema,name]=link.dataset.table.split('.');
  const database=link.dataset.databaseLink;
  // Keep pipeline links explicit: select the requested table rather than a previous SQL draft.
  delete databaseState.drafts[database];
  if(databaseState.database===database&&databaseState.catalog){selectDatabaseTable(schema,name);location.hash='data';}
  else {changeDatabase(database,{schema,name});location.hash='data';}
});
if(state.view==='data')databaseView();
