const API_URL = "/api/market";
const AUTO_REFRESH_MS = 30000;

const statusEl = document.getElementById("status");
const bodyEl = document.getElementById("stats-body");
const filterInput = document.getElementById("filter-input");
const refreshButton = document.getElementById("refresh-button");
const lastUpdatedEl = document.getElementById("last-updated");
const headerCells = document.querySelectorAll("#stats-table th[data-key]");

let allRows = [];
let sortKey = "item_name";
let sortDirection = 1;

function setStatus(text, kind) {
  statusEl.textContent = text;
  statusEl.classList.remove("error", "loading");
  if (kind) statusEl.classList.add(kind);
}

function formatTimestamp(date) {
  return `Last updated ${date.toLocaleTimeString()}`;
}

function formatPrice(value) {
  return `$${Number(value).toFixed(2)}`;
}

function formatScrapedAt(value) {
  return new Date(value).toLocaleString();
}

function compareRows(a, b) {
  const aVal = a[sortKey];
  const bVal = b[sortKey];
  if (typeof aVal === "number" && typeof bVal === "number") {
    return (aVal - bVal) * sortDirection;
  }
  return String(aVal).localeCompare(String(bVal)) * sortDirection;
}

function renderRows() {
  const filterText = filterInput.value.trim().toLowerCase();
  const filtered = filterText
    ? allRows.filter((row) => row.item_name.toLowerCase().includes(filterText))
    : allRows.slice();

  filtered.sort(compareRows);

  bodyEl.textContent = "";

  if (filtered.length === 0) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 4;
    td.className = "empty-state";
    td.textContent = allRows.length === 0 ? "No market data yet." : "No items match your filter.";
    tr.appendChild(td);
    bodyEl.appendChild(tr);
    return;
  }

  for (const row of filtered) {
    const tr = document.createElement("tr");

    const nameTd = document.createElement("td");
    nameTd.textContent = row.item_name;
    tr.appendChild(nameTd);

    const priceTd = document.createElement("td");
    priceTd.textContent = formatPrice(row.lowest_price);
    tr.appendChild(priceTd);

    const volumeTd = document.createElement("td");
    volumeTd.textContent = row.volume;
    tr.appendChild(volumeTd);

    const scrapedTd = document.createElement("td");
    scrapedTd.textContent = formatScrapedAt(row.scraped_at);
    tr.appendChild(scrapedTd);

    bodyEl.appendChild(tr);
  }
}

function updateSortIndicators() {
  headerCells.forEach((th) => {
    const arrow = th.querySelector(".sort-arrow");
    if (th.dataset.key === sortKey) {
      arrow.textContent = sortDirection === 1 ? "▲" : "▼";
    } else {
      arrow.textContent = "";
    }
  });
}

async function loadStats() {
  setStatus("Loading...", "loading");
  try {
    const response = await fetch(API_URL);
    if (!response.ok) {
      throw new Error(`API returned ${response.status}`);
    }
    allRows = await response.json();
    renderRows();
    setStatus("");
    lastUpdatedEl.textContent = formatTimestamp(new Date());
  } catch (err) {
    setStatus(`Failed to load market data: ${err.message}`, "error");
  }
}

headerCells.forEach((th) => {
  th.addEventListener("click", () => {
    const key = th.dataset.key;
    if (sortKey === key) {
      sortDirection *= -1;
    } else {
      sortKey = key;
      sortDirection = 1;
    }
    updateSortIndicators();
    renderRows();
  });
});

filterInput.addEventListener("input", renderRows);
refreshButton.addEventListener("click", loadStats);

updateSortIndicators();
loadStats();
setInterval(loadStats, AUTO_REFRESH_MS);
