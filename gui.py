from __future__ import annotations

import json
import subprocess
import sys
import threading
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox
import tkinter as tk
from tkinter import ttk

import yaml
import pystray
from PIL import Image, ImageDraw
from win10toast import ToastNotifier
import os

SRC_DIR = Path(__file__).resolve().parent / "src"
if SRC_DIR.exists() and str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from agentfix.localization import disposition_label, risk_label, root_cause_label, status_label


APP_TITLE = "AgentFix 桌面控制台"
BASE_CONFIG = Path("agentfix.yaml")
LOCAL_CONFIG = Path("agentfix.local.yaml")


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


class AgentFixGUI(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1280x820")
        self.minsize(1120, 720)
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

        # Background Service Variables
        self.background_service_enabled = tk.BooleanVar(value=False)
        self.agent_process = None

        # Tray and Toast setup
        self.toaster = ToastNotifier()
        self.icon = None
        self.protocol('WM_DELETE_WINDOW', self.hide_window)

        self._configure_style()
        self.load_config()
        self._build_shell()
        self.show_page("dashboard")
        self.refresh_all()

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        themes = set(style.theme_names())
        if "clam" in themes:
            style.theme_use("clam")
            
        style.configure(".", font=("Microsoft YaHei UI", 10))
        style.configure("TFrame", background="#f7f8fb")
        style.configure("Card.TFrame", background="#ffffff", relief="flat")
        style.configure("Sidebar.TFrame", background="#ffffff")
        style.configure("Title.TLabel", background="#f7f8fb", foreground="#1f2329", font=("Microsoft YaHei UI", 20, "bold"))
        style.configure("Subtitle.TLabel", background="#f7f8fb", foreground="#646a73", font=("Microsoft YaHei UI", 10))
        style.configure("CardTitle.TLabel", background="#ffffff", foreground="#1f2329", font=("Microsoft YaHei UI", 12, "bold"))
        style.configure("Muted.TLabel", background="#ffffff", foreground="#646a73")
        style.configure("SidebarTitle.TLabel", background="#ffffff", foreground="#1f2329", font=("Microsoft YaHei UI", 16, "bold"))
        style.configure("SidebarSub.TLabel", background="#ffffff", foreground="#646a73", font=("Microsoft YaHei UI", 9))
        
        # Modern Button Styles
        style.configure("TButton", background="#ffffff", foreground="#1f2329", bordercolor="#d0d3d6", lightcolor="#ffffff", darkcolor="#ffffff", borderwidth=1, focuscolor="#ffffff", padding=(12, 6))
        style.map("TButton", background=[("active", "#f2f3f5"), ("pressed", "#e5e6eb")])
        
        style.configure("Primary.TButton", background="#3370ff", foreground="#ffffff", bordercolor="#3370ff", lightcolor="#3370ff", darkcolor="#3370ff", borderwidth=1, focuscolor="#3370ff", padding=(12, 6))
        style.map("Primary.TButton", background=[("active", "#1e5def"), ("pressed", "#1043c7")])
        
        style.configure("Treeview", rowheight=34, fieldbackground="#ffffff", background="#ffffff")
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 10, "bold"), background="#f7f9fc", foreground="#646a73")

    def _build_shell(self) -> None:
        self.sidebar = ttk.Frame(self, style="Sidebar.TFrame", width=230)
        self.sidebar.pack(side=tk.LEFT, fill=tk.Y)
        self.sidebar.pack_propagate(False)

        brand = ttk.Frame(self.sidebar, style="Sidebar.TFrame")
        brand.pack(fill=tk.X, padx=22, pady=(24, 18))
        ttk.Label(brand, text="AgentFix", style="SidebarTitle.TLabel").pack(anchor=tk.W)
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

    def make_header(self, parent, title: str, subtitle: str) -> ttk.Frame:
        header = ttk.Frame(parent)
        header.pack(fill=tk.X, padx=26, pady=(24, 16))
        ttk.Label(header, text=title, style="Title.TLabel").pack(anchor=tk.W)
        ttk.Label(header, text=subtitle, style="Subtitle.TLabel").pack(anchor=tk.W, pady=(6, 0))
        return header

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
        header = self.make_header(page, "总览", "查看 AgentFix 当前配置风险、修复成果和最近事故")
        ttk.Button(header, text="刷新", style="Primary.TButton", command=self.refresh_all).pack(side=tk.RIGHT)

        metrics = ttk.Frame(page)
        metrics.pack(fill=tk.X, padx=26, pady=(0, 8))
        self.metric_labels: dict[str, tk.Label] = {}
        for key, label in [
            ("total", "总事件"),
            ("fixed", "已修复 PR"),
            ("reported", "只报告"),
            ("ignored", "已忽略"),
        ]:
            card = tk.Frame(metrics, bg="#ffffff", highlightthickness=1, highlightbackground="#e5e8ef")
            card.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 12))
            tk.Label(card, text=label, bg="#ffffff", fg="#646a73", font=("Microsoft YaHei UI", 10)).pack(anchor=tk.W, padx=16, pady=(14, 4))
            value = tk.Label(card, text="0", bg="#ffffff", fg="#1f2329", font=("Microsoft YaHei UI", 24, "bold"))
            value.pack(anchor=tk.W, padx=16, pady=(0, 14))
            self.metric_labels[key] = value

        card = self.make_card(page, "最近事故")
        columns = ("incident_id", "target", "status", "disposition", "message")
        self.dashboard_tree = ttk.Treeview(card, columns=columns, show="headings", height=8)
        for col, text, width in [
            ("incident_id", "事件 ID", 180),
            ("target", "目标服务", 160),
            ("status", "状态", 120),
            ("disposition", "处理结论", 130),
            ("message", "摘要", 520),
        ]:
            self.dashboard_tree.heading(col, text=text)
            self.dashboard_tree.column(col, width=width, stretch=col == "message")
        self.dashboard_tree.pack(fill=tk.BOTH, expand=True, padx=16, pady=16)

    def _build_incidents_page(self) -> None:
        page = self.pages["incidents"]
        header = self.make_header(page, "事故记录", "查看每次事件的分诊结论、工具调用、PR 和人工处理建议")
        ttk.Button(header, text="刷新记录", style="Primary.TButton", command=self.refresh_records).pack(side=tk.RIGHT)

        body = ttk.Frame(page)
        body.pack(fill=tk.BOTH, expand=True, padx=26, pady=8)
        left_outer = tk.Frame(body, bg="#ffffff", highlightthickness=1, highlightbackground="#e5e8ef")
        left_outer.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 12))
        left = ttk.Frame(left_outer, style="Card.TFrame")
        left.pack(fill=tk.BOTH, expand=True)

        filters = ttk.Frame(left, style="Card.TFrame")
        filters.pack(fill=tk.X, padx=14, pady=12)
        self.incident_query = tk.StringVar()
        self.incident_status = tk.StringVar(value="全部")
        ttk.Entry(filters, textvariable=self.incident_query, width=32).pack(side=tk.LEFT)
        ttk.Combobox(
            filters,
            textvariable=self.incident_status,
            values=["全部", "pr_created", "validated", "reported", "ignored", "needs_more_context", "needs_manual_intervention"],
            width=22,
            state="readonly",
        ).pack(side=tk.LEFT, padx=8)
        ttk.Button(filters, text="筛选", command=self.render_incident_table).pack(side=tk.LEFT)

        columns = ("incident_id", "target", "status", "disposition", "updated_at")
        self.incidents_tree = ttk.Treeview(left, columns=columns, show="headings")
        for col, text, width in [
            ("incident_id", "事件 ID", 180),
            ("target", "目标服务", 150),
            ("status", "状态", 120),
            ("disposition", "结论", 120),
            ("updated_at", "更新时间", 150),
        ]:
            self.incidents_tree.heading(col, text=text)
            self.incidents_tree.column(col, width=width, stretch=col == "incident_id")
        self.incidents_tree.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 14))
        self.incidents_tree.bind("<<TreeviewSelect>>", self.on_record_selected)

        right_outer = tk.Frame(body, bg="#ffffff", highlightthickness=1, highlightbackground="#e5e8ef", width=430)
        right_outer.pack(side=tk.RIGHT, fill=tk.BOTH)
        right_outer.pack_propagate(False)
        right = ttk.Frame(right_outer, style="Card.TFrame")
        right.pack(fill=tk.BOTH, expand=True)
        ttk.Label(right, text="事故详情", style="CardTitle.TLabel").pack(anchor=tk.W, padx=16, pady=(14, 8))
        ttk.Separator(right).pack(fill=tk.X)
        self.record_detail = tk.Text(
            right,
            wrap=tk.WORD,
            bd=0,
            bg="#ffffff",
            fg="#1f2329",
            font=("Microsoft YaHei UI", 10),
            padx=16,
            pady=14,
        )
        self.record_detail.pack(fill=tk.BOTH, expand=True)

    def _build_config_page(self) -> None:
        page = self.pages["config"]
        header = self.make_header(page, "配置中心", "编辑模型、密钥、Planner、风控和运行参数")
        ttk.Button(header, text="保存到 agentfix.local.yaml", style="Primary.TButton", command=self.save_global_config).pack(side=tk.RIGHT)

        scroll = ScrollFrame(page)
        scroll.pack(fill=tk.BOTH, expand=True, padx=26, pady=(0, 16))
        body = scroll.body

        self._add_section(body, "模型与密钥")
        self._add_entry(body, ("openai", "model"), "模型名称")
        self._add_secret(body, ("openai", "api_key"), "模型 / ARK API Key")
        self._add_entry(body, ("openai", "base_url"), "模型接口地址")
        self._add_entry(body, ("openai", "transport"), "模型调用方式")
        self._add_entry(body, ("openai", "analysis_reasoning_effort"), "分析推理强度")
        self._add_entry(body, ("openai", "patch_reasoning_effort"), "修复推理强度")
        self._add_secret(body, ("github", "token"), "GitHub 访问令牌")
        self._add_entry(body, ("github", "api_base_url"), "GitHub API 地址")
        self._add_secret(body, ("feishu", "webhook_url"), "飞书机器人地址")
        self._add_secret(body, ("feishu", "webhook_secret"), "飞书签名密钥")

        self._add_section(body, "Agent Planner 与风控")
        self._add_check(body, ("agent", "planner", "enabled"), "启用环境感知 Planner")
        self._add_entry(body, ("agent", "planner", "max_steps"), "Planner 最大工具步数")
        self._add_text(body, ("agent", "planner", "allowed_tools"), "允许调用的工具，每行一个")
        self._add_entry(body, ("guardrails", "max_changed_files"), "最大修改文件数")
        self._add_entry(body, ("guardrails", "max_patch_lines"), "最大补丁行数")
        self._add_entry(body, ("guardrails", "min_confidence"), "最小分析置信度")
        self._add_text(body, ("guardrails", "ignored_paths"), "忽略路径，每行一个")
        self._add_check(body, ("agent", "report", "notify_on_ignored"), "忽略事件也发送飞书")
        self._add_check(body, ("agent", "report", "notify_on_report_only"), "只报告事件发送飞书")
        self._add_check(body, ("agent", "report", "notify_on_needs_more_context"), "上下文不足事件发送飞书")

        self._add_section(body, "运行与验证")
        self._add_entry(body, ("runtime", "artifact_root"), "运行产物目录")
        self._add_entry(body, ("runtime", "max_repair_attempts"), "最大修复尝试次数")
        self._add_entry(body, ("server", "host"), "Agent 服务监听地址")
        self._add_entry(body, ("server", "port"), "Agent 服务端口")
        self._add_entry(body, ("server", "poll_interval_seconds"), "日志轮询间隔秒")
        self._add_entry(body, ("server", "state_path"), "事件去重数据库")
        self._add_entry(body, ("validation", "python_executable"), "Python 可执行文件")
        self._add_entry(body, ("validation", "service_start_timeout_seconds"), "服务启动超时秒")
        self._add_entry(body, ("validation", "healthcheck_timeout_seconds"), "健康检查超时秒")
        self._add_entry(body, ("validation", "healthcheck_interval_seconds"), "健康检查间隔秒")
        self._add_text(body, ("validation", "test_commands"), "全局测试命令，每行一个")
        self._add_entry(body, ("records", "root"), "修复记录目录")
        self._add_check(body, ("records", "auto_commit"), "records 自动 commit")
        self.load_global_form()

    def _build_targets_page(self) -> None:
        page = self.pages["targets"]
        header = self.make_header(page, "目标服务管理", "配置被 AgentFix 监控和自动修复的本地服务仓库")
        ttk.Button(header, text="保存目标服务", style="Primary.TButton", command=self.save_current_target).pack(side=tk.RIGHT)
        ttk.Button(header, text="新增目标服务", command=self.add_target).pack(side=tk.RIGHT, padx=(0, 8))

        scroll = ScrollFrame(page)
        scroll.pack(fill=tk.BOTH, expand=True, padx=26, pady=(0, 16))
        body = scroll.body
        card = self.make_card(body, expand=False)

        top = ttk.Frame(card, style="Card.TFrame")
        top.pack(fill=tk.X, padx=16, pady=16)
        ttk.Label(top, text="选择目标服务", style="Muted.TLabel").pack(side=tk.LEFT)
        self.target_selector = ttk.Combobox(top, textvariable=self.current_target_name, state="readonly", width=34)
        self.target_selector.pack(side=tk.LEFT, padx=10)
        self.target_selector.bind("<<ComboboxSelected>>", lambda _event: self.load_target_form())
        ttk.Button(top, text="删除", command=self.delete_target).pack(side=tk.RIGHT)
        ttk.Button(top, text="复制", command=self.duplicate_target).pack(side=tk.RIGHT, padx=8)

        form = ttk.Frame(card, style="Card.TFrame")
        form.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 16))
        self._target_entry(form, "name", "目标服务名称")
        self._target_entry(form, "repo_full_name", "GitHub 仓库名")
        self._target_path_entry(form, "repo_path", "本地仓库路径")
        self._target_entry(form, "base_branch", "PR 目标分支")
        self._target_entry(form, "working_dir", "工作目录")
        self._target_entry(form, "service_log_file", "服务日志文件")
        self._target_entry(form, "start_command", "服务启动命令")
        self._target_entry(form, "healthcheck_url", "健康检查地址")
        self._target_text(form, "test_commands", "测试命令，每行一个")
        self._target_text(form, "verification_requests", "接口验证请求（JSON）")
        self._target_check(form, "generated_tests.enabled", "启用自动生成回归测试")
        self._target_entry(form, "generated_tests.framework", "生成测试框架")
        self._target_entry(form, "generated_tests.max_files", "生成测试最大文件数")
        self._target_check(form, "generated_tests.require_prefix_failure", "要求修复前失败")
        self._target_check(form, "generated_tests.commit_when_stable", "稳定后提交生成测试")
        self._target_check(form, "generated_tests.fallback_to_v2_on_failure", "生成测试失败时继续既有验证")
        self.refresh_target_selector()

    def _build_manual_page(self) -> None:
        page = self.pages["manual"]
        self.make_header(page, "手动运行", "直接选择本地仓库和日志文件，触发一次 AgentFix 修复")
        card = self.make_card(page, "运行参数")
        
        # Add background service toggle
        bg_row = ttk.Frame(card)
        bg_row.pack(fill=tk.X, padx=16, pady=6)
        ttk.Label(bg_row, text="守护模式", width=26, style="Subtitle.TLabel").pack(side=tk.LEFT)
        bg_btn = self._make_check(bg_row, self.background_service_enabled, "关闭窗口后，后台常驻监听 (Agent Serve)")
        
        def toggle_service():
            if not self.background_service_enabled.get():
                self.stop_background_service()
                
        bg_btn.config(command=lambda: [self.background_service_enabled.set(not self.background_service_enabled.get()), self._refresh_checks(), toggle_service()])
        bg_btn.pack(side=tk.LEFT)
        
        ttk.Separator(card).pack(fill=tk.X, pady=8)
        
        self.manual_repo = tk.StringVar()
        self.manual_log = tk.StringVar()
        self.manual_branch = tk.StringVar(value="main")
        self.manual_no_pr = tk.BooleanVar(value=True)
        self._row(card, "目标仓库", self.manual_repo, browse=lambda: self._browse_dir(self.manual_repo))
        self._row(card, "日志文件", self.manual_log, browse=lambda: self._browse_file(self.manual_log))
        self._row(card, "PR 目标分支", self.manual_branch)
        self._make_check(card, self.manual_no_pr, "只验证，不创建 PR").pack(anchor=tk.W, padx=16, pady=8)
        ttk.Button(card, text="开始运行", style="Primary.TButton", command=self.run_manual).pack(anchor=tk.W, padx=16, pady=10)
        self.manual_output = tk.Text(card, height=14, bg="#1f2329", fg="#dfe3eb", insertbackground="#ffffff", font=("Cascadia Mono", 10))
        self.manual_output.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 16))

    def _add_section(self, parent, title: str) -> None:
        frame = tk.Frame(parent, bg="#ffffff", highlightthickness=1, highlightbackground="#e5e8ef")
        frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(frame, text=title, style="CardTitle.TLabel").pack(anchor=tk.W, padx=16, pady=(12, 6))

    def _row(self, parent, label: str, variable: tk.StringVar, browse=None, show: str | None = None) -> ttk.Entry:
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, padx=16, pady=6)
        ttk.Label(row, text=label, width=26, style="Subtitle.TLabel").pack(side=tk.LEFT)
        entry = ttk.Entry(row, textvariable=variable, show=show or "")
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        if browse:
            ttk.Button(row, text="选择", command=browse).pack(side=tk.LEFT, padx=(8, 0))
        return entry

    def _add_entry(self, parent, path: tuple[str, ...], label: str) -> None:
        var = tk.StringVar()
        self.form_vars[path] = var
        self._row(parent, label, var)

    def _add_secret(self, parent, path: tuple[str, ...], label: str) -> None:
        var = tk.StringVar()
        self.form_vars[path] = var
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, padx=16, pady=6)
        ttk.Label(row, text=label, width=26, style="Subtitle.TLabel").pack(side=tk.LEFT)
        entry = ttk.Entry(row, textvariable=var, show="*")
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        button = ttk.Button(row, text="预览", width=8, command=lambda p=path: self.toggle_secret_preview(p))
        button.pack(side=tk.LEFT, padx=(8, 0))
        self.secret_entries[path] = entry
        self.secret_buttons[path] = button

    def _add_text(self, parent, path: tuple[str, ...], label: str) -> None:
        ttk.Label(parent, text=label, style="Subtitle.TLabel").pack(anchor=tk.W, padx=16, pady=(10, 4))
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

    def _target_path_entry(self, parent, key: str, label: str) -> None:
        var = tk.StringVar()
        self.target_vars[key] = var
        self._row(parent, label, var, browse=lambda: self._browse_dir(var))

    def _target_text(self, parent, key: str, label: str) -> None:
        ttk.Label(parent, text=label, style="Subtitle.TLabel").pack(anchor=tk.W, padx=16, pady=(10, 4))
        text = tk.Text(parent, height=5, bg="#ffffff", fg="#1f2329", relief=tk.SOLID, bd=1, font=("Cascadia Mono", 10))
        text.pack(fill=tk.X, padx=16, pady=(0, 8))
        self.target_vars[key] = text

    def _target_check(self, parent, key: str, label: str) -> None:
        var = tk.BooleanVar()
        self.target_vars[key] = var
        self._make_check(parent, var, label).pack(anchor=tk.W, padx=16, pady=6)

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
                button.configure(text=f"☑  {label} (已开启)", bg="#edf3ff", fg="#3370ff", highlightbackground="#3370ff")
            else:
                button.configure(text=f"☐  {label} (未开启)", bg="#ffffff", fg="#646a73", highlightbackground="#e5e8ef")

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
        self.base_config = load_yaml(BASE_CONFIG)
        self.local_config = load_yaml(LOCAL_CONFIG)
        self.config_data = deep_merge(self.base_config, self.local_config)

    def save_local_config(self) -> None:
        with LOCAL_CONFIG.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(self.config_data, handle, allow_unicode=True, sort_keys=False)

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
        self.metric_labels["fixed"].configure(text=str(sum(1 for item in self.records if item.get("status") == "pr_created")))
        self.metric_labels["reported"].configure(text=str(sum(1 for item in self.records if item.get("status") == "reported")))
        self.metric_labels["ignored"].configure(text=str(sum(1 for item in self.records if item.get("status") == "ignored")))
        for row in self.dashboard_tree.get_children():
            self.dashboard_tree.delete(row)
        for item in self.records[:12]:
            self.dashboard_tree.insert("", tk.END, values=self._record_values(item, include_message=True))

    def render_incident_table(self) -> None:
        query = self.incident_query.get().strip().lower() if hasattr(self, "incident_query") else ""
        status_filter = self.incident_status.get() if hasattr(self, "incident_status") else "全部"
        for row in self.incidents_tree.get_children():
            self.incidents_tree.delete(row)
        for item in self.records:
            if status_filter != "全部" and item.get("status") != status_filter:
                continue
            searchable = json.dumps(item, ensure_ascii=False).lower()
            if query and query not in searchable:
                continue
            self.incidents_tree.insert("", tk.END, iid=item.get("incident_id"), values=self._record_values(item))

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
        self.record_detail.configure(state=tk.NORMAL)
        self.record_detail.delete("1.0", tk.END)
        data = self.current_record or {}
        rr = data.get("repair_result") or {}
        summary = data.get("message", "")
        decision_reason = data.get("decision_reason") or rr.get("decision_reason")
        if decision_reason and decision_reason not in summary:
            summary = f"{summary}（处理判断：{decision_reason}）"
        analysis = rr.get("analysis") or {}
        repair_plan = analysis.get("repair_plan") or []
        repair_plan_lines = [f"- {item}" for item in repair_plan] if repair_plan else ["- 无"]
        generated_test = rr.get("generated_test") or {}
        generated_test_lines = self._generated_test_detail_lines(generated_test)
        lines = [
            f"事件 ID: {data.get('incident_id', '')}",
            f"目标服务: {data.get('target', '')}",
            f"状态: {status_label(data.get('status', ''))}",
            f"处理结论: {disposition_label(data.get('disposition') or rr.get('disposition'))}",
            f"根因类型: {root_cause_label(data.get('root_cause_type') or rr.get('root_cause_type'))}",
            f"风险等级: {risk_label(data.get('risk_level') or rr.get('risk_level'))}",
            f"PR: {data.get('pr_url') or rr.get('pr_url') or '未创建'}",
            "",
            "摘要:",
            summary,
            "",
            "修复思路:",
            *repair_plan_lines,
            "",
            "自动生成测试说明:",
            *generated_test_lines,
            "",
            "证据:",
            *[f"- {item}" for item in (data.get("evidence") or rr.get("evidence") or [])],
            "",
            "人工处理建议:",
            *[f"- {item}" for item in (data.get("human_resolution_steps") or rr.get("human_resolution_steps") or ["无"])],
            "",
            "工具调用:",
        ]
        for tool in data.get("tool_calls", []):
            lines.append(f"- {tool.get('name')}: {tool.get('status')} - {tool.get('summary')}")
        self.record_detail.insert(tk.END, "\n".join(lines))
        self.record_detail.configure(state=tk.DISABLED)

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
                widget.set("" if value is None else str(value))
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
        except ValueError as exc:
            messagebox.showerror("保存失败", f"数字字段格式错误：{exc}")
            return
        messagebox.showinfo("保存成功", "配置已写入 agentfix.local.yaml。服务 host/port 等改动重启后完全生效。")

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
        try:
            verification_requests = json.loads(self.target_vars["verification_requests"].get("1.0", tk.END).strip() or "[]")
        except json.JSONDecodeError as exc:
            messagebox.showerror("保存失败", f"接口验证请求 JSON 格式错误：{exc}")
            return
        try:
            generated_max_files = int(self.target_vars["generated_tests.max_files"].get().strip() or "1")
        except ValueError as exc:
            messagebox.showerror("保存失败", f"生成测试最大文件数必须是整数：{exc}")
            return
        target = {
            "repo_full_name": self.target_vars["repo_full_name"].get().strip() or None,
            "repo_path": self.target_vars["repo_path"].get().strip(),
            "base_branch": self.target_vars["base_branch"].get().strip() or "main",
            "working_dir": self.target_vars["working_dir"].get().strip() or ".",
            "service_log_file": self.target_vars["service_log_file"].get().strip() or None,
            "start_command": self.target_vars["start_command"].get().strip() or None,
            "healthcheck_url": self.target_vars["healthcheck_url"].get().strip() or None,
            "test_commands": [line.strip() for line in self.target_vars["test_commands"].get("1.0", tk.END).splitlines() if line.strip()],
            "verification_requests": verification_requests,
            "generated_tests": {
                "enabled": self.target_vars["generated_tests.enabled"].get(),
                "framework": self.target_vars["generated_tests.framework"].get().strip() or "auto",
                "max_files": generated_max_files,
                "require_prefix_failure": self.target_vars["generated_tests.require_prefix_failure"].get(),
                "commit_when_stable": self.target_vars["generated_tests.commit_when_stable"].get(),
                "fallback_to_v2_on_failure": self.target_vars["generated_tests.fallback_to_v2_on_failure"].get(),
            },
        }
        self.config_data.setdefault("targets", {})
        if old_name and old_name != name:
            self.config_data["targets"].pop(old_name, None)
        self.config_data["targets"][name] = target
        self.current_target_name.set(name)
        self.save_local_config()
        self.refresh_target_selector()
        messagebox.showinfo("保存成功", "目标服务配置已写入 agentfix.local.yaml。")

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
                "fallback_to_v2_on_failure": True,
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
        self.refresh_target_selector()

    def run_manual(self) -> None:
        repo = self.manual_repo.get().strip()
        log_file = self.manual_log.get().strip()
        if not repo or not log_file:
            messagebox.showerror("无法运行", "请先选择目标仓库和日志文件。")
            return
        command = [
            sys.executable,
            "-m",
            "agentfix",
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
            process = subprocess.run(command, capture_output=True, text=True, check=False)
            output = process.stdout + "\n" + process.stderr
            self.manual_output.after(0, lambda: self.manual_output.insert(tk.END, output))

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
        image = Image.new('RGB', (64, 64), color=(44, 62, 80))
        dc = ImageDraw.Draw(image)
        dc.rectangle([(16, 16), (48, 48)], fill=(46, 204, 113))
        return image

    def hide_window(self):
        # If background service is NOT enabled, clicking X should just quit the app normally
        if not self.background_service_enabled.get():
            self.quit_window()
            return
            
        # Otherwise, hide to tray
        self.withdraw()
        if not self.icon:
            menu = pystray.Menu(
                pystray.MenuItem('显示面板 (Show)', self.show_window, default=True),
                pystray.MenuItem('完全退出 (Quit)', self.quit_window)
            )
            self.icon = pystray.Icon("AgentFix", self.create_image(), "AgentFix 监控守护中", menu)
            
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
            
            # Start background service if not already started
            if not self.agent_process:
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
        if self.agent_process:
            try:
                self.agent_process.terminate()
                self.agent_process.wait(timeout=3)
            except Exception:
                self.agent_process.kill()
            self.agent_process = None

    def start_background_service(self):
        def run_service():
            try:
                env = os.environ.copy()
                src_path = os.path.abspath("src")
                if "PYTHONPATH" in env:
                    env["PYTHONPATH"] = f"{src_path}{os.pathsep}{env['PYTHONPATH']}"
                else:
                    env["PYTHONPATH"] = src_path
                    
                self.agent_process = subprocess.Popen(
                    [sys.executable, "-m", "agentfix", "serve"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=env,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
                )
            except Exception as e:
                print(f"Failed to start background service: {e}")
                
        threading.Thread(target=run_service, daemon=True).start()


if __name__ == "__main__":
    app = AgentFixGUI()
    app.mainloop()
