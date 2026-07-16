// global.js

const GLOBAL_API_URL = window.location.origin.includes(":5500")
  ? "http://127.0.0.1:8000"
  : window.location.origin;

// =========================================================
// AUTHENTICATION GATEKEEPER
// =========================================================
if (!window.location.pathname.includes("login.html")) {
  const token = localStorage.getItem("access_token");
  if (!token) {
    window.location.href = "login.html";
  }
}

// =========================================================
// SMART API FETCH (Automatically attaches the JWT Token)
// =========================================================
window.apiFetch = async function (url, options = {}) {
  const token = localStorage.getItem("access_token");

  options.headers = options.headers || {};
  options.headers["Content-Type"] =
    options.headers["Content-Type"] || "application/json";

  if (token) {
    const trimmedToken = token.trim();
    options.headers["Authorization"] = `Bearer ${trimmedToken}`;
  } else {
    console.warn("apiFetch: No access token found in localStorage.");
  }

  try {
    const response = await fetch(url, options);
    if (response.status === 401) {
      console.warn("apiFetch: Unauthorized response from", url);
      alert("Session expired or unauthorized. Please log in again.");
      localStorage.removeItem("access_token");
      window.location.href = "login.html";
      return null;
    }
    return response;
  } catch (error) {
    console.error("Network Error:", error);
    throw error;
  }
};
// =========================================================
// DEPARTMENT SELECTOR LOGIC
// =========================================================
document.addEventListener("DOMContentLoaded", async () => {
  const globalSelect = document.getElementById("globalDeptSelect");
  if (!globalSelect) return;

  try {
    // NOTE: We now use apiFetch instead of standard fetch!
    const res = await apiFetch(`${GLOBAL_API_URL}/get-departments/`);
    if (!res) return; // Stop if kicked out

    const data = await res.json();
    globalSelect.innerHTML = "";
    data.data.forEach((dept) => {
      globalSelect.innerHTML += `<option value="${dept.id}">${dept.name}</option>`;
    });

    const savedDept = localStorage.getItem("activeDeptId");
    if (savedDept && data.data.some((d) => d.id == savedDept)) {
      globalSelect.value = savedDept;
    } else if (data.data.length > 0) {
      globalSelect.value = data.data[0].id;
      localStorage.setItem("activeDeptId", data.data[0].id);
    }

    window.dispatchEvent(
      new CustomEvent("departmentReady", { detail: globalSelect.value }),
    );

    globalSelect.addEventListener("change", (e) => {
      const newId = e.target.value;
      localStorage.setItem("activeDeptId", newId);
      window.dispatchEvent(
        new CustomEvent("departmentReady", { detail: newId }),
      );
    });
  } catch (err) {
    console.error("Global Department Fetch Failed:", err);
    globalSelect.innerHTML = `<option value="" disabled>Server Offline</option>`;
  }
});

// =========================================================
// SMART ALERT & CONFIRM SYSTEM
// =========================================================

document.addEventListener("DOMContentLoaded", () => {
  // 1. Inject the Custom Confirm Modal HTML
  const modalHtml = `
    <div id="smartConfirmModal" class="fixed inset-0 z-[100] bg-primary/40 backdrop-blur-sm hidden flex items-center justify-center opacity-0 transition-opacity duration-200">
        <div id="smartConfirmContent" class="bg-white hand-drawn-border-sm offset-shadow w-[90%] max-w-md p-6 transform scale-95 transition-transform duration-200">
            <div class="flex items-start gap-4">
                <div id="smartConfirmIcon" class="p-3 rounded-full bg-error-container text-error border-2 border-error shrink-0 mt-1">
                    <span class="material-symbols-outlined text-2xl" id="smartConfirmIconText">delete_forever</span>
                </div>
                <div>
                    <h3 id="smartConfirmTitle" class="font-headline-md text-xl text-primary mb-2 leading-tight">Confirm Action</h3>
                    <p id="smartConfirmMessage" class="text-body-md text-on-surface-variant text-sm mb-6 leading-snug">Are you sure?</p>
                </div>
            </div>
            <div class="flex justify-end gap-3">
                <button id="smartConfirmCancel" class="px-5 py-2 font-label-md text-on-surface-variant hover:bg-surface-container-high transition-colors rounded-lg border-2 border-transparent">Cancel</button>
                <button id="smartConfirmOk" class="px-5 py-2 font-label-md text-white border-2 border-error bg-error shadow-[3px_3px_0px_0px_#ba1a1a] active:translate-y-1 active:translate-x-1 active:shadow-none transition-all rounded-lg">Confirm</button>
            </div>
        </div>
    </div>`;

  // 2. Inject the Toast Notification Container HTML
  const toastHtml = `<div id="smartToastContainer" class="fixed top-24 right-4 md:right-8 z-[110] flex flex-col gap-3 pointer-events-none"></div>`;

  document.body.insertAdjacentHTML("beforeend", modalHtml);
  document.body.insertAdjacentHTML("beforeend", toastHtml);
});

// =========================================================
// THE CONFIRMATION PROMISE (Replaces 'confirm()')
// =========================================================
window.SmartConfirm = function (title, message, type = "danger") {
  return new Promise((resolve) => {
    const modal = document.getElementById("smartConfirmModal");
    const content = document.getElementById("smartConfirmContent");
    const titleEl = document.getElementById("smartConfirmTitle");
    const msgEl = document.getElementById("smartConfirmMessage");
    const btnOk = document.getElementById("smartConfirmOk");
    const btnCancel = document.getElementById("smartConfirmCancel");
    const iconWrapper = document.getElementById("smartConfirmIcon");
    const iconText = document.getElementById("smartConfirmIconText");

    titleEl.innerText = title;
    msgEl.innerText = message;

    // Theme based on action type
    if (type === "danger") {
      iconWrapper.className =
        "p-3 rounded-full bg-error-container text-error border-2 border-error shrink-0 mt-1";
      iconText.innerText = "delete_forever";
      btnOk.className =
        "px-5 py-2 font-label-md bg-error text-white border-2 border-error shadow-[3px_3px_0px_0px_#ba1a1a] hover:bg-[#93000a] active:translate-y-1 active:translate-x-1 active:shadow-none transition-all rounded-lg";
      btnOk.innerText = "Delete Permanently";
    } else if (type === "warning") {
      iconWrapper.className =
        "p-3 rounded-full bg-[#FFE194] text-[#b38000] border-2 border-[#b38000] shrink-0 mt-1";
      iconText.innerText = "warning";
      btnOk.className =
        "px-5 py-2 font-label-md bg-secondary text-white border-2 border-primary shadow-[3px_3px_0px_0px_#181919] active:translate-y-1 active:translate-x-1 active:shadow-none transition-all rounded-lg";
      btnOk.innerText = "Proceed";
    }

    modal.classList.remove("hidden");
    setTimeout(() => {
      modal.classList.remove("opacity-0");
      content.classList.remove("scale-95");
    }, 10);

    const cleanup = (result) => {
      modal.classList.add("opacity-0");
      content.classList.add("scale-95");
      setTimeout(() => modal.classList.add("hidden"), 200);
      btnOk.onclick = null;
      btnCancel.onclick = null;
      resolve(result);
    };

    btnOk.onclick = () => cleanup(true);
    btnCancel.onclick = () => cleanup(false);
  });
};

// =========================================================
// THE TOAST NOTIFICATION (Replaces 'alert()')
// =========================================================
window.SmartAlert = function (type, title, message) {
  const container = document.getElementById("smartToastContainer");
  const toast = document.createElement("div");

  let bgClass = "bg-white",
    icon = "info",
    iconColor = "text-primary",
    border = "border-primary";

  if (type === "error") {
    bgClass = "bg-error-container";
    icon = "error";
    iconColor = "text-error";
    border = "border-error";
  } else if (type === "success") {
    bgClass = "bg-tertiary-fixed";
    icon = "check_circle";
    iconColor = "text-[#3d4b33]";
    border = "border-primary";
  } else if (type === "warning") {
    bgClass = "bg-[#FFE194]";
    icon = "warning";
    iconColor = "text-[#b38000]";
    border = "border-[#b38000]";
  } else if (type === "info") {
    bgClass = "bg-[#c8e7fb]";
    icon = "info";
    iconColor = "text-[#2d4a5a]";
    border = "border-[#2d4a5a]";
  }

  toast.className = `${bgClass} hand-drawn-border-sm p-4 flex items-start gap-3 border-2 ${border} shadow-[4px_4px_0px_0px_rgba(24,25,25,0.15)] transform translate-x-full transition-all duration-300 w-[350px] pointer-events-auto`;
  toast.innerHTML = `
        <span class="material-symbols-outlined ${iconColor} mt-0.5">${icon}</span>
        <div class="flex-1">
            <h4 class="font-label-md text-primary font-bold leading-tight">${title}</h4>
            <p class="text-body-md text-on-surface-variant text-sm mt-1 leading-snug break-words">${message}</p>
        </div>
        <button class="text-on-surface-variant hover:text-primary transition-colors" onclick="this.parentElement.remove()"><span class="material-symbols-outlined text-sm">close</span></button>
    `;

  container.appendChild(toast);

  // Animate sliding in
  requestAnimationFrame(() => toast.classList.remove("translate-x-full"));

  // Remove automatically after 5 seconds
  setTimeout(() => {
    toast.classList.add("translate-x-full", "opacity-0");
    setTimeout(() => toast.remove(), 300);
  }, 5000);
};

// =========================================================
// FASTAPI ERROR PARSER
// =========================================================
window.parseApiError = function (result) {
  if (!result) return "Unknown server error.";

  // 1. If it's a standard text error from our Python code
  if (typeof result.detail === "string") return result.detail;

  // 2. If it's a FastAPI Validation Error (Array of objects)
  if (Array.isArray(result.detail)) {
    return result.detail
      .map((err) => {
        // Capitalize the field name that caused the error
        const field = err.loc[err.loc.length - 1];
        return `${field.toUpperCase()}: ${err.msg}`;
      })
      .join(" | ");
  }

  // 3. Fallback
  return result.message || "An unexpected error occurred.";
};
