const STORAGE_KEY = "bistu-full-credit-planner-v1";
const DEFAULT_STATE = { weights: { early8: 5, afternoonFirst: 0, mondayMorning: 3, fridayMorning: 0, fridayAfternoon: 2, fridayEvening: 2, freeDays: 0 }, allow_self_study: true, fixed: {} };
const copy = (value) => JSON.parse(JSON.stringify(value));
const el = (id) => document.getElementById(id);
const app = {
  catalog: [], slots: [], days: [], solution: null, state: copy(DEFAULT_STATE), previous: {},
  lastGood: null, ready: false, solving: false, queued: false, revision: 0, solveTimer: null,
  serverRevision: 0, week: 0, maxWeek: 17, pendingNavigation: null, activeCourseId: null, exporting: false,
};

function escapeHtml(value) {
  return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
}
function showToast(message) {
  const toast = el("toast");
  toast.textContent = message;
  toast.hidden = false;
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => { toast.hidden = true; }, 7000);
}
function setStatus(message, state = "") {
  el("solver-status").textContent = message;
  el("solver-status").dataset.state = state;
}
function setText(id, text) {
  if (el(id)) el(id).textContent = text;
}
function savePlan() {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify({week:app.week})); } catch {}
}
function assignmentFor(course) {
  return app.solution?.assignments?.[course.id] ?? { kind: "unassigned", label: "待计算", events: [] };
}
function courseUrl(courseId) {
  return "/courses.html?course=" + encodeURIComponent(courseId);
}
function eventTimeText(event) {
  return (event.kind === "lab" ? "实验 · " : "") + String(event.weeks_text) + " " + app.days[event.day] + " 第" + event.start + "-" + event.end + "节";
}
function optionComplete(option) { return Boolean(option.events?.length); }
function capacityText(option) {
  return Number.isInteger(option?.capacity) && option.capacity >= 0 ? "总容量 " + option.capacity + " 人" : "";
}
function optionText(option, index) {
  const times = option.events.map(eventTimeText).join(" + ");
  const capacity = capacityText(option);
  const teacher = TimetableLayout.teacherText(option);
  return (index + 1) + ". " + (capacity ? capacity + " · " : "") + times + (teacher ? " · " + teacher : "");
}
function chooseCourse(id, choice) {
  const course = app.catalog.find((item) => item.id === id);
  if (!course || !app.ready) return;
  if (choice === "self-study") {
    if (!app.state.allow_self_study) return;
    if (Object.entries(app.state.fixed).filter(([key, value]) => key !== id && value === "self-study").length >= 2) {
      showToast("最多只能选择两门自主学习课程");
      renderCourseList();
      renderAlternatives();
      return;
    }
  } else if (choice !== "auto" && !course.options.some((option) => option.id === choice && optionComplete(option))) return;
  if (choice === "auto") delete app.state.fixed[id];
  else app.state.fixed[id] = choice;
  markChanged();
}
function highlightActiveCourse() {
  document.querySelectorAll(".event-card").forEach((card) => {
    const selected = card.dataset.courseId === app.activeCourseId;
    card.classList.toggle("is-selected", selected);
    card.setAttribute("aria-expanded", String(selected));
  });
}
function openAlternatives(id) {
  if (!el("course-alternatives") || !app.catalog.some((course) => course.id === id)) return;
  if (app.activeCourseId !== id) {
    el("alternative-search").value = "";
    el("alternative-options").scrollTop = 0;
  }
  app.activeCourseId = id;
  renderAlternatives();
  highlightActiveCourse();
  el("close-alternatives").focus({ preventScroll: true });
}
function closeAlternatives() {
  const id = app.activeCourseId;
  app.activeCourseId = null;
  renderAlternatives();
  highlightActiveCourse();
  const card = [...document.querySelectorAll(".event-card")].find((item) => item.dataset.courseId === id);
  (card || document.querySelector(".timetable-wrap"))?.focus({ preventScroll: true });
}
function renderAlternatives() {
  const panel = el("course-alternatives");
  if (!panel) return;
  const course = app.catalog.find((item) => item.id === app.activeCourseId);
  panel.hidden = !course;
  el("schedule-layout").classList.toggle("is-editing", !!course);
  if (!course) return;
  const assignment = assignmentFor(course);
  const choice = app.state.fixed[course.id];
  setText("alternatives-title", course.name);
  setText("alternatives-meta", course.code + " · " + course.options.length + " 个班次");
  el("alternative-course-link").href = courseUrl(course.id);
  el("alternative-auto").disabled = !choice;
  el("alternative-self-study").hidden = !app.state.allow_self_study;
  el("alternative-self-study").disabled = choice === "self-study";
  el("alternative-self-study").textContent = choice === "self-study" && assignment.kind !== "self-study" ? "计算中" : "自主学习";
  const query = el("alternative-search").value.trim().toLowerCase();
  const groups = TimetableLayout.groupAlternatives(course.options, assignment.option_id);
  const focusedChoice = panel.contains(document.activeElement) ? document.activeElement.dataset.choice : null;
  const scrollTop = el("alternative-options").scrollTop;
  el("alternative-options").innerHTML = [["same", "相同时间"], ["other", assignment.option_id ? "其他时间" : "可选班次"]].map(([key, label]) => {
    const items = groups[key].filter(({ option, index }) => [TimetableLayout.teacherText(option), option.label, "班次 " + (index + 1), ...option.events.flatMap((event) => [TimetableLayout.teacherText(event), event.room, eventTimeText(event)])].join(" ").toLowerCase().includes(query));
    if (!items.length) return "";
    return '<section class="alternative-group" data-group="' + key + '"><h3>' + label + ' · ' + items.length + '</h3>' + items.map(({ option, index, isCurrent }) => {
      const teacher = option.teacher || [...new Set(option.events.map((event) => event.teacher).filter(Boolean))].join("、") || "教师待定";
      const pending = choice === option.id && !isCurrent;
      const fixed = choice === option.id && isCurrent;
      const buttonLabel = !optionComplete(option) ? "时间待补全" : pending ? "计算中" : fixed ? "已固定" : isCurrent ? "固定此班" : "选择";
      return '<article class="alternative-option" data-option-id="' + escapeHtml(option.id) + '" aria-current="' + isCurrent + '">' +
        '<div class="alternative-option-heading"><div><h4>' + escapeHtml(TimetableLayout.teacherText(option) || teacher) + '</h4><span class="course-code">班次 ' + (index + 1) + '</span></div>' +
        (isCurrent ? '<span class="alternative-current">当前班次</span>' : '') + '</div>' +
        '<ul class="assignment-times">' + option.events.map((event) => '<li>' + escapeHtml([eventTimeText(event), event.room, event.teacher && event.teacher !== teacher ? TimetableLayout.teacherText(event) : ""].filter(Boolean).join(" · ")) + '</li>').join("") + '</ul>' +
        '<div class="alternative-option-footer"><span class="class-capacity">' + capacityText(option) + '</span><button class="button" data-choice="' + escapeHtml(option.id) + '" aria-label="' + escapeHtml(buttonLabel + "班次 " + (index + 1) + "，" + teacher) + '"' + (pending || fixed || !optionComplete(option) ? ' disabled' : '') + '>' + buttonLabel + '</button></div></article>';
    }).join("") + '</section>';
  }).join("") || '<div class="empty-list">' + (course.options.length ? "无匹配班次" : "无课表记录") + '</div>';
  el("alternative-options").scrollTop = scrollTop;
  // 计算结果更新列表时保留键盘位置；当前按钮变为禁用时退回关闭按钮。
  if (focusedChoice) {
    const button = [...panel.querySelectorAll("button[data-choice]")].find((item) => item.dataset.choice === focusedChoice && !item.disabled);
    (button || el("close-alternatives")).focus({ preventScroll: true });
  }
}
function renderCourseList() {
  const container = el("course-list");
  if (!container) return;
  const query = el("course-search").value.trim().toLowerCase();
  const visible = app.catalog.filter((course) => (course.name + " " + course.code + " " + course.module).toLowerCase().includes(query));
  setText("course-count", app.catalog.length + " 门");
  container.innerHTML = visible.map((course) => {
    const assignment = assignmentFor(course);
    const fixed = app.state.fixed[course.id];
    const options = course.options.map((option, index) => '<option value="' + escapeHtml(option.id) + '"' + (optionComplete(option) ? '' : ' disabled') + '>' + escapeHtml(optionText(option, index) + (optionComplete(option) ? '' : ' · 时间待补全')) + "</option>").join("");
    const selfItem = app.state.allow_self_study ? '<option value="self-study">自主学习</option>' : "";
    const choiceIndex = course.options.findIndex((option) => option.id === assignment.option_id);
    const label = assignment.kind === "option" ? (fixed ? "已固定" : "自动") + " · 班次 " + (choiceIndex + 1) : assignment.label;
    const capacity = capacityText(course.options[choiceIndex]);
    return '<article class="course-row" id="course-' + escapeHtml(course.id) + '" data-course-id="' + escapeHtml(course.id) + '">' +
      '<div><div class="course-title"><h3>' + escapeHtml(course.name) + '</h3><span class="course-code">' + escapeHtml(course.code) + '</span></div>' +
      '<div class="course-meta"><span>' + escapeHtml(course.module) + '</span><span>' + course.credits + ' 学分</span><span>' + course.hours + ' 学时</span><span>' + course.options.length + ' 个班次</span></div></div>' +
      '<div class="course-selection"><select class="course-select" data-course-id="' + escapeHtml(course.id) + '" aria-label="调整 ' + escapeHtml(course.name) + '"><option value="auto">自动</option>' + selfItem + options + '</select>' +
      '<div class="assignment-details"><span class="assignment-chip ' + escapeHtml(assignment.kind) + '">' + escapeHtml(label) + '</span>' +
      (capacity ? '<span class="class-capacity">' + capacity + '</span>' : '') + '</div>' +
      '<ul class="assignment-times">' + (assignment.events ?? []).map((event) => '<li>' + escapeHtml(eventTimeText(event) + " · " + [TimetableLayout.teacherText(event), event.room].filter(Boolean).join(" · ")) + "</li>").join("") + "</ul></div></article>";
  }).join("") || '<div class="empty-list">无匹配课程</div>';
  container.querySelectorAll(".course-select").forEach((select) => {
    select.value = app.state.fixed[select.dataset.courseId] ?? "auto";
  });
}
function renderTimetable() {
  const container = el("timetable");
  if (!container) return;
  // 背景、星期、节次和事件全部显式定位。自动定位会避让课程卡片，导致整张表错位。
  const cells = ['<div class="time-header" style="grid-row:1;grid-column:1">节次</div>'];
  app.days.forEach((day, index) => cells.push('<div class="day-header" style="grid-row:1;grid-column:' + (index + 2) + '">' + escapeHtml(day) + "</div>"));
  app.slots.forEach((slot) => {
    const sessionClass = [6, 11].includes(slot.index) ? " session-start" : "";
    cells.push('<div class="time-cell' + sessionClass + '" data-slot="' + slot.index + '" style="grid-row:' + (slot.index + 1) + ';grid-column:1"><strong>' + slot.index + '</strong><span>' + slot.start + '</span><span>' + slot.end + "</span></div>");
    for (let day = 0; day < 7; day += 1) {
      cells.push('<div class="calendar-cell' + sessionClass + (day > 4 ? " weekend" : "") + '" data-day="' + day + '" data-slot="' + slot.index + '" style="grid-row:' + (slot.index + 1) + ';grid-column:' + (day + 2) + '"></div>');
    }
  });
  const positioned = TimetableLayout.positionEvents(app.solution?.events ?? [], app.week);
  const cards = positioned.map(({ event, lane, laneCount }) => {
    const color = Math.max(0, app.catalog.findIndex((course) => course.id === event.course_id)) % 8;
    const course = app.catalog.find((item) => item.id === event.course_id);
    const assignment = course ? assignmentFor(course) : null;
    const optionIndex = course?.options.findIndex((option) => option.id === assignment?.option_id);
    const label = event.course_code + (optionIndex >= 0 ? " · 班次 " + (optionIndex + 1) : "");
    const capacity = capacityText(course?.options[optionIndex]);
    const location = [event.room, TimetableLayout.teacherText(event)].filter(Boolean).join(" · ");
    const title = [event.course_name, label, eventTimeText(event), location, capacity].filter(Boolean).join("\n");
    return '<a class="event-card course-tone-' + color + (capacity ? " has-capacity" : "") + (event.start === event.end ? " short-event" : "") +
      '" href="' + courseUrl(event.course_id) + '" data-day="' + event.day + '" data-start="' + event.start + '" data-end="' + event.end +
      '" data-course-id="' + escapeHtml(event.course_id) + '" data-lane="' + lane + '" data-lanes="' + laneCount +
      '" style="grid-column:' + (event.day + 2) + ';grid-row:' + (event.start + 1) + ' / span ' + (event.end - event.start + 1) + ';--lane:' + lane + ';--lane-count:' + laneCount +
      '" title="' + escapeHtml(title) + '" aria-controls="course-alternatives" aria-label="' + escapeHtml(title) + '"><strong class="event-title">' + escapeHtml(event.course_name) +
      '</strong><span class="event-weeks">' + escapeHtml(event.weeks_text) + ' · ' + event.start + "-" + event.end +
      '节</span><span class="event-place">' + escapeHtml(location || label) + '</span>' +
      (capacity ? '<span class="event-capacity">' + capacity + '</span>' : '') + '</a>';
  });
  container.innerHTML = cells.join("") + cards.join("");
  highlightActiveCourse();
  setText("calendar-title", app.week ? "第 " + app.week + " 周" : "学期课表");
  el("week-empty").hidden = !app.solution || positioned.length > 0;
  el("week-select").value = String(app.week);
  el("previous-week").disabled = !app.ready || app.week <= 1;
  el("next-week").disabled = !app.ready || app.week >= app.maxWeek;
  const groups = [["self-study", "自主学习"], ["unassigned", "无课表记录"]].map(([kind, label]) => {
    const courses = app.catalog.filter((course) => assignmentFor(course).kind === kind);
    if (!courses.length || !app.solution) return "";
    return '<div><h2>' + label + " · " + courses.length + '</h2><ul>' + courses.map((course) => '<li><a href="' + courseUrl(course.id) + '">' + escapeHtml(course.name) + "</a></li>").join("") + "</ul></div>";
  }).join("");
  el("off-grid").innerHTML = groups;
  el("off-grid").hidden = !groups;
}
function renderPreferences() {
  if (!el("weight-controls")) return;
  for (const [key, value] of Object.entries(app.state.weights)) {
    el(key).value = value;
    el(key + "-value").value = value;
  }
  el("self-study-toggle").checked = app.state.allow_self_study;
  if (app.solution) {
    setText("scheduled-count", app.solution.scheduled_count);
    setText("self-study-metric", app.solution.self_study_count);
    setText("unassigned-count", app.solution.unassigned_count);
    setText("self-study-count", app.solution.self_study_count + "/2");
    setText("solve-time", app.solution.elapsed_ms + " ms");
  }
}
function renderAll() {
  renderFreeDays();
  renderCourseList();
  renderTimetable();
  renderPreferences();
  renderAlternatives();
  updateExportButtons();
}
function weekRanges(weeks) {
  const ranges = [];
  for (const week of weeks) {
    const last = ranges[ranges.length - 1];
    if (last && week === last[1] + 1) last[1] = week;
    else ranges.push([week, week]);
  }
  return ranges.map(([first,last]) => first === last ? String(first) : first + "–" + last).join("、");
}
function freeDayGroups(rows, field, days) {
  const groups = new Map();
  for (const row of rows) {
    if (!row[field].length) continue;
    const key = row[field].join(",");
    if (!groups.has(key)) groups.set(key, { weeks: [], days: row[field] });
    groups.get(key).weeks.push(row.week);
  }
  return [...groups.values()].map((group) => "第 " + weekRanges(group.weeks) + " 周：" + group.days.map((day) => days[day]).join("、"));
}
function renderFreeDays() {
  if (!el("free-weekdays")) return;
  const summary = app.solution?.day_off;
  if (!summary) return;
  const rows = summary.rows.filter((row) => !app.week || row.week === app.week);
  setText("free-days-range", app.week ? "第 " + app.week + " 周" : summary.first_week === null ? "暂无课程时间" : "第 " + summary.first_week + "–" + summary.last_week + " 周");
  for (const [field, listId, countId] of [["weekdays", "free-weekdays", "free-weekday-count"], ["weekends", "free-weekends", "free-weekend-count"]]) {
    const groups = freeDayGroups(rows, field, app.days);
    setText(countId, rows.reduce((total, row) => total + row[field].length, 0) + " 天");
    el(listId).innerHTML = groups.length ? groups.map((text) => '<span class="free-day-group">' + escapeHtml(text) + '</span>').join("") : rows.length ? "无" : "该周无课程时间数据";
  }
}
function updateExportButtons() {
  for (const format of ["xlsx", "png"]) {
    const button = el("export-" + format);
    if (button) button.disabled = !app.solution || app.solving || app.queued || !!app.solveTimer || app.exporting;
  }
}
async function exportTimetable(format) {
  if (!app.solution || app.solving || app.queued || app.solveTimer || app.exporting) return;
  // 异步生成前拍下已成功求解的结果；后续修改不能混入这份导出。
  const snapshot = copy({catalog:app.catalog, solution:app.solution, week:app.week, days:app.days, slots:app.slots});
  app.exporting = true;
  updateExportButtons();
  const button = el("export-" + format), label = button.textContent;
  button.textContent = "导出中";
  try {
    await TimetableExport.download(snapshot, format);
  } catch (error) {
    showToast(error.message || "导出失败，请重试");
  } finally {
    app.exporting = false;
    button.textContent = label;
    updateExportButtons();
  }
}
function focusRequestedCourse() {
  const id = new URLSearchParams(location.search).get("course");
  const row = id && el("course-" + id);
  if (!row || focusRequestedCourse.done) return;
  focusRequestedCourse.done = true;
  row.classList.add("is-target");
  row.scrollIntoView({ block: "center" });
  row.querySelector("select").focus({ preventScroll: true });
}
function markChanged(delay = 0) {
  // 修改时立即增加版本号。旧请求返回后只能启动最新一次计算，不能覆盖新输入。
  app.revision += 1;
  app.queued = true;
  savePlan();
  updateExportButtons();
  setStatus("等待计算", "busy");
  renderAlternatives();
  clearTimeout(app.solveTimer);
  if (delay) app.solveTimer = setTimeout(solveNow, delay);
  else solveNow();
}
async function solveNow() {
  clearTimeout(app.solveTimer);
  app.solveTimer = null;
  if (!app.ready) return;
  app.queued = true;
  if (app.solving) return;
  app.solving = true;
  updateExportButtons();
  app.queued = false;
  const revision = app.revision;
  const requested = copy(app.state);
  el("solve-button").disabled = true;
  setStatus("计算中", "busy");
  let succeeded = false;
  try {
    const response = await fetch("/api/solve", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...requested, previous: app.previous, revision: app.serverRevision }),
    });
    const payload = await response.json();
    if (!response.ok || payload.error) throw new Error(payload.error || "计算失败");
    if (revision !== app.revision) return;
    const savedResponse = await fetch('/api/plan', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({solution:payload.solution,state:requested,revision:payload.revision})});
    const saved = await savedResponse.json();
    if (!savedResponse.ok) throw new Error(saved.error || '课表保存失败');
    app.serverRevision = saved.revision;
    app.solution = payload.solution;
    app.lastGood = copy(requested);
    app.previous = Object.fromEntries(Object.entries(app.solution.assignments).filter(([, assignment]) => assignment.option_id).map(([id, assignment]) => [id, assignment.option_id]));
    savePlan();
    setStatus(app.solution.status === "optimal" ? "已求得最优解" : "已求得可行解", "ready");
    el("toast").hidden = true;
    renderAll();
    focusRequestedCourse();
    succeeded = true;
  } catch (error) {
    if (revision !== app.revision) return;
    app.pendingNavigation = null;
    setStatus("调整未生效", "error");
    if (app.lastGood) {
      app.state = copy(app.lastGood);
      savePlan();
      renderAll();
    }
    showToast(error.message);
  } finally {
    app.solving = false;
    el("solve-button").disabled = false;
    if (app.queued || revision !== app.revision) {
      app.queued = false;
      solveNow();
    } else if (succeeded && app.pendingNavigation) {
      location.assign(app.pendingNavigation);
    }
    updateExportButtons();
  }
}
function bindControls() {
  el("export-xlsx")?.addEventListener("click", () => exportTimetable("xlsx"));
  el("export-png")?.addEventListener("click", () => exportTimetable("png"));
  el("solve-button").addEventListener("click", () => {
    if (!app.ready) load();
    else solveNow();
  });
  el("course-search")?.addEventListener("input", renderCourseList);
  el("course-list")?.addEventListener("change", (event) => {
    const select = event.target.closest(".course-select");
    if (!select) return;
    chooseCourse(select.dataset.courseId, select.value);
  });
  el("close-alternatives")?.addEventListener("click", closeAlternatives);
  el("alternative-search")?.addEventListener("input", renderAlternatives);
  el("alternative-auto")?.addEventListener("click", () => chooseCourse(app.activeCourseId, "auto"));
  el("alternative-self-study")?.addEventListener("click", () => chooseCourse(app.activeCourseId, "self-study"));
  el("alternative-options")?.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-choice]");
    if (button && !button.disabled) chooseCourse(app.activeCourseId, button.dataset.choice);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && app.activeCourseId) {
      event.preventDefault();
      closeAlternatives();
    }
  });
  for (const key of Object.keys(DEFAULT_STATE.weights)) {
    el(key)?.addEventListener("input", (event) => {
      app.state.weights[key] = Number(event.target.value);
      el(key + "-value").value = event.target.value;
      markChanged(260);
    });
  }
  el("self-study-toggle")?.addEventListener("change", (event) => {
    app.state.allow_self_study = event.target.checked;
    if (!event.target.checked) {
      for (const [id, value] of Object.entries(app.state.fixed)) {
        if (value === "self-study") delete app.state.fixed[id];
      }
    }
    markChanged();
  });
  function setWeek(week) {
    app.week = week;
    savePlan();
    renderFreeDays();
    renderTimetable();
    el("timetable").parentElement.scrollTop = 0;
  }
  el("week-select")?.addEventListener("change", (event) => setWeek(Number(event.target.value)));
  el("previous-week")?.addEventListener("click", () => setWeek(Math.max(1, app.week - 1)));
  el("next-week")?.addEventListener("click", () => setWeek(Math.min(app.maxWeek, app.week + 1)));
  document.addEventListener("click", (event) => {
    const link = event.target.closest('a[href]');
    if (!link || link.hasAttribute("download") || event.button || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    if (link.classList.contains("event-card") && el("course-alternatives")) {
      event.preventDefault();
      openAlternatives(link.dataset.courseId);
      return;
    }
    if (app.solving || app.queued || app.solveTimer) {
      event.preventDefault();
      app.pendingNavigation = link.href;
      if (!app.solving) solveNow();
    }
  });
  window.addEventListener("storage", (event) => {
    if (event.key === STORAGE_KEY && app.ready && !app.solving && !app.queued) load();
  });
}
async function load() {
  el("solve-button").disabled = true;
  try {
    const response = await fetch("/api/catalog");
    const payload = await response.json();
    if (!response.ok || payload.error) throw new Error(payload.error || "课程数据加载失败");
    app.catalog = payload.courses;
    app.slots = payload.slots;
    app.days = payload.days;
    app.maxWeek = Math.max(17, ...app.catalog.flatMap((course) => course.options.flatMap((option) => option.events.flatMap((event) => event.weeks))));
    app.serverRevision = payload.revision;
    app.state = copy(payload.state);
    app.solution = payload.solution;
    app.lastGood = copy(app.state);
    app.previous = Object.fromEntries(Object.entries(app.solution?.assignments || {}).filter(([,a])=>a.option_id).map(([id,a])=>[id,a.option_id]));
    try { app.week = Math.min(app.maxWeek, Math.max(0, Number(JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}').week) || 0)); } catch {}
    setText('term-label', payload.term || '课程安排');
    if (el("week-select")) {
      el("week-select").innerHTML = '<option value="0">学期总览</option>' + Array.from({ length: app.maxWeek }, (_, i) => '<option value="' + (i + 1) + '">第 ' + (i + 1) + " 周</option>").join("");
    }
    app.ready = true;
    for (const id of ["course-search", "week-select", "weight-controls", "self-study-toggle"]) {
      if (el(id)) el(id).disabled = false;
    }
    renderAll();
    if (app.solution) {
      setStatus('已保存的课表', 'ready');
      el('solve-button').disabled = false;
    } else if (app.catalog.length) await solveNow();
    else {
      setStatus('暂无课程', 'ready');
      app.ready = false;
      el('solve-button').disabled = true;
      for (const id of ['weight-controls','self-study-toggle','week-select']) if(el(id)) el(id).disabled=true;
      for (const id of ['free-weekdays','free-weekends','free-days-range']) setText(id,'—');
    }
  } catch (error) {
    setStatus("加载失败", "error");
    showToast(error.message);
    el("solve-button").disabled = false;
  }
}
bindControls();
load();
