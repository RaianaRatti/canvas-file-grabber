# Canvas File Grabber

A desktop app that logs into your Canvas account, shows all your courses (current and past) in a folder browser, and lets you download only the files you need.

## Features

- List all Canvas courses including past ones (if your school keeps them visible)
- Browse course folders like a file explorer - click to open, navigate with breadcrumbs
- Select whole courses, specific folders, or individual files
- Filter downloads by file type (pdf, pptx, docx, etc.) or keep all types
- Single-session login - log in once, reused until expiry
- Real browser login supporting SSO and one-time password (OTP)
- Batch download with progress tracking
- Organized output - files sorted by course name into subfolders

## Demo

https://github.com/user-attachments/assets/e268b68f-2aab-4b9a-a2a2-639137f3548a

## Quick Start

Download the latest release for your operating system from [Releases](https://github.com/RaianaRatti/canvas-file-grabber/releases):

- **Windows**: CanvasFileGrabber-Windows.exe
- **macOS**: CanvasFileGrabber-Mac.dmg
- **Linux**: CanvasFileGrabber-Linux.zip

No Python install needed. Download, run, and log in.

## How Login Works

The app opens your real web browser to your school's Canvas login page. You enter your email, password, and one-time code exactly as you normally would. The app never sees or stores your password. After login, your session is saved locally and reused on future launches until it expires.

## Development Setup

If you want to modify or build the app yourself:

**Requirements:**
- Python 3.10 or newer
- macOS 10.14+, Windows 10+, or Linux with GTK/Qt webview

**Install:**

```bash
git clone https://github.com/your-username/canvas-file-grabber.git
cd canvas-file-grabber
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
cp config.example.json config.json
```

Edit `config.json` and set `base_url` to your school's Canvas URL (example: `https://canvas.youruniversity.edu`).

On Linux, install webview dependencies:

```bash
sudo apt install python3-gi gir1.2-webkit2-4.1
```

**Run:**

```bash
python run.py
```

A window opens. Click **Log in to Canvas** the first time and complete login including any SSO or one-time code steps in the browser that appears. Return to the app and courses load.

## Using the App

1. Tick a course checkbox to select the whole course, or click the folder icon to browse inside it
2. Open folders by clicking them. Breadcrumbs at the top let you jump back to any level
3. Tick folders to select everything inside, or click individual files to pick them
4. Enter file types to keep (comma separated: pdf, docx, pptx) or leave blank for all types
5. Choose an output folder where downloads go
6. Click **Download selected**

Files save as `output-folder/Course Name/filename.ext`, organized by course.

## Project Structure

```
canvas-file-grabber/
├── README.md              # This file
├── PLAN.md                # Architecture and design decisions
├── requirements.txt       # Python dependencies
├── config.example.json    # Configuration template
├── run.py                 # Entry point
├── src/
│   ├── config.py          # Config loading and validation
│   ├── auth.py            # Playwright login and session
│   ├── canvas.py          # Canvas API client
│   ├── downloader.py      # File filtering and download
│   └── api.py             # Backend methods for frontend
└── web/
    ├── index.html         # UI markup
    ├── styles.css         # Styling
    └── app.js             # Browser-side logic
```

See `PLAN.md` for full architecture, design rationale, and implementation details.

## Building a Standalone Executable

The GitHub Actions workflow in `.github/workflows/build.yml` automatically builds Windows, macOS, and Linux executables on each release. No manual build needed.

To build locally:

```bash
pip install pyinstaller
pyinstaller --name CanvasFileGrabber --windowed --onefile \
  --collect-all playwright --collect-all webview \
  --add-data "web:web" --add-data "config.example.json:." \
  run.py
```

On Windows, use semicolons instead of colons in `--add-data` paths.

The built executable is in `dist/CanvasFileGrabber`.

## Known Limitations

**Terms of service.** Automating login to your school's Canvas may violate acceptable use policies even when accessing only your own files. Check your institution's rules first.

**Login requires browser window.** The first login must happen in a visible browser so you can complete SSO steps and two-factor codes. This is intentional - automating these directly is fragile on school SSO setups.

**Session file is sensitive.** `storage_state.json` contains live login cookies. Anyone who copies it could impersonate your account until the session expires. Never share this file.

**Folder selection is one level only.** Selecting a folder downloads files directly inside it. To get subfolders, open them and select separately.

**Past courses depend on school policy.** Some schools lock old courses after terms end. Those will not show up.

**Rate limits apply.** Canvas throttles heavy API use. Large downloads may need pauses between requests.

**Linux requires webview.** macOS and Windows include webview by default. Linux needs GTK or Qt bindings installed.

## License

MIT