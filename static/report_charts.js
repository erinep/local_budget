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

            return {
                segment,
                markup: `
                    <li class="chart-legend-item">
                        <span class="chart-swatch" style="background:${color}"></span>
                        <span class="chart-legend-label">${escapeHtml(item.label)}</span>
                        <span class="chart-legend-value">${currency.format(item.value)}</span>
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
                <ul class="chart-legend">
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

        const width = 1320;
        const height = 560;
        const margin = { top: 56, right: 20, bottom: 108, left: 120 };
        const plotWidth = width - margin.left - margin.right;
        const plotHeight = height - margin.top - margin.bottom;
        const maxValue = Math.max(...datasets.flatMap((dataset) => dataset.values), 1);
        const roundedMax = Math.ceil(maxValue / 100) * 100;
        const tickCount = 5;
        const tickStep = roundedMax / tickCount;
        const monthBand = plotWidth / labels.length;
        const innerGap = 14;
        const barWidth = Math.max(16, ((monthBand - innerGap * 2) / datasets.length) * 0.82);
        const gridLines = Array.from({ length: tickCount + 1 }, (_, index) => {
            const value = tickStep * (tickCount - index);
            const y = margin.top + (plotHeight / tickCount) * index;
            return `
                <line x1="${margin.left}" y1="${y}" x2="${width - margin.right}" y2="${y}" class="chart-grid-line"></line>
                <text x="${margin.left - 18}" y="${y + 6}" class="chart-axis-label chart-axis-label-y">${currency.format(value)}</text>
            `;
        }).join("");

        const bars = labels.map((label, monthIndex) => {
            const groupStart = margin.left + (monthBand * monthIndex) + innerGap;
            const monthBars = datasets.map((dataset, seriesIndex) => {
                const value = dataset.values[monthIndex] || 0;
                const barHeight = roundedMax ? (value / roundedMax) * plotHeight : 0;
                const x = groupStart + (seriesIndex * barWidth);
                const y = margin.top + plotHeight - barHeight;
                const color = colorFor(dataset.label, seriesIndex);
                const labelY = y - 12;

                return `
                    <rect x="${x}" y="${y}" width="${barWidth - 4}" height="${barHeight}" rx="8" fill="${color}">
                        <title>${escapeHtml(dataset.label)}: ${currency.format(value)} in ${escapeHtml(label)}</title>
                    </rect>
                    ${value > 0 ? `<text x="${x + ((barWidth - 4) / 2)}" y="${labelY}" class="chart-total-label">${currency.format(value)}</text>` : ""}
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
                <svg viewBox="0 0 ${width} ${height}" class="bar-chart-svg" role="img" aria-label="${escapeHtml(host.getAttribute("aria-label") || "Chart")}">
                    ${gridLines}
                    <line x1="${margin.left}" y1="${margin.top + plotHeight}" x2="${width - margin.right}" y2="${margin.top + plotHeight}" class="chart-axis-line"></line>
                    <line x1="${margin.left}" y1="${margin.top}" x2="${margin.left}" y2="${margin.top + plotHeight}" class="chart-axis-line"></line>
                    ${bars}
                </svg>
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
}());
