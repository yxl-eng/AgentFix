from __future__ import annotations

import json
import subprocess
import sys
import threading
import ctypes
from collections import deque
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox
import tkinter as tk
from tkinter import ttk

import yaml
import os

try:
    import pystray
except ImportError:  # 托盘能力是可选功能，缺失时不影响 GUI 启动。
    pystray = None

try:
    from PIL import Image, ImageDraw
except ImportError:  # Pillow 只用于生成托盘图标。
    Image = None
    ImageDraw = None

try:
    from win10toast import ToastNotifier
except Exception:  # win10toast 依赖 pkg_resources，缺失时禁用桌面通知。
    ToastNotifier = None

SRC_DIR = Path(__file__).resolve().parent / "src"
if SRC_DIR.exists() and str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from patchpilot.event_state import EventStateStore
from patchpilot.localization import disposition_label, public_status, risk_label, root_cause_label, status_label


APP_TITLE = "PatchPilot"
BASE_CONFIG = Path("patchpilot.yaml")
LOCAL_CONFIG = Path("patchpilot.local.yaml")
LEGACY_BASE_CONFIG = Path("agentfix.yaml")
LEGACY_LOCAL_CONFIG = Path("agentfix.local.yaml")


def enable_windows_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return data if isinstance(data, dict) else {}


def deep_merge(base: dict, override: dict) -> dict:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def get_nested(data: dict, path: tuple[str, ...], default=""):
    cursor = data
    for key in path:
        if not isinstance(cursor, dict) or key not in cursor:
            return default
        cursor = cursor[key]
    return cursor


def set_nested(data: dict, path: tuple[str, ...], value) -> None:
    cursor = data
    for key in path[:-1]:
        cursor = cursor.setdefault(key, {})
    cursor[path[-1]] = value


class ScrollFrame(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.canvas = tk.Canvas(self, highlightthickness=0, background="#f7f8fb")
        self.scrollbar = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self.canvas.yview)
        self.body = ttk.Frame(self.canvas)
        self.window = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.bind("<Configure>", self._resize_window)
        self.body.bind("<Configure>", lambda _event: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel, add="+")
        self.canvas.bind_all("<Button-4>", self._on_mousewheel, add="+")
        self.canvas.bind_all("<Button-5>", self._on_mousewheel, add="+")
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def _resize_window(self, event) -> None:
        self.canvas.itemconfigure(self.window, width=event.width)

    def reset_scroll(self) -> None:
        self.canvas.update_idletasks()
        self.canvas.coords(self.window, 0, 0)
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.canvas.yview_moveto(0)

    def _on_mousewheel(self, event) -> None:
        widget = self.winfo_containing(event.x_root, event.y_root)
        if not self._contains(widget):
            return
        if getattr(event, "num", None) == 4:
            delta = -1
        elif getattr(event, "num", None) == 5:
            delta = 1
        else:
            delta = -1 if event.delta > 0 else 1
        self.canvas.yview_scroll(delta, "units")

    def _contains(self, widget) -> bool:
        while widget is not None:
            if widget == self:
                return True
            widget = widget.master
        return False


class PatchPilotGUI(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1440x900")
        self.minsize(1280, 800)
        self.configure(bg="#f7f8fb")

        self.base_config: dict = {}
        self.local_config: dict = {}
        self.config_data: dict = {}
        self.records: list[dict] = []
        self.current_record: dict | None = None
        self.current_target_name = tk.StringVar()

        self.form_vars: dict[tuple[str, ...], object] = {}
        self.target_vars: dict[str, object] = {}
        self.secret_entries: dict[tuple[str, ...], ttk.Entry] = {}
        self.secret_buttons: dict[tuple[str, ...], ttk.Button] = {}
        self.check_refreshers: list[callable] = []
        self.segmented_defaults: dict[tuple[str, ...], str] = {}
        self.page_scrolls: dict[str, ScrollFrame] = {}

        # Background Service Variables
        self.background_service_enabled = tk.BooleanVar(value=True)
        self.agent_process = None
        self._background_service_starting = False
        self._background_service_generation = 0

        # Tray and Toast setup
        self.toaster = ToastNotifier() if ToastNotifier is not None else None
        self.icon = None
        self.protocol('WM_DELETE_WINDOW', self.hide_window)

        self._configure_style()
        self.load_config()
        self._build_shell()
        self.show_page("dashboard")
        self.refresh_all()
        if self.background_service_enabled.get():
            self.start_background_service()

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        themes = set(style.theme_names())
        if "clam" in themes:
            style.theme_use("clam")

        self.option_add("*Font", "{Microsoft YaHei UI} 10")
        base_font = ("Microsoft YaHei UI", 10)
        text_font = ("Microsoft YaHei UI", 10)
        title_font = ("Microsoft YaHei UI", 30, "bold")
        card_title_font = ("Microsoft YaHei UI", 11, "bold")

        style.configure(".", font=base_font)
        style.configure("TFrame", background="#f7f8fb")
        style.configure("Card.TFrame", background="#ffffff", relief="flat")
        style.configure("Sidebar.TFrame", background="#ffffff")
        style.configure("Header.TFrame", background="#f3f6fb")
        style.configure("Title.TLabel", background="#f3f6fb", foreground="#1f2329", font=title_font)
        style.configure("HeaderSubtitle.TLabel", background="#f3f6fb", foreground="#646a73", font=("Microsoft YaHei UI", 10))
        style.configure("Subtitle.TLabel", background="#f7f8fb", foreground="#646a73", font=text_font)
        style.configure("FormLabel.TLabel", background="#f7f8fb", foreground="#4e5969", font=text_font)
        style.configure("CardTitle.TLabel", background="#ffffff", foreground="#1f2329", font=card_title_font)
        style.configure("Muted.TLabel", background="#ffffff", foreground="#646a73", font=text_font)
        style.configure("SidebarTitle.TLabel", background="#ffffff", foreground="#1f2329", font=("Microsoft YaHei UI", 16, "bold"))
        style.configure("SidebarSub.TLabel", background="#ffffff", foreground="#646a73", font=("Microsoft YaHei UI", 9))
        
        # Modern Button Styles
        style.configure("TButton", font=base_font, background="#ffffff", foreground="#1f2329", bordercolor="#d0d3d6", lightcolor="#ffffff", darkcolor="#ffffff", borderwidth=1, focuscolor="#ffffff", padding=(12, 7))
        style.map("TButton", background=[("active", "#f2f3f5"), ("pressed", "#e5e6eb")])
        
        style.configure("Primary.TButton", font=base_font, background="#3370ff", foreground="#ffffff", bordercolor="#3370ff", lightcolor="#3370ff", darkcolor="#3370ff", borderwidth=1, focuscolor="#3370ff", padding=(12, 7))
        style.map("Primary.TButton", background=[("active", "#1e5def"), ("pressed", "#1043c7")])

        style.configure("TEntry", padding=(8, 6), fieldbackground="#ffffff", bordercolor="#d9dee8", lightcolor="#ffffff", darkcolor="#ffffff")
        style.configure("TCombobox", padding=(8, 6), fieldbackground="#ffffff", background="#ffffff", bordercolor="#d9dee8", lightcolor="#ffffff", darkcolor="#ffffff", arrowsize=14)
        style.map("TCombobox", fieldbackground=[("readonly", "#ffffff")], selectbackground=[("readonly", "#ffffff")], selectforeground=[("readonly", "#1f2329")])

        style.configure("TNotebook", background="#ffffff", borderwidth=0)
        style.configure("TNotebook.Tab", font=("Microsoft YaHei UI", 9, "bold"), padding=(12, 8), background="#f7f8fb", foreground="#646a73")
        style.map("TNotebook.Tab", background=[("selected", "#ffffff"), ("active", "#edf3ff")], foreground=[("selected", "#3370ff"), ("active", "#3370ff")])

        style.configure("Treeview", font=text_font, rowheight=34, fieldbackground="#ffffff", background="#ffffff", foreground="#1f2329", borderwidth=0)
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 10, "bold"), background="#f7f9fc", foreground="#646a73")

    def _build_shell(self) -> None:
        self.sidebar = ttk.Frame(self, style="Sidebar.TFrame", width=230)
        self.sidebar.pack(side=tk.LEFT, fill=tk.Y)
        self.sidebar.pack_propagate(False)

        brand = ttk.Frame(self.sidebar, style="Sidebar.TFrame")
        brand.pack(fill=tk.X, padx=22, pady=(24, 18))
        ttk.Label(brand, text="PatchPilot", style="SidebarTitle.TLabel").pack(anchor=tk.W)
        ttk.Label(brand, text="环境感知自动修复平台", style="SidebarSub.TLabel").pack(anchor=tk.W, pady=(4, 0))

        self.nav_buttons: dict[str, tk.Button] = {}
        for key, label in [
            ("dashboard", "总览"),
            ("incidents", "事故记录"),
            ("config", "配置中心"),
            ("targets", "目标服务"),
            ("manual", "手动运行"),
        ]:
            button = tk.Button(
                self.sidebar,
                text=label,
                anchor="w",
                bd=0,
                padx=18,
                pady=10,
                bg="#ffffff",
                fg="#646a73",
                activebackground="#edf3ff",
                activeforeground="#3370ff",
                font=("Microsoft YaHei UI", 10),
                command=lambda page=key: self.show_page(page),
            )
            button.pack(fill=tk.X, padx=12, pady=3)
            self.nav_buttons[key] = button

        self.content = ttk.Frame(self)
        self.content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.pages: dict[str, ttk.Frame] = {}
        for key in ["dashboard", "incidents", "config", "targets", "manual"]:
            self.pages[key] = ttk.Frame(self.content)

        self._build_dashboard_page()
        self._build_incidents_page()
        self._build_config_page()
        self._build_targets_page()
        self._build_manual_page()

    def show_page(self, page: str) -> None:
        for frame in self.pages.values():
            frame.pack_forget()
        self.pages[page].pack(fill=tk.BOTH, expand=True)
        for key, button in self.nav_buttons.items():
            if key == page:
                button.configure(bg="#edf3ff", fg="#3370ff", font=("Microsoft YaHei UI", 10, "bold"))
            else:
                button.configure(bg="#ffffff", fg="#646a73", font=("Microsoft YaHei UI", 10))
        scroll = self.page_scrolls.get(page)
        if scroll is not None:
            self.after_idle(scroll.reset_scroll)

    def make_header(self, parent, title: str, subtitle: str) -> ttk.Frame:
        header_bg = "#f3f6fb"
        header = tk.Frame(parent, bg=header_bg, highlightthickness=0)
        header.pack(fill=tk.X, padx=26, pady=(18, 14))
        actions = ttk.Frame(header, style="Header.TFrame")
        actions.pack(side=tk.RIGHT, padx=18, pady=20)
        title_area = tk.Frame(header, bg=header_bg)
        title_area.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=24, pady=20)
        tk.Label(
            title_area,
            text=title,
            bg=header_bg,
            fg="#1f2329",
            font=("Microsoft YaHei UI", 30, "bold"),
            anchor="w",
        ).pack(anchor=tk.W)
        tk.Label(
            title_area,
            text=subtitle,
            bg=header_bg,
            fg="#646a73",
            font=("Microsoft YaHei UI", 10),
            anchor="w",
        ).pack(anchor=tk.W, pady=(8, 0))
        return actions

    def make_card(self, parent, title: str | None = None, expand: bool = True) -> ttk.Frame:
        outer = tk.Frame(parent, bg="#ffffff", highlightthickness=1, highlightbackground="#e5e8ef")
        outer.pack(fill=tk.BOTH if expand else tk.X, expand=expand, padx=26, pady=8)
        card = ttk.Frame(outer, style="Card.TFrame")
        card.pack(fill=tk.BOTH, expand=True)
        if title:
            ttk.Label(card, text=title, style="CardTitle.TLabel").pack(anchor=tk.W, padx=16, pady=(14, 8))
            ttk.Separator(card).pack(fill=tk.X)
        return card

    def _build_dashboard_page(self) -> None:
        page = self.pages["dashboard"]
        header = self.make_header(page, "总览", "查看 PatchPilot 当前配置风险、修复成果和最近事故")
        ttk.Button(header, text="刷新", style="Primary.TButton", command=self.refresh_all).pack(side=tk.RIGHT)

        metrics = ttk.Frame(page)
        metrics.pack(fill=tk.X, padx=26, pady=(0, 8))
        self.metric_labels: dict[str, tk.Label] = {}
        for key, label in [
            ("total", "总事件"),
            ("fixed", "已修复"),
            ("needs_human_verification", "需人工验证"),
            ("needs_manual_intervention", "需人工处理"),
            ("ignored", "已忽略"),
        ]:
            card = tk.Frame(metrics, bg="#ffffff", highlightthickness=1, highlightbackground="#e5e8ef")
            card.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 12))
            tk.Label(card, text=label, bg="#ffffff", fg="#646a73", font=("Microsoft YaHei UI", 10)).pack(anchor=tk.W, padx=16, pady=(14, 4))
            value = tk.Label(card, text="0", bg="#ffffff", fg="#1f2329", font=("Microsoft YaHei UI", 24, "bold"))
            value.pack(anchor=tk.W, padx=16, pady=(0, 14))
            self.metric_labels[key] = value

        card = self.make_card(page, "最近事故")
        tree_wrap = ttk.Frame(card, style="Card.TFrame")
        tree_wrap.pack(fill=tk.BOTH, expand=True, padx=16, pady=16)
        columns = ("incident_id", "target", "status", "disposition", "message")
        self.dashboard_tree = ttk.Treeview(tree_wrap, columns=columns, show="headings", height=8)
        for col, text, width in [
            ("incident_id", "事件 ID", 260),
            ("target", "目标服务", 190),
            ("status", "状态", 100),
            ("disposition", "处理结论", 130),
            ("message", "摘要", 760),
        ]:
            self.dashboard_tree.heading(col, text=text)
            self.dashboard_tree.column(col, width=width, minwidth=90, stretch=col == "message")
        dashboard_y = ttk.Scrollbar(tree_wrap, orient=tk.VERTICAL, command=self.dashboard_tree.yview)
        dashboard_x = ttk.Scrollbar(tree_wrap, orient=tk.HORIZONTAL, command=self.dashboard_tree.xview)
        self.dashboard_tree.configure(yscrollcommand=dashboard_y.set, xscrollcommand=dashboard_x.set)
        self.dashboard_tree.grid(row=0, column=0, sticky="nsew")
        dashboard_y.grid(row=0, column=1, sticky="ns")
        dashboard_x.grid(row=1, column=0, sticky="ew")
        tree_wrap.grid_rowconfigure(0, weight=1)
        tree_wrap.grid_columnconfigure(0, weight=1)

    def _build_incidents_page(self) -> None:
        page = self.pages["incidents"]
        header = self.make_header(page, "事故记录", "查看每次事件的分诊结论、工具调用、PR 和人工处理建议")
        ttk.Button(header, text="刷新记录", style="Primary.TButton", command=self.refresh_records).pack(side=tk.RIGHT)
        ttk.Button(header, text="删除选中记录", command=self.delete_current_record).pack(side=tk.RIGHT, padx=(0, 8))

        body = tk.PanedWindow(
            page,
            orient=tk.HORIZONTAL,
            bg="#f7f8fb",
            sashwidth=8,
            sashrelief=tk.RAISED,
            opaqueresize=True,
            borderwidth=0,
            showhandle=False,
        )
        body.pack(fill=tk.BOTH, expand=True, padx=26, pady=8)
        left_outer = tk.Frame(body, bg="#ffffff", highlightthickness=1, highlightbackground="#e5e8ef")
        left = ttk.Frame(left_outer, style="Card.TFrame")
        left.pack(fill=tk.BOTH, expand=True)

        filters = ttk.Frame(left, style="Card.TFrame")
        filters.pack(fill=tk.X, padx=14, pady=12)
        filters.grid_columnconfigure(1, weight=1)

        ttk.Label(filters, text="服务名搜索", style="Muted.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=(0, 8))
        self.incident_query = tk.StringVar()
        self.incident_status = tk.StringVar(value="全部")
        ttk.Entry(filters, textvariable=self.incident_query).grid(row=0, column=1, columnspan=3, sticky="ew", pady=(0, 8))

        ttk.Label(filters, text="状态筛选", style="Muted.TLabel").grid(row=1, column=0, sticky="w", padx=(0, 8))
        ttk.Combobox(
            filters,
            textvariable=self.incident_status,
            values=["全部", "已修复", "需要人工验证", "需要人工处理", "已忽略"],
            width=16,
            state="readonly",
        ).grid(row=1, column=1, sticky="w")
        ttk.Button(filters, text="筛选", command=self.render_incident_table).grid(row=1, column=2, sticky="w", padx=(10, 0))

        tree_wrap = ttk.Frame(left, style="Card.TFrame")
        tree_wrap.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 14))
        columns = ("incident_id", "target", "status", "disposition", "updated_at")
        self.incidents_tree = ttk.Treeview(tree_wrap, columns=columns, show="headings")
        for col, text, width in [
            ("incident_id", "事件 ID", 270),
            ("target", "目标服务", 170),
            ("status", "状态", 90),
            ("disposition", "结论", 120),
            ("updated_at", "更新时间", 150),
        ]:
            self.incidents_tree.heading(col, text=text)
            self.incidents_tree.column(col, width=width, minwidth=80, stretch=False)
        yscroll = ttk.Scrollbar(tree_wrap, orient=tk.VERTICAL, command=self.incidents_tree.yview)
        xscroll = ttk.Scrollbar(tree_wrap, orient=tk.HORIZONTAL, command=self.incidents_tree.xview)
        self.incidents_tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.incidents_tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        tree_wrap.grid_rowconfigure(0, weight=1)
        tree_wrap.grid_columnconfigure(0, weight=1)
        self.incidents_tree.bind("<<TreeviewSelect>>", self.on_record_selected)

        right_outer = tk.Frame(body, bg="#ffffff", highlightthickness=1, highlightbackground="#e5e8ef")
        right = ttk.Frame(right_outer, style="Card.TFrame")
        right.pack(fill=tk.BOTH, expand=True)
        detail_header = ttk.Frame(right, style="Card.TFrame")
        detail_header.pack(fill=tk.X, padx=16, pady=(14, 8))
        ttk.Label(detail_header, text="事故详情", style="CardTitle.TLabel").pack(side=tk.LEFT, anchor=tk.W)
        ttk.Button(detail_header, text="删除记录", command=self.delete_current_record).pack(side=tk.RIGHT)
        ttk.Separator(right).pack(fill=tk.X)
        
        self.detail_notebook = ttk.Notebook(right)
        self.detail_notebook.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

        def detail_text_tab() -> tuple[ttk.Frame, tk.Text]:
            frame = ttk.Frame(self.detail_notebook, style="Card.TFrame")
            text = tk.Text(
                frame,
                wrap=tk.WORD,
                bd=0,
                bg="#fbfcff",
                fg="#1f2329",
                font=("Microsoft YaHei UI", 10),
                padx=18,
                pady=16,
                spacing1=3,
                spacing3=8,
            )
            text.tag_configure("section", foreground="#1f2329", font=("Microsoft YaHei UI", 11, "bold"), spacing1=10, spacing3=6)
            text.tag_configure("label", foreground="#4e5969", font=("Microsoft YaHei UI", 10, "bold"))
            text.tag_configure("muted", foreground="#646a73")
            text.tag_configure("success", foreground="#20b26c", font=("Microsoft YaHei UI", 10, "bold"))
            text.tag_configure("warning", foreground="#c97700", font=("Microsoft YaHei UI", 10, "bold"))
            text.tag_configure("danger", foreground="#d92d20", font=("Microsoft YaHei UI", 10, "bold"))
            text.tag_configure("bullet", lmargin1=18, lmargin2=32)
            scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=text.yview)
            text.configure(yscrollcommand=scrollbar.set)
            text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            return frame, text

        self.tab_overview_frame, self.tab_overview = detail_text_tab()
        self.tab_analysis_frame, self.tab_analysis = detail_text_tab()
        self.tab_patch_frame, self.tab_patch = detail_text_tab()
        self.tab_tools_frame, self.tab_tools = detail_text_tab()

        self.detail_notebook.add(self.tab_overview_frame, text="概览")
        self.detail_notebook.add(self.tab_analysis_frame, text="分析")
        self.detail_notebook.add(self.tab_patch_frame, text="补丁")
        self.detail_notebook.add(self.tab_tools_frame, text="工具")
        body.add(left_outer, minsize=560, stretch="always")
        body.add(right_outer, minsize=500, stretch="always")

        def set_default_split() -> None:
            try:
                body.update_idletasks()
                body.sash_place(0, int(body.winfo_width() * 0.56), 0)
            except Exception:
                pass

        self.after_idle(set_default_split)

    def _build_config_page(self) -> None:
        page = self.pages["config"]
        header = self.make_header(page, "配置中心", "编辑模型、密钥、Planner、风控和运行参数")
        ttk.Button(header, text="保存到 local.yaml", style="Primary.TButton", command=self.save_global_config).pack(side=tk.RIGHT)

        scroll = ScrollFrame(page)
        self.page_scrolls["config"] = scroll
        scroll.pack(fill=tk.BOTH, expand=True, padx=26, pady=(0, 16))
        body = scroll.body

        self._add_section(body, "模型与外部服务密钥")
        self._add_entry(body, ("openai", "model"), "模型名称")
        self._add_secret(body, ("openai", "api_key"), "模型 / ARK API Key")
        self._add_entry(body, ("openai", "base_url"), "模型接口地址")
        self._add_combo(
            body,
            ("openai", "transport"),
            "模型调用方式",
            ["auto", "responses", "chat_completions", "rest_chat_completions"],
        )
        self._add_segmented(
            body,
            ("openai", "analysis_reasoning_effort"),
            "分析推理强度",
            [("low", "低"), ("medium", "中"), ("high", "高")],
            default="medium",
        )
        self._add_segmented(
            body,
            ("openai", "patch_reasoning_effort"),
            "修复推理强度",
            [("low", "低"), ("medium", "中"), ("high", "高")],
            default="high",
        )
        self._add_secret(body, ("github", "token"), "GitHub 访问令牌")
        self._add_entry(body, ("github", "api_base_url"), "GitHub API 地址")
        self._add_secret(body, ("feishu", "webhook_url"), "飞书机器人地址")
        self._add_secret(body, ("feishu", "webhook_secret"), "飞书签名密钥")

        self._add_section(body, "Agent 决策与风控")
        self._add_entry(body, ("guardrails", "max_changed_files"), "最大修改文件数")
        self._add_entry(body, ("guardrails", "max_patch_lines"), "最大补丁行数")
        self._add_entry(body, ("guardrails", "min_confidence"), "最小分析置信度")
        self._add_check(body, ("agent", "report", "notify_on_ignored"), "忽略事件也发送飞书")
        self._add_check(body, ("agent", "report", "notify_on_report_only"), "只报告事件发送飞书")
        self._add_check(body, ("agent", "report", "notify_on_needs_more_context"), "上下文不足事件发送飞书")

        self._add_section(body, "运行、验证与记录")
        
        bg_row = ttk.Frame(body)
        bg_row.pack(fill=tk.X, padx=16, pady=6)
        ttk.Label(bg_row, text="守护模式", width=22, style="FormLabel.TLabel").pack(side=tk.LEFT)
        bg_btn = self._make_check(bg_row, self.background_service_enabled, "启动后自动常驻监听 (Agent Serve --watch)")
        
        def toggle_service():
            if not self.background_service_enabled.get() and hasattr(self, "stop_background_service"):
                self.stop_background_service()
                
        bg_btn.config(command=lambda: [self.background_service_enabled.set(not self.background_service_enabled.get()), self._refresh_checks(), toggle_service()])
        bg_btn.pack(side=tk.LEFT)

        self._add_path_entry(body, ("runtime", "workspace_root"), "本地代码工作区")
        self._add_entry(body, ("runtime", "artifact_root"), "运行产物目录")
        self._add_entry(body, ("runtime", "max_repair_attempts"), "最大修复尝试次数")
        self._add_entry(body, ("server", "host"), "Agent 服务监听地址")
        self._add_entry(body, ("server", "port"), "Agent 服务端口")
        self._add_entry(body, ("server", "poll_interval_seconds"), "日志轮询间隔秒")
        self._add_entry(body, ("validation", "service_start_timeout_seconds"), "服务启动超时秒")
        self._add_entry(body, ("validation", "healthcheck_timeout_seconds"), "健康检查超时秒")
        self._add_entry(body, ("validation", "healthcheck_interval_seconds"), "健康检查间隔秒")
        self._add_entry(body, ("records", "root"), "修复记录目录")
        self._add_check(body, ("records", "auto_commit"), "records 自动 commit")
        self.load_global_form()

    def _build_targets_page(self) -> None:
        page = self.pages["targets"]
        header = self.make_header(page, "目标服务管理", "配置被 PatchPilot 监控和自动修复的本地服务仓库")
        ttk.Button(header, text="保存目标服务", style="Primary.TButton", command=self.save_current_target).pack(side=tk.RIGHT)
        ttk.Button(header, text="新增目标服务", command=self.add_target).pack(side=tk.RIGHT, padx=(0, 8))

        body = ttk.Frame(page)
        body.pack(fill=tk.BOTH, expand=True, padx=26, pady=(0, 16))

        top = ttk.Frame(body)
        top.pack(fill=tk.X, padx=16, pady=(4, 10))
        ttk.Label(top, text="选择目标服务", width=22, style="FormLabel.TLabel").pack(side=tk.LEFT)
        self.target_selector = ttk.Combobox(top, textvariable=self.current_target_name, state="readonly", width=34)
        self.target_selector.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.target_selector.bind("<<ComboboxSelected>>", lambda _event: self.load_target_form())
        ttk.Button(top, text="删除", command=self.delete_target).pack(side=tk.RIGHT)
        ttk.Button(top, text="复制", command=self.duplicate_target).pack(side=tk.RIGHT, padx=8)

        form = ttk.Frame(body)
        form.pack(fill=tk.BOTH, expand=True)
        self._add_section(form, "仓库与日志")
        self._target_entry(form, "name", "目标服务名称")
        self._target_action_entry(form, "repo_full_name", "远程仓库", "自动定位/克隆", self.auto_locate_repo)
        self._target_path_entry(form, "repo_path", "本地仓库路径")
        self._target_entry(form, "base_branch", "PR 目标分支")
        self._target_path_entry(form, "service_log_file", "服务日志文件", browse_type="file")
        self.refresh_target_selector()

    def _build_manual_page(self) -> None:
        page = self.pages["manual"]
        self.make_header(page, "手动运行", "直接选择本地仓库和日志文件，触发一次 PatchPilot 修复")
        scroll = ScrollFrame(page)
        self.page_scrolls["manual"] = scroll
        scroll.pack(fill=tk.BOTH, expand=True, padx=26, pady=(0, 16))
        body = scroll.body
        self._add_section(body, "运行参数")

        self.manual_repo = tk.StringVar()
        self.manual_log = tk.StringVar()
        self.manual_branch = tk.StringVar(value="main")
        self.manual_no_pr = tk.BooleanVar(value=True)
        self._row(body, "目标仓库", self.manual_repo, browse=lambda: self._browse_dir(self.manual_repo))
        self._row(body, "日志文件", self.manual_log, browse=lambda: self._browse_file(self.manual_log))
        self._row(body, "PR 目标分支", self.manual_branch)
        self._make_check(body, self.manual_no_pr, "只验证，不创建 PR").pack(anchor=tk.W, padx=16, pady=8)

        action_frame = ttk.Frame(body)
        action_frame.pack(fill=tk.X, padx=16, pady=10)
        self.btn_run_manual = ttk.Button(action_frame, text="开始运行", style="Primary.TButton", command=self.run_manual)
        self.btn_run_manual.pack(side=tk.LEFT)
        
        self.manual_status_label = ttk.Label(action_frame, text="当前进度: 闲置 (Idle)", style="Subtitle.TLabel")
        self.manual_status_label.pack(side=tk.LEFT, padx=(12, 0))

        self._add_section(body, "运行输出")
        self.manual_output = tk.Text(
            body,
            height=16,
            bg="#1f2329",
            fg="#dfe3eb",
            insertbackground="#ffffff",
            font=("Cascadia Mono", 10),
            relief=tk.FLAT,
            padx=12,
            pady=10,
        )
        self.manual_output.pack(fill=tk.X, padx=16, pady=(0, 16))

    def _add_section(self, parent, title: str) -> None:
        frame = tk.Frame(parent, bg="#f7f8fb")
        frame.pack(fill=tk.X, padx=16, pady=(18, 8))
        accent = tk.Frame(frame, bg="#3370ff", width=4, height=22)
        accent.pack(side=tk.LEFT, fill=tk.Y, pady=(2, 0))
        tk.Label(
            frame,
            text=title,
            bg="#f7f8fb",
            fg="#1f2329",
            font=("Microsoft YaHei UI", 13, "bold"),
            anchor="w",
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)

    def _add_hint(self, parent, text: str) -> None:
        tk.Label(
            parent,
            text=text,
            bg="#f7f8fb",
            fg="#8f959e",
            anchor="w",
            justify=tk.LEFT,
            font=("Microsoft YaHei UI", 9),
        ).pack(fill=tk.X, padx=(168, 16), pady=(0, 8))

    def _row(self, parent, label: str, variable: tk.StringVar, browse=None, show: str | None = None) -> ttk.Entry:
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, padx=16, pady=6)
        ttk.Label(row, text=label, width=22, style="FormLabel.TLabel").pack(side=tk.LEFT)
        entry = ttk.Entry(row, textvariable=variable, show=show or "")
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        if browse:
            ttk.Button(row, text="选择", command=browse).pack(side=tk.LEFT, padx=(8, 0))
        return entry

    def _add_entry(self, parent, path: tuple[str, ...], label: str) -> None:
        var = tk.StringVar()
        self.form_vars[path] = var
        self._row(parent, label, var)

    def _add_combo(self, parent, path: tuple[str, ...], label: str, values: list[str]) -> None:
        var = tk.StringVar()
        self.form_vars[path] = var
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, padx=16, pady=6)
        ttk.Label(row, text=label, width=22, style="FormLabel.TLabel").pack(side=tk.LEFT)
        combo = ttk.Combobox(row, textvariable=var, values=values, state="readonly", height=min(8, len(values)))
        combo.pack(side=tk.LEFT, fill=tk.X, expand=True)

    def _add_segmented(
        self,
        parent,
        path: tuple[str, ...],
        label: str,
        options: list[tuple[str, str]],
        *,
        default: str,
    ) -> None:
        var = tk.StringVar(value=default)
        self.form_vars[path] = var
        self.segmented_defaults[path] = default
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, padx=16, pady=6)
        ttk.Label(row, text=label, width=22, style="FormLabel.TLabel").pack(side=tk.LEFT)
        group = tk.Frame(row, bg="#dce2ee", highlightthickness=1, highlightbackground="#dce2ee")
        group.pack(side=tk.LEFT, fill=tk.X, expand=True)
        buttons: list[tuple[tk.Button, str]] = []

        def choose(value: str) -> None:
            var.set(value)

        for value, text in options:
            button = tk.Button(
                group,
                text=text,
                bd=0,
                padx=16,
                pady=7,
                cursor="hand2",
                font=("Microsoft YaHei UI", 10, "bold"),
                command=lambda current=value: choose(current),
            )
            button.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=1, pady=1)
            buttons.append((button, value))

        def refresh(*_args) -> None:
            selected = var.get() or default
            for button, value in buttons:
                if value == selected:
                    button.configure(bg="#3370ff", fg="#ffffff", activebackground="#1e5def", activeforeground="#ffffff")
                else:
                    button.configure(bg="#ffffff", fg="#646a73", activebackground="#edf3ff", activeforeground="#3370ff")

        var.trace_add("write", refresh)
        refresh()

    def _add_path_entry(self, parent, path: tuple[str, ...], label: str, browse_type: str = "dir") -> None:
        var = tk.StringVar()
        self.form_vars[path] = var
        def browse():
            if browse_type == "dir":
                p = filedialog.askdirectory()
            else:
                p = filedialog.askopenfilename()
            if p:
                var.set(p)
        self._row(parent, label, var, browse=browse)

    def _add_secret(self, parent, path: tuple[str, ...], label: str) -> None:
        var = tk.StringVar()
        self.form_vars[path] = var
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, padx=16, pady=6)
        ttk.Label(row, text=label, width=22, style="FormLabel.TLabel").pack(side=tk.LEFT)
        entry = ttk.Entry(row, textvariable=var, show="*")
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        button = ttk.Button(row, text="预览", width=8, command=lambda p=path: self.toggle_secret_preview(p))
        button.pack(side=tk.LEFT, padx=(8, 0))
        self.secret_entries[path] = entry
        self.secret_buttons[path] = button

    def _add_text(self, parent, path: tuple[str, ...], label: str) -> None:
        ttk.Label(parent, text=label, style="FormLabel.TLabel").pack(anchor=tk.W, padx=16, pady=(10, 4))
        text = tk.Text(parent, height=4, bg="#ffffff", fg="#1f2329", relief=tk.SOLID, bd=1, font=("Cascadia Mono", 10))
        text.pack(fill=tk.X, padx=16, pady=(0, 8))
        self.form_vars[path] = text

    def _add_check(self, parent, path: tuple[str, ...], label: str) -> None:
        var = tk.BooleanVar()
        self.form_vars[path] = var
        self._make_check(parent, var, label).pack(anchor=tk.W, padx=16, pady=6)

    def _target_entry(self, parent, key: str, label: str) -> None:
        var = tk.StringVar()
        self.target_vars[key] = var
        self._row(parent, label, var)

    def _target_action_entry(self, parent, key: str, label: str, button_text: str, action: callable) -> None:
        var = tk.StringVar()
        self.target_vars[key] = var
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, padx=16, pady=6)
        ttk.Label(row, text=label, width=22, style="FormLabel.TLabel").pack(side=tk.LEFT)
        entry = ttk.Entry(row, textvariable=var)
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(row, text=button_text, command=action).pack(side=tk.LEFT, padx=(8, 0))

    def _target_path_entry(self, parent, key: str, label: str, browse_type: str = "dir") -> None:
        var = tk.StringVar()
        self.target_vars[key] = var
        browse_cmd = lambda: self._browse_dir(var) if browse_type == "dir" else self._browse_file(var)
        self._row(parent, label, var, browse=browse_cmd)

    def _target_text(self, parent, key: str, label: str) -> None:
        ttk.Label(parent, text=label, style="FormLabel.TLabel").pack(anchor=tk.W, padx=16, pady=(10, 4))
        text = tk.Text(parent, height=5, bg="#ffffff", fg="#1f2329", relief=tk.SOLID, bd=1, font=("Cascadia Mono", 10))
        text.pack(fill=tk.X, padx=16, pady=(0, 8))
        self.target_vars[key] = text

    def _target_check(self, parent, key: str, label: str) -> None:
        var = tk.BooleanVar()
        self.target_vars[key] = var
        self._make_check(parent, var, label).pack(anchor=tk.W, padx=16, pady=6)

    def _target_combo(self, parent, key: str, label: str, values: list[str]) -> None:
        var = tk.StringVar()
        self.target_vars[key] = var
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, padx=16, pady=6)
        ttk.Label(row, text=label, width=22, style="FormLabel.TLabel").pack(side=tk.LEFT)
        combo = ttk.Combobox(row, textvariable=var, values=values, state="readonly")
        combo.pack(side=tk.LEFT, fill=tk.X, expand=True)

    def _make_check(self, parent, variable: tk.BooleanVar, label: str) -> tk.Button:
        button = tk.Button(
            parent,
            bd=1,
            relief=tk.SOLID,
            anchor="w",
            padx=12,
            pady=8,
            bg="#ffffff",
            fg="#1f2329",
            activebackground="#edf3ff",
            activeforeground="#3370ff",
            font=("Microsoft YaHei UI", 10, "bold"),
            cursor="hand2",
        )

        def refresh() -> None:
            if variable.get():
                button.configure(text=f"{label}：已开启", bg="#edf3ff", fg="#3370ff", highlightbackground="#3370ff")
            else:
                button.configure(text=f"{label}：未开启", bg="#ffffff", fg="#646a73", highlightbackground="#e5e8ef")

        def toggle() -> None:
            variable.set(not variable.get())
            refresh()

        button.configure(command=toggle)
        self.check_refreshers.append(refresh)
        refresh()
        return button

    def _refresh_checks(self) -> None:
        for refresh in self.check_refreshers:
            refresh()

    def toggle_secret_preview(self, path: tuple[str, ...]) -> None:
        entry = self.secret_entries[path]
        button = self.secret_buttons[path]
        if entry.cget("show"):
            entry.configure(show="")
            button.configure(text="隐藏")
        else:
            entry.configure(show="*")
            button.configure(text="预览")

    def load_config(self) -> None:
        base_path = BASE_CONFIG if BASE_CONFIG.exists() else LEGACY_BASE_CONFIG
        local_path = LOCAL_CONFIG if LOCAL_CONFIG.exists() else LEGACY_LOCAL_CONFIG
        self.base_config = load_yaml(base_path)
        self.local_config = load_yaml(local_path)
        self.config_data = deep_merge(self.base_config, self.local_config)

    def save_local_config(self) -> None:
        with LOCAL_CONFIG.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(self.config_data, handle, allow_unicode=True, sort_keys=False)

    def _apply_saved_config(self) -> None:
        self.load_config()
        self.refresh_records()
        self.load_global_form()
        self.refresh_target_selector()
        self._restart_background_service_if_needed()

    def refresh_all(self) -> None:
        self.load_config()
        self.refresh_records()
        self.load_global_form()
        self.refresh_target_selector()

    def refresh_records(self) -> None:
        records_root = Path(get_nested(self.config_data, ("records", "root"), "records"))
        self.records = []
        if records_root.exists():
            for path in sorted(records_root.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                data["_path"] = str(path)
                data["_updated_at"] = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                self.records.append(data)
        self.render_dashboard()
        self.render_incident_table()

    def render_dashboard(self) -> None:
        self.metric_labels["total"].configure(text=str(len(self.records)))
        self.metric_labels["fixed"].configure(
            text=str(sum(1 for item in self.records if public_status(item.get("status")) == "fixed"))
        )
        self.metric_labels["needs_human_verification"].configure(
            text=str(
                sum(1 for item in self.records if public_status(item.get("status")) == "needs_human_verification")
            )
        )
        self.metric_labels["needs_manual_intervention"].configure(
            text=str(
                sum(1 for item in self.records if public_status(item.get("status")) == "needs_manual_intervention")
            )
        )
        self.metric_labels["ignored"].configure(
            text=str(sum(1 for item in self.records if public_status(item.get("status")) == "ignored"))
        )
        for row in self.dashboard_tree.get_children():
            self.dashboard_tree.delete(row)
        for item in self.records[:12]:
            self.dashboard_tree.insert("", tk.END, values=self._record_values(item, include_message=True))

    def render_incident_table(self) -> None:
        query = self.incident_query.get().strip().lower() if hasattr(self, "incident_query") else ""
        status_filter = self.incident_status.get() if hasattr(self, "incident_status") else "全部"
        
        # 建立中文标签到英文内部状态的映射，需要与 localization 保持一致
        status_map = {
            "已修复": "fixed",
            "需要人工验证": "needs_human_verification",
            "需要人工处理": "needs_manual_intervention",
            "已忽略": "ignored",
            "重复事件": "duplicate",
            "已拒绝": "rejected"
        }
        filter_key = status_map.get(status_filter, status_filter)
        
        for row in self.incidents_tree.get_children():
            self.incidents_tree.delete(row)
        first_iid = None
        for item in self.records:
            if status_filter != "全部" and public_status(item.get("status")) != filter_key:
                continue
            
            target_name = str(item.get("target", "")).lower()
            if query and query not in target_name:
                continue
                
            iid = item.get("incident_id")
            self.incidents_tree.insert("", tk.END, iid=iid, values=self._record_values(item))
            if first_iid is None:
                first_iid = iid
        if first_iid and not self.incidents_tree.selection():
            self.incidents_tree.selection_set(first_iid)
            self.incidents_tree.focus(first_iid)
            self.on_record_selected()
        elif first_iid is None:
            self.current_record = None
            self.render_record_detail()

    def _record_values(self, item: dict, include_message: bool = False) -> tuple:
        rr = item.get("repair_result") or {}
        values = (
            item.get("incident_id", ""),
            item.get("target", ""),
            status_label(item.get("status", "")),
            disposition_label(item.get("disposition") or rr.get("disposition")),
            item.get("_updated_at", ""),
        )
        if include_message:
            return (*values[:4], item.get("message", "")[:120])
        return values

    def on_record_selected(self, _event=None) -> None:
        selected = self.incidents_tree.selection()
        if not selected:
            return
        incident_id = selected[0]
        self.current_record = next((item for item in self.records if item.get("incident_id") == incident_id), None)
        self.render_record_detail()

    def render_record_detail(self) -> None:
        for tab in [self.tab_overview, self.tab_analysis, self.tab_patch, self.tab_tools]:
            tab.configure(state=tk.NORMAL)
            tab.delete("1.0", tk.END)

        data = self.current_record or {}
        if not data:
            self._detail_section(self.tab_overview, "请选择一条事故记录")
            self._detail_text(self.tab_overview, "左侧列表会展示 records 目录中的 JSON 处理记录。")
            for tab in [self.tab_overview, self.tab_analysis, self.tab_patch, self.tab_tools]:
                tab.configure(state=tk.DISABLED)
            return

        rr = data.get("repair_result") or {}
        summary = data.get("message", "")
        decision_reason = data.get("decision_reason") or rr.get("decision_reason")
        if decision_reason and decision_reason not in summary:
            summary = f"{summary}（处理判断：{decision_reason}）"
            
        analysis = rr.get("analysis") or {}
        repair_plan = analysis.get("repair_plan") or []
        status = data.get("status", "")
        public = public_status(status)
        status_tag = {
            "fixed": "success",
            "ignored": "muted",
            "needs_human_verification": "warning",
            "needs_manual_intervention": "danger",
        }.get(public)

        self._detail_section(self.tab_overview, "基本信息")
        self._detail_kv(self.tab_overview, "事件 ID", data.get("incident_id", ""))
        self._detail_kv(self.tab_overview, "目标服务", data.get("target", ""))
        self._detail_kv(self.tab_overview, "来源", data.get("source", ""))
        self._detail_kv(self.tab_overview, "状态", status_label(status), status_tag)
        self._detail_kv(
            self.tab_overview,
            "处理结论",
            disposition_label(data.get("disposition") or rr.get("disposition")),
        )
        self._detail_kv(self.tab_overview, "风险等级", risk_label(data.get("risk_level") or rr.get("risk_level")))
        self._detail_kv(self.tab_overview, "更新时间", data.get("_updated_at", ""))
        self._detail_kv(self.tab_overview, "PR", data.get("pr_url") or rr.get("pr_url") or "未创建")
        self._detail_section(self.tab_overview, "摘要")
        self._detail_text(self.tab_overview, summary or "无")
        self._detail_section(self.tab_overview, "人工处理建议")
        self._detail_list(self.tab_overview, data.get("human_resolution_steps") or rr.get("human_resolution_steps") or ["无"])

        self._detail_section(self.tab_analysis, "根因与判断")
        self._detail_kv(self.tab_analysis, "根因类型", root_cause_label(data.get("root_cause_type") or rr.get("root_cause_type")))
        self._detail_kv(self.tab_analysis, "处理判断", decision_reason or "无")
        self._detail_section(self.tab_analysis, "修复思路")
        self._detail_list(self.tab_analysis, repair_plan or ["无"])
        self._detail_section(self.tab_analysis, "证据")
        self._detail_list(self.tab_analysis, data.get("evidence") or rr.get("evidence") or ["无"])

        generated_test = rr.get("generated_test") or {}
        generated_test_lines = self._generated_test_detail_lines(generated_test)
        validation = rr.get("validation") or {}
        commands = validation.get("commands") or []

        self._detail_section(self.tab_patch, "补丁文件")
        self._detail_list(self.tab_patch, rr.get("changed_files") or ["无"])
        self._detail_section(self.tab_patch, "验证命令")
        if commands:
            for command in commands:
                command_text = command.get("command", "")
                returncode = command.get("returncode")
                tag = "success" if returncode == 0 else "danger"
                self.tab_patch.insert(tk.END, f"- {command_text} -> {returncode}\n", ("bullet", tag))
        else:
            self._detail_list(self.tab_patch, ["无"])
        self._detail_section(self.tab_patch, "自动生成测试")
        self._detail_list(self.tab_patch, generated_test_lines)
        if rr.get("failure_reason"):
            self._detail_section(self.tab_patch, "失败原因")
            self._detail_text(self.tab_patch, rr.get("failure_reason"))

        self._detail_section(self.tab_tools, "工具调用记录")
        for tool in data.get("tool_calls", []):
            status_text = tool.get("status") or "unknown"
            tag = "success" if status_text == "success" else "warning" if status_text in {"warning", "skipped"} else "danger"
            self.tab_tools.insert(tk.END, f"{tool.get('name') or 'Tool'}", "label")
            self.tab_tools.insert(tk.END, f"  {status_text}\n", tag)
            self.tab_tools.insert(tk.END, f"{tool.get('summary') or '无摘要'}\n\n", "muted")
        if not data.get("tool_calls"):
            self._detail_text(self.tab_tools, "无工具调用记录")

        iterations = rr.get("repair_iterations") or []
        if iterations:
            self._detail_section(self.tab_tools, "迭代修复过程")
            for item in iterations:
                self.tab_tools.insert(tk.END, f"第 {item.get('attempt')} 轮：{item.get('status') or 'unknown'}\n", "label")
                if item.get("patch_summary"):
                    self.tab_tools.insert(tk.END, f"{item.get('patch_summary')}\n", "muted")
                feedback = item.get("validation_feedback") or []
                if feedback:
                    self._detail_list(self.tab_tools, feedback)
                self.tab_tools.insert(tk.END, "\n")

        for tab in [self.tab_overview, self.tab_analysis, self.tab_patch, self.tab_tools]:
            tab.configure(state=tk.DISABLED)

    def _detail_section(self, widget: tk.Text, title: str) -> None:
        widget.insert(tk.END, f"{title}\n", "section")

    def _detail_kv(self, widget: tk.Text, label: str, value, value_tag: str | None = None) -> None:
        widget.insert(tk.END, f"{label}: ", "label")
        display = "无" if value is None or value == "" else value
        if value_tag:
            widget.insert(tk.END, f"{display}\n", value_tag)
        else:
            widget.insert(tk.END, f"{display}\n")

    def _detail_text(self, widget: tk.Text, text) -> None:
        display = "无" if text is None or text == "" else text
        widget.insert(tk.END, f"{display}\n")

    def _detail_list(self, widget: tk.Text, items) -> None:
        values = list(items or ["无"])
        for item in values:
            widget.insert(tk.END, f"- {item}\n", "bullet")

    def delete_current_record(self) -> None:
        selected = self.incidents_tree.selection() if hasattr(self, "incidents_tree") else ()
        record = None
        if selected:
            incident_id = selected[0]
            record = next((item for item in self.records if item.get("incident_id") == incident_id), None)
        record = record or self.current_record
        if not record:
            messagebox.showwarning("无法删除", "请先选择一条事故记录。")
            return

        incident_id = record.get("incident_id", "")
        if not messagebox.askyesno("确认删除", f"确定删除事故记录 {incident_id} 吗？\n会删除对应 JSON 和 Markdown 文件。"):
            return

        paths = self._record_file_candidates(record)
        deleted: list[str] = []
        failed: list[str] = []
        for path in paths:
            try:
                if path.exists() and path.is_file():
                    path.unlink()
                    deleted.append(str(path))
            except OSError as exc:
                failed.append(f"{path}: {exc}")
        state_deleted = self._delete_event_state_for_record(str(incident_id))

        self.current_record = None
        self.refresh_records()
        if failed:
            messagebox.showwarning("部分删除失败", "\n".join(failed))
        else:
            messagebox.showinfo("删除成功", f"已删除 {len(deleted)} 个记录文件，并清理 {state_deleted} 条事件状态。")

    def _record_file_candidates(self, record: dict) -> list[Path]:
        records_root = Path(get_nested(self.config_data, ("records", "root"), "records")).resolve()
        raw_paths = [
            record.get("_path"),
            record.get("record_json_path"),
            (record.get("repair_result") or {}).get("record_json_path"),
            record.get("record_markdown_path"),
            (record.get("repair_result") or {}).get("record_markdown_path"),
        ]
        candidates: list[Path] = []
        for raw_path in raw_paths:
            if not raw_path:
                continue
            path = Path(raw_path)
            if not path.is_absolute():
                path = (Path.cwd() / path)
            path = path.resolve()
            if path.suffix not in {".json", ".md"}:
                continue
            try:
                if not path.is_relative_to(records_root):
                    continue
            except ValueError:
                continue
            candidates.append(path)
            if path.suffix == ".json":
                candidates.append(path.with_suffix(".md"))
        return list(dict.fromkeys(candidates))

    def _delete_event_state_for_record(self, incident_id: str) -> int:
        state_path = Path(get_nested(self.config_data, ("server", "state_path"), ".patchpilot-state/events.sqlite3"))
        if not state_path.exists():
            return 0
        try:
            return EventStateStore(state_path).delete_by_incident_id(incident_id)
        except Exception:
            return 0

    def _generated_test_detail_lines(self, generated_test: dict) -> list[str]:
        if not generated_test or not generated_test.get("attempted"):
            return ["- 本次没有尝试自动生成回归测试。"]
        lines = [
            f"- 测试文件：{generated_test.get('test_path') or '未生成'}",
            f"- 测试框架：{generated_test.get('framework') or 'unknown'}",
        ]
        if generated_test.get("summary"):
            lines.append(f"- 用例介绍：{generated_test.get('summary')}")
        if generated_test.get("expected_behavior"):
            lines.append(f"- 预期行为：{generated_test.get('expected_behavior')}")
        test_cases = generated_test.get("test_cases") or []
        if test_cases:
            lines.append("- 覆盖用例：")
            lines.extend(f"  - {item}" for item in test_cases)
        return lines

    def load_global_form(self) -> None:
        for path, widget in self.form_vars.items():
            value = get_nested(self.config_data, path, "")
            if isinstance(widget, tk.Text):
                widget.delete("1.0", tk.END)
                if isinstance(value, list):
                    widget.insert(tk.END, "\n".join(str(item) for item in value))
                else:
                    widget.insert(tk.END, "" if value is None else str(value))
            elif isinstance(widget, tk.BooleanVar):
                widget.set(bool(value))
            else:
                text_value = "" if value is None else str(value)
                if path in self.segmented_defaults and text_value not in {"low", "medium", "high"}:
                    text_value = self.segmented_defaults[path]
                widget.set(text_value)
        for entry in self.secret_entries.values():
            entry.configure(show="*")
        for button in self.secret_buttons.values():
            button.configure(text="预览")
        self._refresh_checks()

    def save_global_config(self) -> None:
        try:
            for path, widget in self.form_vars.items():
                if isinstance(widget, tk.Text):
                    raw = widget.get("1.0", tk.END).strip()
                    value = [line.strip() for line in raw.splitlines() if line.strip()]
                elif isinstance(widget, tk.BooleanVar):
                    value = bool(widget.get())
                else:
                    raw = widget.get().strip()
                    if path[-1] in {"port", "max_steps", "max_changed_files", "max_patch_lines", "max_repair_attempts"}:
                        value = int(raw) if raw else 0
                    elif path[-1] in {
                        "min_confidence",
                        "poll_interval_seconds",
                        "service_start_timeout_seconds",
                        "healthcheck_timeout_seconds",
                        "healthcheck_interval_seconds",
                    }:
                        value = float(raw) if raw else 0.0
                    else:
                        value = raw or None
                set_nested(self.config_data, path, value)
            set_nested(self.config_data, ("agent", "risk", "max_changed_files"), get_nested(self.config_data, ("guardrails", "max_changed_files"), 6))
            set_nested(self.config_data, ("agent", "risk", "max_changed_lines"), get_nested(self.config_data, ("guardrails", "max_patch_lines"), 600))
            self.save_local_config()
            self._apply_saved_config()
        except ValueError as exc:
            messagebox.showerror("保存失败", f"数字字段格式错误：{exc}")
            return
        messagebox.showinfo("保存成功", "配置已写入 patchpilot.local.yaml，并已即时生效。")

    def refresh_target_selector(self) -> None:
        if not hasattr(self, "target_selector"):
            return
        targets = self.config_data.get("targets", {})
        names = list(targets)
        self.target_selector["values"] = names
        if names and (not self.current_target_name.get() or self.current_target_name.get() not in targets):
            self.current_target_name.set(names[0])
        self.load_target_form()

    def load_target_form(self) -> None:
        name = self.current_target_name.get()
        target = self.config_data.get("targets", {}).get(name, {})
        for key, widget in self.target_vars.items():
            if key == "name":
                widget.set(name)
                continue
            if key.startswith("generated_tests."):
                value = get_nested(target, tuple(key.split(".")), False)
                if key == "generated_tests.failure_policy" and not value:
                    legacy = get_nested(target, ("generated_tests", "fallback_to_v2_on_failure"), True)
                    value = "continue_existing_validation" if legacy else "needs_human_verification"
                if isinstance(widget, tk.BooleanVar):
                    widget.set(bool(value))
                else:
                    widget.set("" if value is None else str(value))
            elif isinstance(widget, tk.Text):
                widget.delete("1.0", tk.END)
                value = target.get(key, [])
                if key == "verification_requests":
                    widget.insert(tk.END, json.dumps(value or [], ensure_ascii=False, indent=2))
                elif isinstance(value, list):
                    widget.insert(tk.END, "\n".join(str(item) for item in value))
                else:
                    widget.insert(tk.END, "" if value is None else str(value))
            else:
                value = target.get(key, "")
                widget.set("" if value is None else str(value))
        self._refresh_checks()

    def save_current_target(self) -> None:
        old_name = self.current_target_name.get()
        name = self.target_vars["name"].get().strip()
        if not name:
            messagebox.showerror("保存失败", "目标服务名称不能为空。")
            return
        
        # Preserve old advanced settings if they exist
        old_target = self.config_data.get("targets", {}).get(old_name, {})
        
        target = {
            "repo_full_name": self.target_vars["repo_full_name"].get().strip() or None,
            "repo_path": self.target_vars["repo_path"].get().strip(),
            "base_branch": self.target_vars["base_branch"].get().strip() or "main",
            "working_dir": ".",
            "service_log_file": self.target_vars["service_log_file"].get().strip() or None,
            "start_command": self.target_vars["start_command"].get().strip() or None,
            "healthcheck_url": old_target.get("healthcheck_url"),
            "test_commands": old_target.get("test_commands", []),
            "verification_requests": old_target.get("verification_requests", []),
            "generated_tests": old_target.get("generated_tests", {
                "enabled": True,
                "framework": "auto",
                "max_files": 1,
                "require_prefix_failure": True,
                "commit_when_stable": True,
                "failure_policy": "continue_existing_validation",
            }),
        }
        self.config_data.setdefault("targets", {})
        if old_name and old_name != name:
            self.config_data["targets"].pop(old_name, None)
        self.config_data["targets"][name] = target
        self.current_target_name.set(name)
        self.save_local_config()
        self._apply_saved_config()
        messagebox.showinfo("保存成功", "目标服务配置已写入 patchpilot.local.yaml，并已即时生效。")

    def add_target(self) -> None:
        self.config_data.setdefault("targets", {})
        base = "new-service"
        name = base
        index = 1
        while name in self.config_data["targets"]:
            index += 1
            name = f"{base}-{index}"
        self.config_data["targets"][name] = {
            "repo_path": "",
            "base_branch": "main",
            "working_dir": ".",
            "test_commands": [],
            "verification_requests": [],
            "generated_tests": {
                "enabled": True,
                "framework": "auto",
                "max_files": 1,
                "require_prefix_failure": True,
                "commit_when_stable": True,
                "failure_policy": "continue_existing_validation",
            },
        }
        self.current_target_name.set(name)
        self.refresh_target_selector()

    def duplicate_target(self) -> None:
        name = self.current_target_name.get()
        if not name:
            return
        self.config_data.setdefault("targets", {})
        new_name = f"{name}-copy"
        index = 1
        while new_name in self.config_data["targets"]:
            index += 1
            new_name = f"{name}-copy-{index}"
        self.config_data["targets"][new_name] = deepcopy(self.config_data["targets"][name])
        self.current_target_name.set(new_name)
        self.refresh_target_selector()

    def delete_target(self) -> None:
        name = self.current_target_name.get()
        if not name:
            return
        if not messagebox.askyesno("确认删除", f"确定删除目标服务 `{name}` 吗？"):
            return
        self.config_data.get("targets", {}).pop(name, None)
        self.current_target_name.set("")
        self.save_local_config()
        self._apply_saved_config()

    def run_manual(self) -> None:
        repo = self.manual_repo.get().strip()
        log_file = self.manual_log.get().strip()
        if not repo or not log_file:
            messagebox.showerror("无法运行", "请先选择目标仓库和日志文件。")
            return
        command = [
            sys.executable,
            "-m",
            "patchpilot",
            "run",
            "--repo",
            repo,
            "--log-file",
            log_file,
            "--base-branch",
            self.manual_branch.get().strip() or "main",
        ]
        if self.manual_no_pr.get():
            command.append("--no-pr")
        self.manual_output.delete("1.0", tk.END)
        self.manual_output.insert(tk.END, "运行命令：\n" + " ".join(command) + "\n\n")

        def worker() -> None:
            self.manual_status_label.after(0, lambda: self.manual_status_label.config(text="当前进度: 正在初始化 Agent..."))
            self.btn_run_manual.after(0, lambda: self.btn_run_manual.config(state=tk.DISABLED))
            
            try:
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    encoding="utf-8",
                    errors="replace"
                )
                
                for line in process.stdout:
                    self.manual_output.after(0, lambda l=line: self.manual_output.insert(tk.END, l))
                    self.manual_output.after(0, lambda: self.manual_output.see(tk.END))
                    
                    lower_line = line.lower()
                    if "tool" in lower_line and "call" in lower_line:
                        self.manual_status_label.after(0, lambda l=line.strip()[-50:]: self.manual_status_label.config(text=f"当前进度: 正在调用工具 -> ...{l}"))
                    elif "thought" in lower_line or "思考:" in lower_line:
                        self.manual_status_label.after(0, lambda: self.manual_status_label.config(text="当前进度: Agent 正在思考分析..."))
                    elif "patch" in lower_line and "apply" in lower_line:
                        self.manual_status_label.after(0, lambda: self.manual_status_label.config(text="当前进度: 正在应用代码补丁..."))
                    elif "test" in lower_line and "run" in lower_line:
                        self.manual_status_label.after(0, lambda: self.manual_status_label.config(text="当前进度: 正在运行测试验证..."))
                        
                process.wait()
                if process.returncode == 0:
                    self.manual_status_label.after(0, lambda: self.manual_status_label.config(text="当前进度: 运行完成 (Success)"))
                else:
                    self.manual_status_label.after(0, lambda rc=process.returncode: self.manual_status_label.config(text=f"当前进度: 运行失败 (Exit Code {rc})"))
            except Exception as e:
                self.manual_output.after(0, lambda e=e: self.manual_output.insert(tk.END, f"\n执行出错: {e}\n"))
                self.manual_status_label.after(0, lambda: self.manual_status_label.config(text="当前进度: 发生异常"))
            finally:
                self.btn_run_manual.after(0, lambda: self.btn_run_manual.config(state=tk.NORMAL))

        threading.Thread(target=worker, daemon=True).start()

    def _browse_dir(self, variable: tk.StringVar) -> None:
        path = filedialog.askdirectory()
        if path:
            variable.set(path)

    def _browse_file(self, variable: tk.StringVar) -> None:
        path = filedialog.askopenfilename()
        if path:
            variable.set(path)

    # ================= Tray and Toast Methods =================

    def create_image(self):
        if Image is None or ImageDraw is None:
            return None
        image = Image.new('RGB', (64, 64), color=(44, 62, 80))
        dc = ImageDraw.Draw(image)
        dc.rectangle([(16, 16), (48, 48)], fill=(46, 204, 113))
        return image

    def hide_window(self):
        # If background service is NOT enabled, clicking X should just quit the app normally
        if not self.background_service_enabled.get():
            self.quit_window()
            return

        if pystray is None or Image is None or ImageDraw is None:
            messagebox.showwarning(
                "托盘不可用",
                "当前环境缺少托盘组件，无法隐藏到系统托盘。请保持窗口打开，或安装 pystray 与 Pillow 后重试。",
            )
            return
            
        # Otherwise, hide to tray
        self.withdraw()
        if not self.icon:
            menu = pystray.Menu(
                pystray.MenuItem('显示面板 (Show)', self.show_window, default=True),
                pystray.MenuItem('完全退出 (Quit)', self.quit_window)
            )
            self.icon = pystray.Icon("PatchPilot", self.create_image(), "PatchPilot 监控守护中", menu)
            
            # pystray has an issue on some Windows versions where run() crashes 
            # if it receives certain unhandled window messages.
            # Running it in a separate thread usually helps, but we must catch errors.
            def run_icon():
                try:
                    self.icon.run()
                except Exception as e:
                    print(f"Tray icon error (ignored): {e}")

            # Start tray icon in a separate thread so it doesn't block tkinter
            threading.Thread(target=run_icon, daemon=True).start()
            self.start_background_service()

    def show_window(self, icon=None, item=None):
        if self.icon:
            self.icon.stop()
            self.icon = None
        self.after(0, self.deiconify)

    def quit_window(self, icon=None, item=None):
        if self.icon:
            self.icon.stop()
        self.stop_background_service()
        self.after(0, self.destroy)

    def stop_background_service(self):
        self._background_service_generation += 1
        if self.agent_process:
            try:
                self.agent_process.terminate()
                self.agent_process.wait(timeout=3)
            except Exception:
                self.agent_process.kill()
            self.agent_process = None
        self._background_service_starting = False

    def _restart_background_service_if_needed(self) -> None:
        if not self.background_service_enabled.get():
            return
        self.stop_background_service()
        self.start_background_service()

    def start_background_service(self):
        if not self.background_service_enabled.get():
            return
        if self._background_service_starting:
            return
        if self.agent_process is not None and self.agent_process.poll() is None:
            return
        self._background_service_generation += 1
        generation = self._background_service_generation
        self._background_service_starting = True

        def run_service():
            try:
                env = os.environ.copy()
                src_path = os.path.abspath("src")
                if "PYTHONPATH" in env:
                    env["PYTHONPATH"] = f"{src_path}{os.pathsep}{env['PYTHONPATH']}"
                else:
                    env["PYTHONPATH"] = src_path
                    
                self.agent_process = subprocess.Popen(
                    [sys.executable, "-m", "patchpilot", "serve", "--watch"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=env,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
                )
                if generation != self._background_service_generation or not self.background_service_enabled.get():
                    try:
                        self.agent_process.terminate()
                        self.agent_process.wait(timeout=3)
                    except Exception:
                        try:
                            self.agent_process.kill()
                        except Exception:
                            pass
                    self.agent_process = None
                    return
            except Exception as e:
                print(f"Failed to start background service: {e}")
            finally:
                if generation == self._background_service_generation:
                    self._background_service_starting = False
                
        threading.Thread(target=run_service, daemon=True).start()

    def auto_locate_repo(self) -> None:
        repo_input = self.target_vars["repo_full_name"].get().strip()
        if not repo_input:
            messagebox.showwarning("提示", "请先填写远程仓库链接或名称 (如 owner/repo 或 https://github.com/...)")
            return
        
        workspace = ""
        if ("runtime", "workspace_root") in self.form_vars:
            workspace = self.form_vars[("runtime", "workspace_root")].get().strip()
        if not workspace:
            workspace = get_nested(self.config_data, ("runtime", "workspace_root"), "")
            
        if not workspace or not Path(workspace).exists():
            messagebox.showwarning("提示", "请先在 [配置中心] -> [运行与验证] 中配置有效的 [本地代码工作区]")
            self.show_page("config")
            return
            
        repo_name = repo_input.split("/")[-1].replace(".git", "")
        workspace_path = Path(workspace)
        
        found_path = None
        queue = deque([(workspace_path, 0)])
        while queue and not found_path:
            current_dir, depth = queue.popleft()
            if depth > 2:
                continue
            try:
                for child in current_dir.iterdir():
                    if child.is_dir():
                        if child.name.lower() == repo_name.lower() and (child / ".git").exists():
                            found_path = child
                            break
                        if child.name not in {".git", "node_modules", "venv", ".idea"}:
                            queue.append((child, depth + 1))
            except PermissionError:
                continue

        if found_path:
            self.target_vars["repo_path"].set(str(found_path))
            messagebox.showinfo("定位成功", f"已在工作区找到仓库并填充路径：\n{found_path}")
        else:
            if messagebox.askyesno("未找到仓库", f"在工作区内未找到 {repo_name}，是否立即从远程克隆到该目录？\n目标路径: {workspace_path / repo_name}"):
                self._clone_repo(repo_input, workspace_path / repo_name)

    def _clone_repo(self, repo_url_or_name: str, target_dir: Path) -> None:
        clone_url = repo_url_or_name
        if not clone_url.startswith("http") and not clone_url.startswith("git@"):
            clone_url = f"https://github.com/{repo_url_or_name}.git"
            
        def worker():
            try:
                subprocess.run(["git", "clone", clone_url, str(target_dir)], capture_output=True, text=True, check=True)
                if hasattr(self, "target_vars") and "repo_path" in self.target_vars:
                    self.after(0, lambda: self.target_vars["repo_path"].set(str(target_dir)))
                    self.after(0, lambda: messagebox.showinfo("克隆成功", f"成功克隆仓库到：\n{target_dir}"))
            except subprocess.CalledProcessError as e:
                self.after(0, lambda: messagebox.showerror("克隆失败", f"Git Clone 失败:\n{e.stderr}"))
        
        threading.Thread(target=worker, daemon=True).start()
        messagebox.showinfo("正在克隆", f"正在后台克隆 {clone_url}...\n请稍候，克隆完成后会自动填充路径。")

if __name__ == "__main__":
    enable_windows_dpi_awareness()
    app = PatchPilotGUI()
    app.mainloop()
