const R = 8.314462618;
const DEFAULT_URL = "https://docs.google.com/spreadsheets/d/1Gg9XJk0p5_yHgD5lgZg9oyTWgkWT1sbZA-BtBs7GwVU/edit?gid=193585797#gid=193585797";

const state = {
  rows: [],
  intervals: [],
  fitMode: "average",
  fits: { k1: null, k2: null },
  charts: { arrhenius: null, prediction: null },
};

const $ = (id) => document.getElementById(id);

function norm(text) {
  return String(text ?? "").replace(/\s+/g, "").toLowerCase();
}

function firstNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  if (typeof value === "number" && Number.isFinite(value)) return value;
  const match = String(value).replaceAll(",", "").match(/[-+]?\d+(?:\.\d+)?/);
  return match ? Number(match[0]) : null;
}

function extractSheetInfo(url) {
  const id = String(url).match(/\/spreadsheets\/d\/([a-zA-Z0-9-_]+)/)?.[1];
  if (!id) throw new Error("Google Sheet URL에서 spreadsheet id를 찾을 수 없습니다.");
  const gid = String(url).match(/[?#&]gid=(\d+)/)?.[1] ?? "0";
  return { id, gid };
}

function csvUrlFromSheet(url) {
  const { id, gid } = extractSheetInfo(url);
  return `https://docs.google.com/spreadsheets/d/${id}/gviz/tq?tqx=out:csv&gid=${gid}`;
}

function setStatus(message, type = "") {
  const el = $("statusText");
  el.textContent = message;
  el.className = `status ${type}`;
}

function findHeaderIndex(matrix) {
  return matrix.findIndex((row) => {
    const compact = row.map(norm);
    return compact.some((v) => v.includes("cvd")) && compact.some((v) => v.includes("t1"));
  });
}

function findColumn(headers, candidates) {
  const compact = headers.map(norm);
  for (const candidate of candidates) {
    const target = norm(candidate);
    const exact = compact.findIndex((h) => h === target);
    if (exact >= 0) return exact;
  }
  for (const candidate of candidates) {
    const target = norm(candidate);
    const includes = compact.findIndex((h) => h.includes(target));
    if (includes >= 0) return includes;
  }
  return -1;
}

function parseRows(matrix) {
  const headerIndex = findHeaderIndex(matrix);
  if (headerIndex < 0) throw new Error("header row를 찾지 못했습니다. Codex 탭 또는 gid가 맞는지 확인하세요.");
  const headers = matrix[headerIndex];
  const col = {
    cvd: findColumn(headers, ["CVD 종류", "CVD"]),
    pressure: findColumn(headers, ["공정 압력", "pressure"]),
    temp: findColumn(headers, ["온도", "temperature"]),
    t1: findColumn(headers, ["T1(min.)", "T1(min)", "T1"]),
    t2: findColumn(headers, ["T2(min.)", "T2(min)", "T2"]),
    p1: findColumn(headers, ["p1 (mg)", "p1(mg)", "p1"]),
    p2: findColumn(headers, ["p2(mg)", "p2 (mg)", "p2"]),
  };
  if (Object.values(col).some((v) => v < 0)) throw new Error("필수 열(CVD, 압력, 온도, T1, T2, p1, p2)을 찾지 못했습니다.");

  const intervals = [];
  for (let i = headerIndex + 1; i < matrix.length; i++) {
    const row = matrix[i];
    if (!row || row.every((v) => String(v ?? "").trim() === "")) continue;
    const pressure = firstNumber(row[col.pressure]);
    const temp = firstNumber(row[col.temp]);
    const t1 = firstNumber(row[col.t1]);
    const t2 = firstNumber(row[col.t2]);
    const p1 = firstNumber(row[col.p1]);
    const p2 = firstNumber(row[col.p2]);
    const reasons = [];
    if (pressure === null || Math.abs(pressure - 0.15) > 0.005) reasons.push("0.15 Torr 외 조건");
    if ([temp, t1, t2, p1, p2].some((v) => v === null)) reasons.push("필수값 누락");
    if (t1 !== null && t2 !== null && t2 <= t1) reasons.push("T2 <= T1");
    if (p1 !== null && p2 !== null && (p1 <= 0 || p2 <= 0 || p2 >= p1)) reasons.push("p1/p2 invalid");
    let model = null;
    if (reasons.length === 0) {
      if (t1 >= 0 && t2 <= 120) model = "k1";
      else if (t1 >= 120) model = "k2";
      else reasons.push("120분 경계 교차 row는 fitting 제외");
    }
    const duration = t1 !== null && t2 !== null ? t2 - t1 : null;
    const k = reasons.length === 0 ? -Math.log(p2 / p1) / duration : null;
    intervals.push({
      row: i + 1,
      cvd: row[col.cvd],
      pressure,
      temp,
      t1,
      t2,
      p1,
      p2,
      duration,
      loss: p1 !== null && p2 !== null ? p1 - p2 : null,
      rateHour: p1 !== null && p2 !== null && duration > 0 ? ((p1 - p2) / duration) * 60 : null,
      k,
      model,
      included: reasons.length === 0,
      note: reasons.join(" / "),
    });
  }
  return intervals;
}

function fitArrhenius(intervals, model, mode) {
  const valid = intervals.filter((r) => r.included && r.model === model && r.k > 0 && r.temp !== null);
  let points = [];
  if (mode === "average") {
    const groups = new Map();
    for (const r of valid) {
      const key = String(r.temp);
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(r);
    }
    points = Array.from(groups.entries()).map(([temp, rows]) => {
      const totalDuration = rows.reduce((s, r) => s + r.duration, 0);
      const k = rows.reduce((s, r) => s + r.k * r.duration, 0) / totalDuration;
      return { temp: Number(temp), k, count: rows.length, duration: totalDuration };
    });
  } else {
    points = valid.map((r) => ({ temp: r.temp, k: r.k, count: 1, duration: r.duration }));
  }
  const uniqueTemps = new Set(points.map((p) => p.temp));
  if (points.length < 2 || uniqueTemps.size < 2) {
    return { valid: false, model, points, message: "fitting points < 2" };
  }
  const xs = points.map((p) => 1 / (p.temp + 273.15));
  const ys = points.map((p) => Math.log(p.k));
  const n = xs.length;
  const meanX = xs.reduce((a, b) => a + b, 0) / n;
  const meanY = ys.reduce((a, b) => a + b, 0) / n;
  const ssXX = xs.reduce((s, x) => s + (x - meanX) ** 2, 0);
  const ssXY = xs.reduce((s, x, i) => s + (x - meanX) * (ys[i] - meanY), 0);
  const slope = ssXY / ssXX;
  const intercept = meanY - slope * meanX;
  const predicted = xs.map((x) => slope * x + intercept);
  const ssRes = ys.reduce((s, y, i) => s + (y - predicted[i]) ** 2, 0);
  const ssTot = ys.reduce((s, y) => s + (y - meanY) ** 2, 0);
  const r2 = ssTot === 0 ? 0 : 1 - ssRes / ssTot;
  const ea = -slope * R / 1000;
  return {
    valid: true,
    model,
    points,
    slope,
    intercept,
    r2,
    ea,
    minTemp: Math.min(...points.map((p) => p.temp)),
    maxTemp: Math.max(...points.map((p) => p.temp)),
  };
}

function kFromFit(fit, tempC) {
  return Math.exp(fit.intercept + fit.slope * (1 / (tempC + 273.15)));
}

function refitAndRender() {
  state.fits.k1 = fitArrhenius(state.intervals, "k1", state.fitMode);
  state.fits.k2 = fitArrhenius(state.intervals, "k2", state.fitMode);
  renderMetrics();
  renderOverview();
  renderFitTable();
  renderArrheniusChart();
  runPrediction();
  runSchedule();
}

function fitMetric(fit, temp) {
  if (!fit?.valid) return ["fit 없음", "-"];
  return [`Ea ${fit.ea.toFixed(0)} kJ/mol`, `R² ${fit.r2.toFixed(4)} | k@${temp}C ${kFromFit(fit, temp).toExponential(3)} min⁻¹`];
}

function renderMetrics() {
  const temp = Number($("kTemp").value || 390);
  const [k1Main, k1Sub] = fitMetric(state.fits.k1, temp);
  const [k2Main, k2Sub] = fitMetric(state.fits.k2, temp);
  $("k1Metric").textContent = k1Main;
  $("k1Sub").textContent = k1Sub;
  $("k2Metric").textContent = k2Main;
  $("k2Sub").textContent = k2Sub;
  $("includedMetric").textContent = state.intervals.filter((r) => r.included).length;
}

function table(el, columns, rows) {
  el.innerHTML = "";
  const thead = document.createElement("thead");
  const trh = document.createElement("tr");
  columns.forEach(([key, label]) => {
    const th = document.createElement("th");
    th.textContent = label;
    trh.appendChild(th);
  });
  thead.appendChild(trh);
  const tbody = document.createElement("tbody");
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    columns.forEach(([key]) => {
      const td = document.createElement("td");
      const value = row[key];
      td.textContent = typeof value === "number" ? Number(value.toFixed(5)).toString() : (value ?? "");
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  el.append(thead, tbody);
}

function renderOverview() {
  const rows = ["k1", "k2"].map((model) => {
    const fit = state.fits[model];
    return {
      model: model === "k1" ? "k1: 0-120 min" : "k2: After 120 min",
      status: fit?.valid ? "valid" : "invalid",
      slope: fit?.slope,
      intercept: fit?.intercept,
      ea: fit?.ea,
      r2: fit?.r2,
      range: fit?.valid ? `${fit.minTemp}-${fit.maxTemp}` : "",
      count: fit?.points?.length ?? 0,
    };
  });
  table($("overviewTable"), [
    ["model", "model"], ["status", "status"], ["slope", "slope"], ["intercept", "intercept"],
    ["ea", "Ea kJ/mol"], ["r2", "R²"], ["range", "temperature C"], ["count", "points"]
  ], rows);
}

function renderFitTable() {
  const rows = [];
  for (const model of ["k1", "k2"]) {
    const fit = state.fits[model];
    for (const p of fit?.points ?? []) {
      rows.push({ model, temp: p.temp, k: p.k, lnK: Math.log(p.k), x: 1 / (p.temp + 273.15), count: p.count });
    }
  }
  table($("fitTable"), [
    ["model", "model"], ["temp", "Temperature C"], ["k", "k min^-1"], ["lnK", "ln(k)"], ["x", "1/T"], ["count", "n"]
  ], rows);
}

function renderArrheniusChart() {
  const datasets = [];
  for (const [model, color] of [["k1", "#2563eb"], ["k2", "#e04464"]]) {
    const fit = state.fits[model];
    if (!fit?.valid) continue;
    datasets.push({
      type: "scatter",
      label: `${model} points`,
      data: fit.points.map((p) => ({ x: 1 / (p.temp + 273.15), y: Math.log(p.k) })),
      pointRadius: 6,
      backgroundColor: color,
    });
    const xs = fit.points.map((p) => 1 / (p.temp + 273.15));
    const min = Math.min(...xs);
    const max = Math.max(...xs);
    datasets.push({
      type: "line",
      label: `${model} fit`,
      data: Array.from({ length: 50 }, (_, i) => {
        const x = min + (max - min) * i / 49;
        return { x, y: fit.slope * x + fit.intercept };
      }),
      borderColor: color,
      borderWidth: 3,
      pointRadius: 0,
    });
  }
  if (state.charts.arrhenius) state.charts.arrhenius.destroy();
  state.charts.arrhenius = new Chart($("arrheniusChart"), {
    data: { datasets },
    options: {
      maintainAspectRatio: false,
      parsing: { xAxisKey: "x", yAxisKey: "y" },
      scales: { x: { type: "linear", title: { display: true, text: "1/T, K^-1" } }, y: { title: { display: true, text: "ln(k)" } } },
      plugins: { legend: { position: "bottom" } },
    },
  });
}

function compositePrediction(mass, temp, time, unit) {
  if (!state.fits.k1?.valid) throw new Error("k1 fit이 없습니다.");
  const minutes = unit === "hour" ? time * 60 : time;
  if (minutes > 120 && !state.fits.k2?.valid) throw new Error("120분 이후 계산에 필요한 k2 fit이 없습니다.");
  const segments = [];
  let remaining = mass;
  const k1 = kFromFit(state.fits.k1, temp);
  const first = Math.min(minutes, 120);
  if (first > 0) {
    const before = remaining;
    const loss = remaining * (1 - Math.exp(-k1 * first));
    remaining -= loss;
    segments.push({ model: "k1", start: 0, end: first, k: k1, before, loss, remaining });
  }
  if (minutes > 120) {
    const k2 = kFromFit(state.fits.k2, temp);
    const before = remaining;
    const duration = minutes - 120;
    const loss = remaining * (1 - Math.exp(-k2 * duration));
    remaining -= loss;
    segments.push({ model: "k2", start: 120, end: minutes, k: k2, before, loss, remaining });
  }
  return { minutes, segments, loss: mass - remaining, remaining, avgHour: (mass - remaining) / minutes * 60 };
}

function runPrediction() {
  try {
    const mass = Number($("predMass").value);
    const temp = Number($("predTemp").value);
    const time = Number($("predTime").value);
    const unit = $("predUnit").value;
    const pred = compositePrediction(mass, temp, time, unit);
    $("lossOut").textContent = `${pred.loss.toFixed(2)} mg`;
    $("remainOut").textContent = `${pred.remaining.toFixed(2)} mg`;
    $("avgOut").textContent = `${pred.avgHour.toFixed(2)} mg/h`;
    $("predictionDetail").textContent = pred.segments.map((s) => `${s.model}: ${s.start}-${s.end} min, k=${s.k.toExponential(3)} min^-1`).join(" / ");
    renderPredictionChart(mass, pred);
  } catch (error) {
    $("predictionDetail").textContent = error.message;
  }
}

function renderPredictionChart(mass, pred) {
  const dataLoss = [];
  const dataRemain = [];
  for (let i = 0; i <= 100; i++) {
    const t = pred.minutes * i / 100;
    let rem = mass;
    for (const s of pred.segments) {
      if (t <= s.start) break;
      const d = Math.min(t, s.end) - s.start;
      if (d > 0) rem *= Math.exp(-s.k * d);
    }
    dataRemain.push({ x: t, y: rem });
    dataLoss.push({ x: t, y: mass - rem });
  }
  const yValues = [...dataRemain, ...dataLoss].map((p) => p.y);
  const yMin = Math.min(...yValues);
  const yMax = Math.max(...yValues);
  const pad = Math.max(1, (yMax - yMin) * 0.08);
  if (state.charts.prediction) state.charts.prediction.destroy();
  state.charts.prediction = new Chart($("predictionChart"), {
    type: "line",
    data: {
      datasets: [
        { label: "Remaining P", data: dataRemain, borderColor: "#2563eb", borderWidth: 3, pointRadius: 0 },
        { label: "Cumulative loss", data: dataLoss, borderColor: "#e04464", borderWidth: 3, pointRadius: 0 },
      ],
    },
    options: {
      maintainAspectRatio: false,
      parsing: { xAxisKey: "x", yAxisKey: "y" },
      scales: {
        x: { type: "linear", title: { display: true, text: "Time, min" } },
        y: { min: Math.max(0, yMin - pad), max: yMax + pad, title: { display: true, text: "mg" } },
      },
      plugins: { legend: { position: "bottom" } },
    },
  });
}

function formatHour(v) {
  return Number(v.toFixed(8)).toString();
}

function stageParts(start, end) {
  const parts = [];
  if (start < 2) {
    const firstEnd = Math.min(end, 2);
    if (firstEnd > start) parts.push({ model: "k1", duration: firstEnd - start });
  }
  if (end > 2) {
    const secondStart = Math.max(start, 2);
    if (end > secondStart) parts.push({ model: "k2", duration: end - secondStart });
  }
  return parts;
}

function stageLoss(parts, temp, mass, minRemaining = null) {
  let remaining = mass;
  let initialRate = null;
  let finalRate = 0;
  let weightedK = 0;
  let minutesTotal = 0;
  for (const part of parts) {
    const fit = state.fits[part.model];
    const k = kFromFit(fit, temp);
    const minutes = part.duration * 60;
    if (initialRate === null) initialRate = k * remaining * 60;
    let loss = remaining * (1 - Math.exp(-k * minutes));
    if (minRemaining !== null && remaining - loss < minRemaining) loss = Math.max(0, remaining - minRemaining);
    remaining -= loss;
    finalRate = k * remaining * 60;
    weightedK += k * minutes;
    minutesTotal += minutes;
    if (minRemaining !== null && remaining <= minRemaining + 1e-9) break;
  }
  return { loss: mass - remaining, initialRate: initialRate ?? 0, finalRate, k: minutesTotal ? weightedK / minutesTotal : 0 };
}

function temperatureForLoss(parts, targetLoss, mass, startTemp, endTemp) {
  const lowLoss = stageLoss(parts, startTemp, mass).loss;
  const highLoss = stageLoss(parts, endTemp, mass).loss;
  if (targetLoss <= lowLoss) return startTemp;
  if (targetLoss >= highLoss) return endTemp;
  let low = startTemp, high = endTemp;
  for (let i = 0; i < 70; i++) {
    const mid = (low + high) / 2;
    if (stageLoss(parts, mid, mass).loss < targetLoss) low = mid;
    else high = mid;
  }
  return high;
}

function runSchedule() {
  try {
    if (!state.fits.k1?.valid) throw new Error("k1 fit이 없습니다.");
    const initial = Number($("schMass").value);
    const totalHours = Number($("schHours").value);
    const target = Number($("schTarget").value);
    const minRate = Number($("schMinRate").value);
    const minRemaining = Number($("schMinRemain").value);
    const startTemp = Number($("schStart").value);
    const endTemp = Number($("schEnd").value);
    const step = Number($("schStep").value);
    if (totalHours > 2 && !state.fits.k2?.valid) throw new Error("2시간 이후 schedule에는 k2 fit이 필요합니다.");
    const rows = [];
    let elapsed = 0;
    let remaining = initial;
    let cumulative = 0;
    let stage = 1;
    while (elapsed < totalHours - 1e-12) {
      const duration = Math.min(step, totalHours - elapsed);
      const start = elapsed;
      const end = elapsed + duration;
      const parts = stageParts(start, end);
      const pBefore = remaining;
      const allowed = Math.max(0, pBefore - minRemaining);
      const leftTime = Math.max(totalHours - elapsed, duration);
      let stageRate = Math.max((target * totalHours - cumulative) / leftTime, minRate);
      stageRate = Math.min(stageRate, allowed / duration);
      const targetLoss = Math.max(0, Math.min(stageRate * duration, allowed));
      const requiredTemp = temperatureForLoss(parts, targetLoss, pBefore, startTemp, endTemp);
      const temp = Math.max(Math.ceil(startTemp), Math.min(Math.floor(endTemp), Math.ceil(requiredTemp)));
      const calc = stageLoss(parts, temp, pBefore, minRemaining);
      cumulative += calc.loss;
      remaining = Math.max(minRemaining, initial - cumulative);
      const effective = calc.loss / duration;
      const modelUsed = [...new Set(parts.map((p) => p.model))].join("+");
      const within = parts.every((p) => {
        const fit = state.fits[p.model];
        return temp >= fit.minTemp && temp <= fit.maxTemp;
      });
      rows.push({
        stage,
        range: `${formatHour(start)}-${formatHour(end)}`,
        model: modelUsed,
        temp,
        loss: calc.loss,
        before: pBefore,
        remaining,
        cumulative,
        effective,
        initialRate: calc.initialRate,
        finalRate: calc.finalRate,
        k: calc.k,
        minOk: effective >= minRate,
        targetOk: effective >= target * 0.95 && effective <= target * 1.05,
        note: within ? "" : "실험 범위 밖 외삽",
      });
      elapsed = end;
      stage += 1;
    }
    const avg = cumulative / totalHours;
    $("scheduleSummary").textContent = `전체 평균 ${avg.toFixed(2)} mg/h | 최종 잔류량 ${remaining.toFixed(2)} mg | stage ${rows.length}개`;
    table($("scheduleTable"), [
      ["stage", "Stage"], ["range", "Time range"], ["model", "Model"], ["temp", "Temp C"], ["loss", "Stage loss"],
      ["before", "P before"], ["remaining", "Remaining"], ["cumulative", "Cumulative"], ["effective", "Effective mg/h"],
      ["initialRate", "Initial rate"], ["finalRate", "Final rate"], ["k", "k min^-1"], ["minOk", "Min OK"], ["targetOk", "Target OK"], ["note", "비고"]
    ], rows);
  } catch (error) {
    $("scheduleSummary").textContent = error.message;
  }
}

async function analyze() {
  try {
    setStatus("Google Sheet를 읽는 중입니다...");
    const url = $("sheetUrl").value.trim();
    const response = await fetch(csvUrlFromSheet(url));
    if (!response.ok) throw new Error(`CSV 다운로드 실패: ${response.status}`);
    const csv = await response.text();
    const parsed = Papa.parse(csv, { skipEmptyLines: false });
    state.rows = parsed.data;
    state.intervals = parseRows(parsed.data);
    refitAndRender();
    setStatus(`분석 완료: valid ${state.intervals.filter((r) => r.included).length} / total ${state.intervals.length}`, "ok");
  } catch (error) {
    console.error(error);
    setStatus(`${error.message} 공유 권한이 링크 접근 가능인지, URL의 gid가 Codex 탭인지 확인하세요.`, "error");
  }
}

function bind() {
  $("sheetUrl").value = localStorage.getItem("sheetUrl") || DEFAULT_URL;
  $("loadSample").addEventListener("click", () => { $("sheetUrl").value = DEFAULT_URL; analyze(); });
  $("analyzeBtn").addEventListener("click", () => { localStorage.setItem("sheetUrl", $("sheetUrl").value.trim()); analyze(); });
  document.querySelectorAll(".tab").forEach((btn) => btn.addEventListener("click", () => {
    document.querySelectorAll(".tab, .tab-panel").forEach((el) => el.classList.remove("active"));
    btn.classList.add("active");
    $(btn.dataset.tab).classList.add("active");
  }));
  document.querySelectorAll(".fit-mode").forEach((btn) => btn.addEventListener("click", () => {
    document.querySelectorAll(".fit-mode").forEach((el) => el.classList.remove("active"));
    btn.classList.add("active");
    state.fitMode = btn.dataset.mode;
    refitAndRender();
  }));
  ["kTemp", "predMass", "predTemp", "predTime", "predUnit"].forEach((id) => $(id).addEventListener("input", () => { renderMetrics(); runPrediction(); }));
  ["schMass", "schHours", "schTarget", "schMinRate", "schMinRemain", "schStart", "schEnd", "schStep"].forEach((id) => $(id).addEventListener("input", runSchedule));
  $("predictBtn").addEventListener("click", runPrediction);
  $("scheduleBtn").addEventListener("click", runSchedule);
  analyze();
}

bind();
