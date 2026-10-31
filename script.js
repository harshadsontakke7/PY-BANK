/* PY BANK front-end behaviour. No inline scripts are used (strict CSP). */
(function () {
  "use strict";
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };

  /* Mobile sidebar */
  var body = document.body;
  $$("[data-sidebar-toggle]").forEach(function (b) {
    b.addEventListener("click", function () { body.classList.toggle("sidebar-open"); });
  });
  $$("[data-sidebar-close]").forEach(function (b) {
    b.addEventListener("click", function () { body.classList.remove("sidebar-open"); });
  });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") body.classList.remove("sidebar-open"); });

  /* Notifications: dismiss button + auto-hide */
  function dismiss(n) { n.classList.add("leaving"); setTimeout(function () { n.remove(); }, 260); }
  $$(".notice").forEach(function (n) {
    $(".notice-close", n).addEventListener("click", function () { dismiss(n); });
    setTimeout(function () { if (document.body.contains(n)) dismiss(n); }, n.classList.contains("notice-danger") ? 9000 : 6000);
  });

  /* Digits-only PIN fields */
  $$("[data-digits]").forEach(function (i) {
    i.addEventListener("input", function () { i.value = i.value.replace(/\D/g, "").slice(0, 4); });
  });

  /* Quick amount chips */
  $$("[data-amount-target]").forEach(function (chip) {
    chip.addEventListener("click", function () {
      var t = document.getElementById(chip.dataset.amountTarget);
      if (t) { t.value = chip.dataset.amount; t.focus(); }
    });
  });

  /* Auto-submit selects (history filters) */
  $$("[data-autosubmit]").forEach(function (s) { s.addEventListener("change", function () { s.form.submit(); }); });

  /* Client-side validation + loading state (the server re-validates everything) */
  $$("form[data-validate]").forEach(function (form) {
    var match = $("[data-match]", form);
    function checkMatch() {
      if (!match) return;
      var other = document.getElementById(match.dataset.match);
      match.setCustomValidity(other && match.value !== other.value ? "PINs do not match." : "");
    }
    if (match) {
      match.addEventListener("input", checkMatch);
      document.getElementById(match.dataset.match).addEventListener("input", checkMatch);
    }
    form.addEventListener("submit", function (e) {
      checkMatch();
      if (!form.checkValidity()) {
        e.preventDefault(); e.stopPropagation();
        form.classList.add("was-validated");
        var bad = $(":invalid", form); if (bad) bad.focus();
        return;
      }
      var btn = $("button[type=submit]", form);
      if (btn && form.dataset.loading) {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2" aria-hidden="true"></span>' + form.dataset.loading;
      }
    });
  });

  /* Show / hide balance */
  $$("[data-balance-toggle]").forEach(function (btn) {
    var hidden = false;
    btn.addEventListener("click", function () {
      hidden = !hidden;
      $$("[data-balance-value]").forEach(function (el) { el.textContent = hidden ? "₹ ••••••" : el.dataset.real; });
      btn.innerHTML = '<i class="fa-solid ' + (hidden ? "fa-eye-slash" : "fa-eye") + '"></i>';
      btn.setAttribute("aria-label", hidden ? "Show balance" : "Hide balance");
    });
  });

  /* Balance chart */
  var canvas = document.getElementById("balanceChart");
  if (canvas && window.Chart) {
    var chart, msg = document.getElementById("chartMsg"), select = document.getElementById("rangeSelect");
    var fmt = function (v) { return "₹" + Number(v).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }); };
    var short = function (v) { return v >= 1e7 ? (v / 1e7) + "Cr" : v >= 1e5 ? (v / 1e5) + "L" : v >= 1e3 ? (v / 1e3) + "K" : v; };

    function draw(data) {
      var ctx = canvas.getContext("2d");
      var grad = ctx.createLinearGradient(0, 0, 0, canvas.height || 300);
      grad.addColorStop(0, "rgba(47,111,232,.28)"); grad.addColorStop(1, "rgba(47,111,232,0)");
      var points = data.values.length < 40 ? 4 : 0;
      if (chart) chart.destroy();
      chart = new Chart(canvas, {
        type: "line",
        data: { labels: data.labels, datasets: [{ label: "Balance", data: data.values, borderColor: "#1f5fd6", backgroundColor: grad, fill: true, tension: .35, pointRadius: points, pointBackgroundColor: "#1f5fd6", borderWidth: 2.5 }] },
        options: {
          responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
          plugins: { legend: { display: false }, tooltip: { callbacks: { label: function (c) { return " " + fmt(c.parsed.y); } } } },
          scales: {
            x: { grid: { color: "#eef2fa" }, ticks: { maxTicksLimit: 8, color: "#64739a" } },
            y: { beginAtZero: true, grid: { color: "#eef2fa" }, ticks: { color: "#64739a", callback: short } }
          }
        }
      });
    }

    function load(range) {
      msg.hidden = true;
      fetch(canvas.dataset.url + "?range=" + encodeURIComponent(range), { headers: { "Accept": "application/json" }, credentials: "same-origin" })
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then(function (d) {
          if (!d.values.length) { if (chart) chart.destroy(); msg.textContent = "No transactions yet. Your balance history will appear here."; msg.hidden = false; return; }
          draw(d);
        })
        .catch(function () { if (chart) chart.destroy(); msg.textContent = "The chart could not be loaded. Refresh the page to try again."; msg.hidden = false; });
    }
    select.addEventListener("change", function () { load(select.value); });
    load(select.value);
  }
})();
