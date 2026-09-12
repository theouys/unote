# How to make Thunar open text files with UNote

UNote is a Python/Tkinter app in `/home/theo/Documents/develop/unote/`. These steps make every `.txt` (and common text file) open in UNote when double-clicked in Thunar.

## 1. Prerequisites

```bash
# tkinter (run this inside UNote, otherwise nothing works)
sudo dnf install -y python3-tkinter

# app must accept files passed on the command line
python3 /home/theo/Documents/develop/unote/unote.py test.txt
```

`unote.py` already handles `sys.argv[1:]` — each path becomes a tab.

## 2. Create a `.desktop` entry (so Thunar knows UNote exists)

Create `~/.local/share/applications/unote.desktop`:

```ini
[Desktop Entry]
Type=Application
Version=1.0
Name=UNote
Comment=Simple text editor with tabs
Exec=python3 /home/theo/Documents/develop/unote/unote.py %F
Icon=text-editor
Terminal=false
Categories=Utility;TextEditor;
MimeType=text/plain;text/x-python;text/x-shellscript;application/json;application/xml;
StartupNotify=true
```

Keys that matter:

| Key | Purpose |
|-----|---------|
| `Name` | Shown in menus / file manager |
| `Exec` | Command run when activated; `%F` = list of selected files |
| `MimeType` | Tells the desktop which file types this app can handle |
| `Categories` | Places UNote under the "TextEditor" category in app menus |

Then refresh the desktop database:

```bash
update-desktop-database ~/.local/share/applications
```

## 3. Register UNote as the default handler for text files

### Option A — command line (what I did)

```bash
xdg-mime default unote.desktop text/plain
```

Verify:

```bash
xdg-mime query default text/plain
# → unote.desktop
```

### Option B — edit `~/.config/mimeapps.list` by hand

If the MIME type isn't in the list yet, add it to both sections:

```ini
[Added Associations]
text/plain=unote.desktop;

[Default Applications]
text/plain=unote.desktop;
```

`[Default Applications]` wins over `[Added Associations]`.

## 4. Restart Thunar / session

Thunar caches the MIME configuration at startup. Close all Thunar windows and reopen it, or restart the Xfce session:

```bash
xfce4-session-logout   # then log back in
```

## 5. Test

Double-click any `.txt` file in Thunar → it should open in UNote in a new tab.

## Troubleshooting

- **Still opens in Mousepad**: the old default app may be cached. Run `xdg-mime default unote.desktop text/plain` again and fully restart the session.
- **Does nothing on double-click**: run `env | grep DISPLAY`, then test the launch command by hand in a terminal to see the error.
- **"No module named tkinter"**: install `python3-tkinter` and retry.
- **Wrong app for specific file types** (`.py`, `.json`): run `xdg-mime default unote.desktop <mime-type>` e.g. `text/x-python3` or `application/json`.

## Files touched in this setup

| File | Role |
|------|------|
| `/home/theo/Documents/develop/unote/unote.py` | The app itself (added `sys.argv` support) |
| `/home/theo/Documents/develop/unote/unote-launcher.py` | Thin wrapper (imports `unote.main`) |
| `/home/theo/.local/share/applications/unote.desktop` | Desktop entry used by Thunar |
| `/home/theo/.config/mimeapps.list` | Global MIME association map |