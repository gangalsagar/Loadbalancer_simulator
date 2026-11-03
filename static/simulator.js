/**
 * simulator.js - Simulator workspace logic for Distributed Load Balancer
 *
 * Responsibilities:
 *   - Task preparation (add/remove tasks through authoritative backend API)
 *   - Start simulation (trigger backend /api/simulation/start exactly ONCE)
 *   - Poll backend for worker states, thread states, queues, and task status
 *   - Update worker visualization with dedicated thread and isolated FIFO queue
 *   - Update task monitor table with backend-generated task IDs
 *   - Update metrics with proper units
 *   - Handle real worker failure and recovery via backend APIs
 *   - Detect simulation completion
 *   - Reset simulation and LoadBalancer completely
 *
 * No frameworks — plain fetch() + setInterval() + DOM manipulation.
 */

"use strict";

/* ==========================================================================
   State
   ========================================================================== */

var preparedTasks = [];
var simulationRunning = false;
var pollingInterval = null;

/* ==========================================================================
   Boot
   ========================================================================== */

document.addEventListener("DOMContentLoaded", function () {
    loadPreparedTasks();
    syncAlgorithmDropdown();
    checkUrlParams();
    initSimulationState();

    var nameInput = document.getElementById("task-name");
    var durInput = document.getElementById("task-duration");
    if (nameInput) {
        nameInput.addEventListener("keydown", function (e) {
            if (e.key === "Enter") {
                e.preventDefault();
                addPreparedTask();
            }
        });
    }
    if (durInput) {
        durInput.addEventListener("keydown", function (e) {
            if (e.key === "Enter") {
                e.preventDefault();
                addPreparedTask();
            }
        });
    }
});

function initSimulationState() {
    fetch("/api/simulation/status")
        .then(function (r) { return r.json(); })
        .then(function (sim) {
            if (sim.running || sim.total_submitted > 0) {
                var liveSec = document.getElementById("live-simulation");
                if (liveSec) {
                    liveSec.style.display = "block";
                }
                if (sim.running) {
                    simulationRunning = true;
                    var st = document.getElementById("sim-status");
                    if (st) {
                        st.textContent = "RUNNING";
                        st.className = "sidebar-status status-running";
                    }
                    var nameInput = document.getElementById("task-name");
                    var durInput = document.getElementById("task-duration");
                    var btn = document.querySelector(".task-entry-form button");
                    var btnRun = document.getElementById("btn-run-simulation");
                    if (nameInput) nameInput.disabled = true;
                    if (durInput) durInput.disabled = true;
                    if (btn) btn.disabled = true;
                    if (btnRun) btnRun.disabled = true;
                    startPolling();
                } else if (sim.total_submitted > 0) {
                    var st = document.getElementById("sim-status");
                    if (st) {
                        st.textContent = "COMPLETE";
                        st.className = "sidebar-status status-complete";
                    }
                    var comp = document.getElementById("simulation-complete");
                    if (comp) {
                        comp.style.display = "block";
                    }
                }
                refreshSimulation();
            }
        })
        .catch(function () {});
}

function checkUrlParams() {
    var params = new URLSearchParams(window.location.search);
    var algorithm = params.get("algorithm");
    if (algorithm) {
        var select = document.getElementById("algo-select");
        if (select) {
            select.value = algorithm;
            changeAlgorithm(algorithm);
        }
    }
    updateAlgorithmInfo();
}

function updateAlgorithmInfo() {
    var select = document.getElementById("algo-select");
    var title = document.getElementById("algo-info-title");
    var desc = document.getElementById("algo-info-desc");

    if (select && title && desc) {
        if (select.value === "round_robin") {
            title.textContent = "Round Robin (RR)";
            desc.textContent = "Sequentially assigns tasks across available workers in a fixed cyclic order.";
        } else if (select.value === "least_connections") {
            title.textContent = "Least Connections (LC)";
            desc.textContent = "Selects the available worker with the lowest current workload (executing + queued tasks).";
        }
    }
}

/* ==========================================================================
   Algorithm Selection
   ========================================================================== */

function changeAlgorithm(value) {
    fetch("/api/algorithm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ algorithm: value })
    })
    .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
    .then(function (result) {
        if (result.ok) {
            updateAlgorithmInfo();
            var archSched = document.getElementById("arch-active-scheduler");
            if (archSched) {
                archSched.textContent = value === "least_connections"
                    ? "LEAST CONNECTIONS (WORKLOAD-AWARE)"
                    : "ROUND ROBIN (CYCLIC DISPATCH)";
            }
        }
    })
    .catch(function () {});
}

function syncAlgorithmDropdown() {
    fetch("/api/status")
        .then(function (r) { return r.json(); })
        .then(function (data) {
            var select = document.getElementById("algo-select");
            if (select) {
                if (data.scheduler_name === "Round Robin") {
                    select.value = "round_robin";
                } else if (data.scheduler_name === "Least Connections") {
                    select.value = "least_connections";
                }
            }
            updateAlgorithmInfo();
        })
        .catch(function () {});
}

/* ==========================================================================
   Task Preparation (Backend is the authoritative Single Source of Truth)
   ========================================================================== */

function addPreparedTask() {
    var nameInput = document.getElementById("task-name");
    var durationInput = document.getElementById("task-duration");
    var name = nameInput.value.trim();
    var duration = parseFloat(durationInput.value);

    if (!name) {
        alert("Please enter a task name");
        return;
    }
    if (isNaN(duration) || duration <= 0 || duration > 30) {
        alert("Please enter a valid duration between 0.05 and 30 seconds");
        return;
    }

    fetch("/api/simulation/prepared", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            name: name,
            duration: duration
        })
    })
    .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
    .then(function (res) {
        if (res.ok) {
            nameInput.value = "";
            durationInput.value = "5";
            loadPreparedTasks();
        } else {
            alert("Error adding task: " + (res.data.error || "Unknown error"));
        }
    })
    .catch(function (err) {
        console.error("Error adding prepared task:", err);
    });
}

function removePreparedTask(index) {
    fetch("/api/simulation/prepared/" + index, {
        method: "DELETE"
    })
    .then(function (r) { return r.json(); })
    .then(function () {
        loadPreparedTasks();
    })
    .catch(function (err) {
        console.error("Error removing prepared task:", err);
    });
}

function loadPreparedTasks() {
    fetch("/api/simulation/prepared")
        .then(function (r) { return r.json(); })
        .then(function (data) {
            preparedTasks = data.tasks || [];
            renderPreparedTasks();
        })
        .catch(function () {});
}

function renderPreparedTasks() {
    var tbody = document.getElementById("prepared-tbody");
    if (!tbody) { return; }

    if (preparedTasks.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" class="empty-row">No tasks prepared yet. Enter a task above and click "Add Task".</td></tr>';
        return;
    }

    var rows = "";
    for (var i = 0; i < preparedTasks.length; i++) {
        var task = preparedTasks[i];
        var label = task.label || ("Prepared Task " + (i + 1));
        rows += "<tr>" +
            "<td><b>" + escapeHtml(label) + "</b></td>" +
            "<td>" + escapeHtml(task.name) + "</td>" +
            "<td>" + task.duration + "s</td>" +
            '<td><span class="task-status-badge ts-ready">' + (task.status || "READY") + "</span></td>" +
            '<td><button class="btn btn-secondary btn-sm" onclick="removePreparedTask(' + i + ')">Remove</button></td>' +
        "</tr>";
    }
    tbody.innerHTML = rows;
}

/* ==========================================================================
   Run Simulation (Backend Submits Prepared Tasks Exactly Once)
   ========================================================================== */

function runSimulation() {
    if (simulationRunning) {
        return;
    }

    if (preparedTasks.length === 0) {
        alert("Please add at least one task before running the simulation");
        return;
    }

    var nameInput = document.getElementById("task-name");
    var durInput  = document.getElementById("task-duration");
    var btn       = document.querySelector(".task-entry-form button");
    var btnRun    = document.getElementById("btn-run-simulation");
    var btnLoad   = document.getElementById("btn-load-tasks");

    // ── IMMEDIATELY show live section and scroll to it ──────────────────────
    var liveSection = document.getElementById("live-simulation");
    if (liveSection) {
        liveSection.style.display = "block";
        // Use instant scroll so the user lands there right away,
        // then a smooth follow-up once the browser paints it.
        liveSection.scrollIntoView({ behavior: "instant", block: "start" });
    }

    // Show a launching state in the workers grid before the API responds
    var grid = document.getElementById("workers-grid");
    if (grid && grid.innerHTML.trim() === "") {
        grid.innerHTML =
            '<div class="launch-placeholder">' +
            '<div class="launch-spinner"></div>' +
            '<span>Submitting tasks to Load Balancer…</span>' +
            '</div>';
    }

    // Update status badge immediately
    var statusBadge = document.getElementById("sim-status");
    if (statusBadge) {
        statusBadge.textContent = "STARTING…";
        statusBadge.className = "sidebar-status status-running";
    }

    // Disable controls
    if (nameInput) nameInput.disabled = true;
    if (durInput)  durInput.disabled  = true;
    if (btn)       btn.disabled       = true;
    if (btnRun)    btnRun.disabled    = true;
    if (btnLoad)   btnLoad.disabled   = true;

    // Update arch-flow scheduler label right away
    var algoSelect = document.getElementById("algo-select");
    var archSched  = document.getElementById("arch-active-scheduler");
    if (algoSelect && archSched) {
        archSched.textContent = algoSelect.value === "least_connections"
            ? "LEAST CONNECTIONS (WORKLOAD-AWARE)"
            : "ROUND ROBIN (CYCLIC DISPATCH)";
    }

    // ── Single authoritative submission path ────────────────────────────────
    fetch("/api/simulation/start", { method: "POST" })
    .then(function (r) {
        return r.json().then(function (d) { return { ok: r.ok, data: d }; });
    })
    .then(function (result) {
        if (!result.ok) {
            // Roll back UI on error
            if (liveSection) liveSection.style.display = "none";
            if (statusBadge) { statusBadge.textContent = "READY"; statusBadge.className = "sidebar-status status-ready"; }
            if (grid) grid.innerHTML = "";
            if (nameInput) nameInput.disabled = false;
            if (durInput)  durInput.disabled  = false;
            if (btn)       btn.disabled       = false;
            if (btnRun)    btnRun.disabled    = false;
            if (btnLoad)   btnLoad.disabled   = false;
            alert("Failed to start simulation: " + (result.data.error || "Unknown error"));
            return;
        }

        simulationRunning = true;
        if (statusBadge) { statusBadge.textContent = "RUNNING"; }

        // Kick off live polling immediately
        refreshSimulation();
        startPolling();
    })
    .catch(function (err) {
        console.error("Error starting simulation:", err);
        if (liveSection) liveSection.style.display = "none";
        if (statusBadge) { statusBadge.textContent = "READY"; statusBadge.className = "sidebar-status status-ready"; }
        if (grid) grid.innerHTML = "";
        if (nameInput) nameInput.disabled = false;
        if (durInput)  durInput.disabled  = false;
        if (btn)       btn.disabled       = false;
        if (btnRun)    btnRun.disabled    = false;
        if (btnLoad)   btnLoad.disabled   = false;
        alert("Error starting simulation. Please check server.");
    });
}

/* ==========================================================================
   Polling
   ========================================================================== */

function startPolling() {
    stopPolling();
    pollingInterval = setInterval(function () {
        refreshSimulation();
    }, 1000);
}

function stopPolling() {
    if (pollingInterval) {
        clearInterval(pollingInterval);
        pollingInterval = null;
    }
}

function refreshSimulation() {
    fetchWorkers();
    fetchTasks();
    fetchMetrics();
    fetchTimeline();
    checkSimulationComplete();
}

/* ==========================================================================
   Fetch Workers & Dedicated Queues
   ========================================================================== */

function fetchWorkers() {
    fetch("/api/workers")
        .then(function (r) { return r.json(); })
        .then(function (workers) {
            renderWorkers(workers);
        })
        .catch(function () {});
}

function renderWorkers(workers) {
    var container = document.getElementById("workers-grid");
    if (!container) { return; }

    var html = "";
    for (var i = 0; i < workers.length; i++) {
        html += buildWorkerPanel(workers[i]);
    }
    container.innerHTML = html;
}

function buildWorkerPanel(w) {
    var statusClass = "status-" + w.status.toLowerCase();
    var threadState = w.thread_state || "UNKNOWN";

    var currentTaskHtml = w.current_task_id
        ? '<span class="worker-current-task">' + w.current_task_id + ' — ' + escapeHtml(w.current_task_name || "") + '</span>'
        : '<span class="worker-current-task" style="color: var(--color-text-muted);">None (Idle)</span>';

    var actionBtns = "";
    if (w.status === "IDLE" || w.status === "BUSY") {
        actionBtns = '<button class="btn btn-fail" onclick="failWorker(\'' + w.worker_id + '\')">Fail Worker</button>';
    }
    if (w.status === "FAILED") {
        actionBtns = '<button class="btn btn-recover" onclick="recoverWorker(\'' + w.worker_id + '\')">Recover Worker</button>';
    }

    var threadDot = w.thread_alive ? '●' : '○';
    var threadColor = w.thread_alive ? 'var(--color-success)' : 'var(--color-danger)';
    var threadStateLabel = w.thread_alive ? (w.thread_state || "RUNNING") : "TERMINATED";

    var queueItems = w.queue || [];
    var queueHtml = "";
    if (queueItems.length === 0) {
        queueHtml = '<div class="worker-queue-empty">Queue is Empty</div>';
    } else {
        for (var qi = 0; qi < queueItems.length; qi++) {
            var q = queueItems[qi];
            queueHtml += '<div class="worker-queue-item">' +
                '<span><b>' + escapeHtml(q.task_id) + '</b> ' + escapeHtml(q.name) + '</span>' +
                '<span>' + q.duration + 's</span>' +
            '</div>';
        }
    }

    var qLen = (w.queue_size !== undefined && w.queue_size !== null) ? w.queue_size : queueItems.length;

    return '<div class="worker-panel">' +
        '<div class="worker-panel-header">' +
            '<span class="worker-panel-title">' + w.worker_id + '</span>' +
            '<span class="worker-status-badge ' + statusClass + '">' + w.status + '</span>' +
        '</div>' +
        '<div class="worker-section">' +
            '<div class="worker-section-label">Dedicated Execution Thread</div>' +
            '<div class="worker-section-value">' +
                '<span style="color: ' + threadColor + '; font-weight: bold; margin-right: 0.5rem;">' + threadDot + ' ' + (w.thread_alive ? 'Alive' : 'Dead') + '</span>' +
                '<span class="worker-thread-badge">' + threadStateLabel + '</span>' +
            '</div>' +
        '</div>' +
        '<div class="worker-section">' +
            '<div class="worker-section-label">Current Active Task</div>' +
            currentTaskHtml +
        '</div>' +
        '<div class="worker-section">' +
            '<div class="worker-section-label">Workload (Executing + Queued)</div>' +
            '<div class="worker-section-value">' + w.workload + '</div>' +
        '</div>' +
        '<div class="worker-section">' +
            '<div class="worker-section-label">Dedicated Queue (Length: ' + qLen + ')</div>' +
            '<div class="worker-queue" id="queue-' + w.worker_id.replace(/[^a-zA-Z0-9]/g, "-") + '">' +
                queueHtml +
            '</div>' +
        '</div>' +
        '<div class="worker-section" style="font-size: 0.75rem; color: var(--color-text-muted); margin-top: 0.5rem;">' +
            'Done: ' + w.completed + ' | Interrupted: ' + (w.interrupted || 0) + ' | Failures: ' + (w.failures || 0) + ' | Recoveries: ' + (w.recoveries || 0) +
        '</div>' +
        '<div class="worker-actions">' + actionBtns + '</div>' +
    '</div>';
}

/* ==========================================================================
   Fetch Tasks & Monitor
   ========================================================================== */

function fetchTasks() {
    fetch("/api/tasks")
        .then(function (r) { return r.json(); })
        .then(function (tasks) {
            renderTaskTable(tasks);
        })
        .catch(function () {});
}

function renderTaskTable(tasks) {
    var tbody = document.getElementById("task-tbody");
    if (!tbody) { return; }

    if (tasks.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="empty-row">No tasks submitted yet.</td></tr>';
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
    var execTime = t.execution_time !== null ? t.execution_time.toFixed(3) + "s" : "-";
    var waitTime = t.waiting_time !== null ? t.waiting_time.toFixed(3) + "s" : "-";
    var worker = t.worker || "-";

    return "<tr>" +
        "<td><b>" + t.id + "</b></td>" +
        "<td>" + escapeHtml(t.name) + "</td>" +
        "<td>" + t.duration.toFixed(2) + "s</td>" +
        "<td>" + worker + "</td>" +
        '<td><span class="task-status-badge ' + statusClass + '">' + t.status + "</span></td>" +
        "<td>" + waitTime + "</td>" +
        "<td>" + execTime + "</td>" +
    "</tr>";
}

/* ==========================================================================
   Fetch Real Metrics (Proper Units)
   ========================================================================== */

function fetchMetrics() {
    fetch("/api/metrics")
        .then(function (r) { return r.json(); })
        .then(function (m) {
            var totalElem = document.getElementById("perf-total");
            var waitElem = document.getElementById("perf-avg-wait");
            var execElem = document.getElementById("perf-avg-exec");
            var totalExecElem = document.getElementById("perf-total-exec");

            if (totalElem) totalElem.textContent = m.total_submitted;
            if (waitElem) waitElem.textContent = m.avg_waiting_time.toFixed(2) + " s";
            if (execElem) execElem.textContent = m.avg_execution_time.toFixed(2) + " s";
            if (totalExecElem) totalExecElem.textContent = m.total_execution_time.toFixed(2) + " s";
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

    var executedTasks = tasks.filter(function (t) {
        return t.started_at !== null && t.worker !== null;
    });

    if (executedTasks.length === 0) {
        container.innerHTML = '<p class="empty-text">Run a simulation to see the execution timeline.</p>';
        return;
    }

    var tasksByWorker = {};
    for (var i = 0; i < executedTasks.length; i++) {
        var t = executedTasks[i];
        if (!tasksByWorker[t.worker]) {
            tasksByWorker[t.worker] = [];
        }
        tasksByWorker[t.worker].push(t);
    }

    var minTime = null;
    var maxTime = null;
    for (var workerId in tasksByWorker) {
        for (var i = 0; i < tasksByWorker[workerId].length; i++) {
            var t = tasksByWorker[workerId][i];
            if (t.started_at !== null) {
                if (minTime === null || t.started_at < minTime) minTime = t.started_at;
                var endTime = t.completed_at || (t.started_at + t.duration);
                if (maxTime === null || endTime > maxTime) maxTime = endTime;
            }
        }
    }

    if (minTime === null) {
        container.innerHTML = '<p class="empty-text">No execution data available yet.</p>';
        return;
    }

    var totalDuration = Math.max(0.1, maxTime - minTime);

    var colors = [
        "#0d6efd", "#198754", "#dc3545", "#ffc107", "#0dcaf0",
        "#6f42c1", "#fd7e14", "#20c997", "#6610f2", "#d63384"
    ];

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
                var duration = (t.completed_at || (t.started_at + t.duration)) - t.started_at;
                var leftPercent = (startTime / totalDuration) * 100;
                var widthPercent = Math.max(1, (duration / totalDuration) * 100);

                html += '<div class="timeline-bar" style="' +
                    'left: ' + leftPercent + '%; ' +
                    'width: ' + widthPercent + '%; ' +
                    'background: ' + workerColor + ';" ' +
                    'title="' + t.id + ' - ' + escapeHtml(t.name) + ' (' + duration.toFixed(2) + 's)">' +
                    '<span class="timeline-bar-label">' + t.id + '</span>' +
                    '</div>';
            }
        }

        html += '</div></div>';
    }
    html += '</div>';

    html += '<div class="timeline-time-axis">' +
        '<span class="timeline-time-label">0s</span>' +
        '<span class="timeline-time-label">' + (totalDuration / 2).toFixed(1) + 's</span>' +
        '<span class="timeline-time-label">' + totalDuration.toFixed(1) + 's</span>' +
    '</div>';

    container.innerHTML = html;
}

/* ==========================================================================
   Worker Failure & Recovery (Real Backend APIs)
   ========================================================================== */

function failWorker(workerId) {
    fetch("/api/workers/" + encodeURIComponent(workerId) + "/fail", {
        method: "POST"
    })
    .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
    .then(function (result) {
        if (result.ok) {
            refreshSimulation();
        } else {
            alert("Error: " + (result.data.error || "Could not fail worker"));
        }
    })
    .catch(function () {});
}

function recoverWorker(workerId) {
    fetch("/api/workers/" + encodeURIComponent(workerId) + "/recover", {
        method: "POST"
    })
    .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
    .then(function (result) {
        if (result.ok) {
            refreshSimulation();
        } else {
            alert("Error: " + (result.data.error || "Could not recover worker"));
        }
    })
    .catch(function () {});
}

/* ==========================================================================
   Simulation Completion
   ========================================================================== */

function checkSimulationComplete() {
    fetch("/api/metrics")
        .then(function (r) { return r.json(); })
        .then(function (m) {
            var totalSubmitted = m.total_submitted;
            var completed = m.total_completed;
            var interrupted = m.total_interrupted;
            var failed = m.total_failed;

            var terminal = completed + interrupted + failed;

            if (terminal === totalSubmitted && totalSubmitted > 0) {
                stopPolling();
                showSimulationComplete(m);
            }
        })
        .catch(function () {});
}

function showSimulationComplete(metrics) {
    simulationRunning = false;
    var statusElem = document.getElementById("sim-status");
    if (statusElem) {
        statusElem.textContent = "COMPLETE";
        statusElem.className = "sidebar-status status-complete";
    }
    var compElem = document.getElementById("simulation-complete");
    if (compElem) {
        compElem.style.display = "block";
    }

    var nameInput = document.getElementById("task-name");
    var durInput = document.getElementById("task-duration");
    var btn = document.querySelector(".task-entry-form button");
    var btnRun = document.getElementById("btn-run-simulation");
    if (nameInput) nameInput.disabled = false;
    if (durInput) durInput.disabled = false;
    if (btn) btn.disabled = false;
    if (btnRun) btnRun.disabled = false;
}

/* ==========================================================================
   Reset Simulation & Backend LoadBalancer
   ========================================================================== */

function resetSimulation() {
    stopPolling();

    fetch("/api/simulation/reset", {
        method: "POST"
    })
    .then(function (r) { return r.json(); })
    .then(function (data) {
        preparedTasks = [];
        simulationRunning = false;

        document.getElementById("sim-status").textContent = "READY";
        document.getElementById("sim-status").className = "sidebar-status status-ready";
        document.getElementById("live-simulation").style.display = "none";
        document.getElementById("simulation-complete").style.display = "none";

        var nameInput = document.getElementById("task-name");
        var durInput = document.getElementById("task-duration");
        var btn = document.querySelector(".task-entry-form button");
        var btnRun = document.getElementById("btn-run-simulation");
        if (nameInput) { nameInput.disabled = false; nameInput.value = ""; }
        if (durInput) { durInput.disabled = false; durInput.value = "5"; }
        if (btn) { btn.disabled = false; }
        if (btnRun) { btnRun.disabled = false; }

        loadPreparedTasks();

        var grid = document.getElementById("workers-grid");
        if (grid) { grid.innerHTML = ""; }

        var tbody = document.getElementById("task-tbody");
        if (tbody) {
            tbody.innerHTML = '<tr><td colspan="7" class="empty-row">No tasks submitted yet.</td></tr>';
        }

        var totalElem = document.getElementById("perf-total");
        var waitElem = document.getElementById("perf-avg-wait");
        var execElem = document.getElementById("perf-avg-exec");
        var totalExecElem = document.getElementById("perf-total-exec");
        if (totalElem) totalElem.textContent = "0";
        if (waitElem) waitElem.textContent = "0.00 s";
        if (execElem) execElem.textContent = "0.00 s";
        if (totalExecElem) totalExecElem.textContent = "0.00 s";

        var timeline = document.getElementById("timeline-container");
        if (timeline) {
            timeline.innerHTML = '<p class="empty-text">Run a simulation to see the execution timeline.</p>';
        }
    })
    .catch(function (err) {
        console.error("Error resetting simulation:", err);
    });
}

/* ==========================================================================
   Bulk Task Loader (Quick Load — 10 tasks, 10–20 s each by default)
   ========================================================================== */

/**
 * Sequentially adds `count` tasks to the backend prepared list, one by one.
 * Each task gets a random duration between minDur and maxDur (seconds).
 * Shows a live progress bar while submitting.
 */
function loadBulkTasks() {
    var btn = document.getElementById("btn-load-tasks");
    var progressWrap = document.getElementById("load-tasks-progress");
    var progressBar = document.getElementById("load-tasks-bar");
    var progressText = document.getElementById("load-tasks-progress-text");

    var countInput = document.getElementById("load-task-count");
    var minInput = document.getElementById("load-min-dur");
    var maxInput = document.getElementById("load-max-dur");
    var prefixInput = document.getElementById("load-name-prefix");

    var count = parseInt(countInput ? countInput.value : "10", 10);
    var minDur = parseFloat(minInput ? minInput.value : "10");
    var maxDur = parseFloat(maxInput ? maxInput.value : "20");
    var prefix = (prefixInput ? prefixInput.value.trim() : "") || "Task";

    if (isNaN(count) || count < 1 || count > 20) {
        alert("Number of tasks must be between 1 and 20");
        return;
    }
    if (isNaN(minDur) || isNaN(maxDur) || minDur < 0.05 || maxDur > 30 || minDur >= maxDur) {
        alert("Min duration must be < max duration, both within 0.05 – 30 s");
        return;
    }

    // Disable controls while loading
    if (btn) { btn.disabled = true; btn.textContent = "Loading…"; }
    if (progressWrap) { progressWrap.style.display = "flex"; }
    if (progressBar) { progressBar.style.width = "0%"; }
    if (progressText) { progressText.textContent = "0 / " + count + " added"; }

    // Generate task durations up-front so they look varied and realistic
    var tasks = [];
    for (var i = 0; i < count; i++) {
        var dur = Math.round((minDur + Math.random() * (maxDur - minDur)) * 10) / 10;
        tasks.push({ name: prefix + " " + (i + 1), duration: dur });
    }

    // Submit tasks one-by-one sequentially to the backend
    function submitNext(idx) {
        if (idx >= tasks.length) {
            // All done
            if (btn) { btn.disabled = false; btn.textContent = "Load Tasks"; }
            if (progressText) { progressText.textContent = count + " / " + count + " — done!"; }
            setTimeout(function () {
                if (progressWrap) { progressWrap.style.display = "none"; }
            }, 2000);
            loadPreparedTasks();
            return;
        }

        var t = tasks[idx];
        fetch("/api/simulation/prepared", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: t.name, duration: t.duration })
        })
        .then(function (r) {
            return r.json().then(function (d) { return { ok: r.ok, data: d }; });
        })
        .then(function (res) {
            if (!res.ok) {
                alert("Error adding task " + (idx + 1) + ": " + (res.data.error || "Unknown error"));
                if (btn) { btn.disabled = false; btn.textContent = "Load Tasks"; }
                if (progressWrap) { progressWrap.style.display = "none"; }
                loadPreparedTasks();
                return;
            }
            var done = idx + 1;
            var pct = Math.round((done / count) * 100);
            if (progressBar) { progressBar.style.width = pct + "%"; }
            if (progressText) { progressText.textContent = done + " / " + count + " added"; }
            submitNext(idx + 1);
        })
        .catch(function (err) {
            alert("Network error adding task " + (idx + 1) + ": " + String(err));
            if (btn) { btn.disabled = false; btn.textContent = "Load Tasks"; }
            if (progressWrap) { progressWrap.style.display = "none"; }
            loadPreparedTasks();
        });
    }

    submitNext(0);
}

/* ==========================================================================
   Algorithm Comparison Benchmark
   ========================================================================== */

function runAlgorithmComparison() {
    var btn = document.getElementById("btn-run-comparison");
    var resultsDiv = document.getElementById("comparison-results");
    if (!btn || !resultsDiv) { return; }

    btn.disabled = true;
    btn.textContent = "Running Benchmark…";
    resultsDiv.style.display = "block";
    resultsDiv.innerHTML = '<p style="color: var(--color-text-muted); padding: 1rem;">Running comparison — please wait, this may take a few seconds…</p>';

    fetch("/api/comparison", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({})
    })
    .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
    .then(function (result) {
        btn.disabled = false;
        btn.textContent = "Run Benchmark Comparison";

        if (!result.ok) {
            resultsDiv.innerHTML = '<p style="color: var(--color-danger);">Error: ' + escapeHtml(result.data.error || "Unknown error") + '</p>';
            return;
        }

        var rr = result.data.round_robin;
        var lc = result.data.least_connections;

        if (!rr || !lc) {
            resultsDiv.innerHTML = '<p style="color: var(--color-danger);">Invalid response from server.</p>';
            return;
        }

        function fmt(v) {
            if (v === null || v === undefined) { return "—"; }
            return (typeof v === "number") ? v.toFixed(3) + " s" : String(v);
        }
        function fmtThroughput(v) {
            if (v === null || v === undefined) { return "—"; }
            return (typeof v === "number") ? v.toFixed(4) + " tasks/s" : String(v);
        }
        function fmtCount(v) {
            if (v === null || v === undefined) { return "—"; }
            return String(v);
        }

        function winner(rrVal, lcVal, lowerIsBetter) {
            if (rrVal === null || lcVal === null) { return ["", ""]; }
            if (lowerIsBetter) {
                if (rrVal < lcVal) { return ["🏆", ""]; }
                if (lcVal < rrVal) { return ["", "🏆"]; }
            } else {
                if (rrVal > lcVal) { return ["🏆", ""]; }
                if (lcVal > rrVal) { return ["", "🏆"]; }
            }
            return ["≈", "≈"];
        }

        var rows = [
            { label: "Total Tasks Completed", rrV: rr.total_completed, lcV: lc.total_completed, fmt: fmtCount, lowerBetter: false },
            { label: "Total Execution Time", rrV: rr.total_execution_time, lcV: lc.total_execution_time, fmt: fmt, lowerBetter: true },
            { label: "Avg Waiting Time", rrV: rr.avg_waiting_time, lcV: lc.avg_waiting_time, fmt: fmt, lowerBetter: true },
            { label: "Avg Execution Time", rrV: rr.avg_execution_time, lcV: lc.avg_execution_time, fmt: fmt, lowerBetter: true },
            { label: "Throughput", rrV: rr.throughput, lcV: lc.throughput, fmt: fmtThroughput, lowerBetter: false },
        ];

        var tableHtml =
            '<table class="task-table" style="width:100%;">' +
            '<thead><tr>' +
            '<th>Metric</th>' +
            '<th>Round Robin (RR)</th>' +
            '<th>Least Connections (LC)</th>' +
            '</tr></thead>' +
            '<tbody>';

        for (var i = 0; i < rows.length; i++) {
            var row = rows[i];
            var w = winner(row.rrV, row.lcV, row.lowerBetter);
            tableHtml +=
                '<tr>' +
                '<td><b>' + row.label + '</b></td>' +
                '<td>' + w[0] + ' ' + row.fmt(row.rrV) + '</td>' +
                '<td>' + w[1] + ' ' + row.fmt(row.lcV) + '</td>' +
                '</tr>';
        }

        tableHtml += '</tbody></table>';

        var workerRR = "";
        if (rr.worker_workloads) {
            for (var wid in rr.worker_workloads) {
                workerRR += '<span style="margin-right:1rem;">' + wid + ': ' + rr.worker_workloads[wid] + '</span>';
            }
        }
        var workerLC = "";
        if (lc.worker_workloads) {
            for (var wid in lc.worker_workloads) {
                workerLC += '<span style="margin-right:1rem;">' + wid + ': ' + lc.worker_workloads[wid] + '</span>';
            }
        }

        var workerSection = "";
        if (workerRR || workerLC) {
            workerSection =
                '<div style="margin-top:1rem; padding:1rem; background:var(--color-surface-alt); border-radius:var(--radius); border:1px solid var(--color-border);">' +
                '<b>Worker Utilization</b><br>' +
                '<div style="margin-top:0.5rem; font-size:0.85rem;">' +
                '<div><b>RR:</b> ' + (workerRR || "—") + '</div>' +
                '<div style="margin-top:0.3rem;"><b>LC:</b> ' + (workerLC || "—") + '</div>' +
                '</div></div>';
        }

        var noteHtml = '<p style="margin-top:0.75rem; font-size:0.8rem; color:var(--color-text-muted);">' +
            '🏆 = winner for that metric. Each algorithm ran on a fresh, isolated LoadBalancer instance with the same task workload. Results may vary run-to-run due to OS thread scheduling.' +
            '</p>';

        resultsDiv.innerHTML = tableHtml + workerSection + noteHtml;
    })
    .catch(function (err) {
        btn.disabled = false;
        btn.textContent = "Run Benchmark Comparison";
        resultsDiv.innerHTML = '<p style="color: var(--color-danger);">Network error: ' + escapeHtml(String(err)) + '</p>';
    });
}

/* ==========================================================================
   Helpers
   ========================================================================== */

function escapeHtml(str) {
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}
