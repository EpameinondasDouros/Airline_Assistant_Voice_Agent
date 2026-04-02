import { escapeHtml, titleCase } from "./utils.js";

export function renderOptionList(select, options, { includeBlank = false, blankLabel = "Select..." } = {}) {
  const values = includeBlank ? [{ value: "", label: blankLabel }, ...options] : options;
  select.innerHTML = values
    .map((option) => `<option value="${escapeHtml(option.value)}">${escapeHtml(option.label)}</option>`)
    .join("");
}

export function createStatusBadge(status, label = status) {
  return `<span class="badge ${escapeHtml(String(status))}">${escapeHtml(titleCase(label))}</span>`;
}

export function createEmptyState(message) {
  return `<div class="empty-panel">${escapeHtml(message)}</div>`;
}

export function createFeedback(message) {
  return `<div>${escapeHtml(message)}</div>`;
}

export function createJsonBlock(payload) {
  return `<pre class="json-block">${escapeHtml(JSON.stringify(payload, null, 2))}</pre>`;
}

export function createMetaGrid(items) {
  return `
    <div class="meta-grid">
      ${items
        .map(
          ([label, value]) => `
            <div class="meta-item">
              <span class="meta-item-label">${escapeHtml(String(label))}</span>
              <div>${escapeHtml(String(value))}</div>
            </div>
          `,
        )
        .join("")}
    </div>
  `;
}

export function createDetailList(items) {
  return `
    <div class="detail-list">
      ${items
        .map(
          ([label, value]) => `
            <div class="detail-list-item">
              <strong>${escapeHtml(String(label))}</strong>
              <span>${escapeHtml(String(value))}</span>
            </div>
          `,
        )
        .join("")}
    </div>
  `;
}

export function renderTable(container, { columns, rows, getRowId, isSelected, onRowClick }) {
  container.innerHTML = `
    <table class="data-table">
      <thead>
        <tr>
          ${columns.map((column) => `<th>${escapeHtml(column.label)}</th>`).join("")}
        </tr>
      </thead>
      <tbody>
        ${rows
          .map((row) => {
            const rowId = getRowId(row);
            return `
              <tr data-row-id="${escapeHtml(rowId)}" class="${isSelected(row) ? "is-selected" : ""}">
                ${columns.map((column) => `<td>${column.render(row)}</td>`).join("")}
              </tr>
            `;
          })
          .join("")}
      </tbody>
    </table>
  `;

  container.querySelectorAll("[data-row-id]").forEach((tr) => {
    tr.addEventListener("click", () => {
      const row = rows.find((item) => getRowId(item) === tr.dataset.rowId);
      if (row) {
        onRowClick(row);
      }
    });
  });
}
