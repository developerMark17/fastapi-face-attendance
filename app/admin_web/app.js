const state = {
  token: localStorage.getItem("attendanceAdminToken") || "",
  view: "dashboard",
  students: [],
  plans: [],
};

const els = {
  loginView: document.getElementById("login-view"),
  appView: document.getElementById("app-view"),
  loginForm: document.getElementById("login-form"),
  loginError: document.getElementById("login-error"),
  logoutButton: document.getElementById("logout-button"),
  notice: document.getElementById("notice"),
  viewTitle: document.getElementById("view-title"),
  metrics: document.getElementById("metrics"),
  latestLogs: document.getElementById("latest-logs"),
  departmentBreakdown: document.getElementById("department-breakdown"),
  studentForm: document.getElementById("student-form"),
  studentsTable: document.getElementById("students-table"),
  attendanceTable: document.getElementById("attendance-table"),
  attendanceSummary: document.getElementById("attendance-summary"),
  paymentsTable: document.getElementById("payments-table"),
  planSelect: document.getElementById("plan-select"),
};

function showApp(isAuthed) {
  els.loginView.classList.toggle("hidden", isAuthed);
  els.appView.classList.toggle("hidden", !isAuthed);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function showNotice(message, type = "success") {
  if (!message) {
    els.notice.className = "notice hidden";
    els.notice.textContent = "";
    return;
  }
  els.notice.className = `notice ${type}`;
  els.notice.textContent = message;
}

function dateTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString([], {dateStyle: "medium", timeStyle: "short"});
}

function money(amountCents, currency) {
  return new Intl.NumberFormat([], {
    style: "currency",
    currency: (currency || "usd").toUpperCase(),
  }).format((amountCents || 0) / 100);
}

async function api(path, options = {}) {
  const headers = {
    Accept: "application/json",
    ...(options.headers || {}),
  };
  if (state.token) {
    headers.Authorization = `Bearer ${state.token}`;
  }
  if (options.body && !(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(options.body);
  }

  const response = await fetch(path, {...options, headers});
  const text = await response.text();
  const data = text ? JSON.parse(text) : {};
  if (!response.ok) {
    if (response.status === 401) {
      logout(false);
    }
    throw new Error(data.detail || data.message || "Request failed");
  }
  return data;
}

function renderTable(target, headers, rows, emptyText = "No records found") {
  if (!rows.length) {
    target.innerHTML = `<div class="empty-state">${escapeHtml(emptyText)}</div>`;
    return;
  }

  const head = headers.map((header) => `<th>${escapeHtml(header)}</th>`).join("");
  const body = rows.map((row) => `<tr>${row.join("")}</tr>`).join("");
  target.innerHTML = `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

function badge(value) {
  const normalized = String(value || "").toLowerCase();
  const tone = ["paid", "active", "in"].includes(normalized)
    ? "good"
    : ["pending", "trial", "out"].includes(normalized)
      ? "warn"
      : "";
  return `<span class="badge ${tone}">${escapeHtml(value || "unknown")}</span>`;
}

function setActiveView(view) {
  state.view = view;
  document.querySelectorAll(".tab").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === view);
  });
  document.querySelectorAll(".view-section").forEach((section) => {
    section.classList.toggle("hidden", section.id !== `${view}-section`);
  });
  els.viewTitle.textContent = {
    dashboard: "Overview",
    students: "Students",
    attendance: "Attendance",
    payments: "Payments",
  }[view];

  showNotice("");
  if (view === "dashboard") loadDashboard();
  if (view === "students") loadStudents();
  if (view === "attendance") loadAttendance();
  if (view === "payments") loadPayments();
}

async function loadDashboard() {
  try {
    const data = await api("/admin/dashboard");
    els.metrics.innerHTML = data.metrics
      .map((metric) => `<article class="metric"><span>${escapeHtml(metric.label)}</span><strong>${escapeHtml(metric.value)}</strong></article>`)
      .join("");
    renderTable(
      els.latestLogs,
      ["Student", "Code", "Action", "Time"],
      (data.latest_logs || []).map((row) => [
        `<td>${escapeHtml(row.name)}</td>`,
        `<td>${escapeHtml(row.student_code || "")}</td>`,
        `<td>${badge(row.action)}</td>`,
        `<td>${escapeHtml(dateTime(row.timestamp))}</td>`,
      ]),
      "No attendance yet",
    );

    const entries = Object.entries(data.department_breakdown || {});
    const max = Math.max(1, ...entries.map((entry) => entry[1]));
    els.departmentBreakdown.innerHTML = entries
      .map(([label, value]) => {
        const width = Math.max(6, Math.round((value / max) * 100));
        return `<div class="bar-row"><div class="bar-label"><span>${escapeHtml(label)}</span><span>${value}</span></div><div class="bar"><span style="width:${width}%"></span></div></div>`;
      })
      .join("");
  } catch (error) {
    showNotice(error.message, "error");
  }
}

async function loadStudents() {
  try {
    const search = document.getElementById("student-search").value.trim();
    const params = new URLSearchParams({limit: "100"});
    if (search) params.set("q", search);
    const data = await api(`/admin/students?${params}`);
    state.students = data.items || [];
    renderTable(
      els.studentsTable,
      ["Name", "Code", "Dept", "Sem", "Face", "Payment", "Status", ""],
      state.students.map((student) => [
        `<td><strong>${escapeHtml(student.name)}</strong><br><small>${escapeHtml(student.email || "")}</small></td>`,
        `<td>${escapeHtml(student.student_code || "")}</td>`,
        `<td>${escapeHtml(student.department)} / ${escapeHtml(student.section)}</td>`,
        `<td>${escapeHtml(student.semester)}</td>`,
        `<td>${badge(student.face_enrolled ? "ready" : "pending")}</td>`,
        `<td>${badge(student.payment_status)}</td>`,
        `<td>${badge(student.status)}</td>`,
        `<td><div class="row-actions"><button class="secondary-button" data-action="edit-student" data-id="${student.id}">Edit</button><button class="secondary-button" data-action="deactivate-student" data-id="${student.id}">Disable</button></div></td>`,
      ]),
      "No students found",
    );
  } catch (error) {
    showNotice(error.message, "error");
  }
}

function resetStudentForm() {
  els.studentForm.reset();
  document.getElementById("student-id").value = "";
  document.getElementById("student-save").textContent = "Add Student";
  document.getElementById("student-department").value = "General";
  document.getElementById("student-program").value = "General";
  document.getElementById("student-semester").value = "1";
  document.getElementById("student-section").value = "A";
}

function fillStudentForm(student) {
  document.getElementById("student-id").value = student.id;
  document.getElementById("student-name").value = student.name || "";
  document.getElementById("student-code").value = student.student_code || "";
  document.getElementById("student-email").value = student.email || "";
  document.getElementById("student-phone").value = student.phone || "";
  document.getElementById("student-department").value = student.department || "General";
  document.getElementById("student-program").value = student.program || "General";
  document.getElementById("student-semester").value = student.semester || 1;
  document.getElementById("student-section").value = student.section || "A";
  document.getElementById("student-status").value = student.status || "active";
  document.getElementById("student-payment-status").value = student.payment_status || "trial";
  document.getElementById("student-save").textContent = "Update Student";
}

async function saveStudent(event) {
  event.preventDefault();
  const id = document.getElementById("student-id").value;
  const payload = {
    name: document.getElementById("student-name").value.trim(),
    student_code: document.getElementById("student-code").value.trim() || null,
    email: document.getElementById("student-email").value.trim() || null,
    phone: document.getElementById("student-phone").value.trim() || null,
    department: document.getElementById("student-department").value.trim() || "General",
    program: document.getElementById("student-program").value.trim() || "General",
    semester: Number(document.getElementById("student-semester").value || 1),
    section: document.getElementById("student-section").value.trim() || "A",
    status: document.getElementById("student-status").value,
    payment_status: document.getElementById("student-payment-status").value,
  };

  try {
    if (id) {
      await api(`/admin/students/${id}`, {method: "PUT", body: payload});
      showNotice("Student updated");
    } else {
      await api("/admin/students", {method: "POST", body: payload});
      showNotice("Student added");
    }
    resetStudentForm();
    loadStudents();
    loadDashboard();
  } catch (error) {
    showNotice(error.message, "error");
  }
}

async function loadAttendance() {
  try {
    const params = new URLSearchParams({limit: "150"});
    const department = document.getElementById("attendance-department").value.trim();
    const section = document.getElementById("attendance-section-filter").value.trim();
    const course = document.getElementById("attendance-course").value.trim();
    if (department) params.set("department", department);
    if (section) params.set("section", section);
    if (course) params.set("course_code", course);

    const data = await api(`/admin/reports/attendance?${params}`);
    els.attendanceSummary.innerHTML = [
      ["Records", data.total],
      ["Present", data.present_students],
      ["Checked In", data.checked_in_now],
    ]
      .map(([label, value]) => `<article class="metric"><span>${label}</span><strong>${value}</strong></article>`)
      .join("");
    renderTable(
      els.attendanceTable,
      ["Student", "Code", "Dept", "Action", "Course", "Time"],
      (data.logs || []).map((row) => [
        `<td>${escapeHtml(row.name)}</td>`,
        `<td>${escapeHtml(row.student_code || "")}</td>`,
        `<td>${escapeHtml(row.department || "")} / ${escapeHtml(row.section || "")}</td>`,
        `<td>${badge(row.action)}</td>`,
        `<td>${escapeHtml(row.course_code || "")}</td>`,
        `<td>${escapeHtml(dateTime(row.timestamp))}</td>`,
      ]),
      "No attendance records found",
    );
  } catch (error) {
    showNotice(error.message, "error");
  }
}

async function loadPlans() {
  const data = await api("/billing/plans");
  state.plans = data.plans || [];
  els.planSelect.innerHTML = state.plans
    .map((plan) => `<option value="${escapeHtml(plan.code)}">${escapeHtml(plan.name)} - ${escapeHtml(money(plan.amount_cents, plan.currency))}</option>`)
    .join("");
}

async function loadPayments() {
  try {
    if (!state.plans.length) {
      await loadPlans();
    }
    const data = await api("/admin/payments?limit=100");
    renderTable(
      els.paymentsTable,
      ["Student", "Code", "Plan", "Amount", "Status", "Paid", "Provider"],
      (data.items || []).map((row) => [
        `<td>${escapeHtml(row.student_name || "")}</td>`,
        `<td>${escapeHtml(row.student_code || "")}</td>`,
        `<td>${escapeHtml(row.plan_code)}</td>`,
        `<td>${escapeHtml(money(row.amount_cents, row.currency))}</td>`,
        `<td>${badge(row.status)}</td>`,
        `<td>${escapeHtml(dateTime(row.paid_at))}</td>`,
        `<td>${escapeHtml(row.provider)}</td>`,
      ]),
      "No payments found",
    );
  } catch (error) {
    showNotice(error.message, "error");
  }
}

async function startCheckout() {
  try {
    const payload = {
      plan_code: els.planSelect.value,
      student_code: document.getElementById("payment-student-code").value.trim() || null,
    };
    const data = await api("/payments/checkout-session", {method: "POST", body: payload});
    showNotice(data.status === "paid" ? "Demo payment completed" : "Checkout created");
    if (data.checkout_url) {
      window.open(data.checkout_url, "_blank", "noopener,noreferrer");
    }
    loadPayments();
    loadDashboard();
  } catch (error) {
    showNotice(error.message, "error");
  }
}

async function logout(callServer = true) {
  if (callServer && state.token) {
    try {
      await api("/auth/logout", {method: "POST"});
    } catch (_) {
      /* Local logout still clears the token. */
    }
  }
  state.token = "";
  localStorage.removeItem("attendanceAdminToken");
  showApp(false);
}

els.loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  els.loginError.textContent = "";
  try {
    const data = await api("/auth/token", {
      method: "POST",
      body: {
        username: document.getElementById("login-username").value,
        password: document.getElementById("login-password").value,
      },
    });
    state.token = data.access_token;
    localStorage.setItem("attendanceAdminToken", state.token);
    showApp(true);
    setActiveView("dashboard");
  } catch (error) {
    els.loginError.textContent = error.message;
  }
});

els.logoutButton.addEventListener("click", () => logout(true));
els.studentForm.addEventListener("submit", saveStudent);
document.getElementById("student-reset").addEventListener("click", resetStudentForm);
document.getElementById("refresh-dashboard").addEventListener("click", loadDashboard);
document.getElementById("refresh-students").addEventListener("click", loadStudents);
document.getElementById("refresh-attendance").addEventListener("click", loadAttendance);
document.getElementById("refresh-payments").addEventListener("click", loadPayments);
document.getElementById("start-checkout").addEventListener("click", startCheckout);
document.getElementById("student-search").addEventListener("input", () => {
  window.clearTimeout(window.studentSearchTimer);
  window.studentSearchTimer = window.setTimeout(loadStudents, 250);
});

document.querySelector(".tabs").addEventListener("click", (event) => {
  const button = event.target.closest("[data-view]");
  if (button) setActiveView(button.dataset.view);
});

document.body.addEventListener("click", async (event) => {
  const actionButton = event.target.closest("[data-action]");
  if (!actionButton) return;
  const id = Number(actionButton.dataset.id);

  if (actionButton.dataset.action === "edit-student") {
    const student = state.students.find((item) => item.id === id);
    if (student) fillStudentForm(student);
  }

  if (actionButton.dataset.action === "deactivate-student") {
    try {
      await api(`/admin/students/${id}`, {method: "DELETE"});
      showNotice("Student disabled");
      loadStudents();
      loadDashboard();
    } catch (error) {
      showNotice(error.message, "error");
    }
  }
});

["attendance-department", "attendance-section-filter", "attendance-course"].forEach((id) => {
  document.getElementById(id).addEventListener("input", () => {
    window.clearTimeout(window.attendanceFilterTimer);
    window.attendanceFilterTimer = window.setTimeout(loadAttendance, 300);
  });
});

const params = new URLSearchParams(window.location.search);
if (params.get("payment")) {
  showNotice(`Payment status: ${params.get("payment")}`);
}

showApp(Boolean(state.token));
if (state.token) {
  setActiveView("dashboard");
}
