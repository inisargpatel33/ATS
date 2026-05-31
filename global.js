// global.js
const GLOBAL_API_URL = "http://127.0.0.1:8000";

document.addEventListener("DOMContentLoaded", async () => {
  const globalSelect = document.getElementById("globalDeptSelect");
  if (!globalSelect) return; // Exit if header isn't on this page

  try {
    // 1. Fetch departments from database
    const res = await fetch(`${GLOBAL_API_URL}/get-departments/`);
    const data = await res.json();

    // 2. Populate the dropdown
    globalSelect.innerHTML = "";
    data.data.forEach((dept) => {
      globalSelect.innerHTML += `<option value="${dept.id}">${dept.name}</option>`;
    });

    // 3. Check browser memory (localStorage) for a previously selected department
    const savedDept = localStorage.getItem("activeDeptId");

    if (savedDept && data.data.some((d) => d.id == savedDept)) {
      // If we remember one, set it
      globalSelect.value = savedDept;
    } else if (data.data.length > 0) {
      // Otherwise, default to the very first department
      globalSelect.value = data.data[0].id;
      localStorage.setItem("activeDeptId", data.data[0].id);
    }

    // 4. Alert the current page what the active department is
    window.dispatchEvent(
      new CustomEvent("departmentReady", { detail: globalSelect.value }),
    );

    // 5. When the user clicks the dropdown and changes it
    globalSelect.addEventListener("change", (e) => {
      const newId = e.target.value;
      // Save to memory
      localStorage.setItem("activeDeptId", newId);
      // Alert the page to reload its data!
      window.dispatchEvent(
        new CustomEvent("departmentReady", { detail: newId }),
      );
    });
  } catch (err) {
    console.error("Global Department Fetch Failed:", err);
    globalSelect.innerHTML = `<option value="" disabled>Server Offline</option>`;
  }
});
