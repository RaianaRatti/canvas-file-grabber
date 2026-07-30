const state = {
  courses: [],
  folders: {},   // course_id -> [folders]
  selected: {},  // course_id -> { course_name, folder_ids: Set }
  outputDir: "downloads",
};

const api = () => window.pywebview.api;
const el = (id) => document.getElementById(id);

async function init() {
  const s = await api().status();
  state.outputDir = s.output_dir;
  el("folder-path").textContent = s.output_dir;

  if (s.logged_in) {
    showMain();
  } else {
    el("login-view").classList.remove("hidden");
  }

  el("login-btn").addEventListener("click", onLogin);
  el("show-past").addEventListener("change", renderCourses);
  el("folder-btn").addEventListener("click", onChooseFolder);
  el("download-btn").addEventListener("click", onDownload);
}

async function onLogin() {
  el("login-status").textContent = "A browser window opened. Finish logging in there.";
  el("login-btn").disabled = true;
  const res = await api().login();
  if (res.logged_in) {
    showMain();
  } else {
    el("login-status").textContent = "Login did not complete. Try again.";
    el("login-btn").disabled = false;
  }
}

async function showMain() {
  el("login-view").classList.add("hidden");
  el("main-view").classList.remove("hidden");
  el("course-list").innerHTML = "<p class='muted'>Loading courses...</p>";
  state.courses = await api().get_courses();
  renderCourses();
}

function renderCourses() {
  const showPast = el("show-past").checked;
  const list = el("course-list");
  list.innerHTML = "";

  const courses = state.courses.filter((c) => showPast || !c.is_past);
  if (courses.length === 0) {
    list.innerHTML = "<p class='muted'>No courses found.</p>";
    return;
  }
  courses.forEach((c) => list.appendChild(courseCard(c)));
  updateDownloadButton();
}

function courseCard(course) {
  const card = document.createElement("div");
  card.className = "course-card";
  if (state.selected[course.id]) card.classList.add("selected");

  const head = document.createElement("div");
  head.className = "course-head";

  const cb = document.createElement("input");
  cb.type = "checkbox";
  cb.checked = !!state.selected[course.id];
  cb.addEventListener("change", () => {
    toggleCourse(course, cb.checked);
    card.classList.toggle("selected", cb.checked);
  });

  const title = document.createElement("div");
  title.className = "course-title";
  const name = document.createElement("span");
  name.className = "name";
  name.textContent = course.name;
  title.appendChild(name);
  if (course.term) {
    const t = document.createElement("small");
    t.textContent = course.term;
    title.appendChild(t);
  }
  if (course.is_past) {
    const tag = document.createElement("span");
    tag.className = "tag";
    tag.textContent = "past";
    title.appendChild(tag);
  }

  const expand = document.createElement("button");
  expand.className = "expand";
  expand.textContent = "Folders";
  expand.addEventListener("click", () => toggleFolders(course, card));

  head.append(cb, title, expand);
  card.appendChild(head);

  const box = document.createElement("div");
  box.className = "folder-box hidden";
  card.appendChild(box);
  return card;
}

function toggleCourse(course, checked) {
  if (checked) {
    state.selected[course.id] = state.selected[course.id] ||
      { course_name: course.name, folder_ids: new Set() };
  } else {
    delete state.selected[course.id];
  }
  updateDownloadButton();
}

async function toggleFolders(course, card) {
  const box = card.querySelector(".folder-box");
  if (!box.classList.contains("hidden")) {
    box.classList.add("hidden");
    return;
  }
  box.classList.remove("hidden");

  if (!state.folders[course.id]) {
    box.innerHTML = "<p class='muted'>Loading folders...</p>";
    state.folders[course.id] = await api().get_folders(course.id);
  }
  box.innerHTML = "";
  const folders = state.folders[course.id];
  if (folders.length === 0) {
    box.innerHTML = "<p class='muted'>No folders available for this course.</p>";
    return;
  }
  folders.forEach((f) => {
    const row = document.createElement("label");
    row.className = "folder-row";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    const sel = state.selected[course.id];
    cb.checked = sel ? sel.folder_ids.has(f.id) : false;
    cb.addEventListener("change", () => toggleFolder(course, f.id, cb.checked));
    const label = document.createElement("span");
    label.textContent = `${f.name} (${f.files_count})`;
    row.append(cb, label);
    box.appendChild(row);
  });
}

function toggleFolder(course, folderId, checked) {
  const entry = state.selected[course.id] ||
    { course_name: course.name, folder_ids: new Set() };
  if (checked) entry.folder_ids.add(folderId);
  else entry.folder_ids.delete(folderId);
  state.selected[course.id] = entry;
  updateDownloadButton();
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
  const extensions = el("ext-input").value
    .split(",").map((s) => s.trim()).filter(Boolean);

  const selections = Object.entries(state.selected).map(([cid, v]) => ({
    course_id: Number(cid),
    course_name: v.course_name,
    folder_ids: Array.from(v.folder_ids),
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
    ? `Done. Downloaded ${p.done} of ${p.total} files into your folder.`
    : `Downloading ${p.done} of ${p.total}: ${p.current}`;

  if (!p.finished) {
    setTimeout(pollProgress, 500);
  } else {
    updateDownloadButton();
  }
}

window.addEventListener("pywebviewready", init);