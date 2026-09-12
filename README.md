# UNote

A lightweight, tab-based text editor written in Python and Tkinter. Use it to view, write, and edit any text-related file — plain text, source code, configs, JSON, scripts, and more.

Written by Theo Uys.

## Features

- **Multiple tabs** — open several files at once, one per tab
- **Open / Save** — open any file with Ctrl+O and save with Ctrl+S
- **Save As** — save an unsaved file under a new name (Ctrl+Shift+S)
- **Tab naming** — tabs show the real filename (with extension) when a file is opened or first saved
- **Undo / Redo** — Ctrl+Z and Ctrl+Y
- **Clipboard** — cut, copy, and paste (Ctrl+X / Ctrl+C / Ctrl+V)
- **Select all** — Ctrl+A
- **Both scrollbars** — vertical and horizontal scrolling; horizontal appears for long lines (text does not wrap)
- **Unsaved-change protection** — tabs are flagged with `*`, and you are asked before closing a dirty tab or exiting
- **About dialog** — Help > About
- **File association** — registered as the default handler for text files in file managers (see below)

## Getting started

### Requirements

- Python 3.x
- Tkinter (`python3-tkinter` on Fedora/Debian)
- A display environment (X11/Wayland desktop)

### Run

```bash
python3 unote.py
```

Open files directly:

```bash
python3 unote.py notes.txt config.json script.py
```

Each path opens in its own tab.

## Keyboard shortcuts

| Shortcut           | Action        |
|--------------------|---------------|
| Ctrl+N             | New tab       |
| Ctrl+O             | Open file     |
| Ctrl+S             | Save          |
| Ctrl+Shift+S       | Save As       |
| Ctrl+Z             | Undo          |
| Ctrl+Y             | Redo          |
| Ctrl+C / X / V     | Copy / Cut / Paste |
| Ctrl+A             | Select all    |

Right-clicking a tab shows a quick menu (new / close).

## Making it the default text editor (Thunar / Linux)

1. Install Tkinter if missing:
   ```bash
   sudo dnf install -y python3-tkinter
   ```
2. Add `~/.local/share/applications/unote.desktop` (see `SETUP-THUNAR.md`).
3. Register it as the default for text files:
   ```bash
   xdg-mime default unote.desktop text/plain
   ```
4. Restart Thunar or the Xfce session.

See `SETUP-THUNAR.md` for the full step-by-step setup.

## Project layout

```
unote.py            The application (single file)
unote-launcher.py   Optional thin launcher wrapper
SETUP-THUNAR.md     How to register UNote as the default text editor
```

## License

Personal project — free to use.