
"use strict";

const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];

const esc = s =>
  String(s ?? "").replace(/[&<>"']/g, c => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  }[c]));

const num = v =>
  v == null
    ? "—"
    : new Intl.NumberFormat(undefined, {
        maximumFractionDigits: Math.abs(v) >= 100 ? 0 : 2
      }).format(v);

const ICONS = {
  overview: "M3 3v18h18M7 15l4-4 3 3 5-6",
  explorer: "M3 5h18M3 12h18M3 19h18",
  insights: "M9 18h6M10 22h4M12 2a7 7 0 0 0-4 12.7V17h8v-2.3A7 7 0 0 0 12 2z",
  ask: "M21 12a8 8 0 0 1-11.6 7.1L3 21l1.9-6.4A8 8 0 1 1 21 12z",
  settings: "M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6"
};

const VIEWS = [
  ["overview", "Overview"],
  ["explorer", "Data Explorer"],
  ["insights", "Insights"],
  ["ask", "Ask DataPilot"],
  ["settings", "Settings"]
];

const ROLES = [
  ["revenue", "Revenue / sales"],
  ["profit", "Profit"],
  ["date", "Date"],
  ["product", "Product"],
  ["category", "Category"],
  ["quantity", "Quantity"]
];

let A = null;
let charts = {};
let tbl = { page: 1, sort: "", dir: "asc", q: "" };
let timer;

// ----- API -----

async function api(url, opt) {
  let r, d;

  try {
    r = await fetch(url, opt);
  } catch {
    throw new Error(
      "Cannot reach the DataPilot server. Is it still running?"
    );
  }

  try {
    d = await r.json();
  } catch {
    d = { error: "Unexpected response from the server." };
  }

  if (!r.ok) {
    throw new Error(d.error || "Request failed.");
  }

  return d;
}

function setStatus(t, k) {
  const s = $("#status");
  s.textContent = t;
  s.dataset.kind = k || "idle";
}

// ----- NAVIGATION -----

$("#nav").innerHTML = VIEWS.map(([id, label]) =>
  `<button type="button" data-view="${id}">
    <svg viewBox="0 0 24 24" width="18" height="18"
      fill="none" stroke="currentColor" stroke-width="1.8"
      stroke-linecap="round" stroke-linejoin="round"
      aria-hidden="true">
      <path d="${ICONS[id]}"/>
    </svg>
    <span>${label}</span>
  </button>`
).join("");

function show(id) {
  if (!VIEWS.some(v => v[0] === id)) {
    id = "overview";
  }

  $$(".view").forEach(v => {
    v.classList.toggle("active", v.id === "v-" + id);
  });

  $$("#nav button").forEach(b => {
    const on = b.dataset.view === id;
    b.classList.toggle("active", on);

    if (on) {
      b.setAttribute("aria-current", "page");
    } else {
      b.removeAttribute("aria-current");
    }
  });

  if (history.replaceState) {
    history.replaceState(null, "", "#" + id);
  }

  if (A && id === "overview") renderCharts();
  if (A && id === "explorer") loadRows();

  window.scrollTo(0, 0);
}

$("#nav").addEventListener("click", e => {
  const b = e.target.closest("button");
  if (b) show(b.dataset.view);
});

// ----- THEME -----

function theme(t) {
  document.documentElement.dataset.theme = t;

  try {
    localStorage.setItem("dp-theme", t);
  } catch {}

  $$(".js-theme").forEach(b => {
    b.textContent =
      t === "dark" ? "Switch to light mode" : "Switch to dark mode";
  });

  if (A) renderCharts();
}

$$(".js-theme").forEach(b => {
  b.addEventListener("click", () => {
    theme(
      document.documentElement.dataset.theme === "dark"
        ? "light"
        : "dark"
    );
  });
});

// ----- DATA LOADING AND UPLOAD -----

async function load(fn, msg) {
  $$("#btnUpload,#btnSample").forEach(b => {
    b.disabled = true;
  });

  setStatus(msg, "busy");

  try {
    A = await fn();
    tbl = { page: 1, sort: "", dir: "asc", q: "" };
    $("#search").value = "";

    render();

    setStatus(
      `Loaded: ${A.rows.toLocaleString()} rows, ${A.cols} columns`,
      "ok"
    );
  } catch (e) {
    setStatus(
      e.message + (A ? " The previous dataset is still loaded." : ""),
      "err"
    );
  } finally {
    $$("#btnUpload,#btnSample").forEach(b => {
      b.disabled = false;
    });
  }
}

function upload(f) {
  if (!f) return;

  const ext = f.name.split(".").pop().toLowerCase();

  if (!["csv", "xlsx", "xls"].includes(ext)) {
    return setStatus("Unsupported file type. Use CSV, XLSX or XLS.", "err");
  }

  if (f.size > 16 * 1024 * 1024) {
    return setStatus("The file is larger than 16 MB.", "err");
  }

  if (f.size === 0) {
    return setStatus("The file is empty.", "err");
  }

  const fd = new FormData();
  fd.append("file", f);

  load(
    () => api("/api/upload", { method: "POST", body: fd }),
    `Analysing ${f.name}…`
  );
}

$("#btnUpload").onclick = () => $("#file").click();

$("#file").onchange = e => {
  upload(e.target.files[0]);
  e.target.value = "";
};

$("#btnSample").onclick = () =>
  load(
    () => api("/api/sample", { method: "POST" }),
    "Loading sample data…"
  );

const drop = $("#drop");

drop.onclick = () => $("#file").click();

drop.onkeydown = e => {
  if (e.key === "Enter" || e.key === " ") {
    e.preventDefault();
    $("#file").click();
  }
};

["dragenter", "dragover"].forEach(t => {
  drop.addEventListener(t, e => {
    e.preventDefault();
    drop.classList.add("over");
  });
});

["dragleave", "drop"].forEach(t => {
  drop.addEventListener(t, e => {
    e.preventDefault();
    drop.classList.remove("over");
  });
});

drop.addEventListener("drop", e => {
  upload(e.dataTransfer.files[0]);
});

window.addEventListener("dragover", e => e.preventDefault());
window.addEventListener("drop", e => e.preventDefault());

// ----- RENDER DASHBOARD -----

function render() {
  const has = !!A;

  $("#dsName").textContent = has ? A.name : "None loaded";

  ["ov", "ex", "in"].forEach(p => {
    $(`#${p}-empty`).hidden = has;
    $(`#${p}-body`).hidden = !has;
  });

  if (!has) return;

  const used = ROLES
    .filter(([r]) => A.mapping[r])
    .map(([r, label]) =>
      `${label}: <strong>${esc(A.mapping[r])}</strong>`
    )
    .join(" · ") || "No columns matched";

  $("#detect").innerHTML =
    (A.notes.length
      ? `<div class="note-box">
          <strong>Column detection</strong>
          <ul>${A.notes.map(n => `<li>${esc(n)}</li>`).join("")}</ul>
        </div>`
      : "") +
    `<div class="maprow">Columns in use. ${used}. Change in Settings.</div>`;

  $("#kpis").innerHTML = A.kpis.map(k =>
    `<div class="card kpi">
      <div class="lbl">${esc(k.label)}</div>
      ${
        k.value == null
          ? `<div class="val na">Not available</div>`
          : `<div class="val">${
              k.kind === "pct"
                ? k.value.toFixed(1) + "%"
                : num(k.value)
            }</div>`
      }
      <div class="note">${esc(k.note)}</div>
    </div>`
  ).join("");

  const q = A.quality;

  $("#qstrip").innerHTML =
    `<span>Missing cells: <strong>${q.missing_cells.toLocaleString()}</strong></span>
     <span>Duplicate rows: <strong>${q.duplicate_rows.toLocaleString()}</strong></span>
     <a id="toQ" role="link" tabindex="0">See data-quality details</a>`;

  $("#toQ").onclick = () => show("insights");

  renderCharts();

  // Data Explorer
  $("#ex-dims").textContent =
    `${A.rows.toLocaleString()} rows × ${A.cols} columns. ` +
    `Missing cells: ${q.missing_cells.toLocaleString()}. ` +
    `Duplicate rows: ${q.duplicate_rows.toLocaleString()}.`;

  $("#colTable").innerHTML =
    `<thead><tr>
      <th>Column</th><th>Type</th><th>Missing</th><th>Unique</th>
    </tr></thead><tbody>` +
    A.columns.map(c =>
      `<tr>
        <td>${esc(c.name)}</td>
        <td>${esc(c.dtype)}</td>
        <td class="n">${
          c.missing
            ? `<span class="na">${c.missing.toLocaleString()} (${c.missing_pct}%)</span>`
            : "0"
        }</td>
        <td class="n">${c.unique.toLocaleString()}</td>
      </tr>`
    ).join("") +
    "</tbody>";

  const ns = Object.entries(A.numeric_summary);

  $("#sumTable").innerHTML = ns.length
    ? `<thead><tr>
        <th>Column</th><th>Count</th><th>Mean</th>
        <th>Std</th><th>Min</th><th>Median</th><th>Max</th>
      </tr></thead><tbody>` +
      ns.map(([c, s]) =>
        `<tr><td>${esc(c)}</td>${
          ["count", "mean", "std", "min", "50%", "max"]
            .map(k => `<td class="n">${num(s[k])}</td>`)
            .join("")
        }</tr>`
      ).join("") +
      "</tbody>"
    : `<tbody><tr><td class="muted">No numeric columns were detected.</td></tr></tbody>`;

  // Insights
  $("#qlist").innerHTML = q.warnings.map(w =>
    `<li>
      <span class="tag ${w.level === "warn" ? "warn" : ""}">
        ${{ warn: "Warning", info: "Note", ok: "OK" }[w.level]}
      </span>
      ${esc(w.text)}
    </li>`
  ).join("");

  $("#ilist").innerHTML = A.insights.length
    ? A.insights.map(i =>
        `<li>
          <span class="tag ${i.kind === "fact" ? "" : "ctx"}">
            ${i.kind === "fact" ? "Observed" : "Possible explanation"}
          </span>
          ${esc(i.text)}
          <span class="basis">Basis: ${esc(i.basis)}</span>
        </li>`
      ).join("")
    : `<li class="muted">No insights could be generated. See below.</li>`;

  $("#ulist").innerHTML = A.unavailable.length
    ? A.unavailable.map(u =>
        `<li><strong>${esc(u.title)}.</strong> ${esc(u.reason)}</li>`
      ).join("")
    : `<li class="muted">Every insight type was available.</li>`;

  renderMapping();

  if ($("#v-explorer").classList.contains("active")) {
    loadRows();
  }
}

function renderMapping() {
  const box = $("#mapBox");
  if (!A) return;

  box.innerHTML =
    `<div class="maprow2">` +
    ROLES.map(([r, label]) =>
      `<label for="m-${r}">${label}</label>
       <select id="m-${r}">
         <option value="">(none)</option>
         ${A.columns.map(c =>
           `<option value="${esc(c.name)}" ${
             A.mapping[r] === c.name ? "selected" : ""
           }>${esc(c.name)}</option>`
         ).join("")}
       </select>`
    ).join("") +
    `</div>
     <button class="btn primary" id="applyMap" type="button">Apply mapping</button>
     <span id="mapMsg" class="small muted"></span>`;

  $("#applyMap").onclick = async () => {
    const mapping = {};

    ROLES.forEach(([r]) => {
      mapping[r] = $("#m-" + r).value || null;
    });

    try {
      A = await api("/api/mapping", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mapping })
      });

      render();
      $("#mapMsg").textContent = "Mapping applied.";
      setStatus("Mapping applied", "ok");
    } catch (e) {
      $("#mapMsg").textContent = e.message;
      $("#mapMsg").style.color = "var(--err)";
    }
  };
}

// ----- CHARTS -----

const css = n =>
  getComputedStyle(document.documentElement).getPropertyValue(n).trim();

function renderCharts() {
  Object.values(charts).forEach(c => c.destroy());
  charts = {};

  const box = $("#charts");

  if (!A) {
    box.innerHTML = "";
    return;
  }

  const order = ["trend", "category", "products", "profit_cat", "hist"];

  box.innerHTML = order.map(k => {
    const c = A.charts[k];

    return `<article class="card chart ${k === "trend" ? "wide" : ""}">
      <h3>${esc(c.title)}</h3>
      ${
        c.available
          ? `<div class="cv"><canvas id="ch-${k}" role="img" aria-label="${esc(c.title)}"></canvas></div>`
          : `<p class="muted pad">${esc(c.reason)}</p>`
      }
    </article>`;
  }).join("");

  if (typeof Chart === "undefined") {
    box.innerHTML =
      `<p class="muted">Charts could not load (static/vendor/chart.umd.js is missing).</p>`;
    return;
  }

  const mut = css("--muted");
  const grid = css("--border");
  const cols = [css("--accent"), css("--series2")];

  Chart.defaults.font.family = "Inter, 'Segoe UI', system-ui, sans-serif";
  Chart.defaults.color = mut;

  order.forEach(k => {
    const c = A.charts[k];
    if (!c.available) return;

    const horiz = c.type === "hbar";
    const line = c.type === "line";

    const val = {
      title: { display: true, text: c.ylabel, color: mut },
      grid: { color: grid },
      ticks: { color: mut, callback: v => num(v) },
      beginAtZero: true
    };

    const cat = {
      title: { display: true, text: c.xlabel, color: mut },
      grid: { display: false },
      ticks: {
        color: mut,
        autoSkip: true,
        maxRotation: 45,
        callback: function (v) {
          const l = this.getLabelForValue(v);
          return l.length > 22 ? l.slice(0, 21) + "…" : l;
        }
      }
    };

    charts[k] = new Chart($("#ch-" + k), {
      type: line ? "line" : "bar",
      data: {
        labels: c.labels,
        datasets: c.datasets.map((s, i) => ({
          label: s.label,
          data: s.data,
          backgroundColor: cols[i],
          borderColor: cols[i],
          borderWidth: line ? 2 : 0,
          tension: 0.25,
          pointRadius: line ? 3 : 0,
          spanGaps: false,
          borderRadius: 2,
          maxBarThickness: 36
        }))
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        indexAxis: horiz ? "y" : "x",
        plugins: {
          legend: {
            display: c.datasets.length > 1,
            labels: { color: mut, boxWidth: 10 }
          },
          tooltip: {
            callbacks: {
              label: x =>
                ` ${x.dataset.label}: ${num(horiz ? x.parsed.x : x.parsed.y)}`
            }
          }
        },
        scales: horiz
          ? { x: val, y: cat }
          : { x: cat, y: val }
      }
    });
  });
}

// ----- DATA EXPLORER TABLE -----

async function loadRows() {
  const box = $("#rowsBox");

  try {
    const d = await api(
      "/api/rows?" +
      new URLSearchParams({
        page: tbl.page,
        q: tbl.q,
        sort: tbl.sort,
        dir: tbl.dir
      })
    );

    tbl.page = d.page;
    tbl.pages = d.pages;

    const arrow = c =>
      tbl.sort === c
        ? (tbl.dir === "asc" ? " ▲" : " ▼")
        : "";

    const start = d.total ? (d.page - 1) * d.size + 1 : 0;
    const end = Math.min(d.page * d.size, d.total);

    box.innerHTML =
      `<div class="tw"><table><thead><tr>
        <th>#</th>
        ${d.columns.map(c =>
          `<th data-col="${esc(c)}" title="Sort by ${esc(c)}">${esc(c)}${arrow(c)}</th>`
        ).join("")}
      </tr></thead><tbody>` +
      (
        d.rows.length
          ? d.rows.map((r, i) =>
              `<tr><td class="muted">${d.index[i]}</td>${
                r.map(v =>
                  v == null
                    ? `<td><span class="na">empty</span></td>`
                    : `<td>${esc(v)}</td>`
                ).join("")
              }</tr>`
            ).join("")
          : `<tr><td colspan="${d.columns.length + 1}" class="muted">No rows match your search.</td></tr>`
      ) +
      `</tbody></table></div>
       <div class="pager">
         <span>Showing ${start}–${end} of ${d.total.toLocaleString()}</span>
         <span>
           <button class="btn small" data-pg="-1" ${d.page <= 1 ? "disabled" : ""}>Previous</button>
           Page ${d.page} of ${d.pages}
           <button class="btn small" data-pg="1" ${d.page >= d.pages ? "disabled" : ""}>Next</button>
         </span>
       </div>`;
  } catch (e) {
    box.innerHTML = `<p class="na">${esc(e.message)}</p>`;
  }
}

$("#rowsBox").addEventListener("click", e => {
  const th = e.target.closest("th[data-col]");
  const pg = e.target.closest("button[data-pg]");

  if (th) {
    tbl.dir =
      tbl.sort === th.dataset.col && tbl.dir === "asc"
        ? "desc"
        : "asc";

    tbl.sort = th.dataset.col;
    tbl.page = 1;
    loadRows();
  }

  if (pg) {
    tbl.page += Number(pg.dataset.pg);
    loadRows();
  }
});

$("#search").addEventListener("input", e => {
  clearTimeout(timer);

  timer = setTimeout(() => {
    tbl.q = e.target.value;
    tbl.page = 1;
    loadRows();
  }, 250);
});

// ----- ASK DATAPILOT -----

const SUGGEST = [
  "What are my total sales?",
  "Which product generated the most revenue?",
  "What is my total profit?",
  "What is the profit margin?",
  "Which category performs best?",
  "How have sales changed month by month?",
  "How many duplicate rows are present?",
  "Which columns contain missing values?"
];

$("#chips").innerHTML = SUGGEST.map(s =>
  `<button type="button">${esc(s)}</button>`
).join("");

$("#chips").addEventListener("click", e => {
  if (e.target.tagName === "BUTTON") {
    $("#q").value = e.target.textContent;
    ask();
  }
});

function bubble(html, cls) {
  const c = $("#chat");

  if (
    c.firstElementChild &&
    c.firstElementChild.tagName === "P"
  ) {
    c.innerHTML = "";
  }

  c.insertAdjacentHTML(
    "beforeend",
    `<div class="msg ${cls}">${html}</div>`
  );

  c.scrollTop = c.scrollHeight;
}

// Voice elements are initialized before the user can submit a question.
const voiceBtn = $("#voiceBtn");
const speakToggle = $("#speakToggle");
const voiceStatus = $("#voiceStatus");
const assistantStatus = $("#assistantStatus");

const SpeechRecognition =
  window.SpeechRecognition || window.webkitSpeechRecognition;

let recognition = null;
let listening = false;

function setAssistantStatus(message) {
  if (assistantStatus) {
    assistantStatus.textContent = message;
  }
}

function setVoiceStatus(message) {
  if (voiceStatus) {
    voiceStatus.textContent = message;
  }
}

// ----- SPOKEN ANSWERS -----

function speakAnswer(text) {
  if (!speakToggle || !speakToggle.checked) return;

  if (!("speechSynthesis" in window) ||
      typeof SpeechSynthesisUtterance === "undefined") {
    setVoiceStatus(
      "Spoken responses are not supported by this browser."
    );
    return;
  }

  window.speechSynthesis.cancel();

  const speech = new SpeechSynthesisUtterance(String(text));
  speech.lang = "en-IN";
  speech.rate = 1;

  window.speechSynthesis.speak(speech);
}

if (speakToggle) {
  speakToggle.addEventListener("change", () => {
    if (
      !speakToggle.checked &&
      "speechSynthesis" in window
    ) {
      window.speechSynthesis.cancel();
    }
  });
}

// ----- ASK QUESTION -----

async function ask() {
  const input = $("#q");
  const q = input.value.trim();

  if (!q) return;

  input.value = "";
  bubble(esc(q), "u");
  setAssistantStatus("Thinking");

  try {
    const d = await api("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: q })
    });

    bubble(
      `${esc(d.answer)}<span class="basis">Basis: ${esc(d.basis)}</span>`,
      "b"
    );

    setAssistantStatus("Ready");
    speakAnswer(d.answer);
  } catch (e) {
    bubble(esc(e.message), "err");
    setAssistantStatus("Error");
  }
}

$("#askBtn").onclick = ask;

$("#q").addEventListener("keydown", e => {
  if (e.key === "Enter") ask();
});

// ----- VOICE INPUT -----

if (voiceBtn) {
  if (SpeechRecognition) {
    recognition = new SpeechRecognition();

    recognition.lang = "en-IN";
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;

    recognition.onstart = () => {
      listening = true;
      voiceBtn.textContent = "Listening...";
      setVoiceStatus("Listening. Ask your question now.");
      setAssistantStatus("Listening");
    };

    recognition.onresult = event => {
      const result = event.results[0];

      if (!result || !result[0]) {
        setVoiceStatus(
          "I couldn't understand that. Please try again or type your question."
        );
        return;
      }

      const spokenQuestion = result[0].transcript.trim();

      if (!spokenQuestion) {
        setVoiceStatus(
          "No question was detected. Please try again."
        );
        return;
      }

      $("#q").value = spokenQuestion;
      setVoiceStatus(`Heard: "${spokenQuestion}"`);

      ask();
    };

    recognition.onerror = event => {
      const messages = {
        "not-allowed":
          "Microphone access was blocked. Allow microphone access in Chrome site settings.",
        "service-not-allowed":
          "The browser speech service is unavailable. You can type your question instead.",
        "no-speech":
          "No speech was detected. Click Try voice and speak clearly.",
        "audio-capture":
          "No microphone was detected. Check your microphone connection.",
        "network":
          "The browser speech service encountered a network error. Try again or type your question.",
        "aborted":
          "Voice input was cancelled."
      };

      setVoiceStatus(
        messages[event.error] ||
        `Voice input error: ${event.error}. You can type your question instead.`
      );

      if (event.error !== "aborted") {
        setAssistantStatus("Ready");
      }
    };

    recognition.onend = () => {
      listening = false;
      voiceBtn.textContent = "Try voice";

      if (
        assistantStatus &&
        assistantStatus.textContent === "Listening"
      ) {
        setAssistantStatus("Ready");
      }
    };

    voiceBtn.addEventListener("click", () => {
      if (listening) {
        recognition.stop();
        return;
      }

      try {
        recognition.start();
      } catch (error) {
        setVoiceStatus(
          "Voice input could not start. Wait a moment and try again."
        );
      }
    });

    setVoiceStatus(
      "Click Try voice, allow microphone access, and ask your question."
    );
  } else {
    voiceBtn.disabled = true;
    voiceBtn.title = "Speech recognition is not supported in this browser.";

    setVoiceStatus(
      "Voice input is not supported in this browser. You can still type questions."
    );
  }
} else {
  console.error(
    "DataPilot voice button not found. Check templates/index.html for id=\"voiceBtn\"."
  );
}

console.log("DataPilot voice button:", voiceBtn);
console.log(
  "DataPilot speech recognition:",
  SpeechRecognition || "Not supported by this browser"
);

// ----- START APPLICATION -----

theme(document.documentElement.dataset.theme || "light");

show((location.hash || "#overview").slice(1));

api("/api/state")
  .then(d => {
    if (d.name) {
      A = d;
      render();

      setStatus(
        `Loaded: ${A.rows.toLocaleString()} rows, ${A.cols} columns`,
        "ok"
      );
    }
  })
  .catch(() => {});

render();
