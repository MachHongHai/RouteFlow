"use strict";
let activeGeneration = null,
  generationSnapshot = null,
  systemFlow = null,
  selectedStep = "raw";
let generationPolling = false,
  generationVersion = 0,
  generationRequest = crypto.randomUUID();
let generationSubmitting = false,
  generationOptionsReady = false;
let generationSubmitError = "";
const phaseLabels = {
  waiting: "Chờ xử lý",
  running: "Đang xử lý",
  success: "Đã xử lý",
  failed: "Lỗi",
  skipped: "Chưa chạy",
  unknown: "Chưa có số liệu",
};
let previousFlowCounts = null,
  previousFlowId = null;
const flowSymbols = {
  generate: '<path d="M5 7h14M5 12h8M5 17h8M18 13v8m-4-4h8"/>',
  outbox:
    '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 4 16 4 16 0V5M4 12c0 4 16 4 16 0"/>',
  publish:
    '<path d="M5 12h14m-4-4 4 4-4 4"/><circle cx="4" cy="5" r="2"/><circle cx="4" cy="19" r="2"/><path d="m6 6 3 4m-3 8 3-4M20 3v4m0 10v4"/>',
  raw: '<path d="M4 4h16v16H4zM4 9h16M9 9v11M14 9v11M4 14h16"/>',
  dbt: '<circle cx="5" cy="5" r="2"/><circle cx="5" cy="19" r="2"/><circle cx="19" cy="12" r="3"/><path d="m7 6 9 5m-9 7 9-5"/>',
};
const flowIcon = (key) => `<svg viewBox="0 0 24 24" aria-hidden="true">${flowSymbols[key]}</svg>`;

function syncGenerationControls() {
  const required = ["source", "warehouse", "pubsub", "api", "relay", "consumer"];
  const ready = required.every((id) =>
    state.overview?.services.some(
      (s) => s.id === id && s.state === "running" && !/unhealthy|starting/.test(s.status || ""),
    ),
  );
  $("#generate-submit").disabled =
    !generationOptionsReady ||
    !ready ||
    state.busy ||
    state.generating ||
    generationSubmitting ||
    !storageReady();
  $("#generate-submit").textContent = generationSubmitting
    ? "Đang gửi…"
    : state.generating
      ? "Đang chạy một đợt…"
      : "Tạo dữ liệu";
  const reason = !state.overview
    ? "Đang chờ trạng thái dịch vụ."
    : !storageReady()
      ? "Kiểm tra cấu hình Docker trên E trước khi tạo dữ liệu."
      : !ready
        ? "Bật đủ Source, Warehouse, Pub/Sub, API, Relay và Consumer để tạo dữ liệu."
        : "";
  $("#generation-readiness").hidden = !reason;
  $("#generation-readiness").textContent = reason;
}

async function generationView() {
  if (!generationOptionsReady) {
    try {
      const options = await api("/api/generation/options");
      $("#generation-date").value = options.default_date;
      $("#generation-date").min = options.min_date;
      $("#generation-date").max = options.max_date;
      $("#generation-orders").max = options.max_orders;
      generationOptionsReady = true;
    } catch (error) {
      showGenerationError(error.message);
    }
  }
  syncGenerationControls();
  await pollGeneration();
}

function showGenerationError(message) {
  $("#generation-error").hidden = !message;
  $("#generation-error").textContent = message || "";
}

async function pollGeneration() {
  if (generationPolling) return;
  generationPolling = true;
  const version = generationVersion;
  try {
    const [runs, flow] = await Promise.all([api("/api/generation"), api("/api/flow")]);
    if (version !== generationVersion) return;
    if (activeGeneration === null) activeGeneration = runs[0]?.id || "";
    const options =
      '<option value="">Toàn bộ pipeline</option>' +
      runs
        .map(
          (run) =>
            `<option value="${run.id}">${date(run.started_at, true)} · ${number(run.options.orders)} đơn · ${run.id.slice(0, 8)}</option>`,
        )
        .join("");
    if ($("#generation-runs").innerHTML !== options) {
      $("#generation-runs").innerHTML = options;
      $("#generation-runs").value = activeGeneration;
    }
    state.generating = runs.some((run) => run.status === "running");
    systemFlow = flow;
    const current = activeGeneration
      ? await api(`/api/generation/${encodeURIComponent(activeGeneration)}`)
      : null;
    if (version !== generationVersion) return;
    generationSnapshot = current;
    renderGeneration();
    syncControls();
    syncGenerationControls();
  } catch (error) {
    showGenerationError(`Chưa cập nhật được luồng: ${error.message}`);
  } finally {
    generationPolling = false;
  }
}

function renderGeneration() {
  const focusedStep = document.activeElement?.dataset.pipelineStep;
  const job = generationSnapshot,
    progress = job?.progress,
    source = progress?.source ?? (job ? null : systemFlow?.source),
    warehouse = progress?.warehouse ?? (job ? null : systemFlow?.warehouse);
  const expected = source?.events,
    generated = source?.orders,
    target = job?.options.orders ?? generated;
  const eventsKnown = source != null,
    rawKnown = warehouse != null;
  const publishState = !eventsKnown
    ? "unknown"
    : expected > 0 && source.published === expected
      ? "success"
      : job?.phases.publish || "waiting";
  const rawState = !rawKnown
    ? "unknown"
    : expected > 0 && warehouse.events === expected
      ? "success"
      : job?.phases.raw || "waiting";
  const dbt = systemFlow?.runs.find((run) => run.pipeline_name === "dbt");
  const dbtState =
    job?.phases.dbt ||
    (!dbt
      ? "unknown"
      : dbt.status === "RUNNING"
        ? "running"
        : dbt.status === "FAILED"
          ? "failed"
          : warehouse?.facts === source?.orders && source?.orders > 0
            ? "success"
            : "waiting");
  const nodes = [
    [
      "generate",
      "Generate",
      "Tạo đơn mẫu",
      generated,
      `đơn${job ? " / " + number(target) : ""}`,
      job?.phases.generate || (eventsKnown ? "success" : "unknown"),
      "Đã tạo",
      "source",
      "public.orders",
    ],
    [
      "outbox",
      "Source",
      "PostgreSQL · Outbox",
      expected,
      "sự kiện đã ghi",
      eventsKnown && expected > 0 ? "success" : job?.phases.generate || "unknown",
      "Đã ghi",
      "source",
      "public.outbox_events",
    ],
    [
      "publish",
      "Pub/Sub",
      "Outbox relay",
      source?.published,
      "sự kiện đã phát",
      publishState,
      "Đã publish",
      "source",
      "public.outbox_events",
    ],
    [
      "raw",
      "Consumer",
      "Archive + RAW",
      warehouse?.events,
      "sự kiện đã nhận",
      rawState,
      "Đã nhận",
      "warehouse",
      "public.raw_events",
    ],
    [
      "dbt",
      "dbt",
      "Analytics mart",
      warehouse?.facts,
      `đơn${target != null ? " / " + number(target) : ""}`,
      dbtState,
      "Đã dựng mart",
      "warehouse",
      "analytics.fact_order",
    ],
  ];
  const currentCounts = nodes.map((node) => node[3]);
  $("#pipeline-track").innerHTML = nodes
    .map(([key, label, subtitle, count, unit, status, done], index) => {
      const advanced =
        job?.status === "running" &&
        [2, 3].includes(index) &&
        previousFlowId === job.id &&
        count > previousFlowCounts?.[index];
      return `<li class="stage-${status}"><button type="button" class="pipeline-step" data-pipeline-step="${key}" aria-pressed="${key === selectedStep}"><span class="node-symbol">${flowIcon(key)}<span class="node-index">${index + 1}</span></span><span class="step-title">${label}</span><span class="step-subtitle">${subtitle}</span><strong class="step-count">${number(count)}</strong><span class="step-unit">${unit}</span><span class="step-state"><span class="state-dot" aria-hidden="true"></span>${status === "success" ? done : phaseLabels[status] || status}</span></button>${advanced ? '<span class="connector-signal" aria-hidden="true"></span>' : ""}</li>`;
    })
    .join("");
  previousFlowCounts = currentCounts;
  previousFlowId = job?.id || "";
  if (focusedStep)
    $("#pipeline-track")
      .querySelector(`[data-pipeline-step="${focusedStep}"]`)
      ?.focus({ preventScroll: true });
  const status = job
    ? {
        running:
          job.phase === "generate"
            ? "Đang tạo đơn"
            : job.phase === "dbt"
              ? "Đang chạy dbt"
              : "Đang chờ publish / ingest",
        success: job.options.transform
          ? "Hoàn thành · đã kiểm tra mart"
          : "Hoàn thành đến RAW · không chạy dbt",
        failed: "Đợt chạy có lỗi",
        interrupted: "Theo dõi đã bị ngắt",
      }[job.status]
    : "Toàn bộ dữ liệu hiện có";
  $("#generation-status").textContent = status;
  $("#generation-status").className = `run-status ${job?.status || "global"}`;
  $("#generation-id").hidden = !job;
  $("#generation-id").textContent = job
    ? `Mã đợt: ${job.id} · ngày UTC ${job.options.business_date} · seed ${job.options.seed}`
    : "";
  showGenerationError(job?.error || generationSubmitError);
  $("#ingestion-bar").hidden = !expected || !rawKnown;
  $("#ingestion-count").textContent =
    `Ingest: ${number(warehouse?.events)} / ${number(expected)} sự kiện`;
  $("#flow-updated").textContent = `Cập nhật ${date(job?.checked_at || systemFlow?.checked_at)}`;
  $("#ingestion-progress").max = Math.max(1, expected || 1);
  $("#ingestion-progress").value = warehouse?.events || 0;
  $("#flow-percent").textContent =
    expected && rawKnown ? `${Math.round((warehouse.events / expected) * 100)}%` : "—";
  const received = rawKnown && eventsKnown ? Math.min(expected, warehouse.events) : 0;
  const publishing = eventsKnown && rawKnown ? Math.max(0, source.published - received) : 0;
  const waiting = eventsKnown ? Math.max(0, expected - source.published) : 0;
  const segment = (value) =>
    expected ? Math.max(0, Math.min(1000, (value / expected) * 1000)) : 0;
  $("#flow-distribution").innerHTML =
    `<svg viewBox="0 0 1000 8" preserveAspectRatio="none"><rect width="1000" height="8" class="segment-empty"/><rect width="${segment(received)}" height="8" class="segment-received"/><rect x="${segment(received)}" width="${segment(publishing)}" height="8" class="segment-transit"/><rect x="${segment(received + publishing)}" width="${segment(waiting)}" height="8" class="segment-waiting"/></svg>`;
  $("#flow-legend").innerHTML =
    `<span><i class="legend-received"></i>Đã vào RAW <strong>${number(warehouse?.events)}</strong></span><span><i class="legend-transit"></i>Đã phát, chờ RAW <strong>${eventsKnown && rawKnown ? number(publishing) : "—"}</strong></span><span><i class="legend-waiting"></i>Chờ publish <strong>${eventsKnown ? number(waiting) : "—"}</strong></span>`;
  const dlq = progress?.dlq ?? (job ? null : state.overview?.data.source?.dlq);
  $("#flow-health").textContent =
    dlq > 0
      ? `${number(dlq)} sự kiện trong DLQ`
      : dlq === 0
        ? "Không có lỗi DLQ" + (job ? " trong đợt" : "")
        : "Chưa đọc được DLQ";
  $("#flow-health").className = dlq > 0 ? "flow-error" : "meta";
  const descriptions = {
    generate: `Bộ sinh tạo đơn mẫu và diễn biến giao hàng qua nghiệp vụ của dự án. Đây là dữ liệu được thêm vào Source, không phải số HTTP request đến Delivery API. ${
      job
        ? `Kết quả đợt: ${
            Object.entries(job.outcome || {})
              .map(([name, value]) => `${name}: ${number(value)}`)
              .join(", ") || "chưa hoàn tất"
          }.`
        : ""
    }`,
    outbox: `Source đã ghi ${number(expected)} sự kiện vào transactional outbox. ${eventsKnown ? number(expected - source.published) : "—"} sự kiện chưa đánh dấu publish; ${number(source?.retrying)} đang có lỗi retry.`,
    publish: `${number(source?.published)} / ${number(expected)} sự kiện đã có published_at sau xác nhận của broker. Đây không phải số message đang nằm trong hàng đợi Pub/Sub.`,
    raw: `${number(warehouse?.events)} / ${number(expected)} sự kiện đã ghi RAW. Consumer ghi archive trước RAW. ${job ? `DLQ của riêng đợt: ${number(dlq)}.` : "Chọn một đợt để xem tiến độ theo mã tương quan."}`,
    dbt: `Mart hiện có ${number(warehouse?.facts)} / ${number(target)} đơn ${job ? "thuộc đợt này" : "trong hệ thống"}. ${job && !job.options.transform ? "Đợt này không yêu cầu chạy dbt; một lần dbt sau đó vẫn có thể đưa dữ liệu này vào mart." : dbt ? `dbt gần nhất: ${dbt.status}, ${date(dbt.created_at, true)}.` : "Chưa có bản ghi chạy dbt."}`,
  };
  const selected = nodes.find((row) => row[0] === selectedStep) || nodes[3];
  $("#step-detail-title").textContent = selected[1] + " · " + selected[2];
  $("#step-data-link").dataset.databaseLink = selected[7];
  $("#step-data-link").dataset.table = selected[8];
  $("#step-detail-body").textContent = descriptions[selectedStep];
  const spark = systemFlow?.runs.find((run) => run.pipeline_name === "spark_gps");
  $("#gps-flow").innerHTML =
    `<div><span class="gps-node-label">Archive / RAW</span><strong>${number(warehouse?.gps)} <small>điểm GPS</small></strong><span class="meta">${job ? "Riêng đợt đang chọn" : "Toàn bộ hệ thống"}</span></div><span class="flow-arrow" aria-hidden="true">→</span><div><span class="gps-node-label">Apache Spark</span><strong class="spark-result">${spark ? escape({ SUCCESS: "Thành công", FAILED: "Thất bại", RUNNING: "Đang chạy" }[spark.status] || spark.status) : "Chưa chạy"}</strong><span class="meta">${spark ? "Lần cuối " + date(spark.created_at, true) : "Job độc lập"}</span></div><span class="flow-arrow" aria-hidden="true">→</span><div><a href="#data" data-database-link="warehouse" data-table="staging.stg_driver_gps_daily" class="gps-node-label inline-link">Parquet → GPS mart ↗</a><strong>${number(systemFlow?.warehouse?.gps_summary)} <small>điểm GPS</small></strong><span class="meta">Toàn bộ hệ thống</span></div>`;
  $("#gps-freshness").textContent =
    "Spark không tự chạy cùng đợt tạo. Số liệu GPS mart chưa xác nhận đã bao gồm các điểm mới.";
  $("#generation-events").hidden = !job;
  $("#generation-events-body").innerHTML =
    (progress?.events || [])
      .map(
        (event) =>
          `<tr><td>${escape(event.event_type)}</td><td title="${escape(event.event_id)}"><code>${escape(event.event_id.slice(0, 8))}</code></td><td>${event.published_at ? "Đã publish" : "Chờ publish"}</td><td>${event.received === true ? "Đã nhận" : event.received === false ? "Chưa nhận" : "Chưa đọc được"}</td></tr>`,
      )
      .join("") || '<tr><td colspan="4">Chưa ghi nhận sự kiện của đợt.</td></tr>';
}

$("#generation-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (generationSubmitting || state.generating) return;
  generationSubmitting = true;
  generationSubmitError = "";
  showGenerationError("");
  syncGenerationControls();
  try {
    const body = {
      request_id: generationRequest,
      orders: Number($("#generation-orders").value),
      seed: Number($("#generation-seed").value),
      business_date: $("#generation-date").value,
      transform: $("#generation-transform").checked,
    };
    const job = await api("/api/generation", { method: "POST", body: JSON.stringify(body) });
    activeGeneration = job.id;
    generationVersion++;
    generationRequest = crypto.randomUUID();
    state.generating = job.status === "running";
    await pollGeneration();
  } catch (error) {
    generationSubmitError = `Chưa tạo được đợt: ${error.message}`;
    showGenerationError(generationSubmitError);
  } finally {
    generationSubmitting = false;
    syncControls();
    syncGenerationControls();
  }
});
$("#generation-form").addEventListener("input", () => {
  if (!generationSubmitting) generationRequest = crypto.randomUUID();
});
$("#generation-runs").addEventListener("change", (event) => {
  activeGeneration = event.target.value;
  generationVersion++;
  pollGeneration();
});
$("#pipeline-track").addEventListener("click", (event) => {
  const button = event.target.closest("[data-pipeline-step]");
  if (button) {
    selectedStep = button.dataset.pipelineStep;
    renderGeneration();
    $("#pipeline-track")
      .querySelector(`[data-pipeline-step="${selectedStep}"]`)
      ?.focus({ preventScroll: true });
  }
});
if (state.view === "generate") generationView();
setInterval(() => {
  if (state.view === "generate" && !document.hidden) pollGeneration();
}, 2000);
