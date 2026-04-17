# WwiseTagExplorer

Tag-based Wwise resource navigator. Connects to an active Wwise project via WAAPI and lets you drill down into audio assets using the naming convention tags embedded in object names.

![screenshot placeholder](assets/screenshot.png)

---

## Requirements

- [Audiokinetic Wwise](https://www.audiokinetic.com/products/wwise/) with WAAPI enabled
- [sk-wwise-mcp](https://github.com/snapshotpl/sk-wwise-mcp) installed at `~/sk-wwise-mcp`

### Enable WAAPI in Wwise
**Wwise → Project Settings → User Settings → Enable Wwise Authoring API**

---

## Installation

Download `WwiseTagExplorer.exe` from the [latest release](https://github.com/jaewon-sung/WwiseTagExplorer/releases/latest) and place it anywhere. No Python installation required.

---

## Usage

1. Open Wwise and load your project
2. Run `WwiseTagExplorer.exe`
3. The app auto-connects to the active project on startup

---

## Features

### Work Unit filtering
- Select a work unit to narrow the scope, or use **All** to search across everything
- Star (☆/★) any work unit to mark it as a favorite — favorites are remembered across sessions and auto-selected on startup

### Tag-based filtering
Object names are split by `_` into tags (e.g. `pc_weapon_bow_shot_01` → `pc`, `weapon`, `bow`, `shot`).

Each click narrows the result set by one tag level. New levels stop appearing when:
- All remaining results share the same parent folder
- Only one result remains
- No tag in the next level would further narrow the results

### Results view
- Displays matching objects with their Wwise path
- Click any row to reveal it in the Wwise Project Explorer
- Drag the column divider to resize the Name / Path columns

### Tag sorting
- **빈도순** — sort tag buttons by frequency (default)
- **A-Z** — sort tag buttons alphabetically
- **Clear** — reset all tag selections

---

## Running from source

```bash
pip install -r requirements.txt
python main.py
```

---

## Building

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name WwiseTagExplorer --add-data "assets/icons;assets/icons" main.py
```

Output: `dist/WwiseTagExplorer.exe`
