# Installing the UNote launcher on Ubuntu XFCE

Files involved:

- `unote.desktop` — the launcher entry (this directory)
- `unote/icon.png` — the app logo used by the launcher

`unote.desktop` already points at the absolute paths of this checkout
(`/home/theo/Documents/develop/new-unote/unote/unote.py` and
`.../unote/icon.png`). If you ever move the project, update `Exec=` and
`Icon=` in the file first.

## 1. Install the icon (recommended)

Copying the logo into the hicolor theme is what makes the entry render
correctly in the Whisker/Applications menu and the Thunar "Open With" list:

```bash
mkdir -p ~/.local/share/icons/hicolor/256x256/apps
cp /home/theo/Documents/develop/new-unote/unote/icon.png \
   ~/.local/share/icons/hicolor/256x256/apps/unote.png
```

## 2. Install the launcher

```bash
mkdir -p ~/.local/share/applications
cp /home/theo/Documents/develop/new-unote/unote.desktop \
   ~/.local/share/applications/unote.desktop
chmod +x ~/.local/share/applications/unote.desktop
```

The launcher must be executable, otherwise XFCE silently ignores it and the
app never shows up in the menu.

## 3. Refresh the caches

```bash
update-desktop-database ~/.local/share/applications 2>/dev/null
gtk-update-icon-cache -f -t ~/.local/share/icons/hicolor 2>/dev/null
```

Log out and back in if the menu does not pick it up right away.

## 4. Optional: add a desktop icon

```bash
cp /home/theo/Documents/develop/new-unote/unote.desktop ~/Desktop/
chmod +x ~/Desktop/unote.desktop
```

On XFCE you also need to allow launching from the Desktop. Either right-click
the icon → *Allow Launching*, or run:

```bash
xfconf-query -c xfce4-desktop -p /desktop-icons/style -s
```

and set the desktop-icons style to allow launching.

## 5. Test it

```bash
gtk-launch unote
```

or from the menu: **Applications → UNote**.

## Troubleshooting

**Entry missing from the menu**
Check the file is in `~/.local/share/applications`, is executable, and that
`Exec=` points at a real file:

```bash
desktop-file-validate ~/.local/share/applications/unote.desktop
```

**Wrong or missing icon**
Confirm the `Icon=` path exists, or install the icon as in step 1. Only after
installing into `hicolor` can you shorten the field to just `Icon=unote`.

**Nothing happens when clicked**
Open a terminal and run the `Exec=` line by hand to see the error. `No module
named tkinter` means tkinter is missing:

```bash
sudo apt install python3-tkinter
```

**App opens in a new icon group**
`StartupWMClass=unote` must match the class Tk reports. Run the app and check:

```bash
xprop WM_CLASS
```

Then put the reported class (e.g. `unote.py`) into `StartupWMClass=`.
