/**
 * app.js - Dashboard logic for Distributed Load Balancer (Phase 4)
 *
 * Responsibilities:
 *   - Poll the Flask REST API every 1.5 seconds
 *   - Render stat cards, worker cards, task table, metrics panel
 *   - Update Chart.js charts with live data
 *   - Handle user actions: submit task, batch submit, fail/recover worker,
 *     change algorithm
 *
 * No frameworks — plain fetch() + setInterval() + DOM manipulation.
 */

"use strict";

/* ==========================================================================
   State
   ========================================================================== */

var charts = {};               // Stores Chart.js instances keyed by canvas id
var throughputHistory = [];    // Ring buffer of recent throughput readings
var MAX_THROUGHPUT_HISTORY = 30;

/* ==========================================================================
   Boot — start polling as soon as the page loads
   ========================================================================== */

document.addEventListener("DOMContentLoaded", function () {
    initCharts();
    refreshAll();                         // Immediate first fetch
    setInterval(refreshAll, 1500);        // Then poll every 1.5 s
    syncAlgoDropdown();                   // Sync dropdown to current algorithm
});

/* ==========================================================================
   Top-level refresh orchestrator
   ========================================================================== */

function refreshAll() {
    fetchStatus();
    fetchWorkers();
    fetchTasks();
    fetchMetrics();
    fetchTimeline();
}

/* ==========================================================================
   API: Status (header stat cards)
   ========================================================================== */

function fetchStatus() {
    fetch("/api/status")
        .then(function (r) { return r.json(); })
        .then(function (data) {
            setText("stat-workers",          data.total_workers);
            setText("stat-active",           data.active_workers);
            setText("stat-failed-workers",   data.failed_workers);
            setText("stat-running",          data.total_running);
            setText("stat-completed",        data.total_completed);
            setText("stat-throughput",       data.throughput.toFixed(3));
            setText("current-algorithm",     data.scheduler_name);
            setText("uptime-display",        "Uptime: " + fmtTime(data.elapsed_time));

            // Keep dropdown in sync
            var sel = document.getElementById("algo-select");
            if (sel) {
                if (data.scheduler_name === "Round Robin") {
                    sel.value = "round_robin";
                } else if (data.scheduler_name === "Least Connections") {
                    sel.value = "least_connections";
                }
            }
        })
        .catch(function () { /* silently ignore transient errors */ });
}

/* ==========================================================================
   API: Workers
   ========================================================================== */

function fetchWorkers() {
    fetch("/api/workers")
        .then(function (r) { return r.json(); })
        .then(function (workers) {
            renderWorkerCards(workers);
            updateWorkloadChart(workers);
        })
        .catch(function () {});
}

function renderWorkerCards(workers) {
    var container = document.getElementById("worker-cards");
    if (!container) { return; }

    var html = "";
    for (var i = 0; i < workers.length; i++) {
        html += buildWorkerCard(workers[i]);
    }
    container.innerHTML = html;
}

function buildWorkerCard(w) {
    var statusLower = w.status.toLowerCase();
    var badgeClass  = "badge-" + statusLower;
    var cardClass   = "state-" + statusLower;

    var currentTaskText = "(none)";
    if (w.current_task_name) {
        currentTaskText = w.current_task_id + " — " + w.current_task_name;
    }

    // Fail/Recover buttons
    var actionBtns = "";
    if (w.status === "IDLE" || w.status === "BUSY") {
        actionBtns = '<button class="btn btn-danger" onclick="failWorker(\'' + w.worker_id + '\')">' +
                     'Fail</button>';
    }
    if (w.status === "FAILED") {
        actionBtns = '<button class="btn btn-success" onclick="recoverWorker(\'' + w.worker_id + '\')">' +
                     'Recover</button>';
    }

    return '<div class="worker-card ' + cardClass + '">' +
        '<div class="worker-card-header">' +
            '<span class="worker-name">' + w.worker_id + '</span>' +
            '<span class="status-badge ' + badgeClass + '">' + w.status + '</span>' +
        '</div>' +
        '<div class="worker-stats">' +
            '<span class="worker-stat-label">Workload</span>' +
            '<span class="worker-stat-value">' + w.workload + '</span>' +
            '<span class="worker-stat-label">Queue size</span>' +
            '<span class="worker-stat-value">' + w.queue_size + '</span>' +
            '<span class="worker-stat-label">Completed</span>' +
            '<span class="worker-stat-value">' + w.completed + '</span>' +
            '<span class="worker-stat-label">Assigned</span>' +
            '<span class="worker-stat-value">' + w.assigned + '</span>' +
            '<span class="worker-stat-label">Failures</span>' +
            '<span class="worker-stat-value">' + w.failures + '</span>' +
            '<span class="worker-stat-label">Recoveries</span>' +
            '<span class="worker-stat-value">' + w.recoveries + '</span>' +
        '</div>' +
        '<div class="worker-current-task">Current: <span>' + currentTaskText + '</span></div>' +
        '<div class="worker-actions">' + actionBtns + '</div>' +
    '</div>';
}

/* ==========================================================================
   API: Tasks
   ========================================================================== */

function fetchTasks() {
    fetch("/api/tasks")
        .then(function (r) { return r.json(); })
        .then(function (tasks) {
            renderTaskTable(tasks);
            updateTaskStatusChart(tasks);
        })
        .catch(function () {});
}

function renderTaskTable(tasks) {
    var badge = document.getElementById("task-count-value");
    if (badge) { badge.textContent = tasks.length + " task" + (tasks.length === 1 ? "" : "s"); }

    var tbody = document.getElementById("task-tbody");
    if (!tbody) { return; }

    if (tasks.length === 0) {
        tbody.innerHTML = '<tr><td colspan="9" class="empty-row">No tasks submitted yet.</td></tr>';
        return;
    }

    var rows = "";
    for (var i = 0; i < tasks.length; i++) {
        var t = tasks[i];
        rows += buildTaskRow(t);
    }
    tbody.innerHTML = rows;
}

function buildTaskRow(t) {
    var statusClass = "ts-" + t.status.toLowerCase();
    var reroutedTag = t.rerouted ? '<span class="rerouted-tag">RE-ROUTED</span>' : "";
    var execTime    = t.execution_time !== null ? t.execution_time.toFixed(3) : "-";
    var waitTime    = t.waiting_time   !== null ? t.waiting_time.toFixed(3)   : "-";
    var worker      = t.worker         || "-";
    var algo        = t.algorithm      || "-";
    var arrival     = t.arrival_time !== null ? (t.arrival_time - t.created_at).toFixed(2) + "s" : "0s";

    return "<tr>" +
        "<td><code>" + t.id + "</code></td>" +
        "<td>" + escHtml(t.name) + "</td>" +
        '<td><span class="task-status ' + statusClass + '">' + t.status + "</span></td>" +
        "<td>" + worker + "</td>" +
        "<td>" + t.duration.toFixed(2) + "</td>" +
        "<td>" + arrival + "</td>" +
        "<td>" + execTime + "</td>" +
        "<td>" + waitTime + "</td>" +
        "<td>" + algo + "</td>" +
        "<td>" + reroutedTag + "</td>" +
    "</tr>";
}

/* ==========================================================================
   API: Metrics
   ========================================================================== */

function fetchMetrics() {
    fetch("/api/metrics")
        .then(function (r) { return r.json(); })
        .then(function (m) {
            setText("metric-avg-exec",    m.avg_execution_time.toFixed(3) + " s");
            setText("metric-avg-wait",    m.avg_waiting_time.toFixed(3)   + " s");
            setText("metric-total-exec",  m.total_execution_time.toFixed(3) + " s");
            setText("metric-queued",      m.total_queued);
            setText("metric-interrupted", m.total_interrupted);
            setText("metric-rerouted",    m.total_re_routed);
            setText("metric-w-failures",  m.total_worker_failures);
            setText("metric-w-recoveries",m.total_worker_recoveries);

            updateThroughputChart(m.throughput);
        })
        .catch(function () {});
}

/* ==========================================================================
   User actions
   ========================================================================== */

function submitTask() {
    var nameInput     = document.getElementById("task-name");
    var durationInput = document.getElementById("task-duration");
    var arrivalInput  = document.getElementById("task-arrival");
    var name          = nameInput.value.trim() || "Web Task";
    var duration      = parseFloat(durationInput.value);
    var arrival       = parseFloat(arrivalInput.value);

    if (isNaN(duration) || duration <= 0) {
        showMessage("Please enter a valid duration > 0", true);
        return;
    }
    if (isNaN(arrival) || arrival < 0) {
        showMessage("Please enter a valid arrival time >= 0", true);
        return;
    }

    fetch("/api/tasks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ duration: duration, name: name, arrival_time: arrival })
    })
    .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
    .then(function (result) {
        if (result.ok) {
            showMessage("Task " + result.data.task_id + " submitted to " + result.data.worker, false);
        } else {
            showMessage("Error: " + result.data.error, true);
        }
    })
    .catch(function () { showMessage("Network error — is the server running?", true); });
}

function submitBatch() {
    var countInput    = document.getElementById("batch-count");
    var durationInput = document.getElementById("batch-duration");
    var count         = parseInt(countInput.value, 10);
    var duration      = parseFloat(durationInput.value);

    if (isNaN(count) || count < 1 || count > 20) {
        showMessage("Count must be between 1 and 20", true);
        return;
    }
    if (isNaN(duration) || duration <= 0) {
        showMessage("Please enter a valid duration > 0", true);
        return;
    }

    fetch("/api/tasks/batch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ count: count, duration: duration })
    })
    .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
    .then(function (result) {
        if (result.ok) {
            showMessage(result.data.message + " submitted successfully", false);
        } else {
            showMessage("Error: " + result.data.error, true);
        }
    })
    .catch(function () { showMessage("Network error — is the server running?", true); });
}

function changeAlgorithm(value) {
    fetch("/api/algorithm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ algorithm: value })
    })
    .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
    .then(function (result) {
        if (result.ok) {
            showMessage("Algorithm switched to: " + result.data.algorithm, false);
        } else {
            showMessage("Error: " + result.data.error, true);
        }
    })
    .catch(function () { showMessage("Network error", true); });
}

function failWorker(workerId) {
    fetch("/api/workers/" + encodeURIComponent(workerId) + "/fail", {
        method: "POST"
    })
    .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
    .then(function (result) {
        if (result.ok) {
            showMessage(workerId + " has been failed (simulated failure)", false);
        } else {
            showMessage("Error: " + result.data.error, true);
        }
    })
    .catch(function () { showMessage("Network error", true); });
}

function recoverWorker(workerId) {
    fetch("/api/workers/" + encodeURIComponent(workerId) + "/recover", {
        method: "POST"
    })
    .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
    .then(function (result) {
        if (result.ok) {
            showMessage(workerId + " has been recovered", false);
        } else {
            showMessage("Error: " + result.data.error, true);
        }
    })
    .catch(function () { showMessage("Network error", true); });
}

/* ==========================================================================
   Charts (Chart.js)
   ========================================================================== */

function initCharts() {
    // --- Task Status Doughnut ---
    var ctxStatus = document.getElementById("chart-task-status");
    if (ctxStatus) {
        charts.taskStatus = new Chart(ctxStatus, {
            type: "doughnut",
            data: {
                labels: ["Completed", "Running", "Queued", "Interrupted", "Failed", "Pending"],
                datasets: [{
                    data: [0, 0, 0, 0, 0, 0],
                    backgroundColor: [
                        "rgba(34,197,94,0.8)",
                        "rgba(249,115,22,0.8)",
                        "rgba(59,130,246,0.8)",
                        "rgba(168,85,247,0.8)",
                        "rgba(239,68,68,0.8)",
                        "rgba(234,179,8,0.8)"
                    ],
                    borderWidth: 1,
                    borderColor: "#1a1d2e"
                }]
            },
            options: chartOpts({ legend: true })
        });
    }

    // --- Worker Workload Bar ---
    var ctxWork = document.getElementById("chart-workload");
    if (ctxWork) {
        charts.workload = new Chart(ctxWork, {
            type: "bar",
            data: {
                labels: [],
                datasets: [{
                    label: "Workload",
                    data: [],
                    backgroundColor: "rgba(99,102,241,0.7)",
                    borderColor: "rgba(99,102,241,1)",
                    borderWidth: 1,
                    borderRadius: 4
                }]
            },
            options: chartOpts({ legend: false, yBeginAtZero: true })
        });
    }

    // --- Throughput Line ---
    var ctxThru = document.getElementById("chart-throughput");
    if (ctxThru) {
        charts.throughput = new Chart(ctxThru, {
            type: "line",
            data: {
                labels: [],
                datasets: [{
                    label: "Throughput (tasks/s)",
                    data: [],
                    borderColor: "rgba(34,197,94,0.9)",
                    backgroundColor: "rgba(34,197,94,0.1)",
                    fill: true,
                    tension: 0.4,
                    pointRadius: 2,
                    borderWidth: 2
                }]
            },
            options: chartOpts({ legend: false, yBeginAtZero: true })
        });
    }
}

function updateTaskStatusChart(tasks) {
    if (!charts.taskStatus) { return; }

    var counts = { COMPLETED: 0, RUNNING: 0, QUEUED: 0, INTERRUPTED: 0, FAILED: 0, PENDING: 0 };
    for (var i = 0; i < tasks.length; i++) {
        var s = tasks[i].status;
        if (counts[s] !== undefined) { counts[s]++; }
    }

    charts.taskStatus.data.datasets[0].data = [
        counts.COMPLETED, counts.RUNNING, counts.QUEUED,
        counts.INTERRUPTED, counts.FAILED, counts.PENDING
    ];
    charts.taskStatus.update("none");
}

function updateWorkloadChart(workers) {
    if (!charts.workload) { return; }

    var labels = [];
    var values = [];
    for (var i = 0; i < workers.length; i++) {
        labels.push(workers[i].worker_id);
        values.push(workers[i].workload);
    }

    // Colour bars by worker status
    var colors = workers.map(function (w) {
        var s = w.status;
        if (s === "IDLE")    { return "rgba(34,197,94,0.7)"; }
        if (s === "BUSY")    { return "rgba(249,115,22,0.7)"; }
        if (s === "FAILED")  { return "rgba(239,68,68,0.7)"; }
        return "rgba(107,114,128,0.7)";
    });

    charts.workload.data.labels = labels;
    charts.workload.data.datasets[0].data = values;
    charts.workload.data.datasets[0].backgroundColor = colors;
    charts.workload.update("none");
}

function updateThroughputChart(value) {
    if (!charts.throughput) { return; }

    throughputHistory.push(parseFloat(value.toFixed(4)));
    if (throughputHistory.length > MAX_THROUGHPUT_HISTORY) {
        throughputHistory.shift();
    }

    // Labels: most recent reading on the right, older on the left
    var labels = [];
    for (var i = 0; i < throughputHistory.length; i++) {
        labels.push("");   // No per-point x-label clutter
    }

    charts.throughput.data.labels = labels;
    charts.throughput.data.datasets[0].data = throughputHistory.slice();
    charts.throughput.update("none");
}

/* --------------------------------------------------------------------------
   Chart.js shared options builder
   -------------------------------------------------------------------------- */

function chartOpts(opts) {
    return {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 200 },
        plugins: {
            legend: {
                display: opts.legend === true,
                labels: { color: "#8892aa", font: { size: 11 } }
            },
            tooltip: {
                backgroundColor: "#222540",
                titleColor: "#e2e8f0",
                bodyColor: "#8892aa",
                borderColor: "#2e3255",
                borderWidth: 1
            }
        },
        scales: opts.legend ? {} : {
            x: {
                ticks: { color: "#8892aa", font: { size: 11 } },
                grid:  { color: "rgba(46,50,85,0.5)" }
            },
            y: {
                beginAtZero: opts.yBeginAtZero !== false,
                ticks: { color: "#8892aa", font: { size: 11 } },
                grid:  { color: "rgba(46,50,85,0.5)" }
            }
        }
    };
}

/* ==========================================================================
   Helpers
   ========================================================================== */

function setText(id, value) {
    var el = document.getElementById(id);
    if (el) { el.textContent = value; }
}

function showMessage(msg, isError) {
    var bar = document.getElementById("status-bar");
    if (!bar) { return; }

    bar.textContent = msg;
    bar.className = "status-bar " + (isError ? "error" : "success");

    // Auto-hide after 4 seconds
    clearTimeout(bar._hideTimer);
    bar._hideTimer = setTimeout(function () {
        bar.className = "status-bar hidden";
    }, 4000);
}

function fmtTime(seconds) {
    var s = Math.floor(seconds);
    if (s < 60)   { return s + "s"; }
    if (s < 3600) { return Math.floor(s / 60) + "m " + (s % 60) + "s"; }
    return Math.floor(s / 3600) + "h " + Math.floor((s % 3600) / 60) + "m";
}

function escHtml(str) {
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

function syncAlgoDropdown() {
    fetch("/api/status")
        .then(function (r) { return r.json(); })
        .then(function (data) {
            var sel = document.getElementById("algo-select");
            if (!sel) { return; }
            if (data.scheduler_name === "Round Robin") {
                sel.value = "round_robin";
            } else if (data.scheduler_name === "Least Connections") {
                sel.value = "least_connections";
            }
        })
        .catch(function () {});
}

function fetchTimeline() {
    fetch("/api/tasks")
        .then(function (r) { return r.json(); })
        .then(function (tasks) {
            renderTimeline(tasks);
        })
        .catch(function () {});
}

function renderTimeline(tasks) {
    var container = document.getElementById("timeline-container");
    if (!container) { return; }

    // Filter tasks that have been started (have started_at)
    var executedTasks = tasks.filter(function (t) {
        return t.started_at !== null && t.worker !== null;
    });

    if (executedTasks.length === 0) {
        container.innerHTML = '<p class="loading-text">Submit tasks to see the execution timeline.</p>';
        return;
    }

    // Group tasks by worker
    var tasksByWorker = {};
    for (var i = 0; i < executedTasks.length; i++) {
        var t = executedTasks[i];
        if (!tasksByWorker[t.worker]) {
            tasksByWorker[t.worker] = [];
        }
        tasksByWorker[t.worker].push(t);
    }

    // Find time range
    var minTime = null;
    var maxTime = null;
    for (var workerId in tasksByWorker) {
        for (var i = 0; i < tasksByWorker[workerId].length; i++) {
            var t = tasksByWorker[workerId][i];
            if (t.started_at !== null) {
                if (minTime === null || t.started_at < minTime) minTime = t.started_at;
                var endTime = t.completed_at || t.started_at + t.duration;
                if (maxTime === null || endTime > maxTime) maxTime = endTime;
            }
        }
    }

    if (minTime === null) {
        container.innerHTML = '<p class="loading-text">No execution data available yet.</p>';
        return;
    }

    var totalDuration = maxTime - minTime;

    // Generate colors for tasks
    var colors = [
        "#0d6efd", "#198754", "#dc3545", "#ffc107", "#0dcaf0",
        "#6f42c1", "#fd7e14", "#20c997", "#6610f2", "#d63384"
    ];

    // Build timeline HTML
    var html = '<div class="timeline-legend">';
    var uniqueWorkers = Object.keys(tasksByWorker).sort();
    for (var i = 0; i < uniqueWorkers.length; i++) {
        var workerId = uniqueWorkers[i];
        var colorIndex = i % colors.length;
        html += '<div class="timeline-legend-item">' +
            '<div class="timeline-legend-color" style="background: ' + colors[colorIndex] + ';"></div>' +
            '<span>' + workerId + '</span>' +
        '</div>';
    }
    html += '</div>';

    html += '<div class="timeline-chart">';
    for (var i = 0; i < uniqueWorkers.length; i++) {
        var workerId = uniqueWorkers[i];
        var workerTasks = tasksByWorker[workerId];
        var colorIndex = i % colors.length;
        var workerColor = colors[colorIndex];

        html += '<div class="timeline-worker-row">' +
            '<div class="timeline-worker-label">' + workerId + '</div>' +
            '<div class="timeline-track">';

        for (var j = 0; j < workerTasks.length; j++) {
            var t = workerTasks[j];
            if (t.started_at !== null) {
                var startTime = t.started_at - minTime;
                var duration = (t.completed_at || t.started_at + t.duration) - t.started_at;
                var leftPercent = (startTime / totalDuration) * 100;
                var widthPercent = (duration / totalDuration) * 100;

                html += '<div class="timeline-bar" style="' +
                    'left: ' + leftPercent + '%; ' +
                    'width: ' + widthPercent + '%; ' +
                    'background: ' + workerColor + ';" ' +
                    'title="' + t.id + ' - ' + escHtml(t.name) + ' (' + duration.toFixed(2) + 's)">' +
                    '<span class="timeline-bar-label">' + t.id + '</span>' +
                    '</div>';
            }
        }

        html += '</div></div>';
    }
    html += '</div>';

    // Time axis
    html += '<div class="timeline-time-axis">' +
        '<span class="timeline-time-label">0s</span>' +
        '<span class="timeline-time-label">' + (totalDuration / 2).toFixed(1) + 's</span>' +
        '<span class="timeline-time-label">' + totalDuration.toFixed(1) + 's</span>' +
    '</div>';

    container.innerHTML = html;
}

