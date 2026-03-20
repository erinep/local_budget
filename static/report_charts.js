(function () {
    const palette = [
        "#0f766e",
        "#f59e0b",
        "#b45309",
        "#0f4c5c",
        "#8a5a44",
        "#2f855a",
        "#c05621",
        "#5b6c5d",
        "#9c4221",
        "#3b6f9c",
    ];

    const currency = new Intl.NumberFormat("en-CA", {
        style: "currency",
        currency: "CAD",
        maximumFractionDigits: 0,
    });

    function renderTransactionsTable(transactions) {
        if (!transactions.length) {
            return '<p class="chart-empty">No transactions found for this selection.</p>';
        }

        const rows = transactions.map((transaction) => `
            <tr>
                <td>${escapeHtml(transaction["Transaction Date"])}</td>
                <td>${escapeHtml(transaction.Description)}</td>
                <td>${escapeHtml(transaction.Category)}</td>
                <td>${currency.format(transaction.Net)}</td>
            </tr>
        `).join("");

        return `
            <table class="data-table transaction-table">
                <thead>
                    <tr>
                        <th>Date</th>
                        <th>Description</th>
                        <th>Category</th>
                        <th>Amount</th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
        `;
    }

    function colorFor(label, index) {
        let hash = 0;
        for (let i = 0; i < label.length; i += 1) {
            hash = ((hash << 5) - hash) + label.charCodeAt(i);
            hash |= 0;
        }

        return palette[Math.abs(hash + index) % palette.length];
    }

    function escapeHtml(value) {
        return String(value)
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#39;");
    }

    function renderDonut(host, data) {
        const total = data.reduce((sum, item) => sum + item.value, 0);
        const drilldownKind = host.dataset.drilldownKind || "";
        const isCategoryDrilldown = drilldownKind === "category";

        if (!total) {
            host.innerHTML = '<p class="chart-empty">No chart data available.</p>';
            return;
        }

        let start = 0;
        const legend = data.map((item, index) => {
            const color = colorFor(item.label, index);
            const share = item.value / total;
            const end = start + (share * 360);
            const segment = `${color} ${start}deg ${end}deg`;
            start = end;
            const isClickable = isCategoryDrilldown && Array.isArray(item.transactions);
            const defaultLegendInner = `
                <span class="chart-swatch" style="background:${color}"></span>
                <span class="chart-legend-label">${escapeHtml(item.label)}</span>
                <span class="chart-legend-value">${currency.format(item.value)}</span>
            `;
            const legendInner = defaultLegendInner;

            return {
                segment,
                markup: `
                    <li class="chart-legend-item ${isClickable ? "chart-legend-item-clickable" : ""} ${isCategoryDrilldown ? "chart-legend-item-fullwidth" : ""}">
                        ${isClickable ? `
                            <button
                                type="button"
                                class="chart-legend-button ${isCategoryDrilldown ? "chart-legend-button-fullwidth" : ""}"
                                data-transactions='${escapeHtml(JSON.stringify(item.transactions))}'
                                data-modal-title='${escapeHtml(item.label)} purchases'
                            >
                                ${legendInner}
                            </button>
                        ` : legendInner}
                    </li>
                `,
            };
        });

        host.innerHTML = `
            <div class="donut-chart-layout">
                <div class="donut-chart" style="--segments: conic-gradient(${legend.map((item) => item.segment).join(", ")});">
                    <div class="donut-center">
                        <span class="donut-total-label">Total</span>
                        <strong class="donut-total-value">${currency.format(total)}</strong>
                    </div>
                </div>
                <ul class="chart-legend ${isCategoryDrilldown ? "chart-legend-fullwidth" : ""}">
                    ${legend.map((item) => item.markup).join("")}
                </ul>
            </div>
        `;
    }

    function renderGroupedBar(host, chart) {
        const labels = chart.labels || [];
        const datasets = (chart.datasets || []).filter((dataset) =>
            (dataset.values || []).some((value) => value > 0)
        );

        if (!labels.length || !datasets.length) {
            host.innerHTML = '<p class="chart-empty">No chart data available.</p>';
            return;
        }

        const maxActiveBars = Math.max(...labels.map((_, monthIndex) =>
            datasets.filter((dataset) => (dataset.values[monthIndex] || 0) > 0).length
        ), 1);
        const minGroupWidth = Math.max(116, (maxActiveBars * 44) + 26);
        const width = Math.max(1320, (labels.length * minGroupWidth) + 140);
        const height = 560;
        const margin = { top: 56, right: 20, bottom: 108, left: 120 };
        const plotWidth = width - margin.left - margin.right;
        const plotHeight = height - margin.top - margin.bottom;
        const maxValue = Math.max(...datasets.flatMap((dataset) => dataset.values), 1);
        const roundedMax = Math.ceil(maxValue / 100) * 100;
        const tickCount = 5;
        const tickStep = roundedMax / tickCount;
        const monthBand = plotWidth / labels.length;
        const monthGap = Math.max(10, monthBand * 0.08);
        const availableWidth = monthBand - (monthGap * 2);
        const fixedIntraGap = maxActiveBars > 1 ? Math.min(8, availableWidth * 0.025) : 0;
        const fixedBarWidth = Math.max(
            22,
            (availableWidth - (fixedIntraGap * Math.max(maxActiveBars - 1, 0))) / maxActiveBars
        );
        const gridLines = Array.from({ length: tickCount + 1 }, (_, index) => {
            const value = tickStep * (tickCount - index);
            const y = margin.top + (plotHeight / tickCount) * index;
            return `
                <line x1="${margin.left}" y1="${y}" x2="${width - margin.right}" y2="${y}" class="chart-grid-line"></line>
                <text x="${margin.left - 18}" y="${y + 6}" class="chart-axis-label chart-axis-label-y">${currency.format(value)}</text>
            `;
        }).join("");

        const bars = labels.map((label, monthIndex) => {
            const activeDatasets = datasets.filter((dataset) => (dataset.values[monthIndex] || 0) > 0);
            const slotCount = Math.max(activeDatasets.length, 1);
            const intraGap = slotCount > 1 ? fixedIntraGap : 0;
            const groupWidth = (fixedBarWidth * slotCount) + (intraGap * Math.max(slotCount - 1, 0));
            const groupStart = margin.left + (monthBand * monthIndex) + ((monthBand - groupWidth) / 2);

            const monthBars = activeDatasets.map((dataset, seriesIndex) => {
                const value = dataset.values[monthIndex] || 0;
                const barHeight = roundedMax ? (value / roundedMax) * plotHeight : 0;
                const x = groupStart + (seriesIndex * (fixedBarWidth + intraGap));
                const y = margin.top + plotHeight - barHeight;
                const datasetIndex = datasets.findIndex((item) => item.label === dataset.label);
                const color = colorFor(dataset.label, datasetIndex);
                const labelY = y - 12;
                const rectWidth = Math.max(18, fixedBarWidth - 2);

                return `
                    <rect x="${x}" y="${y}" width="${rectWidth}" height="${barHeight}" rx="8" fill="${color}">
                        <title>${escapeHtml(dataset.label)}: ${currency.format(value)} in ${escapeHtml(label)}</title>
                    </rect>
                    <text x="${x + (rectWidth / 2)}" y="${labelY}" class="chart-total-label">${currency.format(value)}</text>
                `;
            }).join("");

            const tickX = margin.left + (monthBand * monthIndex) + (monthBand / 2);
            return `
                ${monthBars}
                <text x="${tickX}" y="${height - 30}" class="chart-axis-label chart-axis-label-x">${escapeHtml(label)}</text>
            `;
        }).join("");

        const legend = datasets.map((dataset, index) => `
            <li class="chart-legend-item">
                <span class="chart-swatch" style="background:${colorFor(dataset.label, index)}"></span>
                <span class="chart-legend-label">${escapeHtml(dataset.label)}</span>
            </li>
        `).join("");

        host.innerHTML = `
            <div class="bar-chart-layout">
                <div class="bar-chart-scroll">
                    <svg viewBox="0 0 ${width} ${height}" class="bar-chart-svg" style="width:${width}px" role="img" aria-label="${escapeHtml(host.getAttribute("aria-label") || "Chart")}">
                        ${gridLines}
                        <line x1="${margin.left}" y1="${margin.top + plotHeight}" x2="${width - margin.right}" y2="${margin.top + plotHeight}" class="chart-axis-line"></line>
                        <line x1="${margin.left}" y1="${margin.top}" x2="${margin.left}" y2="${margin.top + plotHeight}" class="chart-axis-line"></line>
                        ${bars}
                    </svg>
                </div>
                <ul class="chart-legend chart-legend-compact">
                    ${legend}
                </ul>
            </div>
        `;
    }

    document.querySelectorAll(".chart-host").forEach((host) => {
        const payload = host.dataset.chart;
        if (!payload) {
            return;
        }

        const data = JSON.parse(payload);
        const type = host.dataset.chartType;

        if (type === "donut") {
            renderDonut(host, data);
            return;
        }

        if (type === "grouped-bar") {
            renderGroupedBar(host, data);
        }
    });

    const modal = document.getElementById("month-transactions-modal");
    const modalTitle = document.getElementById("month-transactions-title");
    const modalContent = document.getElementById("month-transactions-content");

    function openModal(title, transactions) {
        if (!modal || !modalTitle || !modalContent) {
            return;
        }

        modalTitle.textContent = title;
        modalContent.innerHTML = renderTransactionsTable(transactions);
        modal.showModal();
    }

    function closeModal() {
        if (modal && modal.open) {
            modal.close();
        }
    }

    document.querySelectorAll(".month-card-clickable").forEach((card) => {
        card.addEventListener("click", () => {
            const month = card.dataset.month || "Month details";
            const transactions = JSON.parse(card.dataset.transactions || "[]");
            openModal(`${month} transactions`, transactions);
        });
    });

    document.querySelectorAll(".chart-legend-button").forEach((button) => {
        button.addEventListener("click", () => {
            const transactions = JSON.parse(button.dataset.transactions || "[]");
            const title = button.dataset.modalTitle || "Category purchases";
            openModal(title, transactions);
        });
    });

    document.querySelectorAll("[data-close-modal]").forEach((button) => {
        button.addEventListener("click", closeModal);
    });

    if (modal) {
        modal.addEventListener("click", (event) => {
            const bounds = modal.getBoundingClientRect();
            const clickedBackdrop = (
                event.clientX < bounds.left ||
                event.clientX > bounds.right ||
                event.clientY < bounds.top ||
                event.clientY > bounds.bottom
            );

            if (clickedBackdrop) {
                closeModal();
            }
        });
    }

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            closeModal();
        }
    });
}());
