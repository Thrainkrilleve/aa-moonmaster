/* Moon Master — frontend utilities */

/**
 * Format a raw ISK number string with thousand separators.
 * e.g. formatISK("1234567890") → "1,234,567,890"
 */
function formatISK(val) {
  const n = parseFloat(val);
  if (isNaN(n)) return val;
  return n.toLocaleString(undefined, { maximumFractionDigits: 0 });
}

/**
 * Fetch live profitability data for a moon and render into #profitData.
 * Used by moon_detail.html if you want fully-AJAX recalculation.
 */
function fetchProfitability(moonId, fleetSharePct, containerId) {
  const url = `/moonmaster/api/moon/${moonId}/profitability/?fleet_share=${fleetSharePct}`;
  fetch(url, { credentials: 'same-origin' })
    .then(r => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    })
    .then(data => {
      const el = document.getElementById(containerId);
      if (!el) return;
      /* Simple render: full page reload is preferred for template-driven pages. */
      console.debug('Profitability data:', data);
    })
    .catch(err => console.error('Failed to fetch profitability:', err));
}
