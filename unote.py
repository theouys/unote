import sys
import subprocess
import shutil
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import tkinter.font as tkfont
import os
import json
import html
import re
import csv
import io
import tempfile
import webbrowser
import pathlib

try:
    import win32print
    import win32ui
    import win32con
    PYWIN32_AVAILABLE = True
except ImportError:
    PYWIN32_AVAILABLE = False

IS_WINDOWS = sys.platform == "win32"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Settings live in the user's config dir, not next to the script: on Linux the
# app is often installed somewhere unwritable (/usr/share, a distro package, a
# read-only mount), and writing user data into a shared directory is a
# permissions smell anyway.
SETTINGS_DIR = os.path.join(
    os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "unote")
SETTINGS_FILE = os.path.join(SETTINGS_DIR, "settings.json")
LEGACY_SETTINGS_FILE = os.path.join(SCRIPT_DIR, "unote_settings.json")

MARKDOWN_EXTENSIONS = (".md", ".markdown", ".mdown", ".mkd")
CSV_EXTENSIONS = (".csv",)

FILE_OUTPUT_PRINTERS = ("pdf", "xps", "onenote", "fax", "document writer")

# "Courier New" and "Consolas" are Microsoft fonts and are usually absent on
# Linux. Prefer real Linux monospace families and only fall back to the
# Windows names (where fontconfig often aliases them anyway).
MONOSPACE_FAMILIES = (
    "DejaVu Sans Mono", "Liberation Mono", "Noto Sans Mono",
    "Ubuntu Mono", "Cascadia Mono", "Consolas", "Courier New",
)

# A GUI app started from a .desktop file or a session manager often inherits a
# minimal PATH with no /usr/local/bin, no ~/.local/bin, no snap or flatpak
# export dir - so shutil.which() alone misses programs that are installed.
EXTRA_BIN_DIRS = (
    os.path.expanduser("~/.local/bin"),
    os.path.expanduser("~/bin"),
    "/usr/local/bin",
    "/usr/local/sbin",
    "/snap/bin",
    "/var/lib/snapd/snap/bin",
    "/var/lib/flatpak/exports/bin",
    os.path.expanduser("~/.local/share/flatpak/exports/bin"),
)

# Browsers, in the order we prefer them.
BROWSER_COMMANDS = (
    "firefox", "firefox-esr", "google-chrome", "google-chrome-stable",
    "chromium", "chromium-browser", "microsoft-edge-stable", "brave",
    "brave-browser", "msedge", "chrome", "opera", "vivaldi",
)

# Editors that can open a file; the label is what we tell the user we tried.
VSCODE_COMMANDS = ("code", "code-insiders", "codium", "vscodium", "code-oss")

# Terminal emulators and the flag each one uses to start in a directory.
# Passing the directory beats spawning `sh -c "cd ... && exec shell"`: it
# needs no shell round-trip and works on terminals whose `-- PROGRAM` form is
# absent or differs. None of these flags need a value at all when we just want
# the terminal to open the user's own shell there.
TERMINAL_WORKDIR_FLAGS = {
    "ptyxis": "--working-directory",
    "gnome-terminal": "--working-directory",
    "xfce4-terminal": "--working-directory",
    "konsole": "--workdir",
    "kitty": "--directory",
    "alacritty": "--working-directory",
    "tilix": "--working-directory",
    "foot": "--working-directory",
    "wezterm": "start",
    "xterm": "",
}


def _user_shell():
    """The user's login shell, falling back to /bin/sh.

    Hardcoding bash means the terminal opens and immediately dies on systems
    that do not ship it, and ignores zsh/fish even where it is present.
    """
    return os.environ.get("SHELL") or "/bin/sh"


def find_executable(name):
    """shutil.which(), plus the usual Linux install locations.

    A process launched from a desktop entry can have a much shorter PATH than
    the one in the user's shell, so falling back to absolute paths keeps
    program discovery working there.
    """
    found = shutil.which(name)
    if found:
        return found
    for folder in EXTRA_BIN_DIRS:
        candidate = os.path.join(folder, name)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def _c_env():
    """Environment forcing the C locale.

    CUPS localises its `lpstat` / `lp` diagnostics, which would break the
    output parsing below on any non-English desktop - a working queue would
    report as "no printers found". Forcing C keeps both the parsing and the
    error messages shown to the user in English.
    """
    env = dict(os.environ)
    env["LC_ALL"] = "C"
    env["LANGUAGE"] = "C"
    return env


def list_printers():
    """Real system printer names, default first.

    Uses the Windows print spooler via pywin32 on Windows, and the
    standard CUPS command-line tools (lpstat) elsewhere.
    """
    if PYWIN32_AVAILABLE and IS_WINDOWS:
        flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
        names = [p[2] for p in win32print.EnumPrinters(flags)]
        try:
            default = win32print.GetDefaultPrinter()
        except Exception:
            default = None
        if default and default in names:
            names.remove(default)
            names.insert(0, default)
        return names, default

    return _list_cups_printers()


def _list_cups_printers():
    lpstat = find_executable("lpstat")
    if not lpstat:
        return [], None
    env = _c_env()
    try:
        out = subprocess.check_output(
            [lpstat, "-p"], text=True, stderr=subprocess.DEVNULL, env=env)
        names = re.findall(r"^printer (\S+)", out, re.MULTILINE)
    except (subprocess.CalledProcessError, OSError):
        names = []

    default = None
    try:
        d_out = subprocess.check_output(
            [lpstat, "-d"], text=True, stderr=subprocess.DEVNULL, env=env)
        m = re.search(r"system default destination:\s*(\S+)", d_out)
        if m:
            default = m.group(1)
    except (subprocess.CalledProcessError, OSError):
        pass

    if default and default in names:
        names.remove(default)
        names.insert(0, default)
    return names, default


def print_text_cups(printer_name, title, content):
    """Print plain text content on Linux/Unix via the CUPS 'lp' command."""
    lp = find_executable("lp")
    if not lp:
        raise RuntimeError("The 'lp' command was not found (CUPS not installed?).")
    # Feed the text on stdin rather than via a temp file: CUPS reads it
    # immediately, so there is no spool-file race, and nothing is left behind
    # if the job is rejected.
    result = subprocess.run(
        [lp, "-d", printer_name, "-t", title, "-"],
        input=content, capture_output=True, text=True, env=_c_env(),
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "lp command failed")
    return True


def choose_printer_dialog(root, theme=None):
    """A small native printer-selection dialog, listing real system
    printers (Windows spooler or CUPS, depending on platform).

    Returns the selected printer name, or None if the user cancelled.
    """
    names, default = list_printers()
    if not names:
        messagebox.showerror(parent=root, title="Print",
                             message="No printers were found on this system.")
        return None

    win = tk.Toplevel(root)
    win.title("Print")
    win.transient(root)
    win.grab_set()
    win.resizable(False, False)
    if theme:
        win.configure(background=theme["bg"])

    ttk.Label(win, text="Select a printer:").grid(
        row=0, column=0, sticky="w", padx=10, pady=(10, 4))

    # Classic Tk widgets ignore the ttk theme, so they have to be coloured
    # explicitly or the dialog shows a white list in an otherwise dark window.
    # Fall back to the light palette rather than Tk's "SystemWindow" family:
    # those colour names are implemented only in Tk's Windows build, so on
    # X11/Wayland they raise TclError and take the whole dialog down with them.
    colors = theme if theme else LIGHT_THEME
    listbox = tk.Listbox(
        win, width=50, height=8, exportselection=False,
        background=colors.get("text_bg", "#ffffff"),
        foreground=colors.get("text_fg", "#1c1c1c"),
        selectbackground=colors.get("sel_bg", "#3399ff"),
        selectforeground=colors.get("sel_fg", "#ffffff"),
        highlightthickness=0, borderwidth=0,
    )
    listbox.grid(row=1, column=0, padx=10, pady=(0, 6))
    for name in names:
        listbox.insert("end", name)
    listbox.selection_set(0)
    listbox.see(0)

    chosen = {}

    def on_ok(_event=None):
        sel = listbox.curselection()
        if sel:
            chosen["name"] = names[sel[0]]
        win.destroy()

    def on_cancel(_event=None):
        win.destroy()

    btn_frame = ttk.Frame(win)
    btn_frame.grid(row=2, column=0, sticky="e", padx=10, pady=(0, 10))
    ttk.Button(btn_frame, text="Cancel", command=on_cancel).pack(side="right", padx=(6, 0))
    ttk.Button(btn_frame, text="Print", command=on_ok).pack(side="right")

    listbox.bind("<Double-Button-1>", on_ok)
    win.bind("<Return>", on_ok)
    win.bind("<Escape>", on_cancel)

    win.wait_window()
    return chosen.get("name")


def print_text_native(printer_name, title, content, font_name="Consolas",
                      font_pt=10, parent=None):
    """Print plain text content to a real Windows printer via GDI.

    Returns True on success. Raises win32ui.error / OSError on failure.
    """
    dc = win32ui.CreateDC()
    dc.CreatePrinterDC(printer_name)

    y_dpi = dc.GetDeviceCaps(win32con.LOGPIXELSY)
    x_dpi = dc.GetDeviceCaps(win32con.LOGPIXELSX)
    page_width = dc.GetDeviceCaps(win32con.HORZRES)
    page_height = dc.GetDeviceCaps(win32con.VERTRES)
    margin_x = int(0.75 * x_dpi)
    margin_y = int(0.75 * y_dpi)

    font = win32ui.CreateFont({
        "name": font_name,
        "height": -int(font_pt * y_dpi / 72),
    })
    dc.SelectObject(font)
    line_height = dc.GetTextExtent("Ag")[1] + int(0.15 * y_dpi / 6)

    def start_doc():
        needs_output = any(t in printer_name.lower() for t in FILE_OUTPUT_PRINTERS)
        if needs_output:
            safe_title = "".join(c for c in title if c.isalnum() or c in " _-") or "print"
            out_path = filedialog.asksaveasfilename(
                parent=parent,
                title="Save print output as",
                initialfile=safe_title,
            )
            if not out_path:
                return False
            dc.StartDoc(title, out_path)
        else:
            dc.StartDoc(title)
        return True

    if not start_doc():
        return False

    dc.StartPage()
    dc.SelectObject(font)
    y = margin_y
    for line in content.split("\n"):
        if y + line_height > page_height - margin_y:
            dc.EndPage()
            dc.StartPage()
            dc.SelectObject(font)
            y = margin_y
        dc.TextOut(margin_x, y, line)
        y += line_height
    dc.EndPage()
    dc.EndDoc()
    return True


def open_html_file(path):
    """Open a local HTML file for viewing/printing in a real browser.

    Prefers a browser executable over the OS file association: on some systems
    .html is still bound to a broken handler (e.g. Internet Explorer on modern
    Windows, or a stale mimeapps.list entry on Linux) which pops up an "Open
    With" dialog instead of actually showing the page. Launching a known
    browser executable directly sidesteps that entirely.

    Returns True only if something actually took the file; callers report
    failure themselves.
    """
    # Percent-encode: a bare f"file://{path}" breaks on '#', '%' and spaces,
    # which are all common in generated temp-file and project paths.
    try:
        url = pathlib.Path(os.path.abspath(path)).as_uri()
    except (ValueError, OSError):
        url = f"file://{path}"

    candidates = []
    for name in BROWSER_COMMANDS:
        found = find_executable(name)
        if found:
            candidates.append(found)

    if IS_WINDOWS:
        for env_var in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            base = os.environ.get(env_var)
            if not base:
                continue
            for rel in (
                os.path.join("Microsoft", "Edge", "Application", "msedge.exe"),
                os.path.join("Google", "Chrome", "Application", "chrome.exe"),
                os.path.join("BraveSoftware", "Brave-Browser", "Application", "brave.exe"),
                os.path.join("Mozilla Firefox", "firefox.exe"),
            ):
                candidate = os.path.join(base, rel)
                if os.path.exists(candidate):
                    candidates.append(candidate)

    for exe in candidates:
        try:
            subprocess.Popen([exe, url])
            return True
        except OSError:
            continue

    # xdg-open honours the desktop's default browser and works on both
    # X11 and Wayland; gio open is the fallback where xdg-utils is absent.
    for opener in ("xdg-open", "gio"):
        exe = find_executable(opener)
        if not exe:
            continue
        try:
            argv = [exe, url] if opener == "xdg-open" else [exe, "open", url]
            subprocess.Popen(argv, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            return True
        except OSError:
            continue

    try:
        return bool(webbrowser.open(url))
    except Exception:
        return False

# --- Theme palettes -------------------------------------------------------
# Every value must be a literal colour or a name that exists on BOTH Tk/X11
# and Tk/Windows. The "System*" names (SystemButtonFace, SystemWindow,
# SystemWindowText) are implemented only in Tk's Windows build: on X11 they
# reach XAllocNamedColor, which knows no such entry, so referencing one raises
# `unknown color name` and takes the whole app down at startup.
LIGHT_THEME = {
    "bg": "#f0f0f0",
    "bg_alt": "#ffffff",
    "fg": "#1c1c1c",
    "text_bg": "#ffffff",
    "text_fg": "#1c1c1c",
    "insert": "#1c1c1c",
    "sel_bg": "#3399ff",
    "sel_fg": "#ffffff",
    "border": "#c8c8c8",
    "active": "#dcdfe4",
    "menu_bg": "#f5f5f5",
    "menu_fg": "#1c1c1c",
    "menu_active_bg": "#4a90d9",
    "menu_active_fg": "#ffffff",
    "menu_disabled_fg": "#9a9a9a",
}

DARK_THEME = {
    "bg": "#1e1e1e",
    "bg_alt": "#252526",
    "fg": "#d4d4d4",
    "text_bg": "#1e1e1e",
    "text_fg": "#add8e6",
    "insert": "#add8e6",
    "sel_bg": "#264f78",
    "sel_fg": "#ffffff",
    "border": "#3c3c3c",
    "active": "#505050",
    "menu_bg": "#161616",
    "menu_fg": "#d4d4d4",
    "menu_active_bg": "#505050",
    "menu_active_fg": "#ffffff",
    "menu_disabled_fg": "#6a6a6a",
}


_MONOSPACE_FONT = None


def resolve_monospace_font(root=None, size=11):
    """The first installed monospace family, so the editor keeps its grid.

    "Courier New" is a Microsoft font; on Linux it only resolves if fontconfig
    happens to ship a metric-compatible alias, and otherwise Tk silently
    substitutes an unrelated - often proportional - family. Asking Tk what is
    actually installed is the only reliable way to keep columns aligned.
    """
    global _MONOSPACE_FONT
    if _MONOSPACE_FONT is not None:
        return _MONOSPACE_FONT
    try:
        installed = set(tkfont.families(root))
    except (tk.TclError, RuntimeError):
        # RuntimeError is what Tk raises when asked before a root window
        # exists; TclError covers a root that is already being torn down.
        # Neither tells us anything about the system, so answer without
        # caching - a later call from inside the app has a real root and can
        # do better than the named-font guess this falls back to.
        return ("TkFixedFont", size)
    family = next((f for f in MONOSPACE_FAMILIES if f in installed), None)
    if family is None:
        # Nothing from the list is installed: defer to whatever Tk considers
        # the fixed-width default rather than naming a family that is absent.
        try:
            family = tkfont.nametofont("TkFixedFont", root=root).actual("family")
        except (tk.TclError, RuntimeError):
            family = None
        family = family or "TkFixedFont"
    _MONOSPACE_FONT = (family, size)
    return _MONOSPACE_FONT


def load_settings():
    """Read settings, migrating a legacy settings file from the script dir."""
    settings = {}
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                settings = json.load(f)
        except (json.JSONDecodeError, OSError):
            settings = {}
    elif os.path.exists(LEGACY_SETTINGS_FILE):
        # First run after moving to ~/.config: carry the old file over rather
        # than silently resetting the user's theme.
        try:
            with open(LEGACY_SETTINGS_FILE, "r", encoding="utf-8") as f:
                settings = json.load(f)
        except (json.JSONDecodeError, OSError):
            settings = {}
        else:
            save_settings(settings)
    return settings


def save_settings(settings):
    try:
        os.makedirs(SETTINGS_DIR, exist_ok=True)
        # The settings file can hold credentials, so keep it user-only.
        fd = os.open(SETTINGS_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
    except OSError:
        # Typically an unwritable install directory. Report it instead of
        # failing silently, so the user knows the setting did not stick.
        print("unote: could not write settings to "
              f"{SETTINGS_FILE}", file=sys.stderr)


def detect_newline(raw):
    """The line ending used by `raw`, so a save does not rewrite the whole file.

    Reading a Windows-authored file with universal newlines turns every CRLF
    into LF in the buffer; writing that back silently converts the file, which
    shows up as a whole-file diff in git and breaks .bat/.cmd/.ps1 scripts.
    Files with no line ending at all default to "\\n".
    """
    if b"\r\n" in raw:
        return "\r\n"
    if b"\r" in raw and b"\n" not in raw:
        return "\r"
    return "\n"


def decode_text(raw):
    """Decode file bytes to text, honouring a BOM.

    Returns (text, encoding, lossy). `lossy` is True when undecodable bytes
    had to be replaced - worth telling the user, because saving then writes
    the replacement characters back to disk.
    """
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig", errors="replace"), "utf-8", False
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", errors="replace"), "utf-16", False
    if raw.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        return raw.decode("utf-32", errors="replace"), "utf-32", False
    try:
        return raw.decode("utf-8"), "utf-8", False
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="replace"), "utf-8", True


def encode_text(content, newline):
    """Serialise buffer text back to bytes using the file's line endings."""
    # Always normalise. Tk stores "\n" internally, so in practice this is a
    # no-op, but leaving the "\n" case unhandled would let a stray "\r\n"
    # through to disk whenever it did arrive.
    content = re.sub(r"\r?\n", newline, content)
    return content.encode("utf-8")


SAFE_URL_SCHEMES = ("http://", "https://", "mailto:", "ftp://", "ftps://",
                    "news:", "irc:", "tel:")


def safe_url(value):
    """A link/image target that is safe to hand to the browser, else None.

    The Markdown preview is rendered into a file:// URL and opened in the
    user's real browser, so a markdown file that arrived from somewhere else
    could otherwise carry `[click me](javascript:...)` and run script the
    moment the link was followed, or `![](data:text/html,...)` and run it on
    load. Anything whose scheme is not explicitly allowed is refused; a target
    with no scheme at all is a relative path, which cannot execute.
    """
    candidate = value.strip()
    if not candidate:
        return None
    lowered = candidate.lower()
    if lowered.startswith(SAFE_URL_SCHEMES):
        return candidate
    if re.match(r"^[a-z][a-z0-9+.\-]*:", lowered):
        # It has a scheme and it is not one of ours: refuse.
        return None
    return candidate


def render_markdown_html(markdown, title):
    """A self-contained HTML preview of a Markdown document.

    This used to shell out to a separate `umdview.pyw` viewer next to the
    script, which is a Windows-only convention and was missing entirely - so
    "View Markdown" and printing a .md file always failed. Rendering here and
    handing the result to the browser keeps both features working everywhere
    with nothing extra to install.

    Deliberately a small subset of CommonMark: headings, fenced and indented
    code, blockquotes, ordered/unordered/task lists, horizontal rules, tables,
    and the usual inline marks. Anything it does not recognise falls through
    as literal text, which is what a plain-text editor's viewer should do.
    """
    out = []
    list_stack = []
    paragraph_open = False

    def close_lists(to_depth=0):
        while len(list_stack) > to_depth:
            out.append(f"</{list_stack.pop()}>")

    def close_paragraph():
        # Track it with a flag. Looking at out[-1] cannot work: the paragraph
        # text and its </p> land in the list as one element, so out[-1] is
        # "text</p>" and never equals "</p>" - which left a stray </p> on
        # every rendered document.
        nonlocal paragraph_open
        if paragraph_open:
            out.append("</p>")
            paragraph_open = False

    def render_inline(text):
        # Pull fenced/inline code out first so its contents are never treated
        # as markup, then apply the inline marks to what is left.
        stash = []

        def stash_code(match):
            stash.append(f"<code>{html.escape(match.group(2))}</code>")
            return f"\x00{len(stash) - 1}\x00"

        text = re.sub(r"(`+)(.+?)\1", stash_code, text, flags=re.DOTALL)
        # Everything from here on is already escaped, so the link and image
        # handlers must not escape again - doing that twice turns a query
        # string's "&" into "&amp;amp;" and corrupts the URL.
        escaped = html.escape(text)

        def image(match):
            alt, src = match.group(1), safe_url(match.group(2))
            if src is None:
                # Refused scheme: keep the alt text, drop the fetch.
                return alt
            return f'<img alt="{alt}" src="{src}">'

        def link(match):
            label, href = match.group(1), safe_url(match.group(2))
            if href is None:
                # Refused scheme: render the label as inert text.
                return label
            return f'<a href="{href}">{label}</a>'

        # CommonMark allows whitespace just inside the parentheses, so
        # `[x]( url )` is a link. Matching it also means such a target goes
        # through safe_url() instead of being left as literal text.
        escaped = re.sub(r"!\[([^\]]*)\]\(\s*([^)\s]+?)\s*\)", image, escaped)
        escaped = re.sub(r"\[([^\]]+)\]\(\s*([^)\s]+?)\s*\)", link, escaped)
        escaped = re.sub(r"\*\*\*(.+?)\*\*\*", r"<strong><em>\1</em></strong>", escaped)
        escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
        escaped = re.sub(r"(?<![\w*])\*([^*\n]+?)\*(?![\w*])", r"<em>\1</em>", escaped)
        escaped = re.sub(r"~~(.+?)~~", r"<del>\1</del>", escaped)
        for index, code in enumerate(stash):
            escaped = escaped.replace(f"\x00{index}\x00", code)
        return escaped

    def open_paragraph():
        nonlocal paragraph_open
        if not paragraph_open:
            out.append("<p>")
            paragraph_open = True

    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if not stripped:
            close_paragraph()
            close_lists()
            index += 1
            continue

        fence = re.match(r"^(`{3,}|~{3,})\s*(\S*)\s*$", stripped)
        if fence:
            close_paragraph()
            close_lists()
            marker, language = fence.group(1)[0] * 3, fence.group(2)
            index += 1
            block = []
            while index < len(lines) and not lines[index].strip().startswith(marker):
                block.append(lines[index])
                index += 1
            index += 1  # consume the closing fence (or run off the end)
            cls = f' class="language-{html.escape(language)}"' if language else ""
            out.append(f"<pre><code{cls}>{html.escape(chr(10).join(block))}</code></pre>")
            continue

        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            close_paragraph()
            close_lists()
            level = len(heading.group(1))
            out.append(f"<h{level}>{render_inline(heading.group(2).rstrip('#').strip())}</h{level}>")
            index += 1
            continue

        if re.match(r"^([-*_])(\s*\1){2,}$", stripped):
            close_paragraph()
            close_lists()
            out.append("<hr>")
            index += 1
            continue

        if stripped.startswith(">"):
            close_paragraph()
            close_lists()
            out.append("<blockquote>")
            out.append(f"<p>{render_inline(stripped.lstrip('>').strip())}</p>")
            out.append("</blockquote>")
            index += 1
            continue

        # A table is a header row, a separator row of dashes/colons, then body.
        if ("|" in stripped and index + 1 < len(lines)
                and re.match(r"^\s*\|?[\s:|-]+\|[\s:|-]*$", lines[index + 1])
                and "-" in lines[index + 1]):
            close_paragraph()
            close_lists()
            def cells(row):
                return [c.strip() for c in row.strip().strip("|").split("|")]

            headers = cells(stripped)
            index += 2
            rows = []
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                rows.append(cells(lines[index]))
                index += 1
            out.append("<table><thead><tr>")
            out.extend(f"<th>{render_inline(c)}</th>" for c in headers)
            out.append("</tr></thead><tbody>")
            for row in rows:
                out.append("<tr>")
                out.extend(f"<td>{render_inline(c)}</td>" for c in row)
                out.append("</tr>")
            out.append("</tbody></table>")
            continue

        bullet = re.match(r"^(\s*)([-*+])\s+(.*)$", line)
        numbered = re.match(r"^(\s*)(\d+)[.)]\s+(.*)$", line)
        if bullet or numbered:
            close_paragraph()
            match = bullet or numbered
            indent = len(match.group(1)) // 2
            if bullet:
                task = re.match(r"^\[([ xX])\]\s*(.*)$", match.group(3))
                marker, kind = "-", "ul"
                if task:
                    checked = " checked" if task.group(1).lower() == "x" else ""
                    # A task list is a disabled checkbox so the preview is
                    # honest about the document's state.
                    body = (f'<input type="checkbox" disabled{checked}> '
                            f"{render_inline(task.group(2))}")
                else:
                    body = render_inline(match.group(3))
            else:
                marker, kind, body = match.group(2), "ol", render_inline(match.group(3))

            close_lists(indent)
            if len(list_stack) <= indent:
                start = (f' start="{match.group(2)}"'
                         if kind == "ol" and bullet is None else "")
                out.append(f"<{kind}{start}>")
                list_stack.append(kind)
            out.append(f"<li>{body}</li>")
            index += 1
            continue

        close_lists()
        open_paragraph()
        out.append(render_inline(stripped))
        index += 1

    close_paragraph()
    close_lists()

    escaped_title = html.escape(title)
    body = "\n".join(out)
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escaped_title}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: system-ui, sans-serif; line-height: 1.6;
         max-width: 46em; margin: 2em auto; padding: 0 1.25em; }}
  pre {{ background: rgba(127,127,127,.12); padding: .8em; overflow-x: auto;
         border-radius: 6px; }}
  code {{ font-family: ui-monospace, monospace; font-size: .92em; }}
  p code {{ background: rgba(127,127,127,.15); padding: .1em .3em;
            border-radius: 4px; }}
  blockquote {{ margin: 1em 0; padding: .2em 1em; opacity: .85;
                 border-left: 4px solid rgba(127,127,127,.4); }}
  table {{ border-collapse: collapse; }}
  th, td {{ border: 1px solid rgba(127,127,127,.4); padding: .35em .7em; }}
  hr {{ border: 0; border-top: 1px solid rgba(127,127,127,.4); }}
  img {{ max-width: 100%; }}
  @media print {{ body {{ margin: 0; max-width: none; }} }}
</style>
</head>
<body>
{body}
</body>
</html>
"""


def show_markdown_preview(root, markdown, title, parent=None):
    """Render `markdown` and open the result in a browser.

    Returns the path of the generated HTML file, or None if no browser could
    be launched (the file is left behind so the user can open it manually).
    """
    document = render_markdown_html(markdown, title)
    try:
        fd, path = tempfile.mkstemp(suffix=".html", prefix="unote_md_")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(document)
    except OSError as exc:
        messagebox.showerror(parent=parent or root, title="View Markdown",
                             message=f"Could not create a preview file:\n{exc}")
        return None
    if open_html_file(path):
        return path
    messagebox.showerror(
        parent=parent or root,
        title="View Markdown",
        message="Could not find a browser to show the preview.\n"
        f"The rendered file was written to:\n{path}")
    return path


class TextTab:
    def __init__(self, title, app=None, path=None, theme=None):
        self.app = app
        self.path = path
        self.modified = False
        # Line ending to write back on save. Detected from the file on load;
        # "\n" for a new tab. Tk stores "\n" internally regardless.
        self.newline = "\n"
        self.load_encoding = "utf-8"
        theme = theme or LIGHT_THEME

        self.frame = ttk.Frame()
        self.text = tk.Text(
            self.frame,
            wrap="none",
            undo=True,
            font=resolve_monospace_font(getattr(self.app, "root", None)),
            padx=6,
            pady=6,
            background=theme["text_bg"],
            foreground=theme["text_fg"],
            insertbackground=theme["insert"],
            selectbackground=theme["sel_bg"],
            selectforeground=theme["sel_fg"],
            highlightthickness=0,
            borderwidth=0,
        )

        vbar = ttk.Scrollbar(self.frame, orient="vertical", command=self.text.yview)
        hbar = ttk.Scrollbar(self.frame, orient="horizontal", command=self.text.xview)
        self.text.configure(yscrollcommand=vbar.set, xscrollcommand=hbar.set)

        self.text.grid(row=0, column=0, sticky="nsew")
        vbar.grid(row=0, column=1, sticky="ns")
        hbar.grid(row=1, column=0, sticky="ew")
        self.frame.rowconfigure(0, weight=1)
        self.frame.columnconfigure(0, weight=1)

        self.text.bind("<<Modified>>", self._on_modified)
        for seq in ("<KeyRelease>", "<Button-1>", "<ButtonRelease-1>",
                    "<FocusIn>"):
            self.text.bind(seq, self._on_cursor_move)
        self.title = title
        self._refresh()

    def _on_cursor_move(self, _event=None):
        if self.app is not None:
            self.app.update_status()

    def _on_modified(self, event):
        if self.text.edit_modified():
            self.modified = True
            self._refresh()
        self.text.edit_modified(False)

    def display_name(self):
        marker = "*" if self.modified else ""
        return f"{marker}{self.title}"

    def _refresh(self):
        if self.app is not None:
            self.app.refresh_tab(self)
            self.app.update_status()
        else:
            self.frame.master.title(f"{self.display_name()} - UNote")

    def set_title(self, title):
        self.title = title
        self._refresh()

    def get_content(self):
        return self.text.get("1.0", "end-1c")

    def set_content(self, content):
        self.text.delete("1.0", "end")
        self.text.insert("1.0", content)
        self.text.mark_set("insert", "1.0")
        self.text.tag_remove("sel", "1.0", "end")
        self.text.edit_modified(False)
        self.text.edit_reset()
        self.modified = False
        self._refresh()

    def load_file(self, path):
        """Read `path` into the buffer, remembering its encoding/line endings."""
        with open(path, "rb") as f:
            raw = f.read()
        content, encoding, lossy = decode_text(raw)
        self.load_encoding = encoding
        self.newline = detect_newline(raw)
        self.set_content(content)
        self.path = path
        self.set_title(os.path.basename(path))
        return lossy

    def apply_theme(self, theme):
        self.text.configure(
            background=theme["text_bg"],
            foreground=theme["text_fg"],
            insertbackground=theme["insert"],
            selectbackground=theme["sel_bg"],
            selectforeground=theme["sel_fg"],
        )


class UNoteApp:
    def __init__(self, root, files=None):
        self.root = root
        self.root.title("UNote")
        self.root.geometry("900x600")

        # Keep a reference: without one the PhotoImage can be collected and the
        # window icon disappears on some Tk/window-manager combinations.
        self._icon = None
        for icon_path in (os.path.join(SCRIPT_DIR, "icon.png"),):
            if os.path.exists(icon_path):
                try:
                    self._icon = tk.PhotoImage(file=icon_path)
                    self.root.iconphoto(True, self._icon)
                except tk.TclError:
                    pass
                break

        self.undo_done = False
        self.tabs = []
        self.current_tab = None

        self._cvar = tk.IntVar()
        self._find_search_job = None
        self._status_flash_id = None

        settings = load_settings()
        self.theme_name = settings.get("theme", "light")
        self._dark_var = tk.BooleanVar(value=(self.theme_name == "dark"))
        self._menus = []

        self._build_menu()
        self._build_find_bar()
        self._build_notebook()
        self._build_status_bar()
        self.apply_theme(self.theme_name, save=False)

        if files:
            for path in files:
                self._open_path(path)
        else:
            self.new_tab()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_menu(self):
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        self._menus = [menubar]

        file_menu = tk.Menu(menubar, tearoff=0)
        self._menus.append(file_menu)
        file_menu.add_command(label="New Tab", accelerator="Ctrl+N", command=self.new_tab)
        file_menu.add_command(label="Open File...", accelerator="Ctrl+O", command=self.open_file)
        file_menu.add_command(label="Refresh", accelerator="F5", command=self.refresh_file)
        file_menu.add_separator()
        file_menu.add_command(label="Open in VS Code", command=self.open_in_vscode)
        file_menu.add_command(label="Open Terminal in Folder", command=self.open_terminal)
        file_menu.add_command(label="View Markdown Preview", accelerator="Ctrl+Shift+M",
                               command=self.view_markdown)
        self._md_menu = file_menu
        self._md_menu_index = file_menu.index("end")
        file_menu.add_separator()
        file_menu.add_command(label="Save", accelerator="Ctrl+S", command=self.save_file)
        file_menu.add_command(label="Save As...", accelerator="Ctrl+Shift+S", command=self.save_file_as)
        file_menu.add_separator()
        file_menu.add_command(label="Print...", accelerator="Ctrl+P", command=self.print_file)
        file_menu.add_separator()

        file_menu.add_command(label="Close Tab", accelerator="Ctrl+W", command=self.close_tab)
        file_menu.add_command(label="Exit", command=self._on_close)
        menubar.add_cascade(label="File", menu=file_menu)

        edit_menu = tk.Menu(menubar, tearoff=0)
        self._menus.append(edit_menu)
        edit_menu.add_command(label="Undo", accelerator="Ctrl+Z", command=self.undo)
        edit_menu.add_command(label="Redo", accelerator="Ctrl+Y", command=self.redo)
        edit_menu.add_separator()
        edit_menu.add_command(label="Cut", accelerator="Ctrl+X", command=lambda: self._event("cut"))
        edit_menu.add_command(label="Copy", accelerator="Ctrl+C", command=lambda: self._event("copy"))
        edit_menu.add_command(label="Paste", accelerator="Ctrl+V", command=lambda: self._event("paste"))
        edit_menu.add_command(label="Select All", accelerator="Ctrl+A", command=lambda: self._event("select_all"))
        edit_menu.add_separator()
        edit_menu.add_command(label="Find...", accelerator="Ctrl+F", command=self.show_find)
        edit_menu.add_command(label="Find Next", accelerator="Ctrl+G", command=self.find_next)
        edit_menu.add_command(label="Find Previous", accelerator="Ctrl+Shift+G", command=self.find_prev)
        edit_menu.add_separator()
        edit_menu.add_command(label="Replace...", accelerator="Ctrl+H", command=self.show_replace)
        edit_menu.add_command(label="Replace All", accelerator="Ctrl+Shift+H", command=self.replace_all)
        menubar.add_cascade(label="Edit", menu=edit_menu)
        self.edit_menu = edit_menu

        view_menu = tk.Menu(menubar, tearoff=0)
        self._menus.append(view_menu)
        view_menu.add_checkbutton(label="Dark Theme", variable=self._dark_var,
                                   command=self.toggle_theme)
        menubar.add_cascade(label="View", menu=view_menu)

        tools_menu = tk.Menu(menubar, tearoff=0)
        self._menus.append(tools_menu)
        tools_menu.add_command(label="Add Prefix / Suffix to Each Line...",
                               command=self.text_affix_dialog)
        tools_menu.add_command(label="Extract Substring from Each Line...",
                               command=self.text_substring_dialog)
        tools_menu.add_separator()
        tools_menu.add_command(label="Trim Each Line", command=self.text_trim)
        tools_menu.add_command(label="Duplicate Each Line (~)", command=self.text_duplicate_line)
        tools_menu.add_command(label="Insert String at Position...",
                               command=self.text_insert_at_position_dialog)
        tools_menu.add_command(label="Remove Lines Containing String...",
                               command=self.text_remove_lines_dialog)
        tools_menu.add_separator()
        tools_menu.add_command(label="Keep Selection Only",
                               command=self.keep_selection)
        tools_menu.add_command(label="Keep Lines From x To y...",
                               command=self.text_keep_lines_dialog)
        tools_menu.add_separator()
        # These two act on the selection itself rather than on whole lines,
        # so they sit apart from the line-oriented tools above.
        tools_menu.add_command(label="Make Selection UPPERCASE", accelerator="Alt+U",
                               command=self.selection_upper)
        tools_menu.add_command(label="Make Selection lowercase", accelerator="Alt+L",
                               command=self.selection_lower)
        menubar.add_cascade(label="Text Tools", menu=tools_menu)

        md_menu = tk.Menu(menubar, tearoff=0)
        self._menus.append(md_menu)
        md_menu.add_command(label="Bold **text**", accelerator="Ctrl+B",
                             command=lambda: self.md_wrap("**", "**", "bold text"))
        md_menu.add_command(label="Italic *text*", accelerator="Ctrl+I",
                             command=lambda: self.md_wrap("*", "*", "italic text"))
        md_menu.add_command(label="Bold Italic ***text***",
                             command=lambda: self.md_wrap("***", "***", "bold italic text"))
        md_menu.add_command(label="Strikethrough ~~text~~",
                             command=lambda: self.md_wrap("~~", "~~", "strikethrough text"))
        md_menu.add_command(label="Inline Code `code`", accelerator="Ctrl+`",
                             command=lambda: self.md_wrap("`", "`", "code"))
        md_menu.add_separator()
        md_menu.add_command(label="Heading 1 (#)", command=lambda: self.md_line_prefix("# "))
        md_menu.add_command(label="Heading 2 (##)", command=lambda: self.md_line_prefix("## "))
        md_menu.add_command(label="Heading 3 (###)", command=lambda: self.md_line_prefix("### "))
        md_menu.add_separator()
        md_menu.add_command(label="Bullet List (-)", command=lambda: self.md_line_prefix("- "))
        md_menu.add_command(label="Numbered List (1.)", command=lambda: self.md_line_prefix("1. "))
        md_menu.add_command(label="Blockquote (>)", command=lambda: self.md_line_prefix("> "))
        md_menu.add_separator()
        md_menu.add_command(label="Link [text](url)", command=self.md_insert_link)
        md_menu.add_command(label="Image ![alt](url)", command=self.md_insert_image)
        md_menu.add_command(label="Code Block ```", command=self.md_insert_code_block)
        md_menu.add_command(label="Horizontal Rule (---)", command=self.md_insert_hr)
        menubar.add_cascade(label="Markdown", menu=md_menu)

        csv_menu = tk.Menu(menubar, tearoff=0)
        self._menus.append(csv_menu)
        csv_menu.add_command(label="Sum Column/Row...",
                              command=lambda: self.csv_calculate("sum"))
        csv_menu.add_command(label="Average Column/Row...",
                              command=lambda: self.csv_calculate("average"))
        csv_menu.add_command(label="Count Column/Row...",
                              command=lambda: self.csv_calculate("count"))
        self._csv_menu = csv_menu
        self._csv_menu_indices = [0, 1, 2]
        menubar.add_cascade(label="CSV Tools", menu=csv_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        self._menus.append(help_menu)
        help_menu.add_command(label="About", command=self.show_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        self._build_shortcuts()

    def _build_shortcuts(self):
        for key, action in [
            ("<Control-n>", "new_tab"),
            ("<Control-o>", "open_file"),
            ("<Control-s>", "save_file"),
            ("<Control-Shift-s>", "save_file_as"),
            ("<Control-Shift-S>", "save_file_as"),
            ("<Control-w>", "close_tab"),
            ("<Control-W>", "close_tab"),
            ("<Control-Shift-m>", "view_markdown"),
            ("<Control-Shift-M>", "view_markdown"),
            ("<Control-p>", "print_file"),
            ("<Control-P>", "print_file"),
            ("<F5>", "refresh_file"),
        ]:
            self.root.bind(key, self._shortcut(action))
        self.root.bind("<Control-a>", self._shortcut("select_all"))
        self.root.bind("<Control-A>", self._shortcut("select_all"))
        self.root.bind("<Control-b>", lambda e: self._md_shortcut("**", "**", "bold text"))
        self.root.bind("<Control-B>", lambda e: self._md_shortcut("**", "**", "bold text"))
        self.root.bind("<Control-i>", lambda e: self._md_shortcut("*", "*", "italic text"))
        self.root.bind("<Control-I>", lambda e: self._md_shortcut("*", "*", "italic text"))
        self.root.bind("<Control-grave>", lambda e: self._md_shortcut("`", "`", "code"))
        # On non-US layouts the grave keysym is asciitilde (or a dead key), so
        # <Control-grave> alone never fires for Ctrl+`.
        self.root.bind("<Control-asciitilde>", lambda e: self._md_shortcut("`", "`", "code"))

        # Selection case conversion. Ctrl+Shift+U would be the obvious mnemonic,
        # but GTK's built-in simple input method claims that chord for Unicode
        # codepoint entry, so it never reaches Tk on GNOME/Wayland. Alt+U and
        # Alt+L are unclaimed, and both letter cases are bound for the same
        # reason the Control-Shift bindings above are doubled.
        for sequence in ("<Alt-u>", "<Alt-U>"):
            self.root.bind(sequence, self._case_shortcut(self.selection_upper))
        for sequence in ("<Alt-l>", "<Alt-L>"):
            self.root.bind(sequence, self._case_shortcut(self.selection_lower))

    @staticmethod
    def _case_shortcut(action):
        def handler(_event=None):
            action()
            # Swallow the chord so it cannot also reach the Text class binding.
            return "break"

        return handler

    def _md_shortcut(self, before, after, placeholder):
        self.md_wrap(before, after, placeholder)
        return "break"

    def _shortcut(self, action):
        def handler(_event=None):
            if action == "select_all":
                self._event("select_all")
            else:
                getattr(self, action)()
            return "break"

        return handler

    def refresh_tab(self, tab):
        """Re-render a tab's label (with unsaved marker) and the window title."""
        if tab in self.tabs:
            index = self.tabs.index(tab)
            self.notebook.tab(index, text=tab.display_name())
        self.refresh_title()

    def refresh_title(self):
        tab = self._current()
        if tab is None:
            self.root.title("UNote")
        else:
            self.root.title(f"{tab.display_name()} - UNote")

    # --- Theming --------------------------------------------------------

    def current_theme_colors(self):
        return DARK_THEME if self.theme_name == "dark" else LIGHT_THEME

    def toggle_theme(self):
        self.theme_name = "dark" if self._dark_var.get() else "light"
        self.apply_theme(self.theme_name)

    def apply_theme(self, name, save=True):
        self.theme_name = name
        self._dark_var.set(name == "dark")
        theme = self.current_theme_colors()

        style = ttk.Style(self.root)
        # "clam" is the only bundled theme that honours the colour options
        # used below (bordercolor, troughcolor, arrowcolor, ...). If this Tk
        # build does not ship it, fall back to whatever it does have and skip
        # the options that would raise `unknown option` and abort startup.
        clam_available = "clam" in style.theme_names()
        if clam_available:
            try:
                style.theme_use("clam")
            except tk.TclError:
                clam_available = False

        self.root.configure(background=theme["bg"])

        common = dict(background=theme["bg"], foreground=theme["fg"],
                      fieldbackground=theme["bg_alt"])
        if clam_available:
            common.update(bordercolor=theme["border"],
                          lightcolor=theme["bg"], darkcolor=theme["bg"])
        style.configure(".", **common)
        style.configure("TFrame", background=theme["bg"])
        style.configure("TLabel", background=theme["bg"], foreground=theme["fg"])
        button = dict(common)
        if clam_available:
            button["focuscolor"] = theme["bg"]
        style.configure("TButton", **button)
        style.map("TButton",
                  background=[("active", theme["active"]), ("pressed", theme["active"])])
        style.configure("TCheckbutton", background=theme["bg"], foreground=theme["fg"])
        style.map("TCheckbutton", background=[("active", theme["bg"])])
        style.configure("TRadiobutton", background=theme["bg"], foreground=theme["fg"])
        style.map("TRadiobutton", background=[("active", theme["bg"])])
        entry = dict(common)
        if clam_available:
            entry["insertcolor"] = theme["fg"]
        style.configure("TEntry", **entry)
        notebook = dict(common)
        if clam_available:
            notebook["bordercolor"] = theme["border"]
        style.configure("TNotebook", **notebook)
        style.configure("TNotebook.Tab", background=theme["bg_alt"], foreground=theme["fg"],
                         padding=(10, 4), **({"bordercolor": theme["border"]} if clam_available else {}))
        style.map("TNotebook.Tab",
                  background=[("selected", theme["bg"])],
                  foreground=[("selected", theme["fg"])])
        scrollbar = dict(background=theme["bg_alt"])
        if clam_available:
            scrollbar.update(troughcolor=theme["bg"], bordercolor=theme["border"],
                             arrowcolor=theme["fg"])
        style.configure("Vertical.TScrollbar", **scrollbar)
        style.configure("Horizontal.TScrollbar", **scrollbar)
        style.map("Vertical.TScrollbar", background=[("active", theme["active"])])
        style.map("Horizontal.TScrollbar", background=[("active", theme["active"])])

        for menu in self._menus:
            menu.configure(
                bg=theme["menu_bg"], fg=theme["menu_fg"],
                activebackground=theme["menu_active_bg"],
                activeforeground=theme["menu_active_fg"],
                disabledforeground=theme.get("menu_disabled_fg", theme["active"]),
            )

        for tab in self.tabs:
            tab.apply_theme(theme)

        if save:
            settings = load_settings()
            settings["theme"] = self.theme_name
            save_settings(settings)

    def show_about(self):
        messagebox.showinfo(
            parent=self.root,
            title="About UNote",
            message="This is a python written tkinter application for opening any "
            "text related files.\n\nWritten by Theo Uys",
        )

    def _build_notebook(self):
        self.root.grid_rowconfigure(1, weight=1)
        self.root.grid_columnconfigure(0, weight=1)
        self.notebook = ttk.Notebook(self.root)
        self.notebook.grid(row=1, column=0, sticky="nsew")
        self.notebook.bind("<Button-3>", self._tab_context_menu)
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

    def _build_status_bar(self):
        bar = ttk.Frame(self.root, padding=(8, 2), relief="sunken")
        self._status_bar = bar
        bar.grid(row=2, column=0, sticky="ew")
        self._csv_status_var = tk.StringVar(value="")
        ttk.Label(bar, textvariable=self._csv_status_var, anchor="w").pack(
            side="left", fill="x")
        self._status_var = tk.StringVar(value="Ln 1, Col 1")
        ttk.Label(bar, textvariable=self._status_var, anchor="e").pack(
            side="right", fill="x", expand=True)
        self.update_status()

    def update_status(self):
        tab = self._current()
        if tab is None:
            self._status_var.set("")
            self._update_md_menu_state()
            self._update_csv_menu_state()
            return
        line, column = tab.text.index("insert").split(".")
        # Show the line ending the file will be written with, so a CRLF file
        # being edited on Linux does not turn into LF without the user noticing.
        ending = {"\r\n": "CRLF", "\n": "LF", "\r": "CR"}.get(
            tab.newline, "LF")
        text = f"{ending}   Ln {line}, Col {int(column) + 1}"
        if text != self._status_var.get():
            self._status_var.set(text)
        self._update_md_menu_state()
        self._update_csv_menu_state()

    def _flash_status(self, message, ms=4000):
        """Show a transient hint in the status bar, then restore the real one.

        Used instead of a modal dialog for shortcuts: a popup that has to be
        dismissed is worse than useless when the user is mid-keystroke.
        """
        if self._status_flash_id is not None:
            self.root.after_cancel(self._status_flash_id)
        self._status_var.set(message)
        self._status_flash_id = self.root.after(ms, self._end_status_flash)

    def _end_status_flash(self):
        self._status_flash_id = None
        self.update_status()

    # --- Line scope + in-place editing helpers ------------------------

    def _total_lines(self, text):
        return int(text.index("end-1c").split(".")[0])

    def _visible_lines(self, text):
        """The number of lines a person would count.

        The buffer always carries a final newline that get_content() strips,
        so a file that ends in a newline presents one more Tk line than it has.
        Line numbers, range checks and reports should all use this instead of
        the raw Tk count, or every one of them reads one line too many.
        """
        total = self._total_lines(text)
        if total > 1 and text.get("1.0", "end-1c").endswith("\n"):
            total -= 1
        return total

    def _line_scope(self, tab):
        """(first, last) 1-based line numbers the operation should touch.

        Uses the selection when there is one, expanded out to whole lines,
        otherwise the whole document. A collapsed cursor is not a selection,
        so it falls back to the whole document.
        """
        text = tab.text
        rng = text.tag_ranges("sel")
        if len(rng) < 2:
            return 1, self._visible_lines(text)
        # A real Tk selection is one range; take the outer bounds of whatever
        # is there so extra ranges can only widen the scope, never shrink it.
        start = min((str(i) for i in rng[::2]),
                    key=lambda s: tuple(int(p) for p in s.split(".")))
        end = max((str(i) for i in rng[1::2]),
                  key=lambda s: tuple(int(p) for p in s.split(".")))
        if start == end:
            return 1, self._visible_lines(text)
        first = int(start.split(".")[0])
        last = int(end.split(".")[0])
        # A selection that stops at column 0 has not really entered that line.
        if last > first and end.split(".")[1] == "0":
            last -= 1
        # "Select All" runs to the buffer's phantom final line, which is not a
        # line of the document; without this the scope counts one line too many.
        return first, min(last, self._visible_lines(text))

    def _scope_lines(self, tab, first, last, skip_blank=True):
        """Yield (line_no, content) for the scope, optionally ignoring blanks."""
        text = tab.text
        for n in range(first, last + 1):
            content = text.get(f"{n}.0", f"{n}.end")
            if skip_blank and not content.strip():
                continue
            yield n, content

    def _apply_line_edits(self, tab, changes):
        """Replace whole lines in place, as a single undoable step.

        Deliberately not set_content(): that resets the undo history and clears
        the modified flag, neither of which we want after a bulk edit.
        """
        text = tab.text
        saved = text.index("insert")
        text.edit_separator()
        for line_no, new_content in changes:
            text.replace(f"{line_no}.0", f"{line_no}.end", new_content)
        text.edit_separator()
        self._restore_insert(text, saved)
        self._after_mutation(tab)

    @staticmethod
    def _restore_insert(text, saved):
        """Put the cursor back where it was, clamped to the rewritten line.

        Tk gives the insert mark right gravity, so replacing the line under it
        would otherwise fling the cursor to the end of that line.
        """
        line, column = saved.split(".")
        line_no, column_no = int(line), int(column)
        if text.compare(f"{line_no}.0", ">", "end"):
            return
        line_end = int(text.index(f"{line_no}.end").split(".")[1])
        text.mark_set("insert", f"{line_no}.{min(column_no, line_end)}")

    def _after_mutation(self, tab):
        """Drop stale find highlights and refresh what is left."""
        tab.text.tag_remove("unote_find", "1.0", "end")
        tab.text.tag_remove("unote_find_sel", "1.0", "end")
        self.update_status()
        if self._find_bar.winfo_manager():
            self._apply_find_tags(tab)

    def _report(self, changed, total, noun="line", verb="Changed"):
        plural = f"{noun}s" if total != 1 else noun
        if not total:
            messagebox.showinfo(
                parent=self.root,
                title="Text Tools",
                message=f"No {plural} to operate on.")
        elif not changed:
            messagebox.showinfo(
                parent=self.root,
                title="Text Tools",
                message=f"0 of {total} {plural} changed - nothing to do.")
        else:
            messagebox.showinfo(
                parent=self.root,
                title="Text Tools",
                message=f"{verb} {changed} of {total} {plural}.")

    def _keep_lines(self, tab, first, last, total=None):
        """Replace the document with lines first..last, as a single undo step.

        Cutting the head and the tail by line number is a trap here. The buffer
        always carries one final newline that get_content() strips, so a file
        ending in a newline has one more "line" than one that does not, and
        whichever side a cut lands on decides whether that newline survives.
        Building the result as a string and replacing the buffer in one call
        sidesteps the question, and keeps undo to a single step.
        """
        text = tab.text
        if total is None:
            total = self._visible_lines(text)
        lines = [text.get(f"{n}.0", f"{n}.end")
                 for n in range(first, min(last, total) + 1)]
        kept = "\n".join(lines)
        # An empty result is an empty document, not a lone newline. Otherwise
        # carry the source's trailing newline over to the trimmed text.
        if kept and text.get("1.0", "end-1c").endswith("\n"):
            kept += "\n"
        if kept == text.get("1.0", "end-1c"):
            return len(lines)
        text.edit_separator()
        text.replace("1.0", "end", kept)
        text.edit_separator()
        # The old selection refers to offsets that no longer mean anything,
        # and would otherwise narrow the scope of the next operation.
        text.tag_remove("sel", "1.0", "end")
        text.mark_set("insert", "1.0")
        self._after_mutation(tab)
        return len(lines)

    def _build_find_bar(self):
        bar = ttk.Frame(self.root, padding=(6, 3))
        self._find_bar = bar
        bar.grid(row=0, column=0, sticky="ew")
        bar.grid_remove()

        top = ttk.Frame(bar)
        top.pack(side="top", fill="x")
        ttk.Label(top, text="Find:").pack(side="left", padx=(4, 4))
        self._find_var = tk.StringVar()
        entry = ttk.Entry(top, width=32, textvariable=self._find_var)
        entry.pack(side="left", ipady=1)
        self._find_entry = entry
        ttk.Button(top, text="Prev", width=5,
                   command=self.find_prev).pack(side="left", padx=(6, 2))
        ttk.Button(top, text="Next", width=5,
                   command=self.find_next).pack(side="left", padx=2)
        self._find_case = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="Match case", variable=self._find_case,
                        command=self._reapply_search).pack(side="left", padx=(10, 0))
        self._find_count = ttk.Label(top, text="")
        self._find_count.pack(side="left", padx=(12, 0))
        ttk.Button(top, text="Close",
                   command=self.hide_find).pack(side="right", padx=(10, 4))

        self._build_replace_row(bar)

        self._find_var.trace_add("write", self._on_find_typed)
        entry.bind("<Return>", lambda e: self.find_next())
        entry.bind("<Shift-Return>", lambda e: self.find_prev())
        entry.bind("<Down>", lambda e: self.find_next())
        entry.bind("<Up>", lambda e: self.find_prev())
        entry.bind("<Escape>", lambda e: self.hide_find())

        self.root.bind("<Control-f>", lambda e: self.show_find())
        self.root.bind("<Control-F>", lambda e: self.show_find())
        self.root.bind("<Control-g>", lambda e: self.find_next())
        self.root.bind("<Control-G>", lambda e: self.find_next())
        self.root.bind("<Control-Shift-g>", lambda e: self.find_prev())
        self.root.bind("<Control-Shift-G>", lambda e: self.find_prev())
        self.root.bind("<Control-h>", lambda e: self.show_replace())
        self.root.bind("<Control-H>", lambda e: self.show_replace())
        self.root.bind("<Control-Shift-h>", lambda e: self.replace_all())
        self.root.bind("<Control-Shift-H>", lambda e: self.replace_all())

    def _build_replace_row(self, bar):
        self._replace_row = ttk.Frame(bar)
        ttk.Label(self._replace_row, text="Replace with:").pack(
            side="left", padx=(4, 4))
        self._replace_var = tk.StringVar()
        self._replace_entry = ttk.Entry(self._replace_row, width=32,
                                        textvariable=self._replace_var)
        self._replace_entry.pack(side="left", ipady=1)
        ttk.Button(self._replace_row, text="Replace", width=9,
                   command=self.replace_current).pack(side="left", padx=(6, 2))
        ttk.Button(self._replace_row, text="Replace All", width=11,
                   command=self.replace_all).pack(side="left", padx=2)
        self._replace_entry.bind("<Escape>", lambda e: self.hide_find())
        # Built hidden; show_replace() packs it into the bar.

    def show_replace(self):
        self._find_bar.grid()
        if not self._replace_row.winfo_manager():
            self._replace_row.pack(side="top", fill="x", pady=(3, 0))
        self._replace_entry.focus_set()
        self._replace_entry.selection_range(0, "end")
        return "break"

    def _current(self):
        if not self.tabs:
            return None
        index = self.notebook.index("current")
        if index >= len(self.tabs):
            return None
        return self.tabs[index]

    def new_tab(self):
        tab = TextTab("Untitled", app=self, theme=self.current_theme_colors())
        tab.frame.master = self.root
        self.tabs.append(tab)
        self.notebook.add(tab.frame, text=tab.display_name())
        self.notebook.select(tab.frame)
        self.current_tab = tab
        tab.text.focus_set()
        self.refresh_title()
        self.update_status()
        return tab

    # --- Markdown snippets -----------------------------------------------

    def _current_line_range(self, tab):
        """1-based (first, last) line numbers to prefix.

        Uses the lines touched by a real selection, or just the cursor's
        current line when there is no selection.
        """
        text = tab.text
        rng = text.tag_ranges("sel")
        if len(rng) == 2 and str(rng[0]) != str(rng[1]):
            start, end = str(rng[0]), str(rng[1])
            first = int(start.split(".")[0])
            last = int(end.split(".")[0])
            if last > first and end.split(".")[1] == "0":
                last -= 1
            return first, last
        line = int(text.index("insert").split(".")[0])
        return line, line

    def md_wrap(self, before, after, placeholder):
        """Wrap the current selection in before/after markers, or insert a
        placeholder (pre-selected so typing replaces it) if nothing is
        selected."""
        tab = self._current()
        if tab is None:
            return
        text = tab.text
        rng = text.tag_ranges("sel")
        text.edit_separator()
        if len(rng) == 2 and str(rng[0]) != str(rng[1]):
            start, end = str(rng[0]), str(rng[1])
            selected = text.get(start, end)
            text.replace(start, end, f"{before}{selected}{after}")
            new_pos = text.index(f"{start}+{len(before) + len(selected) + len(after)}c")
            text.mark_set("insert", new_pos)
        else:
            pos = text.index("insert")
            text.insert(pos, f"{before}{placeholder}{after}")
            sel_start = text.index(f"{pos}+{len(before)}c")
            sel_end = text.index(f"{sel_start}+{len(placeholder)}c")
            text.tag_remove("sel", "1.0", "end")
            text.tag_add("sel", sel_start, sel_end)
            text.mark_set("insert", sel_end)
        text.edit_separator()
        text.see("insert")
        text.focus_set()
        self._after_mutation(tab)

    def md_line_prefix(self, prefix):
        """Add a prefix (heading/bullet/quote marker) to each selected
        line, or just the current line if nothing is selected."""
        tab = self._current()
        if tab is None:
            return
        first, last = self._current_line_range(tab)
        changes = [(n, prefix + content)
                   for n, content in self._scope_lines(tab, first, last, skip_blank=False)]
        if changes:
            self._apply_line_edits(tab, changes)
        self._report(len(changes), len(changes))

    def md_insert_hr(self):
        tab = self._current()
        if tab is None:
            return
        text = tab.text
        pos = text.index("insert")
        needs_leading_nl = pos != "1.0" and text.get(f"{pos} linestart", pos).strip() != ""
        snippet = ("\n" if needs_leading_nl else "") + "---\n"
        text.edit_separator()
        text.insert(pos, snippet)
        text.edit_separator()
        text.see("insert")
        text.focus_set()
        self._after_mutation(tab)

    def md_insert_code_block(self):
        tab = self._current()
        if tab is None:
            return
        text = tab.text
        rng = text.tag_ranges("sel")
        text.edit_separator()
        if len(rng) == 2 and str(rng[0]) != str(rng[1]):
            start, end = str(rng[0]), str(rng[1])
            selected = text.get(start, end)
            text.replace(start, end, f"```\n{selected}\n```\n")
        else:
            pos = text.index("insert")
            text.insert(pos, "```\n\n```\n")
            lang_line = text.index(f"{pos}+4c")
            text.mark_set("insert", lang_line)
        text.edit_separator()
        text.see("insert")
        text.focus_set()
        self._after_mutation(tab)

    def md_insert_link(self):
        self._md_insert_link_or_image(image=False)

    def md_insert_image(self):
        self._md_insert_link_or_image(image=True)

    def _md_insert_link_or_image(self, image):
        tab = self._current()
        if tab is None:
            return
        text = tab.text
        rng = text.tag_ranges("sel")
        bang = "!" if image else ""
        default_text = "alt text" if image else "link text"
        text.edit_separator()
        if len(rng) == 2 and str(rng[0]) != str(rng[1]):
            start, end = str(rng[0]), str(rng[1])
            selected = text.get(start, end)
            text.replace(start, end, f"{bang}[{selected}](url)")
            url_start = text.index(f"{start}+{len(bang) + len(selected) + 3}c")
            url_end = text.index(f"{url_start}+3c")
        else:
            pos = text.index("insert")
            text.insert(pos, f"{bang}[{default_text}](url)")
            url_start = text.index(f"{pos}+{len(bang) + len(default_text) + 3}c")
            url_end = text.index(f"{url_start}+3c")
        text.tag_remove("sel", "1.0", "end")
        text.tag_add("sel", url_start, url_end)
        text.mark_set("insert", url_end)
        text.edit_separator()
        text.see("insert")
        text.focus_set()
        self._after_mutation(tab)

    # --- Markdown viewer -------------------------------------------------

    def _is_markdown_tab(self, tab):
        if tab is None or not tab.path:
            return False
        return os.path.splitext(tab.path)[1].lower() in MARKDOWN_EXTENSIONS

    def _update_md_menu_state(self):
        menu = getattr(self, "_md_menu", None)
        if menu is None:
            return
        tab = self._current()
        state = "normal" if self._is_markdown_tab(tab) else "disabled"
        menu.entryconfig(self._md_menu_index, state=state)

    # --- CSV tools --------------------------------------------------------

    def _is_csv_tab(self, tab):
        if tab is None or not tab.path:
            return False
        return os.path.splitext(tab.path)[1].lower() in CSV_EXTENSIONS

    def _update_csv_menu_state(self):
        menu = getattr(self, "_csv_menu", None)
        if menu is None:
            return
        tab = self._current()
        state = "normal" if self._is_csv_tab(tab) else "disabled"
        for idx in self._csv_menu_indices:
            menu.entryconfig(idx, state=state)

    def csv_calculate(self, operation):
        tab = self._current()
        if not self._is_csv_tab(tab):
            return

        win, body = self._dialog_shell(f"CSV Tools - {operation.capitalize()}")
        scope_var = tk.StringVar(value="column")
        index_var = tk.StringVar(value="1")
        header_var = tk.BooleanVar(value=True)

        ttk.Label(body, text="Apply to:").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
        ttk.Radiobutton(body, text="Column", variable=scope_var,
                        value="column").grid(row=1, column=0, sticky="w")
        ttk.Radiobutton(body, text="Row", variable=scope_var,
                        value="row").grid(row=1, column=1, sticky="w")

        ttk.Label(body, text="Index (1-based):").grid(
            row=2, column=0, sticky="w", padx=(0, 6), pady=(8, 0))
        index_entry = ttk.Entry(body, textvariable=index_var, width=8)
        index_entry.grid(row=2, column=1, sticky="w", pady=(8, 0))

        ttk.Checkbutton(
            body, text="First row is a header (skip it for column operations)",
            variable=header_var,
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))

        def apply():
            raw = index_var.get().strip()
            if not raw.isdigit() or int(raw) < 1:
                messagebox.showerror(
                    parent=win,
                    title="CSV Tools",
                    message="Index must be a whole number 1 or greater.")
                return
            index = int(raw)
            scope = scope_var.get()
            skip_header = header_var.get() and scope == "column"
            target = self._require_tab(tab)
            if target is None:
                return
            try:
                self._apply_csv_calculate(target, operation, scope, index, skip_header)
            except ValueError as exc:
                messagebox.showerror(parent=win, message=str(exc))
                return
            win.destroy()

        buttons = ttk.Frame(body)
        buttons.grid(row=4, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(buttons, text="Cancel", command=win.destroy).pack(
            side="right", padx=(6, 0))
        ttk.Button(buttons, text="Calculate", command=apply).pack(side="right")
        index_entry.bind("<Return>", lambda e: apply())
        index_entry.bind("<Escape>", lambda e: win.destroy())
        index_entry.focus_set()
        index_entry.selection_range(0, "end")
        return win

    def _apply_csv_calculate(self, tab, operation, scope, index, skip_header):
        content = tab.get_content()
        rows = list(csv.reader(io.StringIO(content)))
        if not rows:
            raise ValueError("The file has no CSV data to operate on.")

        if scope == "row":
            if index > len(rows):
                raise ValueError(
                    f"Row {index} does not exist (file has {len(rows)} row(s)).")
            cells = rows[index - 1]
            label = f"Row {index}"
        else:
            data_rows = rows[1:] if skip_header and len(rows) > 1 else rows
            max_cols = max((len(r) for r in data_rows), default=0)
            if index > max_cols:
                raise ValueError(
                    f"Column {index} does not exist "
                    f"(widest row has {max_cols} column(s)).")
            cells = [r[index - 1] for r in data_rows if index - 1 < len(r)]
            label = f"Column {index}"
            if skip_header and len(rows) > 1:
                label += " (header skipped)"

        non_empty = [c.strip() for c in cells if c.strip() != ""]
        numeric = []
        for c in non_empty:
            try:
                numeric.append(float(c))
            except ValueError:
                continue

        if operation == "count":
            result_text = (
                f"{label} Count: {len(non_empty)} non-empty cell(s) "
                f"of {len(cells)} total")
        else:
            if not numeric:
                raise ValueError(f"{label} has no numeric values to {operation}.")
            if operation == "sum":
                value = sum(numeric)
                result_text = f"{label} Sum: {self._format_number(value)}"
            else:
                value = sum(numeric) / len(numeric)
                result_text = f"{label} Average: {self._format_number(value)}"
            skipped = len(non_empty) - len(numeric)
            if skipped:
                result_text += (
                    f"  ({len(numeric)} numeric of {len(non_empty)} "
                    f"non-empty cells, {skipped} skipped)")

        self._csv_status_var.set(result_text)

    @staticmethod
    def _format_number(value):
        if value == int(value):
            return str(int(value))
        return f"{value:.4f}".rstrip("0").rstrip(".")

    def view_markdown(self):
        tab = self._current()
        if not self._is_markdown_tab(tab):
            return
        show_markdown_preview(self.root, tab.get_content(), tab.title, self.root)

    def _confirm_save_before(self, tab, what):
        """Offer to save a dirty tab first. False means "user cancelled"."""
        answer = messagebox.askyesnocancel(
            parent=self.root,
            title="UNote",
            message=f'"{tab.title}" has unsaved changes.\nSave before {what}?',
        )
        if answer is None:
            return False
        return bool(answer) and self.save_file()

    def print_file(self):
        tab = self._current()
        if tab is None:
            return

        if self._is_markdown_tab(tab):
            # Markdown prints from its rendered form, not as raw source.
            if tab.modified and not self._confirm_save_before(tab, "printing"):
                return
            show_markdown_preview(self.root, tab.get_content(), tab.title,
                                  self.root)
            return

        if not tab.path or not os.path.exists(tab.path):
            messagebox.showinfo(
                parent=self.root,
                title="Print",
                message="This tab has no file on disk yet.\n"
                        "Save it first, then try again.",
            )
            return
        if tab.modified and not self._confirm_save_before(tab, "printing"):
            return

        content = tab.get_content()
        title = tab.title

        if PYWIN32_AVAILABLE and IS_WINDOWS:
            printer = choose_printer_dialog(self.root, self.current_theme_colors())
            if not printer:
                return
            try:
                printed = print_text_native(printer, title, content,
                                            parent=self.root)
            except Exception as exc:
                messagebox.showerror(
                    parent=self.root,
                    title="Print",
                    message=f"Could not print to '{printer}':\n{exc}",
                )
                return
            if printed:
                messagebox.showinfo(
                    parent=self.root,
                    title="Print",
                    message=f"Sent to printer: {printer}",
                )
            return

        if not IS_WINDOWS and find_executable("lp"):
            # Gate on there actually BEING printers, not just on the `lp`
            # binary existing. Any desktop with cups-client installed has
            # `lp` even when no queue is configured or cupsd is not running,
            # and taking the dialog in that state only leads to a dead-end
            # "No printers were found" error instead of the browser preview.
            if list_printers()[0]:
                printer = choose_printer_dialog(self.root,
                                                self.current_theme_colors())
                if not printer:
                    return
                try:
                    print_text_cups(printer, title, content)
                except Exception as exc:
                    messagebox.showerror(
                        parent=self.root,
                        title="Print",
                        message=f"Could not print to '{printer}':\n{exc}",
                    )
                    return
                messagebox.showinfo(
                    parent=self.root,
                    title="Print",
                    message=f"Sent to printer: {printer}",
                )
                return
            # No queues configured: fall through to the browser print preview
            # below rather than giving up.

        self._open_print_preview(content, title)

    def _open_print_preview(self, content, title):
        """Hand the text to the browser, which can print it to PDF."""
        html_doc = self._render_plain_text_html(content, title)
        try:
            fd, tmp_path = tempfile.mkstemp(suffix=".html", prefix="unote_print_")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(html_doc)
        except OSError as exc:
            messagebox.showerror(
                parent=self.root,
                title="Print",
                message=f"Could not create temporary print file:\n{exc}",
            )
            return
        opened = open_html_file(tmp_path)
        if not opened:
            messagebox.showerror(
                parent=self.root,
                title="Print",
                message="Could not find a browser to open the print preview.\n"
                        f"The HTML file was generated at:\n{tmp_path}",
            )

    @staticmethod
    def _render_plain_text_html(content, title):
        escaped = html.escape(content)
        escaped_title = html.escape(title)
        return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{escaped_title}</title>
<style>
  body {{ margin: 2em auto; max-width: 900px; padding: 0 1em; }}
  pre {{ font-family: ui-monospace, "DejaVu Sans Mono", "Liberation Mono",
         Consolas, monospace; font-size: 10pt; white-space: pre-wrap;
         word-wrap: break-word; }}
  @media print {{
    body {{ margin: 0; max-width: none; }}
  }}
</style>
</head>
<body>
<pre>{escaped}</pre>
</body>
</html>
"""

    def _find_vscode(self):
        for cmd in VSCODE_COMMANDS:
            exe = find_executable(cmd)
            if exe:
                return exe
        if IS_WINDOWS:
            candidates = []
            local_appdata = os.environ.get("LOCALAPPDATA")
            if local_appdata:
                candidates.append(os.path.join(
                    local_appdata, "Programs", "Microsoft VS Code", "Code.exe"))
            program_files = os.environ.get("ProgramFiles")
            if program_files:
                candidates.append(os.path.join(
                    program_files, "Microsoft VS Code", "Code.exe"))
            for candidate in candidates:
                if os.path.exists(candidate):
                    return candidate
        return None

    def open_in_vscode(self):
        tab = self._current()
        if tab is None:
            return
        if not tab.path or not os.path.exists(tab.path):
            messagebox.showinfo(
                parent=self.root,
                title="Open in VS Code",
                message="This tab has no file on disk yet.\n"
                        "Save it first, then try again.",
            )
            return
        if tab.modified:
            answer = messagebox.askyesnocancel(
                parent=self.root,
                title="UNote",
                message=f'"{tab.title}" has unsaved changes.\n'
                        "Save before opening in VS Code?",
            )
            if answer is None:
                return
            if answer and not self.save_file():
                return
        code = self._find_vscode()
        if not code:
            messagebox.showerror(
                parent=self.root,
                title="Open in VS Code",
                message="Could not find Visual Studio Code.\n"
                        "Make sure it is installed and either on your PATH "
                        "or in its default install location.",
            )
            return
        subprocess.Popen([code, tab.path])

    def _find_terminal(self):
        for name in TERMINAL_WORKDIR_FLAGS:
            if find_executable(name):
                return name
        return None

    def _terminal_argv(self, name, folder):
        """argv that opens `name` in `folder`, running the user's own shell."""
        if name == "xterm":
            # xterm has no working-directory flag; -e runs the rest of the argv
            # in the new window, so give it the shell directly.
            return ["-e", _user_shell()]
        flag = TERMINAL_WORKDIR_FLAGS[name]
        if not flag:
            return []
        if name == "wezterm":
            return ["start", "--cwd", folder]
        # Use the --flag=value form: it is understood by both GOption (konsole,
        # tilix, xfce4-terminal) and clap (alacritty), which differ on whether
        # a detached value is accepted.
        return [f"{flag}={folder}"]

    def open_terminal(self):
        tab = self._current()
        if tab is None:
            return
        if not tab.path or not os.path.exists(tab.path):
            messagebox.showinfo(
                parent=self.root,
                title="Open Terminal",
                message="This tab has no file on disk yet.\n"
                        "Save it first, then try again.",
            )
            return
        # A path opened from the command line can be relative, and dirname("")
        # would then hand the terminal an empty directory to cd into.
        folder = os.path.dirname(os.path.abspath(tab.path))

        if IS_WINDOWS:
            # Passed as a single command-line string rather than a list:
            # subprocess.list2cmdline() would otherwise re-escape the
            # already-quoted `cd /d "..."` text, corrupting it for cmd.exe's
            # own parser (especially with paths containing spaces).
            subprocess.Popen(f'cmd.exe /K cd /d "{folder}"')
            return

        name = self._find_terminal()
        if not name:
            messagebox.showerror(
                parent=self.root,
                title="Open Terminal",
                message="No supported terminal emulator found.",
            )
            return
        try:
            subprocess.Popen([name] + self._terminal_argv(name, folder))
        except OSError as exc:
            messagebox.showerror(
                parent=self.root,
                title="Open Terminal",
                message=f"Could not start {name}:\n{exc}",
            )

    def open_file(self):
        path = filedialog.askopenfilename(
            parent=self.root, title="Open file",
            filetypes=self._file_types(),
            initialdir=self._dialog_initial_dir())
        if not path:
            return
        self._open_path(path)

    def refresh_file(self):
        """Reload the focused tab's content from disk, discarding any
        in-memory changes (with confirmation if there are any)."""
        tab = self._current()
        if tab is None:
            return
        if not tab.path or not os.path.exists(tab.path):
            messagebox.showinfo(
                parent=self.root,
                title="Refresh",
                message="This tab has no file on disk yet, so there is "
                        "nothing to refresh from.",
            )
            return
        if tab.modified:
            if not messagebox.askyesno(
                    parent=self.root,
                    title="Refresh",
                    message=f'"{tab.title}" has unsaved changes.\n'
                            "Reloading from disk will discard them. Continue?"):
                return
        saved_insert = tab.text.index("insert")
        try:
            tab.load_file(tab.path)
        except Exception as e:
            messagebox.showerror(
                parent=self.root,
                title="Refresh",
                message=f"Cannot refresh file:\n{e}",
            )
            return
        try:
            tab.text.mark_set("insert", saved_insert)
            tab.text.see(saved_insert)
        except tk.TclError:
            pass
        self.update_status()

    def _dialog_initial_dir(self):
        """The folder to start Open/Save dialogs in: the current tab's
        file's folder if there is one, otherwise the user's home directory."""
        tab = self._current()
        if tab is not None and tab.path:
            folder = os.path.dirname(os.path.abspath(tab.path))
            if folder and os.path.isdir(folder):
                return folder
        # Not the working directory: a process started from a .desktop file
        # usually has $HOME (or worse, /) as its cwd.
        home = os.path.expanduser("~")
        return home if os.path.isdir(home) else os.getcwd()

    @staticmethod
    def _file_types():
        """Shared chooser filters.

        The catch-all is "*", not "*.*": Tk passes these to a Tcl glob, and
        "*.*" matches neither dotfiles nor extension-less names, so
        Makefile, Dockerfile, .gitignore and LICENSE become unselectable.
        """
        return [
            ("Text files", "*.txt"),
            ("Markdown", " ".join(f"*{e}" for e in MARKDOWN_EXTENSIONS)),
            ("CSV", " ".join(f"*{e}" for e in CSV_EXTENSIONS)),
            ("All files", "*"),
        ]

    def _open_path(self, path):
        tab = None
        try:
            tab = self.new_tab()
            lossy = tab.load_file(path)
            self._update_tab_text(tab)
        except Exception as e:
            if tab is not None:
                self.close_tab(tab)
            messagebox.showerror(
                parent=self.root,
                title="Open File",
                message=f"Cannot open file:\n{e}")
            return
        if lossy:
            # Undecodable bytes were replaced. Saving would write the
            # replacement characters back over the original, so say so.
            messagebox.showwarning(
                parent=self.root,
                title="Open File",
                message=f'"{os.path.basename(path)}" is not valid UTF-8 text.\n'
                "Some characters were replaced with '?'.\n"
                "Saving will write the replacements to the file.",
            )

    def save_file(self):
        tab = self._current()
        if tab is None:
            return
        if tab.path:
            try:
                self._write(tab.path, tab.get_content(), tab.newline)
                tab.modified = False
                tab.text.edit_modified(False)
                self.refresh_tab(tab)
            except Exception as e:
                messagebox.showerror(
                    parent=self.root,
                    title="Save File",
                    message=f"Cannot save file:\n{e}")
                return False
        else:
            return self.save_file_as()
        return True

    def save_file_as(self):
        tab = self._current()
        if tab is None:
            return
        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="Save file as",
            defaultextension=".txt",
            filetypes=self._file_types(),
            initialdir=self._dialog_initial_dir(),
        )
        if not path:
            return False
        try:
            self._write(path, tab.get_content(), tab.newline)
            tab.path = path
            tab.modified = False
            tab.text.edit_modified(False)
            tab.set_title(os.path.basename(path))
            self._update_tab_text(tab)
            return True
        except Exception as e:
            messagebox.showerror(
                parent=self.root,
                title="Save File As",
                message=f"Cannot save file:\n{e}")
            return False

    @staticmethod
    def _write(path, content, newline="\n"):
        """Write text with an explicit line ending.

        Opening in text mode with the default newline would translate every
        "\n" to os.linesep, which silently rewrites a Windows-authored CRLF
        file to LF on Linux (and the reverse on Windows). Converting here
        keeps the file's own line endings intact.
        """
        with open(path, "wb") as f:
            f.write(encode_text(content, newline))

    def _update_tab_text(self, tab):
        self.refresh_tab(tab)

    def close_tab(self, tab=None):
        tab = tab or self._current()
        if tab is None:
            return
        if tab.modified:
            answer = messagebox.askyesnocancel(
                parent=self.root,
                title="UNote",
                message=f'"{tab.title}" has unsaved changes.\nSave before closing?',
            )
            if answer is None:
                return
            if answer:
                self.notebook.select(tab.frame)
                if not self.save_file():
                    return
        self.tabs.remove(tab)
        self.notebook.forget(tab.frame)
        tab.frame.destroy()
        self.current_tab = self._current()
        if self.tabs:
            self.current_tab.text.focus_set()
        self.refresh_title()
        self.update_status()

    def undo(self):
        tab = self._current()
        if tab:
            tab.text.event_generate("<<Undo>>")
            self._set_undo_done()
            self.update_status()

    def redo(self):
        tab = self._current()
        if tab:
            tab.text.event_generate("<<Redo>>")
            self._set_undo_done()
            self.update_status()

    def _set_undo_done(self):
        self.undo_done = True
        self.root.after(200, self._reset_undo_flag)

    def _reset_undo_flag(self):
        self.undo_done = False

    def _event(self, name):
        tab = self._current()
        if tab:
            if name == "select_all":
                tab.text.tag_add("sel", "1.0", "end")
                self.update_status()
                return "break"
            tab.text.event_generate(f"<<{name}>>")

    def _on_close(self):
        unsaved = [t for t in self.tabs if t.modified]
        if unsaved:
            answer = messagebox.askyesnocancel(
                parent=self.root,
                title="UNote",
                message=f"{len(unsaved)} tab(s) have unsaved changes.\nExit anyway?",
            )
            if answer is None:
                return
            if not answer:
                return
        self.root.destroy()

    def _tab_context_menu(self, event):
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="New Tab", command=self.new_tab)
        menu.add_command(label="Close Tab", command=self.close_tab)
        # tk_popup() returns as soon as the menu is *posted* on X11 (it blocks
        # until dismissal on Windows), so releasing the grab straight away
        # makes the menu flash and vanish. Release it when the menu unmaps.
        menu.bind("<Unmap>", lambda _e: menu.grab_release(), add="+")
        try:
            menu.tk_popup(event.x_root, event.y_root)
        except tk.TclError:
            menu.grab_release()
            raise

    # --- Find / search ------------------------------------------------

    def _find_params(self):
        needle = self._find_var.get()
        if not needle:
            return None
        return needle, not self._find_case.get()

    def show_find(self):
        self._find_bar.grid()
        self._find_entry.focus_set()
        self._find_entry.selection_range(0, "end")

    def hide_find(self):
        self._find_bar.grid_remove()
        self._find_count.config(text="")
        tab = self._current()
        if tab:
            tab.text.tag_remove("unote_find", "1.0", "end")
            tab.text.tag_remove("unote_find_sel", "1.0", "end")
            tab.text.focus_set()

    def _apply_find_tags(self, tab):
        text = tab.text
        text.tag_remove("unote_find", "1.0", "end")
        text.tag_remove("unote_find_sel", "1.0", "end")
        params = self._find_params()
        if params is None:
            self._find_count.config(text="")
            return 0
        needle, ci = params
        text.tag_configure("unote_find", background="#fff08a", foreground="black")
        text.tag_configure("unote_find_sel", background="#8fd0ff", foreground="black")
        count = 0
        pos = "1.0"
        while True:
            idx = text.search(needle, pos, stopindex="end", nocase=ci,
                              count=self._cvar)
            if not idx:
                break
            end = text.index(f"{idx}+{int(self._cvar.get())}c")
            text.tag_add("unote_find", idx, end)
            count += 1
            pos = end
        self._find_count.config(
            text=f"{count} match{'es' if count != 1 else ''}")
        return count

    def _show_match(self, tab, start, end):
        text = tab.text
        text.tag_remove("unote_find_sel", "1.0", "end")
        text.tag_add("unote_find_sel", start, end)
        text.tag_raise("unote_find_sel")
        text.mark_set("insert", start)
        text.see(start)
        self.update_status()

    def _select_first_match(self, tab, needle, ci):
        text = tab.text
        start = text.index("insert")
        idx = text.search(needle, start, stopindex="end", nocase=ci,
                          count=self._cvar)
        if not idx:
            idx = text.search(needle, "1.0", stopindex="end", nocase=ci,
                              count=self._cvar)
        if idx:
            end = text.index(f"{idx}+{int(self._cvar.get())}c")
            self._show_match(tab, idx, end)

    def _on_find_typed(self, *_args):
        if self._find_search_job:
            self.root.after_cancel(self._find_search_job)
        self._find_search_job = self.root.after(150, self._reapply_find_and_select)

    def _reapply_find_and_select(self):
        self._find_search_job = None
        tab = self._current()
        if not tab:
            return
        params = self._find_params()
        if params is None:
            self._apply_find_tags(tab)
            return
        needle, ci = params
        if self._apply_find_tags(tab):
            self._select_first_match(tab, needle, ci)

    def _reapply_search(self):
        tab = self._current()
        if tab:
            self._apply_find_tags(tab)

    def find_next(self):
        if not self._find_bar.winfo_manager():
            self.show_find()
            return
        tab = self._current()
        if not tab:
            return
        params = self._find_params()
        if params is None:
            return
        needle, ci = params
        text = tab.text
        start = text.index("insert")
        rng = text.tag_ranges("unote_find_sel")
        if len(rng) == 2:
            sel_start, sel_end = str(rng[0]), str(rng[1])
            if (text.compare("insert", ">=", sel_start)
                    and text.compare("insert", "<", sel_end)):
                start = sel_end
        idx = text.search(needle, start, stopindex="end", nocase=ci,
                          count=self._cvar)
        if not idx:
            idx = text.search(needle, "1.0", stopindex=start, nocase=ci,
                              count=self._cvar)
        if idx:
            end = text.index(f"{idx}+{int(self._cvar.get())}c")
            self._show_match(tab, idx, end)
            self._find_entry.focus_set()

    def find_prev(self):
        if not self._find_bar.winfo_manager():
            self.show_find()
            return
        tab = self._current()
        if not tab:
            return
        params = self._find_params()
        if params is None:
            return
        needle, ci = params
        text = tab.text
        result = None
        pos = "1.0"
        while True:
            idx = text.search(needle, pos, stopindex="insert", nocase=ci,
                              count=self._cvar)
            if not idx:
                break
            result = idx
            pos = text.index(f"{idx}+{int(self._cvar.get())}c")
        if result is None:
            pos = "1.0"
            while True:
                idx = text.search(needle, pos, stopindex="end", nocase=ci,
                                  count=self._cvar)
                if not idx:
                    break
                result = idx
                pos = text.index(f"{idx}+{int(self._cvar.get())}c")
        if result:
            end = text.index(f"{result}+{int(self._cvar.get())}c")
            self._show_match(tab, result, end)
            self._find_entry.focus_set()

    # --- Replace ------------------------------------------------------

    def _replace_params(self):
        needle = self._find_var.get()
        if not needle:
            return None
        return needle, self._replace_var.get(), not self._find_case.get()

    def _replace_targets(self, text, needle, ci, first, last):
        """Every match inside the scope, as (start, end) index pairs.

        Collected up front against the untouched text so that mutating the
        buffer can never shift a range we have not visited yet.
        """
        targets = []
        pos = f"{first}.0"
        end_limit = f"{last}.end"
        while True:
            idx = text.search(needle, pos, stopindex=end_limit, nocase=ci,
                              count=self._cvar)
            if not idx:
                break
            if int(idx.split(".")[0]) > last:
                break
            length = int(self._cvar.get())
            end = text.index(f"{idx}+{length}c")
            targets.append((idx, end))
            pos = end
        return targets

    def replace_current(self):
        if not self._find_bar.winfo_manager():
            self.show_replace()
            return "break"
        tab = self._current()
        if tab is None:
            return "break"
        params = self._replace_params()
        if params is None:
            messagebox.showinfo(
                parent=self.root,
                title="Replace",
                message="Type something to find first.")
            return "break"
        needle, repl, ci = params
        text = tab.text
        rng = text.tag_ranges("unote_find_sel")
        if len(rng) == 2:
            start, end = str(rng[0]), str(rng[1])
        else:
            start = text.index("insert")
            idx = text.search(needle, start, stopindex="end", nocase=ci,
                              count=self._cvar)
            if not idx:
                idx = text.search(needle, "1.0", stopindex=start, nocase=ci,
                                  count=self._cvar)
            if not idx:
                messagebox.showinfo(
                    parent=self.root,
                    title="Replace",
                    message=f'No more matches for "{needle}".')
                return "break"
            start = idx
            end = text.index(f"{start}+{int(self._cvar.get())}c")

        if text.get(start, end) == repl:
            messagebox.showinfo(
                parent=self.root,
                title="Replace",
                message=f'The match for "{needle}" is already "{repl}".')
            return "break"

        text.edit_separator()
        text.replace(start, end, repl)
        text.edit_separator()
        # _after_mutation refreshes the highlights; the insert mark has been
        # pushed to the end of the replacement, so find_next resumes after it.
        self._after_mutation(tab)
        self.find_next()
        return "break"

    def replace_all(self):
        if not self._find_bar.winfo_manager():
            self.show_replace()
            return "break"
        tab = self._current()
        if tab is None:
            return "break"
        params = self._replace_params()
        if params is None:
            messagebox.showinfo(
                parent=self.root,
                title="Replace",
                message="Type something to find first.")
            return "break"
        needle, repl, ci = params
        text = tab.text
        first, last = self._line_scope(tab)
        targets = self._replace_targets(text, needle, ci, first, last)
        if not targets:
            messagebox.showinfo(
                parent=self.root,
                title="Replace",
                message=f'No matches for "{needle}".')
            return "break"

        # Back to front: every later edit leaves the ranges ahead of it valid.
        changes = 0
        text.edit_separator()
        for start, end in reversed(targets):
            if text.get(start, end) == repl:
                continue
            text.replace(start, end, repl)
            changes += 1
        text.edit_separator()
        if not changes:
            messagebox.showinfo(
                parent=self.root,
                title="Replace",
                message=f'All {len(targets)} matches are already "{repl}".')
            return "break"
        self._after_mutation(tab)
        messagebox.showinfo(
            parent=self.root,
            title="Replace",
            message=f"Replaced {changes} of {len(targets)}.")
        return "break"

    # --- Text tools ---------------------------------------------------

    def _dialog_shell(self, title):
        win = tk.Toplevel(self.root)
        win.title(title)
        win.transient(self.root)
        win.resizable(False, False)
        body = ttk.Frame(win, padding=10)
        body.pack(fill="both", expand=True)
        return win, body

    def _track_scope(self, tab, refresh, win):
        """Keep a scope readout live while a dialog is open."""
        def handler(_event=None):
            try:
                refresh()
            except tk.TclError:
                pass

        tab.text.bind("<<Selection>>", handler, add="+")
        win.bind("<Destroy>",
                 lambda _e: tab.text.unbind("<<Selection>>"),
                 add="+")

    def _scope_label_text(self, tab):
        text = tab.text
        first, last = self._line_scope(tab)
        count = last - first + 1
        if first == 1 and last == self._visible_lines(text):
            where = "whole document"
        else:
            where = "selection"
        noun = "line" if count == 1 else "lines"
        return f"Applies to {count} {noun} ({where})."

    def _require_tab(self, tab):
        if tab is not None and tab is self._current():
            return tab
        messagebox.showinfo(
            parent=self.root,
            title="Text Tools",
            message="That tab is no longer active. Try again.")
        return None

    # -- Add prefix / suffix --

    def text_affix_dialog(self):
        tab = self._current()
        if tab is None:
            return
        win, body = self._dialog_shell("Add Prefix / Suffix to Each Line")
        value = tk.StringVar(value=getattr(self, "_affix_last", ""))
        where = tk.StringVar(value="prefix")
        keep_indent = tk.BooleanVar(value=True)
        indent_box = {}

        ttk.Label(body, text="Text to add:").grid(row=0, column=0,
                                                   sticky="w", pady=(0, 4))
        entry = ttk.Entry(body, textvariable=value, width=36)
        entry.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        entry.focus_set()

        def sync_indent_state(*_args):
            state = ["!disabled"] if where.get() == "prefix" else ["disabled"]
            indent_box["box"].configure(state=state)

        ttk.Radiobutton(body, text="Add at start of line (prefix)",
                        variable=where, value="prefix",
                        command=sync_indent_state).grid(
            row=2, column=0, columnspan=2, sticky="w")
        ttk.Radiobutton(body, text="Add at end of line (suffix)",
                        variable=where, value="suffix",
                        command=sync_indent_state).grid(
            row=3, column=0, columnspan=2, sticky="w")
        indent_box["box"] = ttk.Checkbutton(
            body, text="Keep existing indentation (prefix only)",
            variable=keep_indent)
        indent_box["box"].grid(row=4, column=0, columnspan=2, sticky="w",
                               padx=(14, 0))
        sync_indent_state()

        scope = ttk.Label(body, text=self._scope_label_text(tab))
        scope.grid(row=5, column=0, columnspan=2, sticky="w", pady=(10, 0))
        self._track_scope(tab, lambda: scope.config(
            text=self._scope_label_text(tab)), win)

        def apply():
            affix = value.get()
            if not affix:
                messagebox.showinfo(
                    parent=win,
                    title="Text Tools",
                    message="Enter the text to add first.")
                return
            target = self._require_tab(tab)
            if target is None:
                return
            self._affix_last = affix
            self._apply_affix(target, affix, where.get(), keep_indent.get())
            win.destroy()

        buttons = ttk.Frame(body)
        buttons.grid(row=6, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(buttons, text="Cancel", command=win.destroy).pack(
            side="right", padx=(6, 0))
        ttk.Button(buttons, text="Apply", command=apply).pack(side="right")
        entry.bind("<Return>", lambda e: apply())
        entry.bind("<Escape>", lambda e: win.destroy())
        return win

    def _apply_affix(self, tab, affix, where, keep_indent):
        first, last = self._line_scope(tab)
        changes = []
        total = 0
        for line_no, content in self._scope_lines(tab, first, last):
            total += 1
            if where == "prefix":
                if keep_indent:
                    body = content.lstrip()
                    indent = content[:len(content) - len(body)]
                    new_content = indent + affix + body
                else:
                    new_content = affix + content
            else:
                new_content = content + affix
            if new_content != content:
                changes.append((line_no, new_content))
        if changes:
            self._apply_line_edits(tab, changes)
        self._report(len(changes), total)

    # -- Extract substring --

    def text_substring_dialog(self):
        tab = self._current()
        if tab is None:
            return
        win, body = self._dialog_shell("Extract Substring from Each Line")
        start_var = tk.StringVar()
        end_var = tk.StringVar()

        ttk.Label(body, text="Positions are 1-based and inclusive.").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        ttk.Label(body, text="Start:").grid(row=1, column=0, sticky="w",
                                            padx=(0, 6))
        start_entry = ttk.Entry(body, textvariable=start_var, width=8)
        start_entry.grid(row=1, column=1, sticky="w")
        ttk.Label(body, text="End:").grid(row=2, column=0, sticky="w",
                                          padx=(0, 6), pady=(4, 0))
        end_entry = ttk.Entry(body, textvariable=end_var, width=8)
        end_entry.grid(row=2, column=1, sticky="w", pady=(4, 0))
        ttk.Label(body, text="Leave blank to use the start of the line or "
                             "the end of the line.").grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))

        scope = ttk.Label(body, text=self._scope_label_text(tab))
        scope.grid(row=4, column=0, columnspan=2, sticky="w", pady=(10, 0))
        self._track_scope(tab, lambda: scope.config(
            text=self._scope_label_text(tab)), win)

        def parse(var, name):
            raw = var.get().strip()
            if not raw:
                return None
            if not raw.isdigit():
                raise ValueError(f"{name} must be a whole number.")
            value = int(raw)
            if value < 1:
                raise ValueError(f"{name} must be 1 or greater.")
            return value

        def apply():
            try:
                start = parse(start_var, "Start")
                end = parse(end_var, "End")
            except ValueError as exc:
                messagebox.showerror(parent=win, message=str(exc))
                return
            if start is not None and end is not None and end < start:
                messagebox.showerror(
                    parent=win,
                    title="Text Tools",
                    message="End cannot be before start.")
                return
            target = self._require_tab(tab)
            if target is None:
                return
            self._apply_substring(target, start, end)
            win.destroy()

        buttons = ttk.Frame(body)
        buttons.grid(row=5, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(buttons, text="Cancel", command=win.destroy).pack(
            side="right", padx=(6, 0))
        ttk.Button(buttons, text="Apply", command=apply).pack(side="right")
        for w in (start_entry, end_entry):
            w.bind("<Return>", lambda e: apply())
            w.bind("<Escape>", lambda e: win.destroy())
        start_entry.focus_set()
        return win

    def _apply_substring(self, tab, start, end):
        first, last = self._line_scope(tab)
        begin = 0 if start is None else start - 1
        changes = []
        total = 0
        for line_no, content in self._scope_lines(tab, first, last):
            total += 1
            stop = len(content) if end is None else end
            if stop > len(content) or stop < begin:
                continue
            new_content = content[begin:stop]
            if new_content != content:
                changes.append((line_no, new_content))
        if changes:
            self._apply_line_edits(tab, changes)
        self._report(len(changes), total)

    # -- Trim --

    def text_trim(self):
        tab = self._current()
        if tab is None:
            return
        first, last = self._line_scope(tab)
        changes = []
        total = 0
        # Whitespace-only lines must be included: they are what trim fixes.
        for line_no, content in self._scope_lines(tab, first, last,
                                                  skip_blank=False):
            total += 1
            new_content = content.strip()
            if new_content != content:
                changes.append((line_no, new_content))
        if changes:
            self._apply_line_edits(tab, changes)
        self._report(len(changes), total)

    # -- Duplicate line --

    def text_duplicate_line(self):
        tab = self._current()
        if tab is None:
            return
        first, last = self._line_scope(tab)
        changes = []
        total = 0
        # Include blank lines too: duplicating "" still yields a valid "~"
        # result, so there is no reason to skip them here.
        for line_no, content in self._scope_lines(tab, first, last,
                                                  skip_blank=False):
            total += 1
            new_content = f"{content}~{content}"
            changes.append((line_no, new_content))
        if changes:
            self._apply_line_edits(tab, changes)
        self._report(len(changes), total)

    # -- Selection case conversion --

    def selection_upper(self):
        """UPPERCASE exactly the selected text (Alt+U)."""
        self._convert_selection_case(str.upper)
        return "break"

    def selection_lower(self):
        """lowercase exactly the selected text (Alt+L)."""
        self._convert_selection_case(str.lower)
        return "break"

    def _convert_selection_case(self, transform):
        """Rewrite the selection in the case produced by transform.

        Deliberately not line-scoped like the other Text Tools: only the
        characters the user actually selected are rewritten, so converting a
        fragment inside a line cannot silently recase the rest of that line.
        """
        tab = self._current()
        if tab is None:
            return
        text = tab.text
        rng = text.tag_ranges("sel")
        if len(rng) < 2 or str(rng[0]) == str(rng[1]):
            # Falling back to the whole document here would be a footgun on a
            # bare shortcut, so say what to do instead of guessing.
            self._flash_status(
                "Select the text to convert first, then use the shortcut again.")
            return
        start, end = str(rng[0]), str(rng[1])
        selected = text.get(start, end)
        converted = transform(selected)
        if converted == selected:
            self._flash_status("Selection is already in that case.")
            return
        text.edit_separator()
        text.replace(start, end, converted)
        text.edit_separator()
        # Re-select the result so the two commands can be chained. The end
        # index is recomputed from the inserted length rather than reused:
        # upper() can change the character count (e.g. "ß" becomes "SS").
        new_end = text.index(f"{start}+{len(converted)}c")
        text.tag_remove("sel", "1.0", "end")
        text.tag_add("sel", start, new_end)
        text.mark_set("insert", new_end)
        text.see("insert")
        text.focus_set()
        self._after_mutation(tab)

    # -- Insert string at position --

    def text_insert_at_position_dialog(self):
        tab = self._current()
        if tab is None:
            return
        win, body = self._dialog_shell("Insert String at Position")
        text_var = tk.StringVar(value=getattr(self, "_insert_at_pos_text_last", ""))
        pos_var = tk.StringVar(value=getattr(self, "_insert_at_pos_pos_last", ""))

        ttk.Label(body, text="Text to insert:").grid(
            row=0, column=0, sticky="w", pady=(0, 4))
        text_entry = ttk.Entry(body, textvariable=text_var, width=30)
        text_entry.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        text_entry.focus_set()

        ttk.Label(body, text="Position (1-based):").grid(
            row=2, column=0, sticky="w", padx=(0, 6))
        pos_entry = ttk.Entry(body, textvariable=pos_var, width=8)
        pos_entry.grid(row=2, column=1, sticky="w")
        ttk.Label(body, text="Lines shorter than this position are left "
                             "unchanged (skipped).").grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))

        scope = ttk.Label(body, text=self._scope_label_text(tab))
        scope.grid(row=4, column=0, columnspan=2, sticky="w", pady=(10, 0))
        self._track_scope(tab, lambda: scope.config(
            text=self._scope_label_text(tab)), win)

        def apply():
            insert_text = text_var.get()
            if not insert_text:
                messagebox.showinfo(
                    parent=win,
                    title="Text Tools",
                    message="Enter the text to insert first.")
                return
            raw_pos = pos_var.get().strip()
            if not raw_pos.isdigit() or int(raw_pos) < 1:
                messagebox.showerror(
                    parent=win,
                    title="Text Tools",
                    message="Position must be a whole number 1 or greater.")
                return
            position = int(raw_pos)
            target = self._require_tab(tab)
            if target is None:
                return
            self._insert_at_pos_text_last = insert_text
            self._insert_at_pos_pos_last = raw_pos
            self._apply_insert_at_position(target, insert_text, position)
            win.destroy()

        buttons = ttk.Frame(body)
        buttons.grid(row=5, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(buttons, text="Cancel", command=win.destroy).pack(
            side="right", padx=(6, 0))
        ttk.Button(buttons, text="Apply", command=apply).pack(side="right")
        for w in (text_entry, pos_entry):
            w.bind("<Return>", lambda e: apply())
            w.bind("<Escape>", lambda e: win.destroy())
        return win

    def _apply_insert_at_position(self, tab, insert_text, position):
        first, last = self._line_scope(tab)
        changes = []
        total = 0
        index = position - 1
        for line_no, content in self._scope_lines(tab, first, last,
                                                  skip_blank=False):
            total += 1
            if index >= len(content):
                continue
            new_content = content[:index] + insert_text + content[index:]
            changes.append((line_no, new_content))
        if changes:
            self._apply_line_edits(tab, changes)
        self._report(len(changes), total)

    # -- Remove lines containing string --

    def text_remove_lines_dialog(self):
        tab = self._current()
        if tab is None:
            return
        win, body = self._dialog_shell("Remove Lines Containing String")
        needle_var = tk.StringVar(value=getattr(self, "_remove_lines_needle_last", ""))
        case_var = tk.BooleanVar(value=getattr(self, "_remove_lines_case_last", False))

        ttk.Label(body, text="Remove lines containing:").grid(
            row=0, column=0, sticky="w", pady=(0, 4))
        entry = ttk.Entry(body, textvariable=needle_var, width=30)
        entry.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        entry.focus_set()

        ttk.Checkbutton(body, text="Match case", variable=case_var).grid(
            row=2, column=0, columnspan=2, sticky="w")

        scope = ttk.Label(body, text=self._scope_label_text(tab))
        scope.grid(row=3, column=0, columnspan=2, sticky="w", pady=(10, 0))
        self._track_scope(tab, lambda: scope.config(
            text=self._scope_label_text(tab)), win)

        def apply():
            needle = needle_var.get()
            if not needle:
                messagebox.showinfo(
                    parent=win,
                    title="Text Tools",
                    message="Enter the text to search for first.")
                return
            target = self._require_tab(tab)
            if target is None:
                return
            self._remove_lines_needle_last = needle
            self._remove_lines_case_last = case_var.get()
            self._apply_remove_lines(target, needle, case_var.get())
            win.destroy()

        buttons = ttk.Frame(body)
        buttons.grid(row=4, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(buttons, text="Cancel", command=win.destroy).pack(
            side="right", padx=(6, 0))
        ttk.Button(buttons, text="Apply", command=apply).pack(side="right")
        entry.bind("<Return>", lambda e: apply())
        entry.bind("<Escape>", lambda e: win.destroy())
        return win

    def _apply_remove_lines(self, tab, needle, match_case):
        """Delete whole lines containing `needle`, as a single undo step.

        Removing lines changes the line count, so (unlike the other line
        tools) this can't reuse _apply_line_edits - the buffer is rebuilt
        as one string and swapped in with a single text.replace(), the same
        technique _keep_lines uses.
        """
        text = tab.text
        total_lines = self._visible_lines(text)
        first, last = self._line_scope(tab)
        needle_cmp = needle if match_case else needle.lower()

        kept_lines = []
        total = 0
        removed = 0
        for n in range(1, total_lines + 1):
            content = text.get(f"{n}.0", f"{n}.end")
            if first <= n <= last:
                total += 1
                content_cmp = content if match_case else content.lower()
                if needle_cmp in content_cmp:
                    removed += 1
                    continue
            kept_lines.append(content)

        new_text = "\n".join(kept_lines)
        if new_text and text.get("1.0", "end-1c").endswith("\n"):
            new_text += "\n"
        if new_text != text.get("1.0", "end-1c"):
            text.edit_separator()
            text.replace("1.0", "end", new_text)
            text.edit_separator()
            text.tag_remove("sel", "1.0", "end")
            text.mark_set("insert", "1.0")
            self._after_mutation(tab)
        self._report(removed, total, verb="Removed")

    # -- Keep selection / keep line range --

    def keep_selection(self):
        tab = self._current()
        if tab is None:
            return
        if len(tab.text.tag_ranges("sel")) < 2:
            messagebox.showinfo(
                parent=self.root,
                title="Text Tools",
                message="Select the part you want to keep first.")
            return
        total = self._visible_lines(tab.text)
        first, last = self._line_scope(tab)
        kept = self._keep_lines(tab, first, last, total)
        self._report(total - kept, total, verb="Deleted")

    def text_keep_lines_dialog(self):
        tab = self._current()
        if tab is None:
            return
        win, body = self._dialog_shell("Keep Lines From x To y")
        total = self._visible_lines(tab.text)
        start_var = tk.StringVar()
        end_var = tk.StringVar()

        ttk.Label(body, text=f"This document has {total} "
                             f"line{'s' if total != 1 else ''}. "
                             "Everything outside the range is deleted.").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        ttk.Label(body, text="From line:").grid(row=1, column=0, sticky="w",
                                                padx=(0, 6))
        start_entry = ttk.Entry(body, textvariable=start_var, width=8)
        start_entry.grid(row=1, column=1, sticky="w")
        ttk.Label(body, text="To line:").grid(row=2, column=0, sticky="w",
                                              padx=(0, 6), pady=(4, 0))
        end_entry = ttk.Entry(body, textvariable=end_var, width=8)
        end_entry.grid(row=2, column=1, sticky="w", pady=(4, 0))

        def parse(var, label):
            raw = var.get().strip()
            if not raw:
                raise ValueError(f"Enter a {label} line number.")
            if not raw.isdigit():
                raise ValueError(f"{label} must be a whole number.")
            value = int(raw)
            if value < 1:
                raise ValueError(f"{label} must be 1 or greater.")
            return value

        def apply():
            try:
                first = parse(start_var, "From")
                last = parse(end_var, "To")
            except ValueError as exc:
                messagebox.showerror(parent=win, message=str(exc))
                return
            if last < first:
                messagebox.showerror(
                    parent=win,
                    title="Text Tools",
                    message="The 'To' line cannot come before the "
                    "'From' line.")
                return
            target = self._require_tab(tab)
            if target is None:
                return
            current = self._visible_lines(target.text)
            if last > current:
                messagebox.showerror(
                    parent=win,
                    title="Text Tools",
                    message=f"This document has only {current} lines, so line {last} "
                    f"is out of range. Nothing was changed.")
                return
            kept = self._keep_lines(target, first, last, current)
            self._report(current - kept, current, verb="Deleted")
            win.destroy()

        buttons = ttk.Frame(body)
        buttons.grid(row=3, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="Cancel", command=win.destroy).pack(
            side="right", padx=(6, 0))
        ttk.Button(buttons, text="Apply", command=apply).pack(side="right")
        for w in (start_entry, end_entry):
            w.bind("<Return>", lambda e: apply())
            w.bind("<Escape>", lambda e: win.destroy())
        start_entry.focus_set()
        return win

    def _on_tab_changed(self, event=None):
        self.refresh_title()
        self.update_status()
        if self._find_bar.winfo_manager():
            tab = self._current()
            if tab:
                self._apply_find_tags(tab)


def main():
    try:
        # className is Tk's only lever on the window class (WM_CLASS), which
        # is what StartupWMClass in unote.desktop is matched against; without
        # it Tk registers every app as the generic "tk". Note this cannot help
        # on GNOME/Wayland, where XWayland reparents clients into a Mutter
        # frame and overwrites WM_CLASS with "mutter-x11-frames".
        root = tk.Tk(className="unote")
    except tk.TclError as exc:
        # Double-clicking the .desktop file on a Wayland session without
        # XWayland lands here; a bare traceback tells the user nothing.
        raise SystemExit(
            "UNote needs a graphical display.\n"
            f"Could not open a window: {exc}\n"
            "Is DISPLAY/WAYLAND_DISPLAY set, and is XWayland running?"
        )
    app = UNoteApp(root, files=sys.argv[1:])
    if not app.tabs:
        app.new_tab()
    root.mainloop()


if __name__ == "__main__":
    main()
