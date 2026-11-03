/**
 * simulator.js - Simulator workspace logic for Distributed Load Balancer
 *
 * Responsibilities:
 *   - Task preparation (add/remove tasks without executing)
 *   - Start simulation (submit prepared tasks to LoadBalancer)
 *   - Poll backend for worker states, queues, and task status
 *   - Update worker visualization with thread state and queue contents
 *   - Update task monitor table
 *   - Update metrics
 *   - Handle worker failure and recovery
 *   - Detect simulation completion
 *   - Reset simulation for new run
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
var taskCounter = 1;

/* ==========================================================================
   Boot
   ========================================================================== */

document.addEventListener("DOMContentLoaded", function () {
    loadPreparedTasks();
    syncAlgorithmDropdown();
    checkUrlParams();
});

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
            desc.textContent = "Selects the available worker with the lowest current workload.";
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
                document.getElementById("config-algorithm").textContent = data.scheduler_name;
            }
        })
        .catch(function () {});
}

/* ==========================================================================
   Task Preparation
   ========================================================================== */

function addPreparedTask() {
    var nameInput = document.getElementById("task-name");
    var durationInput = document.getElementById("task-duration");
    var arrivalInput = document.getElementById("task-arrival");
    var name = nameInput.value.trim();
    var duration = parseFloat(durationInput.value);
    var arrival = parseFloat(arrivalInput.value);

    if (!name) {
        alert("Please enter a task name");
        return;
    }
    if (isNaN(duration) || duration <= 0 || duration > 30) {
        alert("Please enter a valid duration between 0.05 and 30 seconds");
        return;
    }
    if (isNaN(arrival) || arrival < 0) {
        alert("Please enter a valid arrival time >= 0");
        return;
    }

    var task = {
        id: "T" + String(taskCounter).padStart(3, "0"),
        name: name,
        duration: duration,
        arrival_time: arrival,
        status: "READY"
    };

    preparedTasks.push(task);
    taskCounter++;

    // Clear inputs
    nameInput.value = "";
    durationInput.value = "8";
    arrivalInput.value = "0";

    savePreparedTasks();
    renderPreparedTasks();
}

function removePreparedTask(index) {
    preparedTasks.splice(index, 1);
    savePreparedTasks();
    renderPreparedTasks();
}

function savePreparedTasks() {
    // Send to backend to persist
    fetch("/api/simulation/prepared", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            name: preparedTasks[preparedTasks.length - 1].name,
            duration: preparedTasks[preparedTasks.length - 1].duration,
            arrival_time: preparedTasks[preparedTasks.length - 1].arrival_time
        })
    }).catch(function () {});
}

function loadPreparedTasks() {
    fetch("/api/simulation/prepared")
        .then(function (r) { return r.json(); })
        .then(function (data) {
            preparedTasks = data.tasks.map(function (t, i) {
                return {
                    id: "T" + String(i + 1).padStart(3, "0"),
                    name: t.name,
                    duration: t.duration,
                    status: t.status
                };
            });
            taskCounter = preparedTasks.length + 1;
            renderPreparedTasks();
        })
        .catch(function () {});
}

function renderPreparedTasks() {
    var tbody = document.getElementById("prepared-tbody");
    if (!tbody) { return; }

    if (preparedTasks.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="empty-row">No tasks prepared yet.</td></tr>';
        return;
    }

    var rows = "";
    for (var i = 0; i < preparedTasks.length; i++) {
        var task = preparedTasks[i];
        rows += "<tr>" +
            "<td>" + task.id + "</td>" +
            "<td>" + escapeHtml(task.name) + "</td>" +
            "<td>" + task.duration + "s</td>" +
            "<td>" + task.arrival_time + "s</td>" +
            '<td><span class="task-status-badge ts-ready">' + task.status + "</span></td>' +
            '<td><button class="btn btn-secondary btn-sm" onclick="removePreparedTask(' + i + ')">Remove</button></td>' +
        "</tr>";
    }
    tbody.innerHTML = rows;
}

function loadSampleTasks() {
    // Add sample tasks with different arrival times and longer durations
    var sampleTasks = [
        { name: "Database Query", duration: 10, arrival_time: 0 },
        { name: "File Processing", duration: 8, arrival_time: 2 },
        { name: "API Request", duration: 6, arrival_time: 4 },
        { name: "Data Analysis", duration: 12, arrival_time: 6 },
        { name: "Report Generation", duration: 7, arrival_time: 8 }
    ];

    for (var i = 0; i < sampleTasks.length; i++) {
        var task = sampleTasks[i];
        preparedTasks.push({
            id: "T" + String(taskCounter).padStart(3, "0"),
            name: task.name,
            duration: task.duration,
            arrival_time: task.arrival_time,
            status: "READY"
        });
        taskCounter++;
    }

    savePreparedTasks();
    renderPreparedTasks();
}

/* ==========================================================================
   Run Simulation
   ========================================================================== */

function runSimulation() {
    if (preparedTasks.length === 0) {
        alert("Please add at least one task before running the simulation");
        return;
    }

    // Disable task preparation
    document.getElementById("task-name").disabled = true;
    document.getElementById("task-duration").disabled = true;
    document.getElementById("task-arrival").disabled = true;
    document.querySelector(".task-entry-form button").disabled = true;

    // Sort tasks by arrival time
    preparedTasks.sort(function (a, b) {
        return a.arrival_time - b.arrival_time;
    });

    // Submit tasks staggered by arrival time
    var baseTime = Date.now();
    var submittedCount = 0;

    preparedTasks.forEach(function (task, index) {
        var delay = task.arrival_time * 1000; // Convert to milliseconds

        setTimeout(function () {
            fetch("/api/tasks", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    name: task.name,
                    duration: task.duration,
                    arrival_time: (baseTime + delay) / 1000
                })
            })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                submittedCount++;
                if (submittedCount === 1) {
                    // First task submitted, show simulation and start polling
                    simulationRunning = true;
                    document.getElementById("sim-status").textContent = "RUNNING";
                    document.getElementById("sim-status").className = "sidebar-status status-running";
                    document.getElementById("live-simulation").style.display = "block";
                    document.getElementById("live-simulation").scrollIntoView({ behavior: "smooth", block: "start" });
                    startPolling();
                }
            })
            .catch(function (err) {
                console.error("Error submitting task:", err);
            });
        }, delay);
    });

    // Update simulation state
    fetch("/api/simulation/start", {
        method: "POST"
    })
    .then(function (r) { return r.json(); })
    .catch(function () {});
}

/* ==========================================================================
   Polling
   ========================================================================== */

function startPolling() {
    pollingInterval = setInterval(function () {
        refreshSimulation();
    }, 1500);
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
   Fetch Workers
   ========================================================================== */

function fetchWorkers() {
    fetch("/api/workers")
        .then(function (r) { return r.json(); })
        .then(function (workers) {
            renderWorkers(workers);
            fetchWorkerQueues();
        })
        .catch(function () {});
}

function fetchWorkerQueues() {
    fetch("/api/workers/queues")
        .then(function (r) { return r.json(); })
        .then(function (queues) {
            for (var workerId in queues) {
                var queueItems = queues[workerId] || [];
                var queueHtml = "";
                if (queueItems.length === 0) {
                    queueHtml = '<div class="worker-queue-empty">Empty</div>';
                } else {
                    for (var i = 0; i < queueItems.length; i++) {
                        var q = queueItems[i];
                        queueHtml += '<div class="worker-queue-item">' + q.task_id + ' — ' + escapeHtml(q.name) + ' (' + q.duration + 's)</div>';
                    }
                }
                var queueContainer = document.getElementById("queue-" + workerId.replace(/[^a-zA-Z0-9]/g, "-"));
                if (queueContainer) {
                    queueContainer.innerHTML = queueHtml;
                }
            }
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
        : '<span class="worker-current-task" style="color: var(--color-text-muted);">None</span>';

    var actionBtns = "";
    if (w.status === "IDLE" || w.status === "BUSY") {
        actionBtns = '<button class="btn btn-fail" onclick="failWorker(\'' + w.worker_id + '\')">Fail Worker</button>';
    }
    if (w.status === "FAILED") {
        actionBtns = '<button class="btn btn-recover" onclick="recoverWorker(\'' + w.worker_id + '\')">Recover Worker</button>';
    }

    return '<div class="worker-panel">' +
        '<div class="worker-panel-header">' +
            '<span class="worker-panel-title">' + w.worker_id + '</span>' +
            '<span class="worker-status-badge ' + statusClass + '">' + w.status + '</span>' +
        '</div>' +
        '<div class="worker-section">' +
            '<div class="worker-section-label">Worker Status</div>' +
            '<div class="worker-section-value">' + w.status + '</div>' +
        '</div>' +
        '<div class="worker-section">' +
            '<div class="worker-section-label">Execution Thread</div>' +
            '<span class="worker-thread-badge">' + threadState + '</span>' +
        '</div>' +
        '<div class="worker-section">' +
            '<div class="worker-section-label">Current Task</div>' +
            currentTaskHtml +
        '</div>' +
        '<div class="worker-section">' +
            '<div class="worker-section-label">Workload</div>' +
            '<div class="worker-section-value">' + w.workload + '</div>' +
        '</div>' +
        '<div class="worker-section">' +
            '<div class="worker-section-label">Queue Length</div>' +
            '<div class="worker-section-value">' + w.queue_size + '</div>' +
        '</div>' +
        '<div class="worker-section">' +
            '<div class="worker-section-label">Queue</div>' +
            '<div class="worker-queue" id="queue-' + w.worker_id.replace(/[^a-zA-Z0-9]/g, "-") + '">' +
                '<div class="worker-queue-empty">Loading...</div>' +
            '</div>' +
        '</div>' +
        '<div class="worker-actions">' + actionBtns + '</div>' +
    '</div>';
}

/* ==========================================================================
   Fetch Tasks
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
    var arrival = t.arrival_time !== null ? (t.arrival_time - t.created_at).toFixed(2) + "s" : "0s";

    return "<tr>" +
        "<td>" + t.id + "</td>" +
        "<td>" + escapeHtml(t.name) + "</td>" +
        "<td>" + t.duration.toFixed(2) + "s</td>" +
        "<td>" + arrival + "</td>" +
        "<td>" + worker + "</td>" +
        '<td><span class="task-status-badge ' + statusClass + '">' + t.status + "</span></td>" +
        "<td>" + waitTime + "</td>" +
        "<td>" + execTime + "</td>" +
    "</tr>";
}

/* ==========================================================================
   Fetch Metrics
   ========================================================================== */

function fetchMetrics() {
    fetch("/api/metrics")
        .then(function (r) { return r.json(); })
        .then(function (m) {
            document.getElementById("perf-total").textContent = m.total_submitted;
            document.getElementById("perf-avg-wait").textContent = m.avg_waiting_time.toFixed(2) + " units";
            document.getElementById("perf-avg-exec").textContent = m.avg_execution_time.toFixed(2) + " units";
            document.getElementById("perf-total-exec").textContent = m.total_execution_time.toFixed(2) + " units";
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
        container.innerHTML = '<p class="empty-text">Run a simulation to see the execution timeline.</p>';
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
        container.innerHTML = '<p class="empty-text">No execution data available yet.</p>';
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
                    'title="' + t.id + ' - ' + escapeHtml(t.name) + ' (' + duration.toFixed(2) + 's)">' +
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

/* ==========================================================================
   Worker Actions
   ========================================================================== */

function failWorker(workerId) {
    fetch("/api/workers/" + encodeURIComponent(workerId) + "/fail", {
        method: "POST"
    })
    .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
    .then(function (result) {
        if (result.ok) {
            // Will be reflected in next poll
        } else {
            alert("Error: " + result.data.error);
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
            // Will be reflected in next poll
        } else {
            alert("Error: " + result.data.error);
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
    document.getElementById("sim-status").textContent = "COMPLETE";
    document.getElementById("sim-status").className = "sidebar-status status-complete";

    document.getElementById("simulation-complete").style.display = "block";
}

/* ==========================================================================
   Reset Simulation
   ========================================================================== */

function resetSimulation() {
    stopPolling();

    fetch("/api/simulation/reset", {
        method: "POST"
    })
    .then(function (r) { return r.json(); })
    .then(function (data) {
        // Reset state
        preparedTasks = [];
        taskCounter = 1;
        simulationRunning = false;

        // Reset UI
        document.getElementById("sim-status").textContent = "READY";
        document.getElementById("sim-status").className = "sidebar-status status-ready";
        document.getElementById("live-simulation").style.display = "none";
        document.getElementById("simulation-complete").style.display = "none";

        // Re-enable inputs
        document.getElementById("task-name").disabled = false;
        document.getElementById("task-duration").disabled = false;
        document.querySelector(".task-entry-form button").disabled = false;

        // Clear prepared tasks display
        renderPreparedTasks();

        // Clear worker grid
        document.getElementById("workers-grid").innerHTML = "";

        // Clear task table
        document.getElementById("task-tbody").innerHTML = '<tr><td colspan="7" class="empty-row">No tasks submitted yet.</td></tr>';

        // Reset metrics
        document.getElementById("perf-total").textContent = "0";
        document.getElementById("perf-avg-wait").textContent = "0.00 units";
        document.getElementById("perf-avg-exec").textContent = "0.00 units";
        document.getElementById("perf-total-exec").textContent = "0.00 units";
    })
    .catch(function () {});
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
