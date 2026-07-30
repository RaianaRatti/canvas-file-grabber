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

/* init */
async function init() {
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
  const res = await api().login();
  if (res.logged_in) showMain();
  else { el("login-status").textContent = "Login did not complete. Try again."; el("login-btn").disabled = false; }
}

async function showMain() {
  el("login-view").classList.add("hidden");
  el("main-view").classList.remove("hidden");
  el("course-list").innerHTML = "<p class='muted pad'>Loading courses...</p>";
  state.courses = await api().get_courses();
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
  check.addEventListener("click", (e) => e.stopPropagation());
  check.addEventListener("change", () => {
    toggleFolder(course, folder.id, check.checked);
    tile.classList.toggle("selected", check.checked);
    refreshCard(tile);
  });

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
  tile.addEventListener("click", () => {
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
  if (!p.finished) setTimeout(pollProgress, 500);
  else updateDownloadButton();
}

window.addEventListener("pywebviewready", init);