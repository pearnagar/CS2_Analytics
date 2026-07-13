const API_URL = "http://localhost:8000/api/stats";

async function loadStats() {
  const statusEl = document.getElementById("status");
  const bodyEl = document.getElementById("stats-body");

  try {
    const response = await fetch(API_URL);
    if (!response.ok) {
      throw new Error(`API returned ${response.status}`);
    }
    const rows = await response.json();

    bodyEl.innerHTML = "";
    rows.forEach((row) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${row.player_name}</td>
        <td>${row.matches_played}</td>
        <td>${row.kills}</td>
        <td>${row.deaths}</td>
        <td>${row.kd_ratio}</td>
      `;
      bodyEl.appendChild(tr);
    });

    statusEl.textContent = "";
    statusEl.classList.remove("error");
  } catch (err) {
    statusEl.textContent = `Failed to load stats: ${err.message}`;
    statusEl.classList.add("error");
  }
}

loadStats();
