/**
 * ExamExpert AI — Client Application Controller
 * SJB Institute of Technology | Office of the Controller of Examinations
 *
 * Implements 2-step OTP + Password Authentication, Progressive Single-Dashboard Allocation,
 * 50:50 Parity Calculation, Conflict Prevention, PDF Generation, and Module Switching.
 */

// ─── Global State ─────────────────────────────────────────────────────────────
const state = {
  token: null,
  currentUser: null,
  targetRole: "Admin", // 'Admin' | 'HOD' | 'Faculty'
  otpPolicy: "ALL_ROLES",
  smtpConfigured: false,
  activeCycle: "2025-26",
  
  // Dashboard selections
  academicYear: "",
  department: "",
  semester: "",
  subjectId: null,
  subjectData: null,
  minHandled: 3,
  totalRequired: 4,

  // Quota & Selection State (dynamically set from policy)
  internalQuota: null,
  externalQuota: null,
  selectedInternalIds: new Set(),
  selectedExternalIds: new Set(),
  allInternalCandidates: [],
  allExternalCandidates: [],

  // Exception State
  requiresException: false,
  exceptionReason: "",

  // Recent confirmed allocation
  lastAllocationId: null,
  lastRefNumber: null,

  // Module 8: Expertise Mappings
  allMappings: [],
  selectedMappingIds: new Set()
};

const API_BASE = "";

// ─── UI Design System: Toast Notifications & Feedback ────────────────────────
function showToast(title, message = "", type = "info", duration = 4000) {
  const container = document.getElementById("toast-container");
  if (!container) return;

  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;

  const iconMap = {
    success: "✓",
    error: "✕",
    warning: "⚠",
    info: "ℹ"
  };

  const icon = iconMap[type] || "ℹ";

  toast.innerHTML = `
    <div class="toast-icon">${icon}</div>
    <div class="toast-content">
      <div class="toast-title">${title}</div>
      ${message ? `<div class="toast-message">${message}</div>` : ""}
    </div>
    <button class="toast-close" onclick="this.parentElement.remove()">&times;</button>
  `;

  container.appendChild(toast);

  if (duration > 0) {
    setTimeout(() => {
      toast.classList.add("toast-fade-out");
      setTimeout(() => {
        if (toast.parentElement) toast.remove();
      }, 200);
    }, duration);
  }
}

function renderEmptyState(container, title = "No Records Found", desc = "There are currently no items matching your criteria.", icon = "📭") {
  if (typeof container === "string") {
    container = document.getElementById(container);
  }
  if (!container) return;
  container.innerHTML = `
    <div class="empty-state">
      <div class="empty-state-icon">${icon}</div>
      <div class="empty-state-title">${title}</div>
      <div class="empty-state-desc">${desc}</div>
    </div>
  `;
}

function showLoading(container, text = "Loading data from Controller of Examinations registry...") {
  if (typeof container === "string") {
    container = document.getElementById(container);
  }
  if (!container) return;
  container.innerHTML = `
    <div class="loading-container">
      <div class="spinner spinner-blue spinner-lg"></div>
      <div>${text}</div>
    </div>
  `;
}



// ─── Initialization & Session Guard ──────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  // Parse role from path if present (e.g. /login/admin, /login/hod, /login/faculty)
  const path = window.location.pathname.toLowerCase();
  if (path.includes("/login/hod")) {
    state.targetRole = "HOD";
  } else if (path.includes("/login/faculty")) {
    state.targetRole = "Faculty";
  } else {
    state.targetRole = "Admin";
  }

  fetchAuthSystemStatus();

  const savedToken = sessionStorage.getItem("examexpert_token") || localStorage.getItem("examexpert_token");
  if (savedToken) {
    state.token = savedToken;
    verifyExistingSession();
  } else {
    showLoginView();
  }
});

async function fetchAuthSystemStatus() {
  try {
    const res = await fetch(`${API_BASE}/api/auth/status`);
    if (res.ok) {
      const data = await res.json();
      state.smtpConfigured = data.smtp_configured;
      state.otpPolicy = data.otp_policy;
      
      const banner = document.getElementById("dev-env-banner");
      if (banner) {
        banner.style.display = data.smtp_configured ? "none" : "flex";
      }
    }
  } catch (e) {}
}


function showLoginView() {
  document.getElementById("login-view").style.display = "flex";
  document.getElementById("app-view").style.display = "none";
  switchRolePortal(state.targetRole, false);
  resetAuthFlow();
}

function showAppView() {
  document.getElementById("login-view").style.display = "none";
  document.getElementById("app-view").style.display = "flex";

  // Role-based visibility
  const isAdmin = state.currentUser && state.currentUser.role === "Admin";
  const navUsers = document.getElementById("nav-users");
  if (navUsers) navUsers.style.display = isAdmin ? "inline-flex" : "none";

  const navDatasets = document.getElementById("nav-datasets");
  if (navDatasets) navDatasets.style.display = isAdmin ? "inline-flex" : "none";

  const navAcceptance = document.getElementById("nav-acceptance");
  if (navAcceptance) navAcceptance.style.display = isAdmin ? "inline-flex" : "none";

  const btnAddSubject = document.getElementById("btn-add-subject");
  if (btnAddSubject) btnAddSubject.style.display = isAdmin ? "inline-flex" : "none";

  const subjSubtitle = document.getElementById("subjects-scope-subtitle");
  const subjDeptFilter = document.getElementById("subj-filter-dept");
  if (state.currentUser && !isAdmin && state.currentUser.department) {
    if (subjSubtitle) {
      subjSubtitle.textContent = `Department Scope: ${state.currentUser.department} (View-Only). Subjects are strictly filtered to your department.`;
    }
    if (subjDeptFilter) {
      subjDeptFilter.value = state.currentUser.department;
      subjDeptFilter.disabled = true;
    }
  } else {
    if (subjSubtitle) {
      subjSubtitle.textContent = "Browse, filter, add, and manage syllabus courses across all academic departments.";
    }
    if (subjDeptFilter) {
      subjDeptFilter.disabled = false;
    }
  }

  // Module 6: Faculty tab role-based scoping
  const facSubtitle = document.getElementById("faculty-scope-subtitle");
  const facDeptFilter = document.getElementById("fac-filter-dept");
  const facTypeFilter = document.getElementById("fac-filter-type");
  const facInstFilter = document.getElementById("fac-filter-inst");
  const whitelistCard = document.getElementById("whitelist-governance-card");

  if (whitelistCard) whitelistCard.style.display = isAdmin ? "block" : "none";

  if (state.currentUser && !isAdmin && state.currentUser.department) {
    if (facSubtitle) {
      facSubtitle.textContent = `Department Scope: ${state.currentUser.department} (View-Only). Viewing internal departmental faculty records.`;
    }
    if (facDeptFilter) {
      facDeptFilter.value = state.currentUser.department;
      facDeptFilter.disabled = true;
    }
    if (facTypeFilter) {
      facTypeFilter.value = "internal";
      facTypeFilter.disabled = true;
    }
    if (facInstFilter) {
      facInstFilter.disabled = true;
    }
  } else if (state.currentUser && state.currentUser.role === "Faculty") {
    if (facSubtitle) {
      facSubtitle.textContent = `Personal Faculty Profile & Status.`;
    }
    if (facDeptFilter) facDeptFilter.disabled = true;
    if (facTypeFilter) {
      facTypeFilter.value = "internal";
      facTypeFilter.disabled = true;
    }
    if (facInstFilter) facInstFilter.disabled = true;
  } else {
    if (facSubtitle) {
      facSubtitle.textContent = "Browse internal faculty records, external experts, eligibility statuses, and external institution whitelisting.";
    }
    if (facDeptFilter) facDeptFilter.disabled = false;
    if (facTypeFilter) facTypeFilter.disabled = false;
    if (facInstFilter) facInstFilter.disabled = false;
  }

  const adminBanner = document.getElementById("admin-live-stats-banner");
  if (adminBanner) {
    adminBanner.style.display = isAdmin ? "grid" : "none";
    if (isAdmin) loadDashboardStats();
  }

  // Module 8: Expertise Mappings role-based scoping & controls
  const mapSubtitle = document.getElementById("mappings-scope-subtitle");
  const mapDeptFilter = document.getElementById("map-filter-dept");
  const btnGenSugg = document.getElementById("btn-generate-mapping-suggestions");
  const btnBulkConf = document.getElementById("btn-bulk-confirm-mappings");
  const btnAddMap = document.getElementById("btn-add-mapping");
  const thBulk = document.getElementById("th-mapping-bulk");
  const thActions = document.getElementById("th-mapping-actions");

  if (btnGenSugg) btnGenSugg.style.display = isAdmin ? "inline-flex" : "none";
  if (btnBulkConf) btnBulkConf.style.display = isAdmin ? "inline-flex" : "none";
  if (btnAddMap) btnAddMap.style.display = isAdmin ? "inline-flex" : "none";
  if (thBulk) thBulk.style.display = isAdmin ? "table-cell" : "none";
  if (thActions) thActions.style.display = isAdmin ? "table-cell" : "none";

  if (state.currentUser && !isAdmin && state.currentUser.department) {
    if (mapSubtitle) {
      mapSubtitle.textContent = `Department Scope: ${state.currentUser.department} (View-Only). Viewing mappings for your department's internal faculty & curriculum.`;
    }
    if (mapDeptFilter) {
      mapDeptFilter.value = state.currentUser.department;
      mapDeptFilter.disabled = true;
    }
  } else if (state.currentUser && state.currentUser.role === "Faculty") {
    if (mapSubtitle) {
      mapSubtitle.textContent = `My Expertise Mappings (View-Only). Showing subject mappings associated with your profile.`;
    }
    if (mapDeptFilter) mapDeptFilter.disabled = true;
  } else {
    if (mapSubtitle) {
      mapSubtitle.textContent = `Review, confirm, or reject faculty-subject expertise mappings (EXACT_EXPERIENCE, SPECIALIZATION, RELATED) used for intelligent question-paper-setter recommendations.`;
    }
    if (mapDeptFilter) mapDeptFilter.disabled = false;
  }

  // Module 12: HOD & Admin Pending Approvals tab visibility
  const isHodOrAdmin = state.currentUser && (state.currentUser.role === "HOD" || state.currentUser.role === "Admin");
  const navPending = document.getElementById("nav-pending-approvals");
  if (navPending) navPending.style.display = isHodOrAdmin ? "inline-flex" : "none";

  const pendingSub = document.getElementById("pending-approvals-subtitle");
  if (pendingSub && state.currentUser) {
    if (state.currentUser.role === "HOD") {
      pendingSub.textContent = `Department Scope: ${state.currentUser.department || "Your Department"}. Review and decide on nominated question-paper setters for your department.`;
    } else if (state.currentUser.role === "Admin") {
      pendingSub.textContent = "Administrative Overview: Review question-paper setter allocations across all departments awaiting HOD approval.";
    }
  }

  initializeDashboard();
  loadUnreadNotificationCount();
}

async function verifyExistingSession() {
  try {
    const res = await fetch(`${API_BASE}/api/auth/me`, {
      headers: { "Authorization": `Bearer ${state.token}` }
    });
    if (res.ok) {
      state.currentUser = await res.json();
      document.getElementById("header-user-badge").textContent = `${state.currentUser.username} (${state.currentUser.role})`;
      showAppView();
    } else {
      sessionStorage.removeItem("examexpert_token");
      showLoginView();
    }
  } catch (err) {
    showLoginView();
  }
}


// ─── Authentication Handlers & Role Portal Switching ─────────────────────────
function switchRolePortal(role, updateUrl = true) {
  state.targetRole = role;
  
  // Update button active state
  ["Admin", "HOD", "Faculty"].forEach(r => {
    const btn = document.getElementById(`btn-role-${r.toLowerCase()}`);
    if (btn) {
      if (r === role) btn.classList.add("active");
      else btn.classList.remove("active");
    }
  });

  const badge = document.getElementById("login-role-badge");
  const emailLabel = document.getElementById("login-email-label");
  const emailInput = document.getElementById("login-email");

  if (role === "Admin") {
    if (badge) {
      badge.textContent = "Controller of Examinations (Admin) Portal";
      badge.className = "badge badge-role-admin";
    }
    if (emailLabel) emailLabel.textContent = "Authorized Administrator Email";
    if (emailInput) {
      emailInput.placeholder = "admin@sjbit.edu.in";
      emailInput.value = "admin@sjbit.edu.in";
    }
  } else if (role === "HOD") {
    if (badge) {
      badge.textContent = "Head of Department (HOD) Portal";
      badge.className = "badge badge-role-hod";
    }
    if (emailLabel) emailLabel.textContent = "Department HOD Email";
    if (emailInput) {
      emailInput.placeholder = "hod.mca@sjbit.edu.in";
      emailInput.value = "hod.mca@sjbit.edu.in";
    }
  } else if (role === "Faculty") {
    if (badge) {
      badge.textContent = "Faculty Member Portal";
      badge.className = "badge badge-role-faculty";
    }
    if (emailLabel) emailLabel.textContent = "Registered Faculty Email";
    if (emailInput) {
      emailInput.placeholder = "faculty.mca@sjbit.edu.in";
      emailInput.value = "faculty.mca@sjbit.edu.in";
    }
  }

  if (updateUrl && window.history && window.history.pushState) {
    window.history.pushState(null, "", `/login/${role.toLowerCase()}`);
  }

  resetAuthFlow();
}

function switchAuthMode(mode) {
  clearLoginAlert();
  document.getElementById("auth-mode-login").style.display = mode === "login" ? "block" : "none";
  document.getElementById("auth-mode-activation").style.display = mode === "activation" ? "block" : "none";
  document.getElementById("auth-mode-forgot").style.display = mode === "forgot" ? "block" : "none";
}

function showLoginAlert(msg, type = "info") {
  const alertBox = document.getElementById("login-alert-box");
  alertBox.className = `login-alert ${type}`;
  alertBox.innerHTML = msg;
  alertBox.style.display = "block";
}

function clearLoginAlert() {
  const alertBox = document.getElementById("login-alert-box");
  alertBox.style.display = "none";
}

function resetAuthFlow() {
  clearLoginAlert();
  document.getElementById("auth-step-email").style.display = "block";
  document.getElementById("auth-step-otp").style.display = "none";
  document.getElementById("auth-step-password").style.display = "none";
  document.getElementById("login-otp").value = "";
  document.getElementById("login-password").value = "";
}

async function handleSendOTP() {
  const email = document.getElementById("login-email").value.trim();
  if (!email) {
    showLoginAlert("Please enter an authorized institutional email.", "error");
    return;
  }

  // If institutional policy does not require OTP for this role, transition directly to password step
  const requiresOtp = state.otpPolicy === "ALL_ROLES" || (state.otpPolicy === "ADMIN_ONLY" && state.targetRole === "Admin");
  if (!requiresOtp) {
    document.getElementById("auth-step-email").style.display = "none";
    document.getElementById("auth-step-password").style.display = "block";
    document.getElementById("login-password").focus();
    return;
  }

  const btn = document.getElementById("btn-send-otp");
  btn.disabled = true;
  btn.textContent = "Processing...";

  try {
    const res = await fetch(`${API_BASE}/api/auth/send-otp`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, purpose: "Login Verification" })
    });
    const data = await res.json();

    if (!res.ok) {
      showLoginAlert(data.detail || "Failed to dispatch verification code.", "error");
      return;
    }

    // Notice: OTP is NEVER returned in response.
    showLoginAlert(`✓ <strong>Verification Code Sent:</strong> A 6-digit code has been dispatched to ${email}.`, "info");
    document.getElementById("auth-step-email").style.display = "none";
    document.getElementById("auth-step-otp").style.display = "block";
    document.getElementById("login-otp").focus();

  } catch (err) {
    showLoginAlert("Network error connecting to authentication server.", "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "Continue with Email →";
  }
}

async function handleVerifyOTP() {
  const email = document.getElementById("login-email").value.trim();
  const otp = document.getElementById("login-otp").value.trim();

  if (!otp || otp.length !== 6) {
    showLoginAlert("Please enter the 6-digit verification code.", "error");
    return;
  }

  const btn = document.getElementById("btn-verify-otp");
  btn.disabled = true;
  btn.textContent = "Verifying...";

  try {
    const res = await fetch(`${API_BASE}/api/auth/verify-otp`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, otp })
    });
    const data = await res.json();

    if (!res.ok) {
      showLoginAlert(data.detail || "Invalid or expired verification code.", "error");
      return;
    }

    showLoginAlert("✓ Verification code confirmed. Please enter your account password.", "success");
    document.getElementById("auth-step-otp").style.display = "none";
    document.getElementById("auth-step-password").style.display = "block";
    document.getElementById("login-password").focus();

  } catch (err) {
    showLoginAlert("Error verifying code.", "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "Verify OTP";
  }
}

async function handleLoginSubmit() {
  const email = document.getElementById("login-email").value.trim();
  const password = document.getElementById("login-password").value;

  if (!password) {
    showLoginAlert("Please enter account password.", "error");
    return;
  }

  const btn = document.getElementById("btn-login-submit");
  btn.disabled = true;
  btn.textContent = "Signing In...";

  const targetRoleEndpoint = state.targetRole ? state.targetRole.toLowerCase() : "admin";

  try {
    const res = await fetch(`${API_BASE}/api/auth/login/${targetRoleEndpoint}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password, target_role: state.targetRole })
    });
    const data = await res.json();

    if (!res.ok) {
      showLoginAlert(data.detail || "Incorrect account password or unauthorized role.", "error");
      return;
    }

    state.token = data.token;
    state.currentUser = data.user;
    sessionStorage.setItem("examexpert_token", data.token);

    document.getElementById("header-user-badge").textContent = `${data.user.username} (${data.user.role})`;
    showToast("Login Successful", `Welcome to ExamExpert AI, ${data.user.full_name || data.user.username}.`, "success");
    showAppView();

  } catch (err) {
    showLoginAlert("Authentication server communication failed.", "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "Sign In to Examination Portal →";
  }
}

// ─── First-Time Account Activation & Password Reset Handlers ──────────────────
async function handleSendActivationOTP() {
  const email = document.getElementById("act-email").value.trim();
  if (!email) {
    showLoginAlert("Please enter registered email address.", "error");
    return;
  }
  const btn = document.getElementById("btn-act-send-otp");
  btn.disabled = true;
  btn.textContent = "Sending...";
  try {
    const res = await fetch(`${API_BASE}/api/auth/send-otp`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, purpose: "Account Activation" })
    });
    const data = await res.json();
    if (res.ok) {
      showToast("Verification Code Dispatched", `A 6-digit activation code was sent to ${email}.`, "info");
      showLoginAlert(`✓ Activation code sent to ${email}.`, "info");
    } else {
      showLoginAlert(data.detail || "Failed to dispatch activation code.", "error");
    }
  } catch (e) {
    showLoginAlert("Error dispatching activation code.", "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "Send Activation OTP";
  }
}

async function handleActivateAccount() {
  const email = document.getElementById("act-email").value.trim();
  const otp = document.getElementById("act-otp").value.trim();
  const new_password = document.getElementById("act-password").value;

  if (!email || !otp || !new_password) {
    showLoginAlert("Please complete all activation fields.", "error");
    return;
  }
  if (new_password.length < 8) {
    showLoginAlert("Password must be at least 8 characters.", "error");
    return;
  }

  try {
    const res = await fetch(`${API_BASE}/api/auth/activate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, otp, new_password })
    });
    const data = await res.json();
    if (res.ok) {
      showToast("Account Activated", "Your account is now active. Please sign in.", "success");
      switchAuthMode("login");
      showLoginAlert("✓ Account successfully activated! Please log in.", "success");
    } else {
      showLoginAlert(data.detail || "Activation failed.", "error");
    }
  } catch (e) {
    showLoginAlert("Error during activation.", "error");
  }
}

async function handleSendForgotOTP() {
  const email = document.getElementById("forgot-email").value.trim();
  if (!email) {
    showLoginAlert("Please enter your registered email.", "error");
    return;
  }
  const btn = document.getElementById("btn-forgot-send-otp");
  btn.disabled = true;
  btn.textContent = "Sending...";
  try {
    const res = await fetch(`${API_BASE}/api/auth/forgot-password`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email })
    });
    const data = await res.json();
    if (res.ok) {
      showToast("Reset Code Sent", `A verification code was dispatched to ${email}.`, "info");
      showLoginAlert(`✓ Verification code sent to ${email}.`, "info");
    } else {
      showLoginAlert(data.detail || "Failed to dispatch reset code.", "error");
    }
  } catch (e) {
    showLoginAlert("Error requesting reset code.", "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "Send Reset OTP";
  }
}

async function handleResetPassword() {
  const email = document.getElementById("forgot-email").value.trim();
  const otp = document.getElementById("forgot-otp").value.trim();
  const new_password = document.getElementById("forgot-new-password").value;

  if (!email || !otp || !new_password) {
    showLoginAlert("Please complete all reset fields.", "error");
    return;
  }
  if (new_password.length < 8) {
    showLoginAlert("Password must be at least 8 characters.", "error");
    return;
  }

  try {
    const res = await fetch(`${API_BASE}/api/auth/reset-password`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, otp, new_password })
    });
    const data = await res.json();
    if (res.ok) {
      showToast("Password Reset Successful", "You may now log in with your new password.", "success");
      switchAuthMode("login");
      showLoginAlert("✓ Password reset successfully. Please log in.", "success");
    } else {
      showLoginAlert(data.detail || "Password reset failed.", "error");
    }
  } catch (e) {
    showLoginAlert("Error resetting password.", "error");
  }
}

async function handleLogout() {
  try {
    await fetch(`${API_BASE}/api/auth/logout`, {
      method: "POST",
      headers: { "Authorization": `Bearer ${state.token}` }
    });
  } catch (e) {}
  sessionStorage.removeItem("examexpert_token");
  localStorage.removeItem("examexpert_token");
  state.token = null;
  state.currentUser = null;
  showToast("Logged Out", "Your session has been securely closed.", "info");
  showLoginView();
}


// ─── Module Tab Switching ─────────────────────────────────────────────────────
function switchTab(tabId) {
  document.querySelectorAll(".nav-pill").forEach(p => p.classList.remove("active"));
  document.querySelectorAll(".tab-pane").forEach(t => t.style.display = "none");

  // Highlight pill
  const activeBtn = Array.from(document.querySelectorAll(".nav-pill")).find(p => p.getAttribute("onclick")?.includes(tabId));
  if (activeBtn) activeBtn.classList.add("active");

  const pane = document.getElementById(`tab-${tabId}`);
  if (pane) pane.style.display = "block";

  if (tabId === "dashboard" && state.currentUser && state.currentUser.role === "Admin") loadDashboardStats();
  if (tabId === "faculty") loadFacultyTab();
  if (tabId === "subjects") loadSubjectMasterList();
  if (tabId === "mappings") loadMappingsList();
  if (tabId === "pending-approvals") loadPendingApprovals();
  if (tabId === "users") loadUsersList();
  if (tabId === "history") loadAllocationHistory();
  if (tabId === "notifications") loadNotifications();
  if (tabId === "acceptance") loadAcceptanceTestSuites();
  if (tabId === "audit") loadAuditLogs();
  if (tabId === "datasets") loadImportHistory();
  if (tabId === "settings") { loadPolicySettings(); loadEligibilitySubjects(); }
}


// ─── Core Allocation Dashboard: Progressive Cascade ──────────────────────────
async function initializeDashboard() {
  await loadAcademicYears();
}

async function loadAcademicYears() {
  try {
    const res = await fetch(`${API_BASE}/api/syllabus/academic-years`);
    const data = await res.json();

    const sel = document.getElementById("sel-academic-year");
    sel.innerHTML = `<option value="">-- Select Examination Academic Year --</option>`;

    let defaultYear = data.default_active_year || "2025-26";
    state.activeCycle = defaultYear;
    document.getElementById("header-cycle-text").textContent = `${defaultYear} Active`;

    data.academic_years.forEach(ay => {
      const opt = document.createElement("option");
      opt.value = ay.year;
      opt.textContent = ay.label;
      if (ay.is_active) opt.selected = true;
      sel.appendChild(opt);
    });

    if (sel.value) {
      onAcademicYearChange();
    }
  } catch (err) {
    console.error("Failed to load academic years", err);
  }
}

async function onAcademicYearChange() {
  const ay = document.getElementById("sel-academic-year").value;
  state.academicYear = ay;

  // Reset dependents
  resetDropdown("sel-department", "-- Select Academic Department --");
  resetDropdown("sel-semester", "-- Select Department First --");
  resetDropdown("sel-subject", "-- Select Semester First --");
  disableControls(["sel-department", "sel-semester", "sel-subject", "sel-min-handled", "sel-total-required"]);
  hideAllocationPanels();

  if (!ay) return;

  try {
    const res = await fetch(`${API_BASE}/api/syllabus/departments?academic_year=${encodeURIComponent(ay)}`);
    const data = await res.json();

    const selDept = document.getElementById("sel-department");
    selDept.innerHTML = `<option value="">-- Select Academic Department --</option>`;
    data.departments.forEach(d => {
      const opt = document.createElement("option");
      opt.value = d;
      opt.textContent = d;
      selDept.appendChild(opt);
    });
    selDept.disabled = false;

    // Auto-select MCA if available
    if (data.departments.includes("MCA")) {
      selDept.value = "MCA";
      onDepartmentChange();
    }
  } catch (err) {
    console.error("Failed to load departments", err);
  }
}

async function onDepartmentChange() {
  const dept = document.getElementById("sel-department").value;
  state.department = dept;

  resetDropdown("sel-semester", "-- Select Semester --");
  resetDropdown("sel-subject", "-- Select Semester First --");
  disableControls(["sel-semester", "sel-subject", "sel-min-handled", "sel-total-required"]);
  hideAllocationPanels();

  if (!dept) return;

  // Visual reminder for MCA strict 4 semesters
  const semHint = document.getElementById("sem-hint");
  if (dept.toLowerCase().includes("mca")) {
    semHint.textContent = "Strictly Sem I–IV";
  } else {
    semHint.textContent = "Step 3";
  }

  try {
    const res = await fetch(`${API_BASE}/api/syllabus/semesters?academic_year=${encodeURIComponent(state.academicYear)}&department=${encodeURIComponent(dept)}`);
    const data = await res.json();

    const selSem = document.getElementById("sel-semester");
    selSem.innerHTML = `<option value="">-- Select Semester --</option>`;
    data.semesters.forEach(s => {
      const opt = document.createElement("option");
      opt.value = s.value;
      opt.textContent = s.label;
      selSem.appendChild(opt);
    });
    selSem.disabled = false;

    if (data.semesters.length > 0) {
      selSem.selectedIndex = 1;
      onSemesterChange();
    }
  } catch (err) {
    console.error("Failed to load semesters", err);
  }
}

async function onSemesterChange() {
  const sem = document.getElementById("sel-semester").value;
  state.semester = sem;

  resetDropdown("sel-subject", "-- Select Theory Course --");
  disableControls(["sel-subject", "sel-min-handled", "sel-total-required"]);
  hideAllocationPanels();

  if (!sem) return;

  try {
    const res = await fetch(`${API_BASE}/api/syllabus/subjects?academic_year=${encodeURIComponent(state.academicYear)}&department=${encodeURIComponent(state.department)}&semester=${encodeURIComponent(sem)}`);
    const data = await res.json();

    const selSubj = document.getElementById("sel-subject");
    selSubj.innerHTML = `<option value="">-- Select Theory Course --</option>`;

    if (data.subjects.length === 0) {
      selSubj.innerHTML = `<option value="">No syllabus subjects found for selected criteria</option>`;
      return;
    }

    data.subjects.forEach(s => {
      const opt = document.createElement("option");
      opt.value = s.id;
      opt.dataset.json = JSON.stringify(s);
      opt.textContent = `${s.course_code} - ${s.title} (${s.badge_label})`;
      selSubj.appendChild(opt);
    });

    selSubj.disabled = false;
    selSubj.selectedIndex = 1;
    onSubjectChange();

  } catch (err) {
    console.error("Failed to load subjects", err);
  }
}

function onSubjectChange() {
  const selSubj = document.getElementById("sel-subject");
  const subjId = selSubj.value;
  if (!subjId) {
    hideAllocationPanels();
    return;
  }

  const selectedOpt = selSubj.options[selSubj.selectedIndex];
  state.subjectId = parseInt(subjId);
  state.subjectData = JSON.parse(selectedOpt.dataset.json);

  // Render subject summary banner
  document.getElementById("disp-course-code").textContent = state.subjectData.course_code;
  document.getElementById("disp-subject-title").textContent = state.subjectData.title;
  document.getElementById("disp-subject-meta").textContent = `Scheme: ${state.subjectData.scheme} • Course Type: ${state.subjectData.course_type} • Sem: ${state.subjectData.semester}`;
  
  const badgeEl = document.getElementById("disp-verification-badge");
  badgeEl.innerHTML = `<span class="badge ${state.subjectData.is_verified ? 'badge-green' : 'badge-amber'}">${state.subjectData.badge_label}</span>`;
  document.getElementById("subject-detail-banner").style.display = "flex";

  // Enable handling count & total faculty controls
  document.getElementById("sel-min-handled").disabled = false;
  document.getElementById("sel-total-required").disabled = false;

  triggerFacultyRecommendation();
}

function onMinHandledChange() {
  state.minHandled = parseInt(document.getElementById("sel-min-handled").value);
  triggerFacultyRecommendation();
}

function onTotalRequiredChange() {
  state.totalRequired = parseInt(document.getElementById("sel-total-required").value);
  triggerFacultyRecommendation();
}


// ─── 50:50 Parity Allocation Engine & Matching ────────────────────────────────
async function triggerFacultyRecommendation() {
  if (!state.subjectId) return;

  state.minHandled = parseInt(document.getElementById("sel-min-handled").value || 3);
  state.totalRequired = parseInt(document.getElementById("sel-total-required").value || 4);

  try {
    const res = await fetch(`${API_BASE}/api/allocation/auto-select`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        subject_id: state.subjectId,
        min_handled: state.minHandled,
        total_required: state.totalRequired
      })
    });
    const data = await res.json();

    if (!res.ok) {
      showToast("Evaluation Error", data.detail || "Error evaluating faculty recommendations.", "error");
      return;
    }

    state.internalQuota = data.internal_quota;
    state.externalQuota = data.external_quota;
    state.selectedInternalIds = new Set(data.selected_internal_ids);
    state.selectedExternalIds = new Set(data.selected_external_ids);
    state.allInternalCandidates = data.all_internal_candidates;
    state.allExternalCandidates = data.all_external_candidates;
    state.requiresException = data.requires_exception;

    // Render Quota Status
    document.getElementById("quota-pill-internal").textContent = `Internal Quota: ${data.selected_internal.length} / ${data.internal_quota} (50%)`;
    document.getElementById("quota-pill-external").textContent = `External Quota: ${data.selected_external.length} / ${data.external_quota} (50%)`;
    document.getElementById("quota-pill-ratio").textContent = `Target: ${data.total_required} Setters (50:50 Parity)`;

    // Shortage warning handling
    const warningBox = document.getElementById("shortage-warning-box");
    const exceptionBox = document.getElementById("exception-approval-box");

    if (data.warnings && data.warnings.length > 0) {
      warningBox.innerHTML = `<strong>Quota Notice:</strong><br/>` + data.warnings.map(w => `• ${w}`).join("<br/>");
      warningBox.style.display = "block";
      if (data.requires_exception) {
        exceptionBox.style.display = "block";
      } else {
        exceptionBox.style.display = "none";
      }
    } else {
      warningBox.style.display = "none";
      exceptionBox.style.display = "none";
    }

    document.getElementById("parity-status-card").style.display = "block";
    document.getElementById("section-internal-faculty").style.display = "block";
    document.getElementById("section-external-faculty").style.display = "block";
    document.getElementById("section-allocation-summary").style.display = "block";

    renderInternalFacultyTable();
    renderExternalFacultyTable();
    updateAllocationSummary();

  } catch (err) {
    console.error("Failed to retrieve recommendations", err);
  }
}


// ─── Faculty Tables Rendering ─────────────────────────────────────────────────
function renderInternalFacultyTable() {
  const tbody = document.getElementById("tbody-internal-faculty");
  tbody.innerHTML = "";

  state.allInternalCandidates.forEach(f => {
    const tr = document.createElement("tr");
    const isChecked = state.selectedInternalIds.has(f.faculty_id);
    if (isChecked) tr.classList.add("row-selected");

    let eligBadge = `<span class="badge badge-green">Qualified</span>`;
    if (f.eligibility_status.includes("Cannot Verify")) {
      eligBadge = `<span class="badge badge-amber">Verification Required</span>`;
    } else if (f.eligibility_status.includes("Not Qualified")) {
      eligBadge = `<span class="badge badge-red">Not Qualified</span>`;
    }

    let handledBadge = `<span class="badge badge-blue">${f.course_handled_display}</span>`;
    if (!f.meets_min_handled) {
      handledBadge = `<span class="badge badge-amber">${f.course_handled_display} (&lt; ${state.minHandled} min)</span>`;
    }

    tr.innerHTML = `
      <td style="text-align:center;">
        <input type="checkbox" ${isChecked ? "checked" : ""} onchange="toggleFacultySelection('internal', ${f.faculty_id}, this.checked)" />
      </td>
      <td><strong>${f.faculty_name}</strong><div style="font-size:11px; color:var(--text-muted);">${f.email || ''}</div></td>
      <td>${f.designation || 'Faculty'}</td>
      <td>${f.department || 'SJBIT'}</td>
      <td>${f.qualification || 'M.Tech'}</td>
      <td>${f.experience_years ? f.experience_years.toFixed(1) + ' Yrs' : 'N/A'}</td>
      <td>${handledBadge}</td>
      <td>${eligBadge}</td>
      <td><span class="badge badge-blue">Rank #${f.rank || 1}</span><div style="font-size:10.5px; color:var(--text-muted);">${f.criteria_reasons?.tier || f.mapping_type || 'Eligible'}</div></td>
    `;
    tbody.appendChild(tr);
  });

  document.getElementById("internal-quota-counter").textContent = `Selected: ${state.selectedInternalIds.size} / ${state.internalQuota}`;
}

function renderExternalFacultyTable() {
  const tbody = document.getElementById("tbody-external-faculty");
  tbody.innerHTML = "";

  state.allExternalCandidates.forEach(f => {
    const tr = document.createElement("tr");
    const isChecked = state.selectedExternalIds.has(f.faculty_id);
    if (isChecked) tr.classList.add("row-selected");

    let eligBadge = `<span class="badge badge-green">Qualified</span>`;
    if (f.eligibility_status.includes("Cannot Verify")) {
      eligBadge = `<span class="badge badge-amber">Cannot Verify (undisclosed)</span>`;
    } else if (f.eligibility_status.includes("Not Qualified")) {
      eligBadge = `<span class="badge badge-red">Not Qualified</span>`;
    }

    // Provenance distinction: External dataset has assumed QP setting count, not verified course teaching count
    let handledCell = `<span class="badge badge-amber" title="External university records do not publicly disclose subject teaching counts">Course History Verification Required</span>`;

    tr.innerHTML = `
      <td style="text-align:center;">
        <input type="checkbox" ${isChecked ? "checked" : ""} onchange="toggleFacultySelection('external', ${f.faculty_id}, this.checked)" />
      </td>
      <td><strong>${f.faculty_name}</strong><div style="font-size:11px; color:var(--text-muted);">${f.email || 'Email in roster'}</div></td>
      <td>${f.institution || 'External University'}</td>
      <td>${f.designation || 'Faculty'}</td>
      <td>${f.qualification || 'Ph.D / M.Tech'}</td>
      <td>${f.experience_years ? f.experience_years.toFixed(1) + ' Yrs' : 'Undisclosed'}</td>
      <td>${handledCell}</td>
      <td>${eligBadge}</td>
      <td><span class="badge badge-blue">Rank #${f.rank || 1}</span><div style="font-size:10.5px; color:var(--text-muted);">${f.criteria_reasons?.tier || f.mapping_type || 'Eligible'}</div></td>
    `;
    tbody.appendChild(tr);
  });

  document.getElementById("external-quota-counter").textContent = `Selected: ${state.selectedExternalIds.size} / ${state.externalQuota}`;
}

function toggleFacultySelection(type, facultyId, isSelected) {
  if (type === "internal") {
    if (isSelected) state.selectedInternalIds.add(facultyId);
    else state.selectedInternalIds.delete(facultyId);
  } else {
    if (isSelected) state.selectedExternalIds.add(facultyId);
    else state.selectedExternalIds.delete(facultyId);
  }

  renderInternalFacultyTable();
  renderExternalFacultyTable();
  updateAllocationSummary();
}

function filterFacultyTable(type) {
  const query = document.getElementById(`search-${type}-table`).value.toLowerCase();
  const rows = document.querySelectorAll(`#tbody-${type}-faculty tr`);
  rows.forEach(r => {
    const text = r.innerText.toLowerCase();
    r.style.display = text.includes(query) ? "" : "none";
  });
}


// ─── Allocation Summary & Conflict Management ─────────────────────────────────
async function updateAllocationSummary() {
  document.getElementById("sum-disp-ay-sem").textContent = `${state.academicYear} • Sem ${state.semester}`;
  document.getElementById("sum-disp-course").textContent = `${state.subjectData.course_code} - ${state.subjectData.title}`;
  document.getElementById("sum-disp-handled").textContent = `${state.minHandled} Times Minimum`;

  const intCount = state.selectedInternalIds.size;
  const extCount = state.selectedExternalIds.size;
  const total = intCount + extCount;
  const ratio = total > 0 ? `${Math.round(intCount / total * 100)}% Int / ${Math.round(extCount / total * 100)}% Ext` : "0:0";
  document.getElementById("sum-disp-ratio").textContent = `${ratio} (${total} of ${state.totalRequired} Setters)`;

  // Render roster of appointed setters
  const rosterDiv = document.getElementById("sum-roster-list");
  rosterDiv.innerHTML = "";

  let setLetterCode = 65; // 'A'

  // Internal Setters
  state.selectedInternalIds.forEach(id => {
    const f = state.allInternalCandidates.find(c => c.faculty_id === id);
    if (f) {
      const item = document.createElement("div");
      item.className = "setter-item";
      item.innerHTML = `
        <div>
          <strong>Set ${String.fromCharCode(setLetterCode++)}: ${f.faculty_name}</strong>
          <span style="font-size:11px; color:var(--text-muted); margin-left:8px;">(${f.designation}, SJBIT)</span>
        </div>
        <span class="badge badge-blue">Internal Setter</span>
      `;
      rosterDiv.appendChild(item);
    }
  });

  // External Setters
  state.selectedExternalIds.forEach(id => {
    const f = state.allExternalCandidates.find(c => c.faculty_id === id);
    if (f) {
      const item = document.createElement("div");
      item.className = "setter-item";
      item.innerHTML = `
        <div>
          <strong>Set ${String.fromCharCode(setLetterCode++)}: ${f.faculty_name}</strong>
          <span style="font-size:11px; color:var(--text-muted); margin-left:8px;">(${f.designation}, ${f.institution})</span>
        </div>
        <span class="badge badge-green">External Setter</span>
      `;
      rosterDiv.appendChild(item);
    }
  });

  // Run real-time Conflict Check
  const conflictAlert = document.getElementById("summary-conflict-alert");
  const submitBtn = document.getElementById("btn-final-submit");
  const complianceBadge = document.getElementById("summary-compliance-badge");

  if (total === 0) {
    conflictAlert.style.display = "none";
    submitBtn.disabled = true;
    complianceBadge.innerHTML = `<span class="badge badge-amber">No Faculty Selected</span>`;
    return;
  }

  try {
    const res = await fetch(`${API_BASE}/api/allocation/check-conflicts`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        subject_id: state.subjectId,
        internal_faculty_ids: Array.from(state.selectedInternalIds),
        external_faculty_ids: Array.from(state.selectedExternalIds),
        total_required: state.totalRequired
      })
    });
    const conflictData = await res.json();

    if (conflictData.has_conflicts) {
      const critical = conflictData.conflicts.filter(c => c.severity === "Critical");
      conflictAlert.innerHTML = `<strong>Conflict Detected:</strong><br/>` + conflictData.conflicts.map(c => `• [${c.severity}] ${c.description}`).join("<br/>");
      conflictAlert.style.display = "block";

      if (critical.length > 0) {
        submitBtn.disabled = true;
        complianceBadge.innerHTML = `<span class="badge badge-red">Critical Conflict</span>`;
        return;
      }
    } else {
      conflictAlert.style.display = "none";
    }

    const quotaSatisfied = (intCount === state.internalQuota && extCount === state.externalQuota);
    if (quotaSatisfied) {
      complianceBadge.innerHTML = `<span class="badge badge-green">✓ 50:50 Quota Satisfied</span>`;
      document.getElementById("section-allocation-summary").classList.add("parity-satisfied");
    } else {
      complianceBadge.innerHTML = `<span class="badge badge-amber">Quota Adjustment Required</span>`;
      document.getElementById("section-allocation-summary").classList.remove("parity-satisfied");
    }

    submitBtn.disabled = false;

  } catch (err) {
    console.error("Conflict checking error", err);
  }
}

function applyExceptionReason() {
  const reason = document.getElementById("input-exception-reason").value.trim();
  if (!reason) {
    showToast("Validation Error", "Please provide an administrative justification note.", "warning");
    return;
  }
  state.exceptionReason = reason;
  showToast("Justification Recorded", "Exception reason recorded. You may now proceed with final submission.", "info");
}


// ─── Final Submission & Order Confirmation ────────────────────────────────────
async function executeFinalAllocationSubmission() {
  if (state.selectedInternalIds.size === 0 && state.selectedExternalIds.size === 0) {
    showToast("Selection Required", "Please select at least one faculty member.", "warning");
    return;
  }

  // Check if unverified external faculty are selected without recorded exception
  const selectedExtList = state.allExternalCandidates.filter(f => state.selectedExternalIds.has(f.faculty_id));
  const hasUnverifiedExt = selectedExtList.some(f => f.eligibility_status.includes("Cannot Verify"));

  if (hasUnverifiedExt && !state.exceptionReason) {
    const promptReason = prompt("Administrative Approval Required:\nOne or more selected external faculty have unverified teaching experience.\nPlease enter an authorized exception note:", "Approved by Controller of Examinations after physical review of service record");
    if (!promptReason) {
      showToast("Submission Aborted", "Exception justification is mandatory for unverified external faculty.", "warning");
      return;
    }
    state.exceptionReason = promptReason;
  }

  const btn = document.getElementById("btn-final-submit");
  btn.disabled = true;
  btn.textContent = "LOCKING ALLOCATION & GENERATING ORDER...";

  try {
    const payload = {
      subject_id: state.subjectId,
      academic_year: state.academicYear,
      department: state.department,
      semester: state.semester,
      min_handled: state.minHandled,
      total_required: state.totalRequired,
      internal_faculty_ids: Array.from(state.selectedInternalIds),
      external_faculty_ids: Array.from(state.selectedExternalIds),
      exception_reason: state.exceptionReason || null,
      exception_approved_by: "Controller of Examinations",
      submission_deadline: "Within 10 days of order receipt"
    };

    const res = await fetch(`${API_BASE}/api/allocation/confirm`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${state.token}`
      },
      body: JSON.stringify(payload)
    });
    const result = await res.json();

    if (!res.ok) {
      showToast("Submission Failed", result.detail || "Failed to submit allocation.", "error");
      btn.disabled = false;
      btn.textContent = "SUBMIT ALLOCATION FOR HOD APPROVAL →";
      return;
    }

    state.lastAllocationId = result.allocation_id;
    state.lastRefNumber = result.reference_number;

    showToast("Submitted to HOD", result.message || "Allocation submitted for HOD approval and workload reserved.", "success");

    // Show Success Modal
    document.getElementById("modal-ref-number").textContent = result.reference_number;
    document.getElementById("success-modal").classList.add("active");

    btn.disabled = false;
    btn.textContent = "SUBMIT ALLOCATION FOR HOD APPROVAL →";

  } catch (err) {
    showToast("Network Error", "Error executing allocation submission.", "error");
    btn.disabled = false;
    btn.textContent = "SUBMIT ALLOCATION FOR HOD APPROVAL →";
  }
}

function triggerModalPDFDownload() {
  if (state.lastAllocationId) {
    window.open(`${API_BASE}/api/reports/download-pdf/${state.lastAllocationId}`, "_blank");
  }
}

function closeSuccessModal() {
  document.getElementById("success-modal").classList.remove("active");
  // Reload dashboard
  onSubjectChange();
}


// ─── Faculty OTP Dispatch & Popup Notification ─────────────────────────────────
async function handleSendFacultyOTP() {
  const allSelectedIds = [...state.selectedInternalIds, ...state.selectedExternalIds];
  if (allSelectedIds.length === 0) {
    showToast("Selection Required", "Please select at least one faculty member before dispatching OTP.", "warning");
    return;
  }
  if (!state.subjectId) {
    showToast("Subject Required", "Please select a subject first.", "warning");
    return;
  }

  const btn = document.getElementById("btn-send-faculty-otp");
  const origText = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Dispatching OTP...";

  try {
    const res = await fetch(`${API_BASE}/api/allocation/send-faculty-otp`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${state.token}`
      },
      body: JSON.stringify({
        subject_id: state.subjectId,
        faculty_ids: allSelectedIds
      })
    });
    const data = await res.json();

    if (!res.ok) {
      showToast("Dispatch Failed", data.detail || "Failed to dispatch faculty OTP.", "error");
      btn.disabled = false;
      btn.textContent = origText;
      return;
    }

    // Populate modal content
    const modalContent = document.getElementById("faculty-otp-modal-content");
    modalContent.innerHTML = "";

    data.dispatches.forEach(d => {
      const item = document.createElement("div");
      item.style.cssText = "display:flex; justify-content:space-between; align-items:center; padding:8px; border-bottom:1px solid #e2e8f0; font-size:12.5px;";
      item.innerHTML = `
        <div>
          <strong>${d.faculty_name}</strong> <span style="font-size:11px; color:var(--text-muted);">(${d.faculty_type === 'internal' ? 'SJBIT Internal' : 'External'})</span><br/>
          <span style="font-size:11.5px; color:#4b5563;">📧 ${d.email_masked} | 📱 ${d.mobile_masked}</span>
        </div>
        <div style="text-align:right;">
          <span class="badge badge-green" style="font-size:11.5px; font-weight:600;">✓ Verification Dispatched</span><br/>
          <span style="font-size:10.5px; color:var(--text-muted);">Directly to Faculty Device</span>
        </div>
      `;
      modalContent.appendChild(item);
    });

    // Show the modal
    document.getElementById("faculty-otp-modal").classList.add("active");

  } catch (err) {
    showToast("Network Error", "Error communicating with server while sending OTP.", "error");
    console.error(err);
  } finally {
    btn.disabled = false;
    btn.textContent = origText;
  }
}

function closeFacultyOtpModal() {
  document.getElementById("faculty-otp-modal").classList.remove("active");
}


// ─── Module 2: Excel Dataset Upload & History ─────────────────────────────────
let currentImportPreview = null;

async function handleExcelPreview() {
  const fileInput = document.getElementById("upload-excel-file");
  const datasetType = document.getElementById("upload-dataset-type").value;
  const statusBox = document.getElementById("upload-status-box");
  const btn = document.getElementById("btn-preview-import");

  if (!fileInput.files || fileInput.files.length === 0) {
    showToast("File Required", "Please select an Excel (.xlsx) file to upload.", "warning");
    return;
  }

  const file = fileInput.files[0];
  if (file.size > 10 * 1024 * 1024) {
    showToast("File Too Large", "Maximum permitted workbook size is 10MB.", "error");
    return;
  }

  const formData = new FormData();
  formData.append("file", file);
  formData.append("dataset_type", datasetType);

  btn.disabled = true;
  btn.textContent = "Analyzing Workbook...";
  statusBox.style.display = "block";
  statusBox.innerHTML = `<span style="color:var(--royal-blue); font-weight:600;">Validating workbook headers, checking for duplicates, and inspecting conflicts...</span>`;

  try {
    const res = await fetch(`${API_BASE}/api/faculty/import-preview`, {
      method: "POST",
      headers: { "Authorization": `Bearer ${state.token}` },
      body: formData
    });
    const data = await res.json();

    if (!res.ok) {
      statusBox.innerHTML = `<span style="color:var(--error-red); font-weight:600;">Validation Failed: ${escapeHtml(data.detail || 'Failed to process file')}</span>`;
      document.getElementById("import-preview-container").style.display = "none";
      return;
    }

    currentImportPreview = data;
    statusBox.style.display = "none";

    // Populate preview stats
    document.getElementById("preview-file-subtitle").textContent = `File: ${data.filename} (${data.dataset_type.toUpperCase()}) • Evaluated ${data.total_rows} row(s)`;
    document.getElementById("pv-stat-total").textContent = data.total_rows;
    document.getElementById("pv-stat-add").textContent = data.to_add_count;
    document.getElementById("pv-stat-dup").textContent = data.duplicate_count;
    document.getElementById("pv-stat-conflict").textContent = data.conflict_count;
    document.getElementById("pv-stat-rej").textContent = data.rejected_count;

    // Render Preview Details Area
    const detailsArea = document.getElementById("preview-details-area");
    let html = "";

    // If conflicts exist, show table
    if (data.conflicts && data.conflicts.length > 0) {
      html += `
        <div style="margin-bottom:16px;">
          <h4 style="font-size:13.5px; font-weight:700; color:#B45309; margin-bottom:8px; display:flex; align-items:center; gap:6px;">
            ⚠️ Conflicting Records (${data.conflicts.length}):
          </h4>
          <div style="max-height:220px; overflow-y:auto; border:1px solid #FDE68A; border-radius:6px; background:#FFFBEB; padding:8px 12px; font-size:12px;">
            <table style="width:100%; border-collapse:collapse;">
              <thead>
                <tr style="text-align:left; border-bottom:1px solid #FDE68A; color:#92400E;">
                  <th style="padding:4px;">Row</th>
                  <th style="padding:4px;">Identifier</th>
                  <th style="padding:4px;">Conflicting Field</th>
                  <th style="padding:4px;">Existing in Database</th>
                  <th style="padding:4px;">Incoming in Workbook</th>
                </tr>
              </thead>
              <tbody>
                ${data.conflicts.map(c => c.diffs.map(d => `
                  <tr style="border-bottom:1px solid #FEF3C7;">
                    <td style="padding:4px; font-weight:600;">#${c.row}</td>
                    <td style="padding:4px;"><strong>${escapeHtml(c.identifier)}</strong></td>
                    <td style="padding:4px; color:#B45309;">${escapeHtml(d.field)}</td>
                    <td style="padding:4px; color:#1E293B;">${escapeHtml(String(d.existing || '—'))}</td>
                    <td style="padding:4px; color:#0369A1;">${escapeHtml(String(d.incoming || '—'))}</td>
                  </tr>
                `).join("")).join("")}
              </tbody>
            </table>
          </div>
        </div>
      `;
    }

    // If rejected rows exist, show table
    if (data.rejected && data.rejected.length > 0) {
      html += `
        <div style="margin-bottom:16px;">
          <h4 style="font-size:13.5px; font-weight:700; color:#DC2626; margin-bottom:8px; display:flex; align-items:center; gap:6px;">
            ✕ Rejected Records (${data.rejected.length}):
          </h4>
          <div style="max-height:180px; overflow-y:auto; border:1px solid #FECACA; border-radius:6px; background:#FEF2F2; padding:8px 12px; font-size:12px;">
            <table style="width:100%; border-collapse:collapse;">
              <thead>
                <tr style="text-align:left; border-bottom:1px solid #FECACA; color:#991B1B;">
                  <th style="padding:4px; width:60px;">Row</th>
                  <th style="padding:4px;">Identifier</th>
                  <th style="padding:4px;">Statutory Rejection Reason</th>
                </tr>
              </thead>
              <tbody>
                ${data.rejected.map(r => `
                  <tr style="border-bottom:1px solid #FEE2E2;">
                    <td style="padding:4px; font-weight:600;">#${r.row}</td>
                    <td style="padding:4px;">${escapeHtml(r.identifier)}</td>
                    <td style="padding:4px; color:#DC2626;">${escapeHtml(r.reason)}</td>
                  </tr>
                `).join("")}
              </tbody>
            </table>
          </div>
        </div>
      `;
    }

    // Sample of rows to add
    if (data.to_add_sample && data.to_add_sample.length > 0) {
      html += `
        <div>
          <h4 style="font-size:13.5px; font-weight:700; color:#059669; margin-bottom:8px;">
            ✓ Sample Rows to Add (${data.to_add_count} total):
          </h4>
          <div style="font-size:12px; color:var(--text-dark); background:#F0FDF4; border:1px solid #BBF7D0; border-radius:6px; padding:10px 14px; max-height:160px; overflow-y:auto;">
            ${data.to_add_sample.map(a => `
              <div style="padding:3px 0; border-bottom:1px solid #DCFCE7;">
                <strong>${escapeHtml(a.name || a.title)}</strong> (${escapeHtml(a.department || "")})
                ${a.qualification ? `— <span class="text-muted">${escapeHtml(a.qualification)}</span>` : ""}
                ${a.experience_years !== null && a.experience_years !== undefined ? `— <span class="badge badge-verified" style="font-size:10px;">${a.experience_years} yrs</span>` : ""}
              </div>
            `).join("")}
          </div>
        </div>
      `;
    }

    if (!html) {
      html = `<div style="text-align:center; padding:14px; color:var(--text-muted); font-size:13px;">All ${data.total_rows} row(s) evaluated as exact duplicates of existing records. No new data will be added.</div>`;
    }

    detailsArea.innerHTML = html;
    document.getElementById("import-preview-container").style.display = "block";
    showToast("Dry-Run Complete", `Analyzed ${data.total_rows} row(s). Review breakdown and confirm.`, "info");

  } catch (err) {
    statusBox.innerHTML = `<span style="color:var(--error-red);">Upload inspection request failed.</span>`;
  } finally {
    btn.disabled = false;
    btn.textContent = "🔍 Preview & Validate";
  }
}

async function handleConfirmImport() {
  if (!currentImportPreview || !currentImportPreview.preview_id) {
    showToast("No Preview", "Please preview an Excel file first.", "warning");
    return;
  }

  const btn = document.getElementById("btn-confirm-import");
  const resolution = document.getElementById("preview-conflict-resolution")?.value || "preserve_existing";

  btn.disabled = true;
  btn.textContent = "Saving to Database...";

  try {
    const res = await fetch(`${API_BASE}/api/faculty/import-confirm`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${state.token}`
      },
      body: JSON.stringify({
        preview_id: currentImportPreview.preview_id,
        conflict_resolution: resolution
      })
    });
    const data = await res.json();

    if (!res.ok) {
      showToast("Import Failed", data.detail || "Could not confirm import.", "error");
      return;
    }

    showToast(
      "Import Confirmed",
      `Saved ${data.added_count} new record(s), ${data.duplicate_count} duplicates skipped, ${data.conflict_count} conflicts (${data.conflict_resolution}).`,
      "success"
    );

    document.getElementById("import-preview-container").style.display = "none";
    document.getElementById("upload-excel-file").value = "";
    currentImportPreview = null;

    await loadImportHistory();
    if (state.currentUser && state.currentUser.role === "Admin") {
      await loadDashboardStats();
    }
  } catch (err) {
    showToast("Network Error", "Could not complete import confirmation.", "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "✓ Confirm & Save Import";
  }
}

async function handleDownloadRejectedReport() {
  if (!currentImportPreview || !currentImportPreview.preview_id) {
    showToast("No Preview", "No active preview session to download report for.", "warning");
    return;
  }

  try {
    const res = await fetch(`${API_BASE}/api/faculty/import-rejected-report/${currentImportPreview.preview_id}`, {
      headers: { "Authorization": `Bearer ${state.token}` }
    });
    if (!res.ok) {
      const err = await res.json();
      showToast("Download Failed", err.detail || "Could not generate report.", "error");
      return;
    }
    const blob = await res.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `rejected_report_${currentImportPreview.dataset_type}_${currentImportPreview.preview_id.substring(0, 8)}.xlsx`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
    showToast("Report Downloaded", "Protected rejection and conflict report downloaded.", "success");
  } catch (e) {
    showToast("Network Error", "Failed to download report file.", "error");
  }
}

function handleCancelPreview() {
  document.getElementById("import-preview-container").style.display = "none";
  document.getElementById("upload-excel-file").value = "";
  currentImportPreview = null;
}

async function handleExcelUpload() {
  await handleExcelPreview();
}

async function loadImportHistory() {
  try {
    const res = await fetch(`${API_BASE}/api/faculty/import-history`, {
      headers: { "Authorization": `Bearer ${state.token}` }
    });
    if (!res.ok) return;
    const data = await res.json();
    const tbody = document.getElementById("tbody-import-history");
    if (!tbody) return;
    tbody.innerHTML = "";

    if (!data.history || data.history.length === 0) {
      tbody.innerHTML = `<tr><td colspan="9"><div class="empty-state"><div class="empty-state-icon">📁</div><div class="empty-state-title">No Import History</div><div class="empty-state-desc">Uploaded dataset workbooks and file verification hashes will appear here.</div></div></td></tr>`;
      return;
    }

    data.history.forEach(h => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${h.imported_at ? h.imported_at.replace('T', ' ').substring(0, 19) : '—'}</td>
        <td><strong>${escapeHtml(h.file_name)}</strong></td>
        <td><span class="badge badge-blue">${escapeHtml(h.file_type.toUpperCase())}</span></td>
        <td><span style="font-weight:600; color:var(--text-dark);">${escapeHtml(h.imported_by || 'Admin')}</span></td>
        <td>${h.total_rows}</td>
        <td><strong style="color:var(--success-green);">${h.valid_rows}</strong></td>
        <td>${h.duplicate_rows}</td>
        <td><span style="color:${h.conflicts_count > 0 ? '#D97706' : 'var(--text-muted)'}; font-weight:600;">${h.conflicts_count || 0}</span></td>
        <td><span style="color:${h.skipped_rows > 0 ? 'var(--error-red)' : 'var(--text-muted)'};">${h.skipped_rows}</span></td>
      `;
      tbody.appendChild(tr);
    });
  } catch (e) {
    console.error("Failed to load import history:", e);
  }
}


// ─── Module 12: HOD Approval Workflow & Pending Approvals ───────────────────
async function loadPendingApprovals() {
  const container = document.getElementById("pending-approvals-container");
  const emptyState = document.getElementById("pending-approvals-empty");
  if (!container) return;

  container.innerHTML = `<div style="text-align:center; padding:30px; color:var(--text-muted);">Loading pending requests...</div>`;
  if (emptyState) emptyState.style.display = "none";

  try {
    const res = await fetch(`${API_BASE}/api/allocation/pending-approvals`, {
      headers: { "Authorization": `Bearer ${state.token}` }
    });
    if (!res.ok) {
      const err = await res.json();
      showToast("Access Notice", err.detail || "Unable to fetch pending approvals.", "warning");
      container.innerHTML = "";
      if (emptyState) emptyState.style.display = "block";
      return;
    }

    const allocs = await res.json();
    container.innerHTML = "";

    if (!allocs || allocs.length === 0) {
      if (emptyState) emptyState.style.display = "block";
      return;
    }

    const isHod = state.currentUser && state.currentUser.role === "HOD";

    allocs.forEach(a => {
      const card = document.createElement("div");
      card.className = "selection-grid-card";
      card.style.borderLeft = "4px solid var(--royal-blue)";
      card.style.marginBottom = "14px";
      card.style.padding = "18px 20px";

      let settersHtml = "";
      (a.setters || []).forEach((s, idx) => {
        const wl = s.workload || {};
        settersHtml += `
          <tr>
            <td>${idx + 1}</td>
            <td><strong>${escapeHtml(s.name || '—')}</strong></td>
            <td><span class="badge ${s.faculty_type === 'internal' ? 'badge-blue' : 'badge-amber'}">${escapeHtml((s.faculty_type || '').toUpperCase())}</span></td>
            <td>${escapeHtml(s.designation || '—')}</td>
            <td>${escapeHtml(s.department || s.institution || '—')}</td>
            <td>${escapeHtml(s.qualification || '—')}</td>
            <td>${s.experience_years ? s.experience_years + ' yrs' : '—'}</td>
            <td>
              <span style="font-size:12px;">Committed: <strong>${wl.committed || 0}</strong> | Reserved: <strong>${wl.reserved || 0}</strong> (Total: <strong>${wl.total_active || 0}</strong>)</span>
            </td>
          </tr>
        `;
      });

      card.innerHTML = `
        <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:12px; flex-wrap:wrap; gap:8px;">
          <div>
            <div style="font-size:16px; font-weight:700; color:var(--primary-navy);">
              ${escapeHtml(a.reference_number)}
            </div>
            <div style="font-size:13px; color:var(--text-muted); margin-top:2px;">
              <strong>Subject:</strong> ${escapeHtml(a.subject ? a.subject.course_code + ' - ' + a.subject.title : '—')} •
              <strong>Dept:</strong> ${escapeHtml(a.department || '—')} •
              <strong>Sem:</strong> ${escapeHtml(a.semester || '—')} •
              <strong>AY:</strong> ${escapeHtml(a.academic_year || '—')}
            </div>
          </div>
          <div style="display:flex; gap:8px; align-items:center;">
            <span class="badge" style="background:#FEF3C7; color:#92400E; font-weight:600; padding:4px 10px; border-radius:12px;">
              ${escapeHtml(a.status)}
            </span>
            <span class="badge badge-blue">
              Mode: ${escapeHtml(a.allocation_mode || 'Balanced')}
            </span>
          </div>
        </div>

        <div style="margin-bottom:14px; font-size:13px;">
          <div class="selection-grid-title" style="font-size:13px; margin-bottom:8px;">Nominated Question-Paper Setters</div>
          <div class="data-table-container">
            <table class="data-table">
              <thead>
                <tr>
                  <th style="width:40px;">#</th>
                  <th>Faculty Name</th>
                  <th>Pool</th>
                  <th>Designation</th>
                  <th>Dept / Institution</th>
                  <th>Qualification</th>
                  <th>Exp</th>
                  <th>Active Workload</th>
                </tr>
              </thead>
              <tbody>
                ${settersHtml}
              </tbody>
            </table>
          </div>
        </div>

        <div style="display:flex; justify-content:space-between; align-items:center; border-top:1px solid var(--border-light); padding-top:12px; margin-top:12px; flex-wrap:wrap; gap:10px;">
          <div style="font-size:12px; color:var(--text-muted);">
            Submitted by <strong>${escapeHtml(a.submitted_by || 'Admin')}</strong> on ${a.created_at ? a.created_at.replace('T', ' ').substring(0, 19) : '—'}
          </div>
          <div style="display:flex; gap:10px;">
            ${isHod ? `
              <button class="btn btn-secondary" onclick="openRejectAllocationModal(${a.id})" style="background:#DC2626; color:white; border:none; padding:7px 16px; border-radius:4px; font-weight:600; cursor:pointer;">
                ✗ Reject
              </button>
              <button class="btn btn-primary" onclick="handleApproveAllocation(${a.id})" style="background:#059669; color:white; border:none; padding:7px 18px; border-radius:4px; font-weight:600; cursor:pointer;">
                ✓ Approve Allocation
              </button>
            ` : `
              <span style="font-size:12px; color:var(--text-muted); font-style:italic;">Awaiting departmental HOD decision</span>
            `}
          </div>
        </div>
      `;

      container.appendChild(card);
    });

  } catch (err) {
    console.error("Failed to load pending approvals:", err);
    showToast("Error", "Failed to retrieve pending approvals.", "error");
  }
}

async function handleApproveAllocation(allocId) {
  if (!confirm("Are you sure you want to approve this faculty allocation? Workload will be formally committed in the ledger.")) {
    return;
  }

  try {
    const res = await fetch(`${API_BASE}/api/allocation/${allocId}/approve`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${state.token}`
      }
    });
    const result = await res.json();

    if (!res.ok) {
      showToast("Approval Failed", result.detail || "Failed to approve allocation.", "error");
      return;
    }

    showToast("Allocation Approved", result.message || "Allocation approved and workload committed.", "success");
    loadPendingApprovals();
  } catch (err) {
    showToast("Network Error", "Failed to execute approval.", "error");
  }
}

function openRejectAllocationModal(allocId) {
  document.getElementById("reject-alloc-id").value = allocId;
  document.getElementById("reject-reason").value = "";
  document.getElementById("modal-reject-allocation").classList.add("active");
}

function closeRejectAllocationModal() {
  document.getElementById("modal-reject-allocation").classList.remove("active");
}

async function handleRejectAllocationSubmit(event) {
  event.preventDefault();
  const allocId = document.getElementById("reject-alloc-id").value;
  const reason = document.getElementById("reject-reason").value;

  if (!reason || reason.trim().length < 3) {
    showToast("Validation Error", "Rejection reason must be at least 3 characters.", "warning");
    return;
  }

  const btn = document.getElementById("btn-submit-rejection");
  btn.disabled = true;
  btn.textContent = "Rejecting...";

  try {
    const res = await fetch(`${API_BASE}/api/allocation/${allocId}/reject`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${state.token}`
      },
      body: JSON.stringify({ reason: reason.trim() })
    });
    const result = await res.json();

    btn.disabled = false;
    btn.textContent = "Confirm Rejection";

    if (!res.ok) {
      showToast("Rejection Failed", result.detail || "Failed to reject allocation.", "error");
      return;
    }

    showToast("Allocation Rejected", result.message || "Allocation rejected and reservations released.", "info");
    closeRejectAllocationModal();
    loadPendingApprovals();
  } catch (err) {
    btn.disabled = false;
    btn.textContent = "Confirm Rejection";
    showToast("Network Error", "Failed to submit rejection.", "error");
  }
}


// ─── Module 3: Allocation Records Archive ─────────────────────────────────────
async function loadAllocationHistory() {
  try {
    const res = await fetch(`${API_BASE}/api/allocation/history`);
    const data = await res.json();
    const tbody = document.getElementById("tbody-allocation-history");
    tbody.innerHTML = "";

    if (!data.allocations || data.allocations.length === 0) {
      tbody.innerHTML = `<tr><td colspan="9"><div class="empty-state"><div class="empty-state-icon">📜</div><div class="empty-state-title">No Allocation Orders Yet</div><div class="empty-state-desc">Generated and confirmed question paper setter orders will appear here.</div></div></td></tr>`;
      return;
    }

    data.allocations.forEach(a => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><strong>${a.reference_number}</strong></td>
        <td>${a.academic_year}</td>
        <td>${a.department}</td>
        <td>${a.semester}</td>
        <td>${a.course_code} - ${a.subject_title}</td>
        <td>${a.total_required}</td>
        <td><span class="badge badge-blue">${a.allocation_ratio}</span></td>
        <td><span class="badge ${a.status === 'Confirmed' ? 'badge-green' : 'badge-red'}">${a.status}</span></td>
        <td>
          <a href="/api/reports/download-pdf/${a.id}" target="_blank" class="btn btn-secondary btn-sm" style="padding:4px 8px; font-size:11px;">
            📄 PDF Order
          </a>
        </td>
      `;
      tbody.appendChild(tr);
    });
  } catch (e) {}
}


// ─── Module 13: In-App Notifications & Header Badge ─────────────────────────
async function loadUnreadNotificationCount() {
  if (!state.token) return;
  try {
    const res = await fetch(`${API_BASE}/api/notifications/unread-count`, {
      headers: { "Authorization": `Bearer ${state.token}` }
    });
    if (!res.ok) return;
    const data = await res.json();
    const badge = document.getElementById("header-unread-count");
    if (badge) {
      if (data.unread_count > 0) {
        badge.textContent = data.unread_count;
        badge.style.display = "inline-block";
      } else {
        badge.style.display = "none";
      }
    }
  } catch (err) {}
}

async function loadNotifications() {
  if (!state.token) return;
  const tbody = document.getElementById("tbody-notifications");
  const emptyState = document.getElementById("notif-empty-state");
  const tableContainer = document.getElementById("notif-table-container");
  const unreadTag = document.getElementById("notif-unread-tag");
  const smtpBanner = document.getElementById("notif-smtp-banner");

  if (tbody) tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:24px; color:var(--text-muted);"><span class="spinner-sm"></span> Loading notifications...</td></tr>`;

  try {
    const res = await fetch(`${API_BASE}/api/notifications/my`, {
      headers: { "Authorization": `Bearer ${state.token}` }
    });
    if (!res.ok) {
      if (tbody) tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; color:var(--error-red); padding:16px;">Failed to load notifications.</td></tr>`;
      return;
    }
    const data = await res.json();

    // SMTP Banner
    if (smtpBanner) {
      if (data.smtp_configured) {
        smtpBanner.style.background = "#EFF6FF";
        smtpBanner.style.borderColor = "#BFDBFE";
        smtpBanner.style.color = "#1E40AF";
        smtpBanner.innerHTML = `<span>✓ <strong>SMTP Email Service:</strong> Configured & Active in .env. Email dispatches are enabled.</span><span style="font-size:11px; background:#DBEAFE; padding:2px 8px; border-radius:10px; font-weight:600;">Email + In-App</span>`;
      } else {
        smtpBanner.style.background = "#FFFBEB";
        smtpBanner.style.borderColor = "#FDE68A";
        smtpBanner.style.color = "#92400E";
        smtpBanner.innerHTML = `<span>ℹ️ <strong>SMTP Email Notice:</strong> SMTP is not configured in .env. Notifications are securely delivered to your personal in-app inbox.</span><span style="font-size:11px; background:#FEF3C7; padding:2px 8px; border-radius:10px; font-weight:600;">In-App Active</span>`;
      }
      smtpBanner.style.display = "flex";
    }

    // Unread tag
    if (unreadTag) {
      if (data.unread_count > 0) {
        unreadTag.textContent = `${data.unread_count} Unread`;
        unreadTag.style.display = "inline-block";
      } else {
        unreadTag.style.display = "none";
      }
    }
    loadUnreadNotificationCount();

    if (!data.notifications || data.notifications.length === 0) {
      if (tableContainer) tableContainer.style.display = "none";
      if (emptyState) emptyState.style.display = "block";
      return;
    }

    if (tableContainer) tableContainer.style.display = "block";
    if (emptyState) emptyState.style.display = "none";
    if (tbody) tbody.innerHTML = "";

    data.notifications.forEach(n => {
      const tr = document.createElement("tr");
      if (!n.is_read) tr.style.background = "#F0F9FF";

      let eventBadge = `<span class="badge badge-blue">${escapeHtml(n.event_type || 'ALERT')}</span>`;
      if (n.event_type === "REQUEST_SUBMITTED") eventBadge = `<span class="badge" style="background:#FEF3C7; color:#92400E;">SUBMITTED</span>`;
      if (n.event_type === "REQUEST_APPROVED") eventBadge = `<span class="badge badge-green">APPROVED</span>`;
      if (n.event_type === "REQUEST_REJECTED") eventBadge = `<span class="badge" style="background:#FEE2E2; color:#991B1B;">REJECTED</span>`;
      if (n.event_type === "FACULTY_ASSIGNED") eventBadge = `<span class="badge badge-blue">APPOINTMENT</span>`;

      tr.innerHTML = `
        <td style="font-size:12px; color:var(--text-muted);">${n.created_at ? n.created_at.replace('T', ' ').substring(0, 19) : '—'}</td>
        <td>${eventBadge}</td>
        <td><strong style="color:var(--primary-navy);">${escapeHtml(n.title)}</strong></td>
        <td style="font-size:12px; color:var(--text-dark); max-width:340px; line-height:1.5;">${escapeHtml(n.message)}</td>
        <td>
          ${n.is_read ? '<span class="badge" style="background:#F1F5F9; color:#64748B;">Read</span>' : '<span class="badge badge-amber">● Unread</span>'}
        </td>
        <td>
          ${!n.is_read ? `<button class="btn btn-secondary" style="padding:4px 10px; font-size:11px;" onclick="handleMarkNotificationRead(${n.id})">Mark Read</button>` : '<span style="color:var(--text-muted); font-size:11px;">—</span>'}
        </td>
      `;
      tbody.appendChild(tr);
    });

  } catch (err) {
    console.error("Failed to load notifications:", err);
  }
}

async function handleMarkNotificationRead(id) {
  try {
    const res = await fetch(`${API_BASE}/api/notifications/${id}/read`, {
      method: "POST",
      headers: { "Authorization": `Bearer ${state.token}` }
    });
    if (res.ok) {
      loadNotifications();
    }
  } catch (err) {}
}

async function handleMarkAllNotificationsRead() {
  try {
    const res = await fetch(`${API_BASE}/api/notifications/mark-all-read`, {
      method: "POST",
      headers: { "Authorization": `Bearer ${state.token}` }
    });
    if (res.ok) {
      showToast("Inbox Updated", "All notifications marked as read.", "success");
      loadNotifications();
    }
  } catch (err) {}
}


// ─── Module 5: Security Audit Registry ────────────────────────────────────────
async function loadAuditLogs() {
  try {
    const res = await fetch(`${API_BASE}/api/reports/audit-logs`);
    const data = await res.json();
    const tbody = document.getElementById("tbody-audit");
    tbody.innerHTML = "";

    if (!data.logs || data.logs.length === 0) {
      tbody.innerHTML = `<tr><td colspan="4"><div class="empty-state"><div class="empty-state-icon">🛡️</div><div class="empty-state-title">No Audit Logs</div><div class="empty-state-desc">Administrative actions and security events will be recorded here.</div></div></td></tr>`;
      return;
    }

    data.logs.forEach(l => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${l.performed_at.replace('T', ' ').substring(0, 19)}</td>
        <td><strong>${l.action}</strong></td>
        <td><span class="badge badge-blue">${l.entity_type}</span></td>
        <td style="font-size:12px;">${l.details}</td>
      `;
      tbody.appendChild(tr);
    });
  } catch (e) {}
}


// ─── Module 9: Institutional Policy Settings & Eligibility Matrix ───────────
let currentEvaluations = [];

async function loadPolicySettings() {
  const isAdmin = state.currentUser && state.currentUser.role === "Admin";
  const btnSave = document.getElementById("btn-save-policy");
  const readOnlyMsg = document.getElementById("policy-read-only-msg");
  if (btnSave) btnSave.style.display = isAdmin ? "inline-block" : "none";
  if (readOnlyMsg) readOnlyMsg.style.display = isAdmin ? "none" : "block";

  // Disable fields for non-admin
  ["cfg-min-exp", "cfg-phd-exp", "cfg-internal-cap", "cfg-external-cap", "cfg-allowed-desigs", "cfg-policy-status", "cfg-active-cycle"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.disabled = !isAdmin;
  });

  try {
    const res = await fetch(`${API_BASE}/api/eligibility/policy`, {
      headers: { "Authorization": `Bearer ${state.token}` }
    });
    if (!res.ok) return;
    const data = await res.json();
    const p = data.active_policy || data.latest_policy;
    if (p) {
      if (document.getElementById("cfg-min-exp")) document.getElementById("cfg-min-exp").value = p.min_experience;
      if (document.getElementById("cfg-phd-exp")) document.getElementById("cfg-phd-exp").value = p.min_experience_phd;
      if (document.getElementById("cfg-internal-cap")) document.getElementById("cfg-internal-cap").value = p.internal_capacity;
      if (document.getElementById("cfg-external-cap")) document.getElementById("cfg-external-cap").value = p.external_capacity;
      if (document.getElementById("cfg-allowed-desigs")) document.getElementById("cfg-allowed-desigs").value = (p.allowed_designations || []).join(", ");
      if (document.getElementById("cfg-policy-status")) document.getElementById("cfg-policy-status").value = p.status || "CONFIRMED";
      if (document.getElementById("cfg-active-cycle")) document.getElementById("cfg-active-cycle").value = p.active_academic_year || "2025-26";

      const badge = document.getElementById("policy-status-badge");
      if (badge) {
        badge.textContent = p.status || "CONFIRMED";
        badge.className = p.status === "CONFIRMED" ? "badge badge-success" : "badge badge-amber";
      }
    }
  } catch (e) {
    console.error("Error loading policy settings:", e);
  }
}

async function savePolicySettings() {
  if (!state.currentUser || state.currentUser.role !== "Admin") {
    showToast("Access Denied", "Only Administrator accounts may modify institutional eligibility policies.", "error");
    return;
  }

  const allowedDesigsRaw = document.getElementById("cfg-allowed-desigs").value.trim();
  const allowedDesigs = allowedDesigsRaw.split(",").map(s => s.trim()).filter(Boolean);

  const payload = {
    min_experience: parseFloat(document.getElementById("cfg-min-exp").value) || 10.0,
    min_experience_phd: parseFloat(document.getElementById("cfg-phd-exp").value) || 5.0,
    internal_capacity: parseInt(document.getElementById("cfg-internal-cap").value) || 2,
    external_capacity: parseInt(document.getElementById("cfg-external-cap").value) || 2,
    allowed_designations: allowedDesigs,
    status: document.getElementById("cfg-policy-status").value || "CONFIRMED",
    active_academic_year: document.getElementById("cfg-active-cycle").value.trim() || "2025-26"
  };

  try {
    const res = await fetch(`${API_BASE}/api/eligibility/policy`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${state.token}`
      },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (res.ok) {
      showToast("Policy Saved", data.message || "Institutional eligibility policy updated and signed into audit log.", "success");
      loadPolicySettings();
      loadAcademicYears();
      if (document.getElementById("elig-subject-select").value) {
        runEligibilityEvaluation();
      }
    } else {
      showToast("Policy Update Failed", data.detail || "Server rejected policy modification.", "error");
    }
  } catch (e) {
    showToast("Network Error", "Unable to connect to server to update policy.", "error");
  }
}

async function loadEligibilitySubjects() {
  const sel = document.getElementById("elig-subject-select");
  if (!sel) return;
  try {
    const res = await fetch(`${API_BASE}/api/syllabus/all`, {
      headers: { "Authorization": `Bearer ${state.token}` }
    });
    if (!res.ok) return;
    const subjects = await res.json();
    sel.innerHTML = `<option value="">-- Choose Subject to Audit (${subjects.length} courses) --</option>`;
    subjects.forEach(s => {
      const opt = document.createElement("option");
      opt.value = s.id;
      opt.textContent = `${s.course_code} - ${s.title} (${s.department || "VTU"}, Sem ${s.semester})`;
      sel.appendChild(opt);
    });
  } catch (e) {}
}

async function runEligibilityEvaluation() {
  const subjectId = document.getElementById("elig-subject-select").value;
  if (!subjectId) {
    document.getElementById("elig-stats-row").style.display = "none";
    document.getElementById("elig-results-card").style.display = "none";
    return;
  }

  try {
    const res = await fetch(`${API_BASE}/api/eligibility/evaluate?subject_id=${subjectId}`, {
      headers: { "Authorization": `Bearer ${state.token}` }
    });
    const data = await res.json();
    if (!res.ok) {
      showToast("Evaluation Error", data.detail || "Failed to evaluate candidates for this subject.", "error");
      return;
    }

    currentEvaluations = data.evaluations || [];

    // Render Stats
    document.getElementById("elig-stats-row").style.display = "grid";
    document.getElementById("elig-results-card").style.display = "block";
    document.getElementById("elig-stat-total").textContent = data.counts.total || 0;
    document.getElementById("elig-stat-eligible").textContent = data.counts.ELIGIBLE || 0;
    document.getElementById("elig-stat-not-eligible").textContent = data.counts["NOT ELIGIBLE"] || 0;
    document.getElementById("elig-stat-pending").textContent = data.counts["PENDING VERIFICATION"] || 0;
    document.getElementById("elig-results-title").textContent = `Candidates Evaluated for ${data.subject.course_code}: ${data.subject.title}`;

    renderEligibilityTable(currentEvaluations);
  } catch (e) {
    showToast("Evaluation Failed", "Network error communicating with eligibility engine.", "error");
  }
}

function renderEligibilityTable(evals) {
  const tbody = document.getElementById("elig-results-tbody");
  tbody.innerHTML = "";
  if (!evals || evals.length === 0) {
    tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; padding:20px; color:var(--text-muted);">No faculty records match current filter or role scope.</td></tr>`;
    return;
  }

  evals.forEach(ev => {
    const tr = document.createElement("tr");

    let statusBadge = "";
    if (ev.overall_status === "ELIGIBLE") {
      statusBadge = `<span class="badge badge-success" style="font-weight:700;">✓ ELIGIBLE</span>`;
    } else if (ev.overall_status === "NOT ELIGIBLE") {
      statusBadge = `<span class="badge badge-danger" style="font-weight:700;">✕ NOT ELIGIBLE</span>`;
    } else {
      statusBadge = `<span class="badge badge-amber" style="font-weight:700;">⚠ PENDING VERIF</span>`;
    }

    const typeBadge = ev.faculty_type === "internal" 
      ? `<span class="badge badge-internal">Internal</span>` 
      : `<span class="badge badge-external">External</span>`;

    const mappingRule = ev.rules?.expertise_mapping;
    const mappingDisplay = mappingRule?.status === "PASS"
      ? `<span style="color:#059669; font-weight:600;">✓ ${mappingRule.mapping_type || "CONFIRMED"}</span>`
      : `<span style="color:#dc2626; font-size:11px;">✕ Unconfirmed</span>`;

    const expDisplay = `${ev.experience_years != null ? ev.experience_years + "y" : "Missing"}` + 
      (ev.has_completed_phd ? ` <span class="badge badge-role-admin" style="font-size:10px; padding:2px 5px;">Ph.D</span>` : "");

    const loadDisplay = `${ev.current_workload} / ${ev.capacity}`;

    tr.innerHTML = `
      <td><strong>${ev.faculty_name}</strong><br><span style="font-size:11px; color:var(--text-muted);">ID: ${ev.faculty_id}</span></td>
      <td>${typeBadge}<br><span style="font-size:11px;">${ev.department || "General"}</span></td>
      <td style="font-size:12px;">${ev.designation || '<span style="color:#dc2626;">Missing</span>'}</td>
      <td style="font-size:12px;">${expDisplay}</td>
      <td>${mappingDisplay}</td>
      <td style="font-weight:600; font-size:12px;">${loadDisplay}</td>
      <td>${statusBadge}</td>
      <td style="font-size:11.5px; max-width:280px; line-height:1.35; color:var(--text-muted);">${ev.summary_reason}</td>
    `;
    tbody.appendChild(tr);
  });
}

function filterEligibilityTable() {
  const q = document.getElementById("elig-table-search").value.trim().toLowerCase();
  if (!q) {
    renderEligibilityTable(currentEvaluations);
    return;
  }
  const filtered = currentEvaluations.filter(ev => {
    return (ev.faculty_name || "").toLowerCase().includes(q) ||
           (ev.department || "").toLowerCase().includes(q) ||
           (ev.designation || "").toLowerCase().includes(q) ||
           (ev.overall_status || "").toLowerCase().includes(q) ||
           (ev.summary_reason || "").toLowerCase().includes(q);
  });
  renderEligibilityTable(filtered);
}


// ─── Helpers ──────────────────────────────────────────────────────────────────
function resetDropdown(id, placeholder) {
  const el = document.getElementById(id);
  el.innerHTML = `<option value="">${placeholder}</option>`;
  el.disabled = true;
}

function disableControls(ids) {
  ids.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.disabled = true;
  });
}

function hideAllocationPanels() {
  document.getElementById("subject-detail-banner").style.display = "none";
  document.getElementById("parity-status-card").style.display = "none";
  document.getElementById("section-internal-faculty").style.display = "none";
  document.getElementById("section-external-faculty").style.display = "none";
  document.getElementById("section-allocation-summary").style.display = "none";
}


// ─── Module 4: Admin Dashboard Stats & User Management ─────────────────────────
async function loadDashboardStats() {
  if (!state.token || !state.currentUser || state.currentUser.role !== "Admin") return;
  try {
    const res = await fetch(`${API_BASE}/api/admin/dashboard-stats`, {
      headers: { "Authorization": `Bearer ${state.token}` }
    });
    if (!res.ok) return;
    const data = await res.json();

    const elInt = document.getElementById("dash-stat-internal");
    const elExt = document.getElementById("dash-stat-external");
    const elUnv = document.getElementById("dash-stat-unverified");
    const elSub = document.getElementById("dash-stat-subjects");
    const elAllocTot = document.getElementById("dash-stat-alloc-total");
    const elAllocBreak = document.getElementById("dash-stat-alloc-breakdown");
    const elUsersTot = document.getElementById("dash-stat-users-total");
    const elUsersBreak = document.getElementById("dash-stat-users-breakdown");

    if (elInt) elInt.textContent = data.faculty.internal_count;
    if (elExt) elExt.textContent = data.faculty.external_count;
    if (elUnv) elUnv.textContent = data.faculty.pending_verification_count;
    if (elSub) elSub.textContent = data.syllabus.total_subjects_count;
    if (elAllocTot) elAllocTot.textContent = data.allocations.total_allocations;
    if (elAllocBreak) {
      const bs = data.allocations.by_status;
      elAllocBreak.textContent = `Draft: ${bs.Draft || 0} | Confirmed: ${bs.Confirmed || 0} | Pending: ${bs["Pending HOD Approval"] || 0}`;
    }
    if (elUsersTot) elUsersTot.textContent = data.users.total_users;
    if (elUsersBreak) {
      elUsersBreak.textContent = `Active: ${data.users.active_users} | Locked: ${data.users.locked_users}`;
    }
  } catch (err) {
    console.error("Failed to load dashboard stats:", err);
  }
}

state.allUsers = [];

async function loadUsersList() {
  if (!state.token || !state.currentUser || state.currentUser.role !== "Admin") return;
  const tbody = document.getElementById("users-table-body");
  if (tbody) tbody.innerHTML = `<tr><td colspan="9" style="text-align:center; padding: 24px; color:var(--text-muted);"><span class="spinner-sm"></span> Loading institutional users...</td></tr>`;

  try {
    const res = await fetch(`${API_BASE}/api/admin/users`, {
      headers: { "Authorization": `Bearer ${state.token}` }
    });
    if (!res.ok) {
      const err = await res.json();
      showToast("Access Denied", err.detail || "Could not retrieve user roster.", "error");
      if (tbody) tbody.innerHTML = `<tr><td colspan="9" style="text-align:center; color:var(--error-red); padding: 20px;">Failed to load users: ${err.detail || "Forbidden"}</td></tr>`;
      return;
    }
    const data = await res.json();
    state.allUsers = data.users || [];
    renderUsersTable(state.allUsers);
  } catch (err) {
    if (tbody) tbody.innerHTML = `<tr><td colspan="9" style="text-align:center; color:var(--error-red); padding: 20px;">Network error loading users.</td></tr>`;
  }
}

function renderUsersTable(users) {
  const tbody = document.getElementById("users-table-body");
  if (!tbody) return;

  if (!users || users.length === 0) {
    tbody.innerHTML = `<tr><td colspan="9" style="text-align:center; padding: 30px; color:var(--text-muted);">No institutional users found matching filters.</td></tr>`;
    return;
  }

  tbody.innerHTML = users.map(u => {
    const roleBadge = u.role === "Admin" ? "badge-role-admin" : (u.role === "HOD" ? "badge-role-hod" : "badge-role-faculty");
    const activeBadge = u.is_active ? `<span class="badge badge-verified">Active</span>` : `<span class="badge badge-unverified">Inactive</span>`;
    const lockBadge = u.is_locked ? `<span class="badge badge-unverified" style="margin-left:4px;">🔒 Locked</span>` : "";
    const lastLogin = u.last_login_at ? new Date(u.last_login_at).toLocaleString() : "Never";

    const isSelf = state.currentUser && state.currentUser.id === u.id;

    return `
      <tr>
        <td style="color:var(--text-muted); font-size:11px;">#${u.id}</td>
        <td>
          <div style="font-weight:600; color:var(--primary-navy);">${escapeHtml(u.full_name || u.username)}</div>
          <div style="font-size:11.5px; color:var(--text-muted); font-family:var(--font-mono);">${escapeHtml(u.username)}</div>
        </td>
        <td>
          <div>${escapeHtml(u.email)}</div>
          <div style="font-size:11px; color:var(--text-muted);">${escapeHtml(u.phone || "—")}</div>
        </td>
        <td><span class="badge-role ${roleBadge}">${u.role}</span></td>
        <td><strong>${escapeHtml(u.department || "System-wide")}</strong></td>
        <td>
          <div style="display:flex; align-items:center;">
            ${activeBadge}
            ${lockBadge}
          </div>
        </td>
        <td style="text-align:center; font-family:var(--font-mono); font-size:11.5px;">${u.failed_attempts || 0}</td>
        <td style="font-size:11.5px; color:var(--text-muted);">${lastLogin}</td>
        <td style="text-align: right;">
          <div style="display:inline-flex; gap:6px; flex-wrap:wrap; justify-content:flex-end;">
            <button class="btn-xs btn-xs-primary" onclick="openEditUserModal(${u.id})">Edit</button>
            ${u.is_locked ? `<button class="btn-xs btn-xs-warning" onclick="handleUnlockUser(${u.id}, '${escapeHtml(u.username)}')">Unlock</button>` : ""}
            <button class="btn-xs btn-xs-warning" onclick="openAdminResetModal(${u.id}, '${escapeHtml(u.username)}')">Reset Pwd</button>
            ${!isSelf ? `
              <button class="btn-xs ${u.is_active ? 'btn-xs-danger' : 'btn-xs-success'}" onclick="handleToggleUserActive(${u.id}, '${escapeHtml(u.username)}', ${u.is_active})">
                ${u.is_active ? 'Deactivate' : 'Activate'}
              </button>
            ` : `<span style="font-size:10.5px; color:var(--text-muted); padding:4px;">(Self)</span>`}
          </div>
        </td>
      </tr>
    `;
  }).join("");
}

function filterUsersTable() {
  const search = (document.getElementById("user-filter-search")?.value || "").toLowerCase().trim();
  const role = document.getElementById("user-filter-role")?.value || "";
  const dept = document.getElementById("user-filter-dept")?.value || "";

  let filtered = state.allUsers || [];
  if (role) filtered = filtered.filter(u => u.role === role);
  if (dept) filtered = filtered.filter(u => u.department === dept);
  if (search) {
    filtered = filtered.filter(u =>
      (u.username && u.username.toLowerCase().includes(search)) ||
      (u.full_name && u.full_name.toLowerCase().includes(search)) ||
      (u.email && u.email.toLowerCase().includes(search))
    );
  }
  renderUsersTable(filtered);
}

function onRoleChange(prefix) {
  const roleEl = document.getElementById(`${prefix}-role`);
  const deptGroup = document.getElementById(`${prefix}-dept-group`);
  if (!roleEl || !deptGroup) return;

  if (roleEl.value === "Admin") {
    deptGroup.style.opacity = "0.4";
  } else {
    deptGroup.style.opacity = "1";
  }
}

// ─── Create User Modal & Action Handlers ───────────────────────────────────────
function openCreateUserModal() {
  const form = document.getElementById("form-create-user");
  if (form) form.reset();
  onRoleChange('cu');
  document.getElementById("modal-create-user").style.display = "flex";
}

function closeCreateUserModal() {
  document.getElementById("modal-create-user").style.display = "none";
}

async function handleCreateUser(e) {
  e.preventDefault();
  const username = document.getElementById("cu-username").value.trim();
  const full_name = document.getElementById("cu-fullname").value.trim();
  const email = document.getElementById("cu-email").value.trim();
  const phone = document.getElementById("cu-phone").value.trim();
  const role = document.getElementById("cu-role").value;
  const dept = document.getElementById("cu-dept").value;
  const password = document.getElementById("cu-password").value;

  if (role !== "Admin" && !dept) {
    showToast("Validation Error", "Department is mandatory for HOD and Faculty accounts.", "error");
    return;
  }

  const btn = document.getElementById("btn-submit-create-user");
  btn.disabled = true;
  btn.textContent = "Creating...";

  try {
    const res = await fetch(`${API_BASE}/api/admin/users`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${state.token}`
      },
      body: JSON.stringify({
        username,
        full_name,
        email,
        phone: phone || null,
        role,
        department: role === "Admin" ? null : dept,
        password
      })
    });

    const data = await res.json();
    if (res.ok) {
      showToast("User Created", `Account '${username}' has been successfully created.`, "success");
      closeCreateUserModal();
      await loadUsersList();
      await loadDashboardStats();
    } else {
      showToast("Creation Failed", data.detail || "Could not create user account.", "error");
    }
  } catch (err) {
    showToast("Network Error", "Failed to connect to authentication server.", "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "Create User Account";
  }
}

// ─── Edit User Modal & Action Handlers ─────────────────────────────────────────
function openEditUserModal(userId) {
  const user = (state.allUsers || []).find(u => u.id === userId);
  if (!user) return;

  document.getElementById("eu-id").value = user.id;
  document.getElementById("eu-username").value = user.username;
  document.getElementById("eu-email").value = user.email;
  document.getElementById("eu-fullname").value = user.full_name || "";
  document.getElementById("eu-phone").value = user.phone || "";
  document.getElementById("eu-role").value = user.role;
  document.getElementById("eu-dept").value = user.department || "";
  document.getElementById("eu-active").checked = user.is_active;

  onRoleChange('eu');
  document.getElementById("modal-edit-user").style.display = "flex";
}

function closeEditUserModal() {
  document.getElementById("modal-edit-user").style.display = "none";
}

async function handleUpdateUser(e) {
  e.preventDefault();
  const userId = document.getElementById("eu-id").value;
  const full_name = document.getElementById("eu-fullname").value.trim();
  const phone = document.getElementById("eu-phone").value.trim();
  const role = document.getElementById("eu-role").value;
  const dept = document.getElementById("eu-dept").value;
  const is_active = document.getElementById("eu-active").checked;

  const btn = document.getElementById("btn-submit-edit-user");
  btn.disabled = true;
  btn.textContent = "Saving...";

  try {
    const res = await fetch(`${API_BASE}/api/admin/users/${userId}`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${state.token}`
      },
      body: JSON.stringify({
        full_name,
        phone: phone || null,
        role,
        department: role === "Admin" ? null : dept,
        is_active
      })
    });

    const data = await res.json();
    if (res.ok) {
      showToast("User Updated", "Account changes saved successfully.", "success");
      closeEditUserModal();
      await loadUsersList();
      await loadDashboardStats();
    } else {
      showToast("Update Failed", data.detail || "Could not save user changes.", "error");
    }
  } catch (err) {
    showToast("Network Error", "Failed to communicate with administration server.", "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "Save Changes";
  }
}

// ─── Unlock User Handler ──────────────────────────────────────────────────────
async function handleUnlockUser(userId, username) {
  if (!confirm(`Are you sure you want to unlock user account '${username}' and reset failed attempts?`)) return;
  try {
    const res = await fetch(`${API_BASE}/api/admin/users/${userId}/unlock`, {
      method: "POST",
      headers: { "Authorization": `Bearer ${state.token}` }
    });
    const data = await res.json();
    if (res.ok) {
      showToast("Account Unlocked", `User '${username}' has been unlocked.`, "success");
      await loadUsersList();
      await loadDashboardStats();
    } else {
      showToast("Unlock Failed", data.detail || "Could not unlock account.", "error");
    }
  } catch (err) {
    showToast("Network Error", "Failed to unlock account.", "error");
  }
}

// ─── Admin Password Reset Handlers ────────────────────────────────────────────
function openAdminResetModal(userId, username) {
  document.getElementById("arp-id").value = userId;
  document.getElementById("arp-target-username").textContent = username;
  document.getElementById("arp-new-pwd").value = "";
  document.getElementById("arp-confirm-pwd").value = "";
  document.getElementById("modal-admin-reset-pwd").style.display = "flex";
}

function closeAdminResetModal() {
  document.getElementById("modal-admin-reset-pwd").style.display = "none";
}

async function handleAdminResetPassword(e) {
  e.preventDefault();
  const userId = document.getElementById("arp-id").value;
  const newPwd = document.getElementById("arp-new-pwd").value;
  const confirmPwd = document.getElementById("arp-confirm-pwd").value;

  if (newPwd !== confirmPwd) {
    showToast("Validation Error", "New password and confirmation do not match.", "error");
    return;
  }
  if (newPwd.length < 8) {
    showToast("Validation Error", "Password must be at least 8 characters long.", "error");
    return;
  }

  const btn = document.getElementById("btn-submit-admin-reset");
  btn.disabled = true;
  btn.textContent = "Resetting...";

  try {
    const res = await fetch(`${API_BASE}/api/admin/users/${userId}/reset-password`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${state.token}`
      },
      body: JSON.stringify({ new_password: newPwd })
    });
    const data = await res.json();
    if (res.ok) {
      showToast("Password Reset", data.message || "Password updated successfully.", "success");
      closeAdminResetModal();
      await loadUsersList();
    } else {
      showToast("Reset Failed", data.detail || "Could not reset password.", "error");
    }
  } catch (err) {
    showToast("Network Error", "Failed to reset password.", "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "Reset Password";
  }
}

// ─── Activate / Deactivate Toggle Handler ─────────────────────────────────────
async function handleToggleUserActive(userId, username, currentActive) {
  const action = currentActive ? "deactivate" : "activate";
  const promptMsg = currentActive
    ? `Deactivate account '${username}'? The user will be immediately logged out and blocked from signing in.`
    : `Reactivate account '${username}'?`;

  if (!confirm(promptMsg)) return;

  try {
    const res = await fetch(`${API_BASE}/api/admin/users/${userId}/${action}`, {
      method: "POST",
      headers: { "Authorization": `Bearer ${state.token}` }
    });
    const data = await res.json();
    if (res.ok) {
      showToast(currentActive ? "User Deactivated" : "User Reactivated", data.message || `Account updated successfully.`, "info");
      await loadUsersList();
      await loadDashboardStats();
    } else {
      showToast("Action Failed", data.detail || `Could not ${action} user.`, "error");
    }
  } catch (err) {
    showToast("Network Error", `Failed to ${action} user account.`, "error");
  }
}


// ─── Module 5: Academic Subject Master & Curriculum Catalog ──────────────────
state.allSubjects = [];

async function loadSubjectMasterList() {
  if (!state.token) return;
  const tbody = document.getElementById("subjects-table-body");
  if (tbody) tbody.innerHTML = `<tr><td colspan="9" style="text-align:center; padding: 24px; color:var(--text-muted);"><span class="spinner-sm"></span> Loading syllabus subjects...</td></tr>`;

  try {
    let url = `${API_BASE}/api/syllabus/all`;
    // If HOD or Faculty, server will enforce scoping, but we pass current UI filters
    const params = new URLSearchParams();
    const ay = document.getElementById("subj-filter-ay")?.value;
    const dept = document.getElementById("subj-filter-dept")?.value;
    const scheme = document.getElementById("subj-filter-scheme")?.value;
    const sem = document.getElementById("subj-filter-sem")?.value;
    const search = document.getElementById("subj-filter-search")?.value;

    if (ay) params.append("academic_year", ay);
    if (dept) params.append("department", dept);
    if (scheme) params.append("scheme", scheme);
    if (sem) params.append("semester", sem);
    if (search) params.append("search", search);

    const qs = params.toString();
    if (qs) url += `?${qs}`;

    const res = await fetch(url, {
      headers: { "Authorization": `Bearer ${state.token}` }
    });

    if (!res.ok) {
      const err = await res.json();
      showToast("Access Denied", err.detail || "Could not retrieve subject catalog.", "error");
      if (tbody) tbody.innerHTML = `<tr><td colspan="9" style="text-align:center; color:var(--error-red); padding: 20px;">Failed to load subjects: ${err.detail || "Forbidden"}</td></tr>`;
      return;
    }

    const data = await res.json();
    state.allSubjects = data.subjects || [];
    renderSubjectsTable(state.allSubjects);
  } catch (err) {
    if (tbody) tbody.innerHTML = `<tr><td colspan="9" style="text-align:center; color:var(--error-red); padding: 20px;">Network communication error.</td></tr>`;
  }
}

function renderSubjectsTable(subjects) {
  const tbody = document.getElementById("subjects-table-body");
  if (!tbody) return;

  if (!subjects || subjects.length === 0) {
    tbody.innerHTML = `<tr><td colspan="9" style="text-align:center; padding: 30px; color:var(--text-muted);">No syllabus courses found matching filters.</td></tr>`;
    return;
  }

  const isAdmin = state.currentUser && state.currentUser.role === "Admin";

  tbody.innerHTML = subjects.map(s => {
    let badgeClass = "badge-verified";
    let badgeLabel = s.badge_label || s.verification_status || "Verified";
    const bLow = (s.badge_class || "").toLowerCase();
    if (bLow === "pending") badgeClass = "badge-pending";
    else if (bLow === "unverified") badgeClass = "badge-unverified";
    else if (bLow === "partially") badgeClass = "badge-role-admin";

    return `
      <tr>
        <td style="font-family:var(--font-mono); font-weight:700; color:var(--royal-blue);">${escapeHtml(s.course_code)}</td>
        <td>
          <div style="font-weight:600; color:var(--primary-navy);">${escapeHtml(s.title)}</div>
          ${s.source_notes ? `<div style="font-size:11px; color:var(--text-muted);">${escapeHtml(s.source_notes)}</div>` : ""}
        </td>
        <td><strong>${escapeHtml(s.department)}</strong></td>
        <td>Sem ${escapeHtml(s.semester)}</td>
        <td>${escapeHtml(s.scheme)}</td>
        <td style="font-size:12px; color:var(--text-muted);">${escapeHtml(s.academic_year)}</td>
        <td>${escapeHtml(s.course_type)} (${s.credits || 4} cr)</td>
        <td><span class="badge ${badgeClass}" title="${escapeHtml(s.verification_status || '')}">${escapeHtml(badgeLabel)}</span></td>
        <td style="text-align: right;">
          ${isAdmin ? `
            <button class="btn-xs btn-xs-primary" onclick="openEditSubjectModal(${s.id})">Edit</button>
          ` : `
            <span class="badge" style="background:#F1F5F9; color:var(--text-muted); border:1px solid #E2E8F0;">Scoped</span>
          `}
        </td>
      </tr>
    `;
  }).join("");
}

function filterSubjectsTable() {
  const search = (document.getElementById("subj-filter-search")?.value || "").toLowerCase().trim();
  const ay = document.getElementById("subj-filter-ay")?.value || "";
  const dept = document.getElementById("subj-filter-dept")?.value || "";
  const scheme = document.getElementById("subj-filter-scheme")?.value || "";
  const sem = document.getElementById("subj-filter-sem")?.value || "";

  let filtered = state.allSubjects || [];
  if (ay) filtered = filtered.filter(s => s.academic_year === ay);
  if (dept) filtered = filtered.filter(s => s.department === dept || s.department.includes(dept));
  if (scheme) filtered = filtered.filter(s => s.scheme === scheme);
  if (sem) filtered = filtered.filter(s => s.semester === sem || s.semester.includes(sem));
  if (search) {
    filtered = filtered.filter(s =>
      (s.course_code && s.course_code.toLowerCase().includes(search)) ||
      (s.title && s.title.toLowerCase().includes(search)) ||
      (s.source_notes && s.source_notes.toLowerCase().includes(search))
    );
  }
  renderSubjectsTable(filtered);
}

function onSubjectDeptChange(prefix) {
  const deptEl = document.getElementById(`${prefix}-dept`);
  const semEl = document.getElementById(`${prefix}-sem`);
  if (!deptEl || !semEl) return;

  const isMca = deptEl.value.toUpperCase().includes("MCA");
  if (isMca) {
    // MCA allowed semesters only (I, II, III, IV)
    semEl.innerHTML = `
      <option value="I">Semester I</option>
      <option value="II">Semester II</option>
      <option value="III">Semester III</option>
      <option value="IV">Semester IV</option>
    `;
  } else {
    // Engineering 8 semesters
    semEl.innerHTML = `
      <option value="I">Semester I</option>
      <option value="II">Semester II</option>
      <option value="III">Semester III</option>
      <option value="IV">Semester IV</option>
      <option value="V">Semester V</option>
      <option value="VI">Semester VI</option>
      <option value="VII">Semester VII</option>
      <option value="VIII">Semester VIII</option>
    `;
  }
}

// ─── Add Subject Modal Handlers ───────────────────────────────────────────────
function openAddSubjectModal() {
  const form = document.getElementById("form-add-subject");
  if (form) form.reset();
  onSubjectDeptChange("as");
  document.getElementById("modal-add-subject").style.display = "flex";
}

function closeAddSubjectModal() {
  document.getElementById("modal-add-subject").style.display = "none";
}

async function handleAddSubject(e) {
  e.preventDefault();
  const code = document.getElementById("as-code").value.trim().toUpperCase();
  const title = document.getElementById("as-title").value.trim();
  const dept = document.getElementById("as-dept").value;
  const sem = document.getElementById("as-sem").value;
  const scheme = document.getElementById("as-scheme").value.trim();
  const ay = document.getElementById("as-ay").value.trim();
  const type = document.getElementById("as-type").value;
  const credits = parseInt(document.getElementById("as-credits").value) || 4;
  const vstatus = document.getElementById("as-vstatus").value.trim();
  const notes = document.getElementById("as-notes").value.trim();

  const btn = document.getElementById("btn-submit-add-subject");
  btn.disabled = true;
  btn.textContent = "Adding...";

  try {
    const res = await fetch(`${API_BASE}/api/syllabus/subjects`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${state.token}`
      },
      body: JSON.stringify({
        course_code: code,
        title,
        department: dept,
        scheme,
        semester: sem,
        academic_year: ay,
        course_type: type,
        credits,
        verification_status: vstatus,
        source_notes: notes || null
      })
    });

    const data = await res.json();
    if (res.ok) {
      showToast("Subject Added", `Academic course '${code}' successfully registered.`, "success");
      closeAddSubjectModal();
      await loadSubjectMasterList();
      if (typeof loadDashboardStats === "function") loadDashboardStats();
    } else {
      showToast("Add Failed", data.detail || "Could not register subject.", "error");
    }
  } catch (err) {
    showToast("Network Error", "Failed to connect to syllabus server.", "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "Add Subject";
  }
}

// ─── Edit Subject Modal Handlers ──────────────────────────────────────────────
async function openEditSubjectModal(subjectId) {
  try {
    const res = await fetch(`${API_BASE}/api/syllabus/subjects/${subjectId}`, {
      headers: { "Authorization": `Bearer ${state.token}` }
    });
    if (!res.ok) {
      const err = await res.json();
      showToast("Access Denied", err.detail || "Could not fetch subject details.", "error");
      return;
    }
    const subj = await res.json();

    document.getElementById("es-id").value = subj.id;
    document.getElementById("es-code").value = subj.course_code;
    document.getElementById("es-title").value = subj.title;
    document.getElementById("es-dept").value = subj.department;

    onSubjectDeptChange("es");

    document.getElementById("es-sem").value = subj.semester.replace("Semester", "").trim();
    document.getElementById("es-scheme").value = subj.scheme || "";
    document.getElementById("es-ay").value = subj.academic_year || "";
    document.getElementById("es-type").value = subj.course_type || "Theory";
    document.getElementById("es-credits").value = subj.credits || 4;
    document.getElementById("es-vstatus").value = subj.verification_status || "";
    document.getElementById("es-notes").value = subj.source_notes || "";

    document.getElementById("modal-edit-subject").style.display = "flex";
  } catch (err) {
    showToast("Network Error", "Could not open edit dialog.", "error");
  }
}

function closeEditSubjectModal() {
  document.getElementById("modal-edit-subject").style.display = "none";
}

async function handleEditSubject(e) {
  e.preventDefault();
  const subjId = document.getElementById("es-id").value;
  const code = document.getElementById("es-code").value.trim().toUpperCase();
  const title = document.getElementById("es-title").value.trim();
  const dept = document.getElementById("es-dept").value;
  const sem = document.getElementById("es-sem").value;
  const scheme = document.getElementById("es-scheme").value.trim();
  const ay = document.getElementById("es-ay").value.trim();
  const type = document.getElementById("es-type").value;
  const credits = parseInt(document.getElementById("es-credits").value) || 4;
  const vstatus = document.getElementById("es-vstatus").value.trim();
  const notes = document.getElementById("es-notes").value.trim();

  const btn = document.getElementById("btn-submit-edit-subject");
  btn.disabled = true;
  btn.textContent = "Saving...";

  try {
    const res = await fetch(`${API_BASE}/api/syllabus/subjects/${subjId}`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${state.token}`
      },
      body: JSON.stringify({
        course_code: code,
        title,
        department: dept,
        scheme,
        semester: sem,
        academic_year: ay,
        course_type: type,
        credits,
        verification_status: vstatus,
        source_notes: notes || null
      })
    });

    const data = await res.json();
    if (res.ok) {
      showToast("Subject Updated", `Changes to '${code}' have been saved.`, "success");
      closeEditSubjectModal();
      await loadSubjectMasterList();
    } else {
      showToast("Update Failed", data.detail || "Could not update subject.", "error");
    }
  } catch (err) {
    showToast("Network Error", "Failed to connect to syllabus server.", "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "Save Changes";
  }
}

// ─── Utility Helper ──────────────────────────────────────────────────────────
function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// ─── Module 6: Faculty Management & Institution Whitelist Governance ─────────
let facultyRosterData = [];
let institutionsData = [];
let facultySearchDebounceTimer = null;

async function loadFacultyTab() {
  const isAdmin = state.currentUser && state.currentUser.role === "Admin";
  if (isAdmin) {
    await loadWhitelistInstitutions();
  }
  await loadFacultyRoster();
}

async function loadWhitelistInstitutions() {
  try {
    const res = await fetch(`${API_BASE}/api/faculty/institutions/whitelist`, {
      headers: { "Authorization": `Bearer ${state.token}` }
    });
    if (!res.ok) return;
    const data = await res.json();
    institutionsData = data.institutions || [];

    // Render Whitelist Table
    const tbody = document.getElementById("whitelist-table-body");
    if (!tbody) return;

    if (institutionsData.length === 0) {
      tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding:20px; color:var(--text-muted);">No external institutions registered.</td></tr>`;
      return;
    }

    tbody.innerHTML = institutionsData.map(inst => `
      <tr>
        <td style="font-weight:600; color:var(--text-muted);">${inst.id}</td>
        <td>
          <strong style="color:var(--primary-navy);">${escapeHtml(inst.name)}</strong>
        </td>
        <td style="text-align:center; font-weight:700; color:var(--royal-blue);">${inst.faculty_count}</td>
        <td style="text-align:center;">
          <span class="badge ${inst.is_allowed ? 'badge-verified' : 'badge-unverified'}">
            ${inst.is_allowed ? 'Whitelisted' : 'Disabled'}
          </span>
        </td>
        <td style="text-align:right;">
          <button class="btn btn-sm ${inst.is_allowed ? 'btn-secondary' : 'btn-success'}" onclick="handleToggleInstitutionWhitelist(${inst.id}, '${escapeHtml(inst.name).replace(/'/g, "\\'")}', ${inst.is_allowed})">
            ${inst.is_allowed ? 'Disable' : 'Enable'}
          </button>
        </td>
      </tr>
    `).join("");

    // Populate Institution filter dropdown if empty or needs update
    const instSelect = document.getElementById("fac-filter-inst");
    if (instSelect) {
      const curVal = instSelect.value;
      let html = `<option value="">All Institutions</option>`;
      html += `<option value="SJB Institute of Technology">SJB Institute of Technology (Internal)</option>`;
      institutionsData.forEach(inst => {
        html += `<option value="${escapeHtml(inst.name)}">${escapeHtml(inst.name)}</option>`;
      });
      instSelect.innerHTML = html;
      instSelect.value = curVal;
    }
  } catch (err) {
    console.error("Failed to load institution whitelist:", err);
  }
}

async function handleToggleInstitutionWhitelist(instId, instName, currentStatus) {
  try {
    const res = await fetch(`${API_BASE}/api/faculty/institutions/${instId}/toggle`, {
      method: "POST",
      headers: { "Authorization": `Bearer ${state.token}` }
    });
    const data = await res.json();
    if (res.ok) {
      showToast("Institution Whitelist Updated", data.message, "success");
      await loadWhitelistInstitutions();
      await loadFacultyRoster();
    } else {
      showToast("Action Failed", data.detail || "Could not toggle institution status.", "error");
    }
  } catch (err) {
    showToast("Network Error", "Could not connect to faculty server.", "error");
  }
}

function filterFacultyTable() {
  clearTimeout(facultySearchDebounceTimer);
  facultySearchDebounceTimer = setTimeout(() => {
    loadFacultyRoster();
  }, 250);
}

async function loadFacultyRoster() {
  const tbody = document.getElementById("faculty-table-body");
  if (!tbody) return;

  const search = document.getElementById("fac-filter-search")?.value.trim() || "";
  const faculty_type = document.getElementById("fac-filter-type")?.value || "";
  const department = document.getElementById("fac-filter-dept")?.value || "";
  const institution = document.getElementById("fac-filter-inst")?.value || "";
  const eligibility_status = document.getElementById("fac-filter-status")?.value || "";
  const is_available = document.getElementById("fac-filter-avail")?.value || "";

  const params = new URLSearchParams();
  if (search) params.append("search", search);
  if (faculty_type) params.append("faculty_type", faculty_type);
  if (department) params.append("department", department);
  if (institution) params.append("institution", institution);
  if (eligibility_status) params.append("eligibility_status", eligibility_status);
  if (is_available !== "") params.append("is_available", is_available);

  try {
    const res = await fetch(`${API_BASE}/api/faculty/all?${params.toString()}`, {
      headers: { "Authorization": `Bearer ${state.token}` }
    });

    if (!res.ok) {
      const err = await res.json();
      tbody.innerHTML = `<tr><td colspan="10" style="text-align:center; padding:24px; color:var(--error-red);">${escapeHtml(err.detail || "Access Denied")}</td></tr>`;
      return;
    }

    const data = await res.json();
    facultyRosterData = data.faculty || [];
    renderFacultyTable(facultyRosterData);
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="10" style="text-align:center; padding:24px; color:var(--error-red);">Failed to connect to faculty database.</td></tr>`;
  }
}

function renderFacultyTable(list) {
  const tbody = document.getElementById("faculty-table-body");
  const countLabel = document.getElementById("faculty-table-count");
  if (!tbody) return;

  if (countLabel) {
    countLabel.textContent = `Showing ${list.length} faculty record${list.length === 1 ? '' : 's'}`;
  }

  if (list.length === 0) {
    tbody.innerHTML = `<tr><td colspan="10" style="text-align:center; padding:30px; color:var(--text-muted);">No faculty records match the applied filters.</td></tr>`;
    return;
  }

  const isAdmin = state.currentUser && state.currentUser.role === "Admin";

  tbody.innerHTML = list.map(f => {
    // Experience formatting: strict preservation of NULL
    const expDisplay = (f.experience_years !== null && f.experience_years !== undefined)
      ? `<strong>${f.experience_years}</strong> yrs`
      : `<span style="color:var(--text-muted); font-style:italic;">Not provided</span>`;

    // Email & mobile formatting: strict preservation of NULL
    const emailDisplay = f.email
      ? `<div style="font-size:12px; color:var(--text-dark);">${escapeHtml(f.email)}</div>`
      : `<div style="font-size:11.5px; color:var(--text-muted); font-style:italic;">Email: Not provided</div>`;
    const mobileDisplay = f.mobile
      ? `<div style="font-size:11.5px; color:var(--text-muted);">📞 ${escapeHtml(f.mobile)}</div>`
      : `<div style="font-size:11.5px; color:var(--text-muted); font-style:italic;">Phone: Not provided</div>`;

    // Qualification & PhD badge
    const qualText = f.qualification ? escapeHtml(f.qualification) : "";
    const isPhd = qualText.toLowerCase().includes("ph.d") || qualText.toLowerCase().includes("phd");
    const isPursuing = ["pursuing", "ongoing", "registered", "enrolled", "candidate"].some(p => qualText.toLowerCase().includes(p));

    let qualBadge = "";
    if (isPhd) {
      if (isPursuing) {
        qualBadge = `<span class="badge badge-amber" style="font-size:10px; margin-left:4px;">Ph.D Pursuing</span>`;
      } else {
        qualBadge = `<span class="badge badge-blue" style="font-size:10px; margin-left:4px;">Ph.D</span>`;
      }
    }

    // Eligibility status badge
    let statusBadge = "";
    const status = f.eligibility_status || "";
    if (status.includes("Qualified") && !status.startsWith("Not")) {
      statusBadge = `<span class="badge badge-verified" title="${escapeHtml(status)}">✓ Qualified</span>`;
    } else if (status.includes("Cannot Verify") || status.includes("Pending")) {
      const reasonTitle = f.pending_reason ? escapeHtml(f.pending_reason) : "Experience details pending physical verification";
      statusBadge = `
        <span class="badge badge-pending" title="${reasonTitle}" style="display:inline-flex; align-items:center; gap:4px; cursor:help;">
          ⚠️ Cannot Verify
        </span>
        <div style="font-size:10px; color:#B45309; margin-top:3px; max-width:170px; line-height:1.2;">
          ${escapeHtml(f.pending_reason || "Experience duration not provided")}
        </div>
      `;
    } else {
      statusBadge = `
        <span class="badge badge-unverified" title="${escapeHtml(f.pending_reason || status)}">✕ Not Qualified</span>
        ${f.pending_reason ? `<div style="font-size:10px; color:#DC2626; margin-top:3px; max-width:170px; line-height:1.2;">${escapeHtml(f.pending_reason)}</div>` : ''}
      `;
    }

    // Availability toggle
    let availControl = "";
    if (isAdmin) {
      availControl = `
        <button class="btn btn-sm ${f.is_available ? 'btn-success' : 'btn-secondary'}"
          style="font-size:11.5px; padding:3px 8px;"
          onclick="handleToggleFacultyAvailability(${f.id}, '${escapeHtml(f.name).replace(/'/g, "\\'")}', ${f.is_available})">
          ${f.is_available ? '✓ Available' : '✕ Unavailable'}
        </button>
      `;
    } else {
      availControl = `
        <span class="badge ${f.is_available ? 'badge-verified' : 'badge-unverified'}" style="font-size:11px;">
          ${f.is_available ? 'Available' : 'Unavailable'}
        </span>
      `;
    }

    // Action button
    const actionBtn = isAdmin
      ? `<button class="btn btn-secondary btn-sm" onclick="openEditFacultyModal(${f.id})">✏️ Edit</button>`
      : `<button class="btn btn-secondary btn-sm" onclick="openEditFacultyModal(${f.id}, true)">👁️ View</button>`;

    return `
      <tr>
        <td style="font-weight:600; color:var(--text-muted);">${f.id}</td>
        <td>
          <div style="font-weight:700; color:var(--primary-navy); display:flex; align-items:center; flex-wrap:wrap;">
            ${escapeHtml(f.name)}
            ${qualBadge}
          </div>
          <div style="font-size:12px; color:var(--text-muted); margin-top:2px;">
            ${escapeHtml(f.designation || "Faculty")}
          </div>
        </td>
        <td>
          <span class="badge ${f.faculty_type === 'internal' ? 'badge-blue' : 'badge-purple'}">
            ${f.faculty_type === 'internal' ? 'Internal' : 'External'}
          </span>
        </td>
        <td><span style="font-weight:600;">${escapeHtml(f.department || "—")}</span></td>
        <td style="font-size:12px; color:var(--text-dark); max-width:160px;">${escapeHtml(f.institution || "SJBIT")}</td>
        <td style="font-size:12.5px;">${expDisplay}</td>
        <td>${emailDisplay}${mobileDisplay}</td>
        <td>${statusBadge}</td>
        <td style="text-align:center;">${availControl}</td>
        <td style="text-align:right;">${actionBtn}</td>
      </tr>
    `;
  }).join("");
}

async function handleToggleFacultyAvailability(facultyId, facultyName, currentAvail) {
  try {
    const res = await fetch(`${API_BASE}/api/faculty/${facultyId}/toggle-availability`, {
      method: "POST",
      headers: { "Authorization": `Bearer ${state.token}` }
    });
    const data = await res.json();
    if (res.ok) {
      showToast("Availability Updated", `Faculty '${facultyName}' is now marked as ${data.is_available ? 'Available' : 'Unavailable'}.`, "success");
      await loadFacultyRoster();
    } else {
      showToast("Action Failed", data.detail || "Could not toggle availability.", "error");
    }
  } catch (err) {
    showToast("Network Error", "Could not connect to faculty server.", "error");
  }
}

async function openEditFacultyModal(facultyId, viewOnly = false) {
  try {
    const res = await fetch(`${API_BASE}/api/faculty/${facultyId}`, {
      headers: { "Authorization": `Bearer ${state.token}` }
    });
    if (!res.ok) {
      const err = await res.json();
      showToast("Access Denied", err.detail || "Could not load faculty profile.", "error");
      return;
    }
    const f = await res.json();

    document.getElementById("ef-id").value = f.id;
    document.getElementById("ef-name").value = f.name || "";
    document.getElementById("ef-designation").value = f.designation || "";
    document.getElementById("ef-dept").value = f.department || "MCA";
    document.getElementById("ef-institution").value = f.institution || "SJB Institute of Technology";
    document.getElementById("ef-qualification").value = f.qualification || "";
    document.getElementById("ef-experience").value = (f.experience_years !== null && f.experience_years !== undefined) ? f.experience_years : "";
    document.getElementById("ef-email").value = f.email || "";
    document.getElementById("ef-mobile").value = f.mobile || "";
    document.getElementById("ef-expertise").value = f.expertise_text || "";
    document.getElementById("ef-availability").value = (f.is_available !== false).toString();

    const isAdmin = state.currentUser && state.currentUser.role === "Admin" && !viewOnly;
    const title = document.getElementById("modal-edit-faculty-title");
    const saveBtn = document.getElementById("btn-submit-edit-faculty");

    if (title) title.textContent = isAdmin ? "Edit Faculty Profile" : "Faculty Profile Details (View-Only)";
    if (saveBtn) saveBtn.style.display = isAdmin ? "inline-block" : "none";

    // Toggle readonly fields for non-admin
    const form = document.getElementById("form-edit-faculty");
    if (form) {
      const inputs = form.querySelectorAll("input, select, textarea");
      inputs.forEach(inp => {
        if (inp.id !== "ef-id") {
          inp.disabled = !isAdmin;
        }
      });
    }

    document.getElementById("modal-edit-faculty").style.display = "flex";
  } catch (err) {
    showToast("Network Error", "Could not open faculty profile.", "error");
  }
}

function closeEditFacultyModal() {
  document.getElementById("modal-edit-faculty").style.display = "none";
}

async function handleUpdateFaculty(e) {
  e.preventDefault();
  const fid = document.getElementById("ef-id").value;
  const name = document.getElementById("ef-name").value.trim();
  const designation = document.getElementById("ef-designation").value.trim();
  const department = document.getElementById("ef-dept").value;
  const institution = document.getElementById("ef-institution").value.trim();
  const qualification = document.getElementById("ef-qualification").value.trim() || null;
  const expRaw = document.getElementById("ef-experience").value.trim();
  const experience_years = expRaw !== "" ? parseFloat(expRaw) : null;
  const emailRaw = document.getElementById("ef-email").value.trim();
  const email = emailRaw !== "" ? emailRaw : null;
  const mobileRaw = document.getElementById("ef-mobile").value.trim();
  const mobile = mobileRaw !== "" ? mobileRaw : null;
  const expertise_text = document.getElementById("ef-expertise").value.trim() || null;
  const is_available = document.getElementById("ef-availability").value === "true";

  const btn = document.getElementById("btn-submit-edit-faculty");
  btn.disabled = true;
  btn.textContent = "Saving...";

  try {
    const res = await fetch(`${API_BASE}/api/faculty/${fid}`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${state.token}`
      },
      body: JSON.stringify({
        name,
        designation,
        department,
        institution,
        qualification,
        experience_years,
        email,
        mobile,
        expertise_text,
        is_available
      })
    });

    const data = await res.json();
    if (res.ok) {
      showToast("Profile Updated", `Profile for '${name}' saved. Statutory eligibility: ${data.eligibility_status}`, "success");
      closeEditFacultyModal();
      await loadFacultyRoster();
      if (state.currentUser && state.currentUser.role === "Admin") {
        await loadDashboardStats();
      }
    } else {
      showToast("Update Failed", data.detail || "Could not update faculty profile.", "error");
    }
  } catch (err) {
    showToast("Network Error", "Failed to connect to faculty server.", "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "Save Profile Changes";
  }
}


// =============================================================================
// MODULE 8: FACULTY-SUBJECT EXPERTISE MAPPINGS CONTROLLER
// =============================================================================

async function loadMappingsList() {
  const tbody = document.getElementById("mappings-table-body");
  if (!tbody) return;
  tbody.innerHTML = `<tr><td colspan="10" style="text-align:center; padding: 24px; color:var(--text-muted);">Loading expertise mappings...</td></tr>`;

  try {
    const params = new URLSearchParams();
    const dept = document.getElementById("map-filter-dept")?.value;
    const status = document.getElementById("map-filter-status")?.value;
    const type = document.getElementById("map-filter-type")?.value;
    const search = document.getElementById("map-filter-search")?.value;

    if (dept) params.append("department", dept);
    if (status) params.append("status", status);
    if (type) params.append("mapping_type", type);
    if (search && search.trim()) params.append("search", search.trim());

    const res = await fetch(`${API_BASE}/api/mappings?${params.toString()}`, {
      headers: { "Authorization": `Bearer ${state.token}` }
    });

    if (!res.ok) {
      const err = await res.json();
      showToast("Access Denied", err.detail || "Could not fetch expertise mappings.", "error");
      tbody.innerHTML = `<tr><td colspan="10" style="text-align:center; padding: 24px; color:var(--crimson);">${err.detail || "Error loading mappings"}</td></tr>`;
      return;
    }

    const data = await res.json();
    state.allMappings = data.mappings || [];
    state.selectedMappingIds.clear();
    updateBulkConfirmButton();

    // Update stats counters
    const total = state.allMappings.length;
    const suggested = state.allMappings.filter(m => m.status === "SUGGESTED").length;
    const confirmed = state.allMappings.filter(m => m.status === "CONFIRMED").length;
    const rejected = state.allMappings.filter(m => m.status === "REJECTED").length;

    const elTotal = document.getElementById("stat-mappings-total");
    const elSugg = document.getElementById("stat-mappings-suggested");
    const elConf = document.getElementById("stat-mappings-confirmed");
    const elRej = document.getElementById("stat-mappings-rejected");
    if (elTotal) elTotal.textContent = total;
    if (elSugg) elSugg.textContent = suggested;
    if (elConf) elConf.textContent = confirmed;
    if (elRej) elRej.textContent = rejected;

    renderMappingsTable(state.allMappings);
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="10" style="text-align:center; padding: 24px; color:var(--crimson);">Network error loading expertise mappings.</td></tr>`;
    showToast("Network Error", "Failed to connect to mappings service.", "error");
  }
}

function renderMappingsTable(mappings) {
  const tbody = document.getElementById("mappings-table-body");
  if (!tbody) return;

  if (!mappings || mappings.length === 0) {
    tbody.innerHTML = `<tr><td colspan="10" style="text-align:center; padding: 36px; color:var(--text-muted);">No faculty-subject expertise mappings found matching criteria.</td></tr>`;
    return;
  }

  const isAdmin = state.currentUser && state.currentUser.role === "Admin";

  tbody.innerHTML = mappings.map(m => {
    const isChecked = state.selectedMappingIds.has(m.id);

    // Badges
    let statusBadge = `<span class="badge" style="background:#FEF3C7; color:#92400E; border:1px solid #FDE68A;">SUGGESTED</span>`;
    if (m.status === "CONFIRMED") {
      statusBadge = `<span class="badge badge-success">CONFIRMED</span>`;
    } else if (m.status === "REJECTED") {
      statusBadge = `<span class="badge" style="background:#FEE2E2; color:#991B1B; border:1px solid #FECACA;">REJECTED</span>`;
    }

    let typeBadge = `<span class="badge" style="background:#EDE9FE; color:#5B21B6; border:1px solid #DDD6FE;">SPECIALIZATION</span>`;
    if (m.mapping_type === "EXACT_EXPERIENCE") {
      typeBadge = `<span class="badge" style="background:#DBEAFE; color:#1E40AF; border:1px solid #BFDBFE;">EXACT_EXPERIENCE</span>`;
    } else if (m.mapping_type === "RELATED") {
      typeBadge = `<span class="badge" style="background:#CCFBF1; color:#0F766E; border:1px solid #99F6E4;">RELATED</span>`;
    }

    const facTypeBadge = m.faculty_type === "internal"
      ? `<span class="badge badge-role-faculty" style="font-size:10px; padding:2px 6px;">Internal</span>`
      : `<span class="badge" style="font-size:10px; padding:2px 6px; background:#E0F2FE; color:#0369A1; border:1px solid #BAE6FD;">External</span>`;

    const bulkCell = isAdmin
      ? `<td style="text-align:center;"><input type="checkbox" ${isChecked ? "checked" : ""} onchange="toggleSelectMapping(${m.id}, this.checked)" /></td>`
      : "";

    let actionButtons = "";
    if (isAdmin) {
      if (m.status === "SUGGESTED") {
        actionButtons = `
          <button class="btn btn-secondary" onclick="handleConfirmMapping(${m.id})" style="padding:4px 8px; font-size:11px; margin-right:4px;" title="Confirm mapping">✅ Confirm</button>
          <button class="btn btn-secondary" onclick="handleRejectMapping(${m.id})" style="padding:4px 8px; font-size:11px; margin-right:4px;" title="Reject mapping">❌ Reject</button>
          <button class="btn btn-secondary" onclick="handleDeleteMapping(${m.id})" style="padding:4px 8px; font-size:11px; color:var(--crimson);" title="Delete mapping">🗑️</button>
        `;
      } else if (m.status === "CONFIRMED") {
        actionButtons = `
          <button class="btn btn-secondary" onclick="handleRejectMapping(${m.id})" style="padding:4px 8px; font-size:11px; margin-right:4px;" title="Reject mapping">❌ Reject</button>
          <button class="btn btn-secondary" onclick="handleDeleteMapping(${m.id})" style="padding:4px 8px; font-size:11px; color:var(--crimson);" title="Delete mapping">🗑️</button>
        `;
      } else {
        actionButtons = `
          <button class="btn btn-secondary" onclick="handleConfirmMapping(${m.id})" style="padding:4px 8px; font-size:11px; margin-right:4px;" title="Confirm mapping">✅ Confirm</button>
          <button class="btn btn-secondary" onclick="handleDeleteMapping(${m.id})" style="padding:4px 8px; font-size:11px; color:var(--crimson);" title="Delete mapping">🗑️</button>
        `;
      }
    }

    const actionCell = isAdmin ? `<td style="text-align:right; white-space:nowrap;">${actionButtons}</td>` : "";

    return `
      <tr>
        ${bulkCell}
        <td>
          <strong style="color:var(--primary-navy);">${escapeHtml(m.faculty_name)}</strong> ${facTypeBadge}
        </td>
        <td>
          <div style="font-size:12px; font-weight:600; color:var(--text-dark);">${escapeHtml(m.faculty_dept || m.institution || "SJBIT")}</div>
          <div style="font-size:11px; color:var(--text-muted);">${escapeHtml(m.institution || "SJBIT")}</div>
        </td>
        <td>
          <div style="font-weight:600; color:var(--primary-navy);">${escapeHtml(m.subject_title)}</div>
          <div style="font-size:11px; color:var(--text-muted);"><code>${escapeHtml(m.course_code)}</code> • ${escapeHtml(m.subject_dept || "")} Sem ${escapeHtml(String(m.semester || ""))}</div>
        </td>
        <td>${typeBadge}</td>
        <td style="text-align:center;">
          <span style="font-weight:600; font-size:12px;">${m.times_handled || 0}</span>
          <span style="font-size:11px; color:var(--text-muted);"> times</span>
        </td>
        <td>${statusBadge}</td>
        <td style="font-size:11.5px; color:var(--text-dark); max-width:240px; line-height:1.4;">
          ${escapeHtml(m.suggestion_reason || "Direct curriculum domain alignment.")}
        </td>
        <td style="font-size:11px; color:var(--text-muted);">
          ${m.confirmed_by ? `<strong>${escapeHtml(m.confirmed_by)}</strong>` : "—"}
        </td>
        ${actionCell}
      </tr>
    `;
  }).join("");
}

function filterMappingsList() {
  loadMappingsList();
}

function resetMappingFilters() {
  const searchInput = document.getElementById("map-filter-search");
  const deptSelect = document.getElementById("map-filter-dept");
  const statusSelect = document.getElementById("map-filter-status");
  const typeSelect = document.getElementById("map-filter-type");

  if (searchInput) searchInput.value = "";
  if (deptSelect && (!state.currentUser || state.currentUser.role === "Admin")) deptSelect.value = "";
  if (statusSelect) statusSelect.value = "";
  if (typeSelect) typeSelect.value = "";

  loadMappingsList();
}

function toggleSelectAllMappings(checked) {
  state.selectedMappingIds.clear();
  if (checked && state.allMappings) {
    state.allMappings.forEach(m => state.selectedMappingIds.add(m.id));
  }
  updateBulkConfirmButton();
  renderMappingsTable(state.allMappings);
}

function toggleSelectMapping(mappingId, checked) {
  if (checked) {
    state.selectedMappingIds.add(mappingId);
  } else {
    state.selectedMappingIds.delete(mappingId);
  }
  updateBulkConfirmButton();
}

function updateBulkConfirmButton() {
  const countEl = document.getElementById("bulk-confirm-count");
  if (countEl) countEl.textContent = state.selectedMappingIds.size;
}

async function handleGenerateMappingSuggestions() {
  if (!confirm("Run automated suggestion generator? This analyzes verified course history and expertise keywords across all faculty and curriculum subjects to propose new mappings in SUGGESTED status.")) {
    return;
  }

  const btn = document.getElementById("btn-generate-mapping-suggestions");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Analyzing...";
  }

  try {
    const res = await fetch(`${API_BASE}/api/mappings/generate-suggestions`, {
      method: "POST",
      headers: { "Authorization": `Bearer ${state.token}` }
    });

    const data = await res.json();
    if (res.ok) {
      showToast("Suggestions Generated", data.message, "success");
      await loadMappingsList();
    } else {
      showToast("Generation Failed", data.detail || "Could not generate suggestions.", "error");
    }
  } catch (err) {
    showToast("Network Error", "Failed to contact mappings server.", "error");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "⚡ Generate Suggestions";
    }
  }
}

async function handleConfirmMapping(mappingId) {
  try {
    const res = await fetch(`${API_BASE}/api/mappings/${mappingId}/confirm`, {
      method: "POST",
      headers: { "Authorization": `Bearer ${state.token}` }
    });

    const data = await res.json();
    if (res.ok) {
      showToast("Mapping Confirmed", `Expertise mapping #${mappingId} confirmed and active for paper-setter matching.`, "success");
      await loadMappingsList();
    } else {
      showToast("Confirmation Failed", data.detail || "Could not confirm mapping.", "error");
    }
  } catch (err) {
    showToast("Network Error", "Failed to update mapping status.", "error");
  }
}

async function handleRejectMapping(mappingId) {
  try {
    const res = await fetch(`${API_BASE}/api/mappings/${mappingId}/reject`, {
      method: "POST",
      headers: { "Authorization": `Bearer ${state.token}` }
    });

    const data = await res.json();
    if (res.ok) {
      showToast("Mapping Rejected", `Expertise mapping #${mappingId} rejected and excluded from paper-setter matching.`, "info");
      await loadMappingsList();
    } else {
      showToast("Rejection Failed", data.detail || "Could not reject mapping.", "error");
    }
  } catch (err) {
    showToast("Network Error", "Failed to update mapping status.", "error");
  }
}

async function handleBulkConfirmMappings() {
  const count = state.selectedMappingIds.size;
  if (count === 0) {
    showToast("Selection Required", "Please select at least one expertise mapping using the checkboxes to bulk confirm.", "warning");
    return;
  }

  if (!confirm(`Are you sure you want to bulk-confirm all ${count} selected expertise mapping(s)? They will immediately become eligible for question-paper-setter recommendations.`)) {
    return;
  }

  const btn = document.getElementById("btn-bulk-confirm-mappings");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Confirming...";
  }

  try {
    const res = await fetch(`${API_BASE}/api/mappings/bulk-confirm`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${state.token}`
      },
      body: JSON.stringify({ mapping_ids: Array.from(state.selectedMappingIds) })
    });

    const data = await res.json();
    if (res.ok) {
      showToast("Bulk Confirmation Complete", data.message, "success");
      state.selectedMappingIds.clear();
      updateBulkConfirmButton();
      await loadMappingsList();
    } else {
      showToast("Bulk Confirm Failed", data.detail || "Could not bulk-confirm mappings.", "error");
    }
  } catch (err) {
    showToast("Network Error", "Failed to execute bulk confirmation.", "error");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = `✅ Bulk Confirm (<span id="bulk-confirm-count">${state.selectedMappingIds.size}</span>)`;
    }
  }
}

async function handleDeleteMapping(mappingId) {
  if (!confirm(`Are you sure you want to delete expertise mapping #${mappingId}?`)) {
    return;
  }

  try {
    const res = await fetch(`${API_BASE}/api/mappings/${mappingId}`, {
      method: "DELETE",
      headers: { "Authorization": `Bearer ${state.token}` }
    });

    const data = await res.json();
    if (res.ok) {
      showToast("Mapping Deleted", data.message || `Mapping #${mappingId} deleted.`, "info");
      await loadMappingsList();
    } else {
      showToast("Delete Failed", data.detail || "Could not delete mapping.", "error");
    }
  } catch (err) {
    showToast("Network Error", "Failed to delete mapping.", "error");
  }
}

async function openCreateMappingModal() {
  const modal = document.getElementById("modal-create-mapping");
  if (!modal) return;

  const facSelect = document.getElementById("cm-faculty-id");
  const subjSelect = document.getElementById("cm-subject-id");

  facSelect.innerHTML = `<option value="">Loading faculty...</option>`;
  subjSelect.innerHTML = `<option value="">Loading subjects...</option>`;
  modal.style.display = "flex";

  try {
    const [facRes, subjRes] = await Promise.all([
      fetch(`${API_BASE}/api/faculty/all`, { headers: { "Authorization": `Bearer ${state.token}` } }),
      fetch(`${API_BASE}/api/syllabus/all`, { headers: { "Authorization": `Bearer ${state.token}` } })
    ]);

    if (facRes.ok && subjRes.ok) {
      const facData = await facRes.json();
      const subjData = await subjRes.json();

      facSelect.innerHTML = `<option value="">-- Choose Faculty Member --</option>` +
        (facData.faculty || []).map(f => `<option value="${f.id}">${escapeHtml(f.name)} (${escapeHtml(f.department || f.institution || "")})</option>`).join("");

      subjSelect.innerHTML = `<option value="">-- Choose Subject Course --</option>` +
        (subjData.subjects || []).map(s => `<option value="${s.id}">[${escapeHtml(s.course_code)}] ${escapeHtml(s.title)} (${escapeHtml(s.department)} Sem ${escapeHtml(String(s.semester))})</option>`).join("");
    }
  } catch (err) {
    showToast("Error", "Could not load faculty or subjects for mapping creation.", "error");
  }
}

function closeCreateMappingModal() {
  const modal = document.getElementById("modal-create-mapping");
  if (modal) modal.style.display = "none";
  const form = document.getElementById("form-create-mapping");
  if (form) form.reset();
}

async function handleCreateMappingSubmit(event) {
  event.preventDefault();
  const facId = parseInt(document.getElementById("cm-faculty-id").value, 10);
  const subjId = parseInt(document.getElementById("cm-subject-id").value, 10);
  const mappingType = document.getElementById("cm-mapping-type").value;
  const timesHandled = parseInt(document.getElementById("cm-times-handled").value || "0", 10);
  const status = document.getElementById("cm-status").value;
  const reason = document.getElementById("cm-reason").value.trim();

  if (!facId || !subjId) {
    showToast("Validation Error", "Please select both a faculty member and a subject course.", "warning");
    return;
  }

  const btn = document.getElementById("btn-submit-mapping");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Creating...";
  }

  try {
    const res = await fetch(`${API_BASE}/api/mappings`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${state.token}`
      },
      body: JSON.stringify({
        faculty_id: facId,
        subject_id: subjId,
        mapping_type: mappingType,
        times_handled: timesHandled,
        status: status,
        suggestion_reason: reason || null
      })
    });

    const data = await res.json();
    if (res.ok) {
      showToast("Mapping Created", `Mapping created successfully for ${data.faculty_name} → ${data.subject_title} (${data.mapping_type}).`, "success");
      closeCreateMappingModal();
      await loadMappingsList();
    } else {
      // Toast notification for duplicate mapping error or validation
      showToast("Creation Failed", data.detail || "Could not create expertise mapping.", "error");
    }
  } catch (err) {
    showToast("Network Error", "Failed to connect to mappings service.", "error");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "Create Mapping";
    }
  }
}


// ─── Module 15: Acceptance Testing & Security Suite Engine ────────────────────
let acceptanceSuitesData = [];

async function loadAcceptanceTestSuites() {
  const tbody = document.getElementById("tbody-acceptance-suites");
  if (!tbody) return;

  try {
    const res = await fetch(`${API_BASE}/api/acceptance/test-suites`, {
      headers: { "Authorization": `Bearer ${state.token}` }
    });
    if (!res.ok) {
      tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; color:#DC2626; padding:20px;">Failed to load acceptance test catalog (${res.status}). Admin authorization required.</td></tr>`;
      return;
    }

    const data = await res.json();
    acceptanceSuitesData = data.test_suites || [];
    document.getElementById("accept-total-count").textContent = acceptanceSuitesData.length;

    renderAcceptanceSuitesTable();
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; color:#DC2626; padding:20px;">Network error loading acceptance test suites.</td></tr>`;
  }
}

function renderAcceptanceSuitesTable() {
  const tbody = document.getElementById("tbody-acceptance-suites");
  if (!tbody) return;

  if (acceptanceSuitesData.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:20px; color:var(--text-muted);">No acceptance test suites registered.</td></tr>`;
    return;
  }

  tbody.innerHTML = acceptanceSuitesData.map(suite => {
    const statusBadge = suite.lastStatus === "PASS"
      ? `<span class="badge badge-success" style="font-weight:700;">PASS</span>`
      : suite.lastStatus === "FAIL"
      ? `<span class="badge badge-danger" style="font-weight:700;">FAIL</span>`
      : `<span class="badge badge-neutral" style="color:var(--text-muted);">Pending</span>`;

    const durationText = suite.lastDuration !== undefined ? `${suite.lastDuration}s` : "--";

    return `
      <tr id="row-suite-${suite.id}">
        <td><strong style="color:var(--primary); font-size:12px;">${escapeHtml(suite.module)}</strong></td>
        <td>
          <div style="font-weight:600; font-size:13px; color:var(--text-main);">${escapeHtml(suite.title)}</div>
          <div style="font-size:11.5px; color:var(--text-muted); margin-top:2px;">${escapeHtml(suite.description)}</div>
        </td>
        <td><code style="font-size:11.5px; background:var(--bg-card-alt); padding:2px 6px; border-radius:4px;">${escapeHtml(suite.file_name)}</code></td>
        <td style="text-align:center;" id="status-suite-${suite.id}">${statusBadge}</td>
        <td style="text-align:center; font-size:12px; font-family:monospace;" id="duration-suite-${suite.id}">${durationText}</td>
        <td style="text-align:right;">
          <div style="display:flex; justify-content:flex-end; gap:6px;">
            <button class="btn btn-secondary btn-sm" id="btn-run-${suite.id}" onclick="runSingleAcceptanceTest('${suite.file_name}', '${suite.id}')" style="font-size:11.5px; padding:3px 8px;">
              ▶ Run
            </button>
            <button class="btn btn-secondary btn-sm" id="btn-log-${suite.id}" onclick="viewSuiteLog('${suite.id}')" style="font-size:11.5px; padding:3px 6px; display:${suite.lastOutput ? 'inline-flex' : 'none'};" title="View Console Output">
              📄
            </button>
          </div>
        </td>
      </tr>
    `;
  }).join("");
}

async function runSingleAcceptanceTest(fileName, suiteId) {
  const btn = document.getElementById(`btn-run-${suiteId}`);
  const statusEl = document.getElementById(`status-suite-${suiteId}`);
  const durEl = document.getElementById(`duration-suite-${suiteId}`);

  if (btn) {
    btn.disabled = true;
    btn.textContent = "⏳ Running...";
  }
  if (statusEl) {
    statusEl.innerHTML = `<span class="badge badge-amber">Running...</span>`;
  }

  try {
    const res = await fetch(`${API_BASE}/api/acceptance/run-test`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${state.token}`
      },
      body: JSON.stringify({ test_file: fileName })
    });

    const data = await res.json();
    if (res.ok && data.result) {
      const r = data.result;
      const targetSuite = acceptanceSuitesData.find(s => s.id === suiteId);
      if (targetSuite) {
        targetSuite.lastStatus = r.status;
        targetSuite.lastDuration = r.duration_seconds;
        targetSuite.lastOutput = (r.stdout || "") + "\n" + (r.stderr || "");
      }

      if (r.status === "PASS") {
        showToast("Suite Passed", `${fileName} executed successfully (${r.duration_seconds}s).`, "success");
      } else {
        showToast("Suite Failed", `${fileName} failed with status: ${r.status}.`, "error");
      }

      renderAcceptanceSuitesTable();
      updateAcceptanceGlobalCounters();
      viewSuiteLog(suiteId);
    } else {
      showToast("Execution Error", data.detail || "Could not execute test suite.", "error");
      if (statusEl) statusEl.innerHTML = `<span class="badge badge-danger">Error</span>`;
    }
  } catch (err) {
    showToast("Network Error", "Failed to communicate with test runner engine.", "error");
    if (statusEl) statusEl.innerHTML = `<span class="badge badge-danger">Failed</span>`;
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "▶ Run";
    }
  }
}

async function runAllAcceptanceTests() {
  const mainBtn = document.getElementById("btn-run-all-tests");
  if (mainBtn) {
    mainBtn.disabled = true;
    mainBtn.textContent = "⏳ Running All Acceptance Suites...";
  }

  showToast("Acceptance Run Started", "Executing all test suites sequentially on isolated temporary databases.", "info");

  for (const suite of acceptanceSuitesData) {
    await runSingleAcceptanceTest(suite.file_name, suite.id);
  }

  if (mainBtn) {
    mainBtn.disabled = false;
    mainBtn.textContent = "▶ Run All Acceptance Suites";
  }

  showToast("Acceptance Run Completed", "All acceptance test suites have completed execution.", "success");
}

function updateAcceptanceGlobalCounters() {
  let passed = 0;
  let failed = 0;
  for (const s of acceptanceSuitesData) {
    if (s.lastStatus === "PASS") passed++;
    if (s.lastStatus === "FAIL" || s.lastStatus === "TIMEOUT" || s.lastStatus === "ERROR") failed++;
  }
  document.getElementById("accept-pass-count").textContent = passed;
  document.getElementById("accept-fail-count").textContent = failed;
  const statusEl = document.getElementById("accept-global-status");
  if (failed > 0) {
    statusEl.textContent = `${failed} Suite(s) Failed`;
    statusEl.style.color = "#DC2626";
  } else if (passed > 0 && passed === acceptanceSuitesData.length) {
    statusEl.textContent = "All Suites Passed (100%)";
    statusEl.style.color = "#16A34A";
  } else if (passed > 0) {
    statusEl.textContent = `In Progress (${passed}/${acceptanceSuitesData.length} Passed)`;
    statusEl.style.color = "#2563EB";
  }
}

function viewSuiteLog(suiteId) {
  const targetSuite = acceptanceSuitesData.find(s => s.id === suiteId);
  if (!targetSuite || !targetSuite.lastOutput) return;

  const card = document.getElementById("acceptance-console-card");
  const title = document.getElementById("console-title");
  const pre = document.getElementById("acceptance-console-output");

  title.textContent = `🖥️ Output Log: ${targetSuite.file_name} [${targetSuite.lastStatus}] (${targetSuite.lastDuration}s)`;
  pre.textContent = targetSuite.lastOutput.trim() || "(No console output produced)";
  card.style.display = "block";
  card.scrollIntoView({ behavior: "smooth" });
}

