"""Tkinter front end: pick a map, a mod and a loadout, press Play.

The window stays open while the game runs (minimised) and comes back when the
game process exits, like a League of Legends-style client.
"""

from __future__ import annotations

import re
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __version__, discovery, launch, settings as settings_mod
from .catalog import GOBBLEGUMS, PERKS, WEAPONS
from .gamefiles import restore_videos

BG, PANEL, FG, MUTED, ACCENT = "#15171c", "#1e2128", "#e8e6e3", "#8b909a", "#c8102e"
NO_MOD = "(no gameplay mod)"


def _labelled(name: str, internal: str) -> str:
    return f"{name} ({internal})"


def _internal(text: str) -> str:
    """'KN-44 (ar_standard)' -> 'ar_standard'; anything else is returned stripped."""
    m = re.search(r"\(([^()]+)\)\s*$", text)
    return (m.group(1) if m else text).strip()


class App:
    def __init__(self, root: tk.Tk, settings: settings_mod.Settings):
        self.root = root
        self.s = settings
        self.maps: list[discovery.ContentItem] = []
        self.mods: list[discovery.ContentItem] = []
        self.by_iid: dict[str, discovery.ContentItem] = {}
        self.preview_img: tk.PhotoImage | None = None
        self.running = False

        root.title(f"NZW {__version__} - Black Ops III Zombies")
        root.geometry("1040x660")
        root.minsize(860, 540)
        root.configure(bg=BG)
        self._style()
        self._build()
        self._load_settings_into_widgets()
        self.refresh()
        if self.s.game_root:
            restore_videos(Path(self.s.game_root))  # recover from a crashed session
        root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ------------------------------------------------------------------ UI
    def _style(self) -> None:
        st = ttk.Style(self.root)
        st.theme_use("clam")
        st.configure(".", background=BG, foreground=FG, fieldbackground=PANEL, bordercolor=PANEL)
        st.configure("TFrame", background=BG)
        st.configure("Panel.TFrame", background=PANEL)
        st.configure("TLabel", background=BG, foreground=FG)
        st.configure("Muted.TLabel", foreground=MUTED)
        st.configure("Title.TLabel", font=("Segoe UI", 18, "bold"))
        st.configure("TCheckbutton", background=BG, foreground=FG)
        st.configure("TRadiobutton", background=BG, foreground=FG)
        st.configure("TNotebook", background=BG, borderwidth=0)
        st.configure("TNotebook.Tab", background=PANEL, foreground=MUTED, padding=(14, 6))
        st.map("TNotebook.Tab", background=[("selected", BG)], foreground=[("selected", FG)])
        st.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=FG, rowheight=24)
        st.map("Treeview", background=[("selected", ACCENT)])
        st.configure("Treeview.Heading", background=BG, foreground=MUTED)
        st.configure("Play.TButton", background=ACCENT, foreground="white",
                     font=("Segoe UI", 13, "bold"), padding=(28, 10))
        st.map("Play.TButton", background=[("disabled", "#5a1520"), ("active", "#e01a3a")])
        for w in ("TCombobox", "TEntry", "TSpinbox"):
            st.configure(w, foreground=FG, fieldbackground=PANEL, background=PANEL, arrowcolor=FG)
            st.map(w, fieldbackground=[("readonly", PANEL)], foreground=[("readonly", FG)],
                   selectbackground=[("readonly", PANEL)], selectforeground=[("readonly", FG)])
        self.root.option_add("*TCombobox*Listbox.background", PANEL)
        self.root.option_add("*TCombobox*Listbox.foreground", FG)

    def _build(self) -> None:
        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(0, weight=1)

        # Map browser
        left = ttk.Frame(outer)
        left.grid(row=0, column=0, sticky="ns", padx=(0, 10))
        left.rowconfigure(1, weight=1)
        self.search = tk.StringVar()
        self.search.trace_add("write", lambda *_: self._fill_tree())
        ttk.Entry(left, textvariable=self.search, width=36).grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self.tree = ttk.Treeview(left, columns=("src",), show="tree headings", selectmode="browse", height=20)
        self.tree.heading("#0", text="Map")
        self.tree.heading("src", text="Source")
        self.tree.column("#0", width=240)
        self.tree.column("src", width=96, anchor="center")
        self.tree.grid(row=1, column=0, sticky="ns")
        sb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        sb.grid(row=1, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<<TreeviewSelect>>", lambda _: self._on_select())
        self.tree.bind("<Double-1>", lambda _: self.play())
        ttk.Button(left, text="Rescan", command=self.refresh).grid(row=2, column=0, sticky="ew", pady=(6, 0))

        # Tabs
        nb = ttk.Notebook(outer)
        nb.grid(row=0, column=1, sticky="nsew")
        nb.add(self._play_tab(nb), text="Play")
        nb.add(self._loadout_tab(nb), text="Loadout")
        nb.add(self._options_tab(nb), text="Options")

        # Bottom bar
        bar = ttk.Frame(outer)
        bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        bar.columnconfigure(0, weight=1)
        self.status = tk.StringVar(value="Ready")
        ttk.Label(bar, textvariable=self.status, style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        self.cmd_preview = tk.StringVar()
        ttk.Entry(bar, textvariable=self.cmd_preview, state="readonly").grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self.play_btn = ttk.Button(bar, text="PLAY", style="Play.TButton", command=self.play)
        self.play_btn.grid(row=0, column=1, rowspan=2, padx=(12, 0))

    def _play_tab(self, parent) -> ttk.Frame:
        f = ttk.Frame(parent, padding=16)
        f.columnconfigure(0, weight=1)
        self.map_title = tk.StringVar(value="Select a map")
        ttk.Label(f, textvariable=self.map_title, style="Title.TLabel").grid(row=0, column=0, sticky="w")
        self.map_info = tk.StringVar()
        ttk.Label(f, textvariable=self.map_info, style="Muted.TLabel", wraplength=560, justify="left").grid(
            row=1, column=0, sticky="w", pady=(4, 12))
        self.preview = ttk.Label(f)
        self.preview.grid(row=2, column=0, sticky="w")
        ttk.Label(f, text="Gameplay mod").grid(row=3, column=0, sticky="w", pady=(16, 4))
        self.mod_var = tk.StringVar(value=NO_MOD)
        self.mod_box = ttk.Combobox(f, textvariable=self.mod_var, state="readonly", width=60)
        self.mod_box.grid(row=4, column=0, sticky="w")
        self.mod_box.bind("<<ComboboxSelected>>", lambda _: self._update_preview_cmd())
        self.notes = tk.StringVar()
        ttk.Label(f, textvariable=self.notes, foreground="#e0a040", wraplength=560).grid(
            row=5, column=0, sticky="w", pady=(10, 0))
        return f

    def _loadout_tab(self, parent) -> ttk.Frame:
        f = ttk.Frame(parent, padding=16)
        weapons = [""] + [_labelled(n, i) for i, n in WEAPONS]
        gums = [""] + GOBBLEGUMS

        ttk.Label(f, text="Starting weapon").grid(row=0, column=0, sticky="w")
        self.weapon = tk.StringVar()
        ttk.Combobox(f, textvariable=self.weapon, values=weapons, width=34).grid(row=0, column=1, sticky="w")
        self.upgraded = tk.BooleanVar()
        ttk.Checkbutton(f, text="Pack-a-Punched", variable=self.upgraded).grid(row=0, column=2, sticky="w", padx=8)

        ttk.Label(f, text="Bonus points").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.points = tk.IntVar()
        ttk.Spinbox(f, from_=0, to=1_000_000, increment=500, textvariable=self.points, width=12).grid(
            row=1, column=1, sticky="w", pady=(8, 0))

        ttk.Label(f, text="Perks").grid(row=2, column=0, sticky="nw", pady=(12, 0))
        perk_frame = ttk.Frame(f)
        perk_frame.grid(row=2, column=1, columnspan=2, sticky="w", pady=(12, 0))
        self.perk_vars: dict[str, tk.BooleanVar] = {}
        for idx, (internal, name) in enumerate(PERKS):
            v = tk.BooleanVar()
            self.perk_vars[internal] = v
            ttk.Checkbutton(perk_frame, text=name, variable=v).grid(row=idx // 3, column=idx % 3, sticky="w", padx=(0, 16))

        ttk.Label(f, text="GobbleGum pack").grid(row=3, column=0, sticky="nw", pady=(12, 0))
        gum_frame = ttk.Frame(f)
        gum_frame.grid(row=3, column=1, columnspan=2, sticky="w", pady=(12, 0))
        self.gum_vars = [tk.StringVar() for _ in range(5)]
        for idx, v in enumerate(self.gum_vars):
            ttk.Combobox(gum_frame, textvariable=v, values=gums, width=34).grid(row=idx, column=0, sticky="w", pady=1)

        ttk.Label(f, text="Activate on spawn").grid(row=4, column=0, sticky="w", pady=(12, 0))
        self.gum_start = tk.StringVar()
        ttk.Combobox(f, textvariable=self.gum_start, values=gums, width=34).grid(row=4, column=1, sticky="w", pady=(12, 0))

        ttk.Label(f, text="Loadouts are applied by the bundled GSC script and need the boiii client. "
                          "Perks/gums the map doesn't have are skipped.",
                  style="Muted.TLabel", wraplength=560).grid(row=5, column=0, columnspan=3, sticky="w", pady=(16, 0))
        return f

    def _options_tab(self, parent) -> ttk.Frame:
        f = ttk.Frame(parent, padding=16)
        f.columnconfigure(1, weight=1)
        r = 0
        ttk.Label(f, text="Game folder").grid(row=r, column=0, sticky="w")
        self.game_root = tk.StringVar()
        ttk.Entry(f, textvariable=self.game_root).grid(row=r, column=1, sticky="ew", padx=6)
        ttk.Button(f, text="Browse", command=self._browse).grid(row=r, column=2)
        r += 1
        ttk.Label(f, text="Client").grid(row=r, column=0, sticky="w", pady=(8, 0))
        cf = ttk.Frame(f)
        cf.grid(row=r, column=1, sticky="w", pady=(8, 0))
        self.client = tk.StringVar()
        ttk.Radiobutton(cf, text="boiii.exe", value="boiii", variable=self.client,
                        command=self._update_preview_cmd).pack(side="left")
        ttk.Radiobutton(cf, text="BlackOps3.exe (Steam)", value="vanilla", variable=self.client,
                        command=self._update_preview_cmd).pack(side="left", padx=12)
        r += 1
        ttk.Label(f, text="Display").grid(row=r, column=0, sticky="w", pady=(8, 0))
        df = ttk.Frame(f)
        df.grid(row=r, column=1, sticky="w", pady=(8, 0))
        self.display = tk.StringVar()
        for val in ("fullscreen", "borderless", "windowed"):
            ttk.Radiobutton(df, text=val.title(), value=val, variable=self.display,
                            command=self._update_preview_cmd).pack(side="left", padx=(0, 12))
        r += 1
        self.flags = {name: tk.BooleanVar() for name in (
            "skip_intro", "skip_cinematics", "unsafe_lua", "uncap_menu_fps", "unlock_gobblegums",
            "unlock_attachments", "unlock_camos", "write_binds", "hide_videos_vanilla")}
        labels = {
            "skip_intro": "Skip intro logo",
            "skip_cinematics": "Skip all cinematics",
            "unsafe_lua": "Allow unsafe Lua (overhaul mods)",
            "uncap_menu_fps": "Uncap MaxFPS (faster loads)",
            "unlock_gobblegums": "Unlock all GobbleGums",
            "unlock_attachments": "Unlock all attachments",
            "unlock_camos": "Unlock all camos and reticles",
            "write_binds": "Write utility key binds",
            "hide_videos_vanilla": "Vanilla: hide intro/forest videos",
        }
        ff = ttk.Frame(f)
        ff.grid(row=r, column=0, columnspan=3, sticky="w", pady=(10, 0))
        for idx, (name, var) in enumerate(self.flags.items()):
            ttk.Checkbutton(ff, text=labels[name], variable=var, command=self._update_preview_cmd).grid(
                row=idx // 2, column=idx % 2, sticky="w", padx=(0, 24), pady=1)
        r += 1
        ttk.Label(f, text="Map command").grid(row=r, column=0, sticky="w", pady=(10, 0))
        self.map_command = tk.StringVar()
        ttk.Combobox(f, textvariable=self.map_command, values=["devmap", "map"], state="readonly", width=10).grid(
            row=r, column=1, sticky="w", pady=(10, 0), padx=6)
        r += 1
        ttk.Label(f, text="Extra arguments").grid(row=r, column=0, sticky="w", pady=(8, 0))
        self.extra_args = tk.StringVar()
        ttk.Entry(f, textvariable=self.extra_args).grid(row=r, column=1, columnspan=2, sticky="ew", padx=6, pady=(8, 0))
        r += 1
        ttk.Label(f, text="Key binds\n(KEY = command)").grid(row=r, column=0, sticky="nw", pady=(8, 0))
        self.binds_text = tk.Text(f, height=5, bg=PANEL, fg=FG, insertbackground=FG, relief="flat")
        self.binds_text.grid(row=r, column=1, columnspan=2, sticky="ew", padx=6, pady=(8, 0))
        return f

    # ------------------------------------------------------------ settings
    def _load_settings_into_widgets(self) -> None:
        s = self.s
        self.game_root.set(s.game_root)
        self.client.set(s.client)
        self.display.set(s.display)
        for name, var in self.flags.items():
            var.set(bool(getattr(s, name)))
        self.map_command.set(s.map_command)
        self.extra_args.set(s.extra_args)
        self.binds_text.insert("1.0", "\n".join(f"{k} = {v}" for k, v in s.binds.items()))
        lo = s.loadout
        names = {i: n for i, n in WEAPONS}
        self.weapon.set(_labelled(names[lo.weapon], lo.weapon) if lo.weapon in names else lo.weapon)
        self.upgraded.set(lo.weapon_upgraded)
        self.points.set(lo.points)
        for perk, var in self.perk_vars.items():
            var.set(perk in lo.perks)
        for idx, var in enumerate(self.gum_vars):
            var.set(lo.bgb_pack[idx] if idx < len(lo.bgb_pack) else "")
        self.gum_start.set(lo.bgb_start)

    def _collect_settings(self) -> None:
        s = self.s
        s.game_root = self.game_root.get().strip()
        s.client = self.client.get()
        s.display = self.display.get()
        for name, var in self.flags.items():
            setattr(s, name, var.get())
        s.map_command = self.map_command.get() or "devmap"
        s.extra_args = self.extra_args.get()
        binds = {}
        for line in self.binds_text.get("1.0", "end").splitlines():
            if "=" in line:
                key, cmd = line.split("=", 1)
                if key.strip() and cmd.strip():
                    binds[key.strip()] = cmd.strip()
        s.binds = binds
        lo = s.loadout
        lo.weapon = _internal(self.weapon.get())
        lo.weapon_upgraded = self.upgraded.get()
        try:
            lo.points = max(0, int(self.points.get()))
        except (tk.TclError, ValueError):
            lo.points = 0
        lo.perks = [p for p, v in self.perk_vars.items() if v.get()]
        lo.bgb_pack = [g.get().strip() for g in self.gum_vars if g.get().strip()]
        lo.bgb_start = self.gum_start.get().strip()
        item = self._selected_map()
        if item:
            s.last_map = item.key
        mod = self._selected_mod()
        s.last_mod = mod.key if mod else ""

    def _browse(self) -> None:
        path = filedialog.askdirectory(title="Black Ops III folder", initialdir=self.game_root.get() or None)
        if path:
            self.game_root.set(path)
            self.refresh()

    # -------------------------------------------------------------- content
    def refresh(self) -> None:
        root = self.game_root.get().strip()
        if not root:
            found = discovery.find_game_root()
            if found:
                self.game_root.set(str(found))
                root = str(found)
        self.maps, self.mods = discovery.scan_all(Path(root) if root else None)
        self.mod_box["values"] = [NO_MOD] + [f"{m.title}  [{m.ugc_name}]" for m in self.mods]
        self.mod_var.set(NO_MOD)
        for idx, m in enumerate(self.mods):
            if m.key == self.s.last_mod:
                self.mod_box.current(idx + 1)
        self._fill_tree()
        custom = sum(1 for m in self.maps if not m.is_official)
        self.status.set(f"{len(self.maps) - custom} official maps, {custom} custom maps, {len(self.mods)} mod{'' if len(self.mods) == 1 else 's'}"
                        + ("" if root else " - set the game folder in Options"))

    def _fill_tree(self) -> None:
        query = self.search.get().lower().strip()
        self.tree.delete(*self.tree.get_children())
        self.by_iid.clear()
        official = self.tree.insert("", "end", text="Official maps", open=True)
        custom = self.tree.insert("", "end", text="Custom maps", open=True)
        select = None
        for item in self.maps:
            if query and query not in item.title.lower() and query not in item.folder_name.lower():
                continue
            parent = official if item.is_official else custom
            iid = self.tree.insert(parent, "end", text=item.title, values=(item.group or item.source,))
            self.by_iid[iid] = item
            if item.key == self.s.last_map:
                select = iid
        if select:
            self.tree.selection_set(select)
            self.tree.see(select)

    def _selected_map(self) -> discovery.ContentItem | None:
        sel = self.tree.selection()
        return self.by_iid.get(sel[0]) if sel else None

    def _selected_mod(self) -> discovery.ContentItem | None:
        idx = self.mod_box.current()
        return self.mods[idx - 1] if idx > 0 else None

    def _on_select(self) -> None:
        item = self._selected_map()
        if item is None:
            return
        self.map_title.set(item.title)
        info = [f"Internal name: {item.folder_name}", f"Source: {item.source}"]
        if item.publisher_id:
            info.append(f"Workshop ID: {item.publisher_id}")
        if item.description:
            desc = re.sub(r"\[/?[^\]]+\]", "", item.description).strip()
            info.append(desc[:400] + ("..." if len(desc) > 400 else ""))
        self.map_info.set("\n".join(info))
        self.preview_img = None
        if item.preview and item.preview.suffix.lower() in (".png", ".gif"):
            try:
                img = tk.PhotoImage(file=str(item.preview))
                factor = max(1, img.width() // 360 + (img.width() % 360 > 0))
                self.preview_img = img.subsample(factor, factor) if factor > 1 else img
            except tk.TclError:
                pass
        self.preview.configure(image=self.preview_img or "")
        self._update_preview_cmd()

    def _update_preview_cmd(self) -> None:
        item = self._selected_map()
        if item is None:
            return
        self._collect_settings()
        try:
            plan = launch.build_plan(self.s, item, self._selected_mod())
        except launch.LaunchError as e:
            self.cmd_preview.set("")
            self.notes.set(str(e))
            return
        self.cmd_preview.set(plan.command_line)
        self.notes.set("\n".join(plan.notes))

    # ----------------------------------------------------------------- play
    def play(self) -> None:
        if self.running:
            return
        item = self._selected_map()
        if item is None or item.kind != "map":
            messagebox.showinfo("NZW", "Pick a map first.")
            return
        self._collect_settings()
        settings_mod.save(self.s)
        try:
            plan = launch.build_plan(self.s, item, self._selected_mod())
            log = launch.prepare(plan, self.s)
            proc = launch.start(plan)
        except (launch.LaunchError, OSError) as e:
            messagebox.showerror("NZW", f"Could not launch:\n{e}")
            return
        self.running = True
        self.play_btn.state(["disabled"])
        self.status.set(f"Playing {item.title}" + (f" ({len(log)} file changes)" if log else ""))
        self.root.iconify()

        def wait() -> None:
            code = proc.wait()
            self.root.after(0, lambda: self._on_exit(plan, code))

        threading.Thread(target=wait, daemon=True).start()

    def _on_exit(self, plan: launch.LaunchPlan, code: int) -> None:
        launch.finish(plan)
        self.running = False
        self.play_btn.state(["!disabled"])
        self.status.set(f"Game closed (exit code {code}). Ready")
        self.root.deiconify()
        self.root.lift()

    def on_close(self) -> None:
        self._collect_settings()
        try:
            settings_mod.save(self.s)
        except OSError:
            pass
        self.root.destroy()


def run(settings: settings_mod.Settings) -> int:
    root = tk.Tk()
    App(root, settings)
    root.mainloop()
    return 0
