const state = {
  courses: [],
  nav: {},      // course_id -> { path: [{id,name}], childrenOf: {} }
  files: {},    // folder_id -> [files]
  selected: {}, // course_id -> { course_name, whole, folder_ids:Set, file_ids:Set }
  outputDir: "downloads",
};

const api = () => window.pywebview.api;
const el = (id) => document.getElementById(id);

const CARET_SVG =
  '<svg viewBox="0 0 16 16" width="16" height="16"><path d="M4 6l4 4 4-4" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
const FOLDER_SVG =
  '<svg class="icon-folder" viewBox="0 0 48 38" xmlns="http://www.w3.org/2000/svg"><path d="M3 6a3 3 0 0 1 3-3h11l4 5h21a3 3 0 0 1 3 3v20a3 3 0 0 1-3 3H6a3 3 0 0 1-3-3z"/></svg>';
const FILE_SVG =
  '<svg class="icon-file" viewBox="0 0 36 46" xmlns="http://www.w3.org/2000/svg"><path class="body" d="M5 4a3 3 0 0 1 3-3h14l11 11v30a3 3 0 0 1-3 3H8a3 3 0 0 1-3-3z"/><path class="fold" d="M22 1l11 11h-8a3 3 0 0 1-3-3z"/></svg>';

/* selection helpers */
function entryFor(course) {
  return (state.selected[course.id] = state.selected[course.id] || {
    course_name: course.name, whole: false,
    folder_ids: new Set(), file_ids: new Set(),
  });
}
const isWhole = (cid) => !!(state.selected[cid] && state.selected[cid].whole);
const isFolderSelected = (cid, fid) => !!(state.selected[cid] && state.selected[cid].folder_ids.has(fid));
const isFileSelected = (cid, fid) => !!(state.selected[cid] && state.selected[cid].file_ids.has(fid));

function cleanup(cid) {
  const e = state.selected[cid];
  if (e && !e.whole && e.folder_ids.size === 0 && e.file_ids.size === 0) delete state.selected[cid];
}
function courseHasSelection(cid) {
  const e = state.selected[cid];
  return !!(e && (e.whole || e.folder_ids.size || e.file_ids.size));
}
function setWhole(course, v) { entryFor(course).whole = v; cleanup(course.id); updateDownloadButton(); }
function toggleFolder(course, fid, v) { const e = entryFor(course); v ? e.folder_ids.add(fid) : e.folder_ids.delete(fid); cleanup(course.id); updateDownloadButton(); }
function toggleFile(course, fid, v) { const e = entryFor(course); v ? e.file_ids.add(fid) : e.file_ids.delete(fid); cleanup(course.id); updateDownloadButton(); }

function refreshCard(node) {
  const card = node.closest(".course-card");
  if (!card) return;
  const cid = Number(card.dataset.courseId);
  card.classList.toggle("selected", courseHasSelection(cid));
  const cb = card.querySelector(".course-head > input[type=checkbox]");
  if (cb) cb.checked = isWhole(cid);
}

/* theme picker */
const THEME_ACCENTS = [
  ["red", "#ef5a45"], ["orange", "#e88b30"], ["yellow", "#f4d24c"], ["green", "#77e08a"],
  ["blue", "#5b9cf0"], ["purple", "#b473f0"], ["pink", "#ec4c96"],
];

function accentSoft(hex) {
  const c = hex.replace("#", "");
  const r = parseInt(c.substr(0, 2), 16), g = parseInt(c.substr(2, 2), 16), b = parseInt(c.substr(4, 2), 16);
  return `rgba(${r}, ${g}, ${b}, 0.14)`;
}
function accentDeep(hex) {
  const c = hex.replace("#", "");
  const f = (i) => Math.max(0, Math.round(parseInt(c.substr(i, 2), 16) * 0.82)).toString(16).padStart(2, "0");
  return `#${f(0)}${f(2)}${f(4)}`;
}
function onAccentFor(hex) {
  const c = hex.replace("#", "");
  const r = parseInt(c.substr(0, 2), 16), g = parseInt(c.substr(2, 2), 16), b = parseInt(c.substr(4, 2), 16);
  return (0.299 * r + 0.587 * g + 0.114 * b) / 255 > 0.6 ? "#191308" : "#ffffff";
}

function applyTheme(mode, accentKey) {
  const root = document.documentElement;
  root.setAttribute("data-mode", mode);
  let accent;
  if (accentKey === "mono") accent = mode === "dark" ? "#e8eaf0" : "#1a1c24";
  else accent = (THEME_ACCENTS.find((a) => a[0] === accentKey) || [])[1] || "#f5b544";
  root.style.setProperty("--accent", accent);
  root.style.setProperty("--accent-deep", accentDeep(accent));
  root.style.setProperty("--accent-soft", accentSoft(accent));
  root.style.setProperty("--on-accent", onAccentFor(accent));
  localStorage.setItem("cfg-theme", JSON.stringify({ mode, accentKey }));
  markActiveSwatch(mode, accentKey);
}

function markActiveSwatch(mode, accentKey) {
  document.querySelectorAll(".swatch").forEach((s) =>
    s.classList.toggle("active", s.dataset.mode === mode && s.dataset.accent === accentKey));
}

function makeSwatch(container, mode, accentKey, top, fill) {
  const s = document.createElement("button");
  s.className = "swatch";
  s.dataset.mode = mode;
  s.dataset.accent = accentKey;
  s.style.background = `linear-gradient(135deg, ${top} 0 50%, ${fill} 50% 100%)`;
  s.addEventListener("click", () => applyTheme(mode, accentKey));
  container.appendChild(s);
}

function buildThemeUI() {
  const dark = el("dark-swatches"), light = el("light-swatches"), mono = el("mono-swatches");
  THEME_ACCENTS.forEach(([key, hex]) => makeSwatch(dark, "dark", key, "#141414", hex));
  THEME_ACCENTS.forEach(([key, hex]) => makeSwatch(light, "light", key, "#ffffff", hex));
  makeSwatch(mono, "dark", "mono", "#141414", "#ffffff");
  makeSwatch(mono, "light", "mono", "#ffffff", "#141414");

  el("settings-btn").addEventListener("click", () => el("theme-modal").classList.remove("hidden"));
  el("theme-close").addEventListener("click", () => el("theme-modal").classList.add("hidden"));
  el("theme-modal").addEventListener("click", (e) => {
    if (e.target.id === "theme-modal") el("theme-modal").classList.add("hidden");
  });

  // Restore saved choices, or fall back to the default dark/amber theme.
  const saved = JSON.parse(localStorage.getItem("cfg-theme") || "null");
  if (saved) applyTheme(saved.mode, saved.accentKey);
}

/* init */
async function init() {
  buildThemeUI();

  const s = await api().status();
  state.outputDir = s.output_dir;
  el("folder-path").textContent = s.output_dir;
  if (s.logged_in) showMain();
  else el("login-view").classList.remove("hidden");

  el("login-btn").addEventListener("click", onLogin);
  el("show-past").addEventListener("change", renderCourses);
  el("folder-btn").addEventListener("click", onChooseFolder);
  el("download-btn").addEventListener("click", onDownload);
}

async function onLogin() {
  el("login-status").textContent = "A browser window opened. Finish logging in there.";
  el("login-btn").disabled = true;
  await api().start_login();
  // From here, Python pushes state changes via window.onLoginStateChange
  // (see below) instead of us polling, since this window is backgrounded
  // for the whole time the user is in the separate SSO browser window, and
  // a setTimeout poll loop can be throttled or suspended while backgrounded.
}

// Called directly by the Python side (Api._set_login_state) as the login
// moves through its stages, so the UI updates even while this window is
// not focused.
window.onLoginStateChange = function (s) {
  if (s.stage === "waiting_for_browser") return;

  if (s.stage === "validating") {
    // The Chrome window just closed itself; move off the login screen right
    // away instead of leaving the user staring at it during the brief
    // session check that follows.
    el("login-view").classList.add("hidden");
    el("loading-view").classList.remove("hidden");
    return;
  }

  // stage === "done"
  if (s.logged_in) {
    showMain();
  } else {
    el("loading-view").classList.add("hidden");
    el("login-view").classList.remove("hidden");
    el("login-status").textContent = "Login did not complete. Try again.";
    el("login-btn").disabled = false;
  }
};

async function showMain() {
  // Show the loading interstitial the moment login resolves, so the user
  // never sits on the login page while the courses are fetched.
  el("login-view").classList.add("hidden");
  el("main-view").classList.add("hidden");
  el("loading-view").classList.remove("hidden");
  try {
    state.courses = await api().get_courses();
  } catch (e) {
    state.courses = [];
  }
  el("loading-view").classList.add("hidden");
  el("main-view").classList.remove("hidden");
  renderCourses();
}

function renderCourses() {
  const showPast = el("show-past").checked;
  const list = el("course-list");
  list.innerHTML = "";
  const courses = state.courses.filter((c) => showPast || !c.is_past);
  if (courses.length === 0) { list.innerHTML = "<p class='muted pad'>No courses found.</p>"; return; }
  courses.forEach((c) => list.appendChild(courseCard(c)));
  updateDownloadButton();
}

function courseCard(course) {
  const card = document.createElement("div");
  card.className = "course-card";
  card.dataset.courseId = course.id;
  if (courseHasSelection(course.id)) card.classList.add("selected");

  const head = document.createElement("div");
  head.className = "course-head";

  const cb = document.createElement("input");
  cb.type = "checkbox";
  cb.title = "Select the whole course";
  cb.checked = isWhole(course.id);
  cb.addEventListener("change", () => { setWhole(course, cb.checked); refreshCard(cb); });

  const title = document.createElement("div");
  title.className = "course-title";
  const name = document.createElement("span");
  name.className = "name";
  name.textContent = course.name;
  title.appendChild(name);
  if (course.term) { const t = document.createElement("small"); t.textContent = course.term; title.appendChild(t); }
  if (course.is_past) { const tag = document.createElement("span"); tag.className = "tag"; tag.textContent = "past"; title.appendChild(tag); }

  const caret = document.createElement("button");
  caret.className = "caret";
  caret.setAttribute("aria-label", "Show folders");
  caret.innerHTML = CARET_SVG;

  const browser = document.createElement("div");
  browser.className = "browser hidden";

  caret.addEventListener("click", () => {
    const open = !browser.classList.toggle("hidden");
    caret.classList.toggle("open", open);
    if (open) openBrowser(course, browser);
  });

  head.append(cb, title, caret);
  card.append(head, browser);
  return card;
}

async function openBrowser(course, browser) {
  if (!state.nav[course.id]) {
    browser.innerHTML = "<p class='muted pad'>Loading folders...</p>";
    const folders = await api().get_folders(course.id);
    const childrenOf = {};
    folders.forEach((f) => {
      const key = f.parent_id === null ? "root" : String(f.parent_id);
      (childrenOf[key] = childrenOf[key] || []).push(f);
    });
    Object.values(childrenOf).forEach((a) => a.sort((x, y) => x.name.localeCompare(y.name)));
    state.nav[course.id] = { path: [], childrenOf };
  }
  renderBrowser(course, browser);
}

function buildCrumb(course, browser) {
  const nav = state.nav[course.id];
  const crumb = document.createElement("div");
  crumb.className = "crumb";
  const root = document.createElement("button");
  root.className = "crumb-link";
  root.textContent = course.name;
  root.addEventListener("click", () => { nav.path = []; renderBrowser(course, browser); });
  crumb.appendChild(root);
  nav.path.forEach((p, i) => {
    const sep = document.createElement("span"); sep.className = "crumb-sep"; sep.textContent = "/";
    const link = document.createElement("button"); link.className = "crumb-link"; link.textContent = p.name;
    link.addEventListener("click", () => { nav.path = nav.path.slice(0, i + 1); renderBrowser(course, browser); });
    crumb.append(sep, link);
  });
  return crumb;
}

async function renderBrowser(course, browser) {
  const nav = state.nav[course.id];
  const inside = nav.path.length > 0;
  const currentId = inside ? nav.path[nav.path.length - 1].id : null;
  const key = inside ? String(currentId) : "root";
  const folders = nav.childrenOf[key] || [];

  let files = [];
  if (inside) {
    if (!state.files[currentId]) {
      browser.innerHTML = "<p class='muted pad'>Loading...</p>";
      state.files[currentId] = await api().get_files(currentId);
    }
    files = state.files[currentId];
  }

  browser.innerHTML = "";
  browser.appendChild(buildCrumb(course, browser));

  const grid = document.createElement("div");
  grid.className = "grid";
  folders.forEach((f) => grid.appendChild(folderTile(course, f, browser)));
  files.forEach((f) => grid.appendChild(fileTile(course, f)));
  if (folders.length === 0 && files.length === 0) {
    const empty = document.createElement("p");
    empty.className = "muted pad";
    empty.textContent = "This folder is empty.";
    grid.appendChild(empty);
  }
  browser.appendChild(grid);
}

function folderTile(course, folder, browser) {
  const tile = document.createElement("div");
  tile.className = "tile folder-tile";
  if (isFolderSelected(course.id, folder.id)) tile.classList.add("selected");

  const check = document.createElement("input");
  check.type = "checkbox";
  check.className = "tile-check";
  check.checked = isFolderSelected(course.id, folder.id);

  const icon = document.createElement("div");
  icon.className = "tile-icon";
  icon.innerHTML = FOLDER_SVG;

  const label = document.createElement("div");
  label.className = "tile-label";
  label.textContent = folder.name;

  const sub = document.createElement("div");
  sub.className = "tile-sub";
  sub.textContent = folder.files_count + " files";

  tile.append(check, icon, label, sub);

  // Single click anywhere on the tile toggles selection; double click opens it.
  let clickTimer = null;
  tile.addEventListener("click", () => {
    if (clickTimer) return;
    clickTimer = setTimeout(() => {
      clickTimer = null;
      const now = !isFolderSelected(course.id, folder.id);
      toggleFolder(course, folder.id, now);
      tile.classList.toggle("selected", now);
      check.checked = now;
      refreshCard(tile);
    }, 220);
  });
  tile.addEventListener("dblclick", () => {
    if (clickTimer) { clearTimeout(clickTimer); clickTimer = null; }
    state.nav[course.id].path.push({ id: folder.id, name: folder.name });
    renderBrowser(course, browser);
  });
  return tile;
}

function fileTile(course, file) {
  const tile = document.createElement("div");
  tile.className = "tile file-tile";
  if (isFileSelected(course.id, file.id)) tile.classList.add("selected");

  const icon = document.createElement("div");
  icon.className = "tile-icon";
  icon.innerHTML = FILE_SVG;

  const label = document.createElement("div");
  label.className = "tile-label";
  label.textContent = file.name;

  tile.append(icon, label);
  tile.addEventListener("click", () => {
    const now = !isFileSelected(course.id, file.id);
    toggleFile(course, file.id, now);
    tile.classList.toggle("selected", now);
    refreshCard(tile);
  });
  return tile;
}

async function onChooseFolder() {
  const res = await api().choose_output_dir();
  state.outputDir = res.path;
  el("folder-path").textContent = res.path;
}

function updateDownloadButton() {
  el("download-btn").disabled = Object.keys(state.selected).length === 0;
}

async function onDownload() {
  const extensions = el("ext-input").value.split(",").map((s) => s.trim()).filter(Boolean);
  const selections = Object.entries(state.selected).map(([cid, v]) => ({
    course_id: Number(cid),
    course_name: v.course_name,
    whole: v.whole,
    folder_ids: Array.from(v.folder_ids),
    file_ids: Array.from(v.file_ids),
  }));
  el("download-btn").disabled = true;
  el("progress").classList.remove("hidden");
  await api().start_download(selections, extensions, state.outputDir);
  pollProgress();
}

async function pollProgress() {
  const p = await api().get_progress();
  const pct = p.total ? Math.round((p.done / p.total) * 100) : 0;
  el("bar-fill").style.width = pct + "%";
  el("progress-text").textContent = p.finished
    ? "Done. Downloaded " + p.done + " of " + p.total + " files into your folder."
    : "Downloading " + p.done + " of " + p.total + ": " + p.current;
  if (!p.finished) {
    setTimeout(pollProgress, 500);
  } else {
    updateDownloadButton();
    // Briefly show "Done", then clear the progress bar and message.
    setTimeout(() => {
      el("progress").classList.add("hidden");
      el("bar-fill").style.width = "0%";
      el("progress-text").textContent = "";
    }, 2500);
  }
}

window.addEventListener("pywebviewready", init);