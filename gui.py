import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import subprocess
import threading
import sys
import os
import yaml

class AgentFixGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AgentFix Console")
        self.geometry("1100x750")
        
        # Configure styles
        style = ttk.Style(self)
        if 'clam' in style.theme_names():
            style.theme_use('clam')
        
        # Load config
        self.config_file = "agentfix.yaml"
        self.local_config_file = "agentfix.local.yaml"
        self.config_data = {}
        self.local_config_data = {}
        self.load_config()

        # Layout: Left Menu and Right Content
        self.paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        self.paned.pack(fill=tk.BOTH, expand=True)

        self.left_frame = tk.Frame(self.paned, width=320, bg="#2c3e50")
        self.right_frame = ttk.Frame(self.paned)
        self.paned.add(self.left_frame, weight=0)
        self.paned.add(self.right_frame, weight=1)

        # Left Menu
        tk.Label(self.left_frame, text="AgentFix\n控制台", font=("Arial", 16, "bold"), bg="#2c3e50", fg="white", pady=20).pack(fill=tk.X)
        
        self.menu_list = tk.Listbox(self.left_frame, font=("Arial", 12), bg="#2c3e50", fg="#bdc3c7", selectbackground="#34495e", selectforeground="white", relief=tk.FLAT, borderwidth=0, highlightthickness=0)
        self.menu_list.pack(fill=tk.BOTH, expand=True, padx=0, pady=5)
        
        menu_items = ["总览看板 (Dashboard)", "事故列表 (Incidents)", "配置中心 (Configuration)", "目标管理 (Targets)", "系统状态 (System)", "手动触发修复 (Manual Run)"]
        for item in menu_items:
            self.menu_list.insert(tk.END, "  " + item)
            
        self.menu_list.bind("<<ListboxSelect>>", self.on_menu_select)
        
        # Right Content Frames
        self.frames = {}
        self.frames["  总览看板 (Dashboard)"] = self.create_dashboard_frame()
        self.frames["  事故列表 (Incidents)"] = self.create_incidents_frame()
        self.frames["  配置中心 (Configuration)"] = self.create_config_frame()
        self.frames["  目标管理 (Targets)"] = self.create_targets_frame()
        self.frames["  系统状态 (System)"] = self.create_system_frame()
        self.frames["  手动触发修复 (Manual Run)"] = self.create_run_frame()

        # Show default
        self.menu_list.selection_set(0)
        self.on_menu_select(None)

        # Force pane sash position
        self.after(100, lambda: self.paned.sashpos(0, 250))

    def load_config(self):
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, "r", encoding="utf-8") as f:
                    self.config_data = yaml.safe_load(f) or {}
            else:
                self.config_data = {}
        except Exception as e:
            messagebox.showwarning("警告 (Warning)", f"无法加载配置 {self.config_file}: {e}")
            self.config_data = {}
            
        try:
            if os.path.exists(self.local_config_file):
                with open(self.local_config_file, "r", encoding="utf-8") as f:
                    self.local_config_data = yaml.safe_load(f) or {}
            else:
                self.local_config_data = {}
        except Exception as e:
            self.local_config_data = {}
            
        return self.config_data

    def save_config(self):
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                yaml.dump(self.config_data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
            
            if self.local_config_data:
                with open(self.local_config_file, "w", encoding="utf-8") as f:
                    yaml.dump(self.local_config_data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
                    
            messagebox.showinfo("成功 (Success)", "配置保存成功！(Configuration saved successfully!)")
        except Exception as e:
            messagebox.showerror("错误 (Error)", f"无法保存配置: {e}")

    def on_menu_select(self, event):
        selection = self.menu_list.curselection()
        if not selection:
            return
        selected_item = self.menu_list.get(selection[0])
        
        for frame in self.frames.values():
            frame.pack_forget()
            
        self.frames[selected_item].pack(fill=tk.BOTH, expand=True)

    def create_dashboard_frame(self):
        frame = ttk.Frame(self.right_frame)
        ttk.Label(frame, text="总览看板 (Dashboard)", font=("Arial", 18, "bold")).pack(pady=15, padx=20, anchor=tk.W)

        # Create a container frame that handles vertical expansion gracefully
        main_container = ttk.Frame(frame)
        main_container.pack(fill=tk.BOTH, expand=True, padx=20, pady=5)

        # Top KPI Cards
        kpi_frame = ttk.Frame(main_container)
        kpi_frame.pack(fill=tk.X, pady=5)
        
        self.kpi_labels = {}
        kpi_items = [
            ("今日事故数\n(Today Incidents)", "0", "today_incidents"),
            ("修复成功率\n(Success Rate)", "0%", "success_rate"),
            ("待人工确认\n(Pending Manual)", "0", "pending_manual"),
            ("Draft PR 数\n(Draft PRs)", "0", "draft_prs")
        ]
        
        for i, (title, default_val, key) in enumerate(kpi_items):
            card = tk.Frame(kpi_frame, bg="#ecf0f1", padx=15, pady=10, relief=tk.FLAT)
            card.grid(row=0, column=i, padx=5, sticky="ew")
            kpi_frame.grid_columnconfigure(i, weight=1)
            
            tk.Label(card, text=title, font=("Arial", 10), bg="#ecf0f1", fg="#7f8c8d").pack(anchor=tk.W)
            val_label = tk.Label(card, text=default_val, font=("Arial", 18, "bold"), bg="#ecf0f1", fg="#2c3e50")
            val_label.pack(anchor=tk.W, pady=5)
            self.kpi_labels[key] = val_label

        # Runtime Status
        status_frame = ttk.Frame(main_container)
        status_frame.pack(fill=tk.X, pady=15)
        ttk.Label(status_frame, text="运行状态 (Runtime Status)", font=("Arial", 12, "bold")).pack(anchor=tk.W, pady=5)
        
        status_inner = ttk.Frame(status_frame)
        status_inner.pack(fill=tk.X)
        
        self.status_labels = {}
        status_items = [
            ("Agent 服务 (Agent Service)", "status_agent"),
            ("Webhook 状态 (Webhook)", "status_webhook"),
            ("Watch 状态 (Watch)", "status_watch")
        ]
        
        for i, (title, key) in enumerate(status_items):
            tk.Label(status_inner, text=title + ": ", font=("Arial", 10)).grid(row=0, column=i*2, sticky=tk.W, padx=(0, 5))
            lbl = tk.Label(status_inner, text="Unknown", font=("Arial", 10, "bold"), fg="gray")
            lbl.grid(row=0, column=i*2+1, sticky=tk.W, padx=(0, 20))
            self.status_labels[key] = lbl

        # Recent Repair Records Table (Give this expand=True so it takes up remaining vertical space)
        table_frame = ttk.Frame(main_container)
        table_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        ttk.Label(table_frame, text="最近修复记录 (Recent Repair Records)", font=("Arial", 12, "bold")).pack(anchor=tk.W, pady=5)
        
        columns = ("incident_id", "target", "status", "changed_files", "pr_url")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=5)
        self.tree.heading("incident_id", text="事故 ID (Incident ID)")
        self.tree.heading("target", text="目标 (Target)")
        self.tree.heading("status", text="状态 (Status)")
        self.tree.heading("changed_files", text="修改文件数 (Changed Files)")
        self.tree.heading("pr_url", text="PR 链接 (PR URL)")
        
        self.tree.column("incident_id", width=150, minwidth=150)
        self.tree.column("target", width=120, minwidth=120)
        self.tree.column("status", width=120, minwidth=120)
        self.tree.column("changed_files", width=100, anchor=tk.CENTER, minwidth=100)
        self.tree.column("pr_url", width=400, minwidth=400)

        tree_scroll_y = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        tree_scroll_x = ttk.Scrollbar(table_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscroll=tree_scroll_y.set, xscroll=tree_scroll_x.set)
        
        tree_scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        tree_scroll_x.pack(side=tk.BOTTOM, fill=tk.X)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Risk Warnings (Keep this at the bottom)
        risk_frame = ttk.Frame(main_container)
        risk_frame.pack(fill=tk.X, pady=10)
        ttk.Label(risk_frame, text="风险提醒 (Risk Warnings)", font=("Arial", 12, "bold")).pack(anchor=tk.W, pady=5)
        self.risk_text = tk.Text(risk_frame, height=2, bg="#fff3cd", fg="#c0392b", font=("Arial", 10), relief=tk.FLAT)
        self.risk_text.pack(fill=tk.X)
        self.risk_text.insert(tk.END, "正在检查... (Checking...)")
        self.risk_text.config(state=tk.DISABLED)

        # Refresh Data
        ttk.Button(main_container, text="刷新数据 (Refresh)", command=self.refresh_dashboard).pack(pady=5)
        
        self.after(500, self.refresh_dashboard)
        return frame

    def refresh_dashboard(self):
        import json
        import glob
        from datetime import datetime

        # Check records directory
        records_root = self.config_data.get("records", {}).get("root", "records")
        records_path = os.path.abspath(records_root)
        
        total_records = 0
        today_incidents = 0
        success_count = 0
        pending_manual = 0
        draft_prs = 0
        
        records_list = []
        today_str = datetime.now().strftime("%Y-%m-%d")

        if os.path.exists(records_path):
            for file_path in glob.glob(os.path.join(records_path, "*.json")):
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        total_records += 1
                        
                        # Date check (assuming file modified time as incident time for simplicity)
                        mod_time = datetime.fromtimestamp(os.path.getmtime(file_path)).strftime("%Y-%m-%d")
                        if mod_time == today_str:
                            today_incidents += 1
                            
                        status = data.get("status", "unknown")
                        if status in ("validated", "pr_created"):
                            success_count += 1
                        if status == "needs_manual_intervention":
                            pending_manual += 1
                        if status == "pr_created":
                            draft_prs += 1
                            
                        records_list.append({
                            "incident_id": data.get("incident_id", ""),
                            "target": data.get("target", ""),
                            "status": status,
                            "changed_files": len(data.get("repair_result", {}).get("changed_files", [])),
                            "pr_url": data.get("pr_url", "None"),
                            "time": os.path.getmtime(file_path)
                        })
                except Exception:
                    pass

        # Update KPIs
        self.kpi_labels["today_incidents"].config(text=str(today_incidents))
        rate = f"{(success_count / total_records * 100):.1f}%" if total_records > 0 else "0%"
        self.kpi_labels["success_rate"].config(text=rate)
        self.kpi_labels["pending_manual"].config(text=str(pending_manual))
        self.kpi_labels["draft_prs"].config(text=str(draft_prs))

        # Update Table
        for row in self.tree.get_children():
            self.tree.delete(row)
            
        records_list.sort(key=lambda x: x["time"], reverse=True)
        for r in records_list[:10]: # show latest 10
            self.tree.insert("", tk.END, values=(r["incident_id"], r["target"], r["status"], r["changed_files"], r["pr_url"]))

        # Update Status
        self.status_labels["status_agent"].config(text="在线 (Online)" if total_records > 0 else "待机 (Standby)", fg="#27ae60")
        self.status_labels["status_webhook"].config(text="未配置 (Not Configured)" if not self.config_data.get("feishu", {}).get("webhook_url_env_var") else "已配置 (Configured)", fg="#e67e22")
        self.status_labels["status_watch"].config(text="活跃 (Active)", fg="#27ae60")

        # Update Risks
        risks = []
        if not os.environ.get(self.config_data.get("openai", {}).get("api_key_env_var", "ARK_API_KEY")):
            risks.append("⚠️ 未检测到 OpenAI API Key 环境变量 (Missing OpenAI API Key)")
        if not os.environ.get(self.config_data.get("github", {}).get("token_env_var", "GITHUB_TOKEN")):
            risks.append("⚠️ 未检测到 GitHub Token 环境变量 (Missing GitHub Token)")
            
        self.risk_text.config(state=tk.NORMAL)
        self.risk_text.delete(1.0, tk.END)
        if risks:
            self.risk_text.insert(tk.END, "\n".join(risks))
        else:
            self.risk_text.insert(tk.END, "✅ 无明显风险，配置良好 (No major risks detected. Configuration is good.)")
            self.risk_text.config(fg="#27ae60", bg="#e8f8f5")
        self.risk_text.config(state=tk.DISABLED)

    def create_targets_frame(self):
        frame = ttk.Frame(self.right_frame)
        ttk.Label(frame, text="目标管理 (Targets)", font=("Arial", 18, "bold")).pack(pady=15, padx=20, anchor=tk.W)

        toolbar = ttk.Frame(frame)
        toolbar.pack(fill=tk.X, padx=20, pady=5)
        ttk.Button(toolbar, text="刷新 (Refresh)", command=self.refresh_targets).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="+ 新增 Target (Add)", command=self.add_target).pack(side=tk.LEFT, padx=10)

        canvas = tk.Canvas(frame, highlightthickness=0)
        scrollbar_y = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        scrollbar_x = ttk.Scrollbar(frame, orient="horizontal", command=canvas.xview)
        self.targets_container = ttk.Frame(canvas)
        
        self.targets_container.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.targets_container, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar_y.set, xscrollcommand=scrollbar_x.set)
        
        scrollbar_y.pack(side="right", fill="y")
        scrollbar_x.pack(side="bottom", fill="x")
        canvas.pack(side="left", fill="both", expand=True, padx=20, pady=10)
        
        self.refresh_targets()
        return frame

    def refresh_targets(self):
        for widget in self.targets_container.winfo_children():
            widget.destroy()
            
        data = self.load_config()
        targets = data.get("targets", {})
        if not targets:
            ttk.Label(self.targets_container, text="暂无配置任何 Target。(No targets configured.)", font=("Arial", 10, "italic"), foreground="gray").pack(pady=20)
            return

        for name, config in targets.items():
            card = ttk.LabelFrame(self.targets_container, text=f"📦 {name}")
            card.pack(fill=tk.X, expand=True, padx=10, pady=10)
            
            # Left Info
            info_frame = ttk.Frame(card)
            info_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=10)
            
            ttk.Label(info_frame, text=f"Repo Full Name: {config.get('repo_full_name', 'N/A')}", font=("Arial", 10)).pack(anchor=tk.W, pady=2)
            ttk.Label(info_frame, text=f"Base Branch: {config.get('base_branch', 'N/A')}", font=("Arial", 10)).pack(anchor=tk.W, pady=2)
            ttk.Label(info_frame, text=f"Local Path: {config.get('repo_path', 'N/A')}", font=("Arial", 10)).pack(anchor=tk.W, pady=2)
            ttk.Label(info_frame, text=f"Log File: {config.get('service_log_file', 'N/A')}", font=("Arial", 10)).pack(anchor=tk.W, pady=2)

            # Right Badges (Status)
            status_frame = ttk.Frame(card)
            status_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=10, pady=10)
            
            has_healthcheck = bool(config.get("healthcheck_url"))
            has_test = bool(config.get("test_commands"))
            has_webhook = bool(config.get("incident_webhook"))

            tk.Label(status_frame, text="✓ 验证已配置" if has_test else "✗ 验证未配置", bg="#d4edda" if has_test else "#f8d7da", fg="#27ae60" if has_test else "#c0392b", padx=8, pady=4, font=("Arial", 9, "bold")).pack(anchor=tk.E, pady=2)
            tk.Label(status_frame, text="✓ Healthcheck 已配置" if has_healthcheck else "✗ Healthcheck 未配置", bg="#d4edda" if has_healthcheck else "#f8d7da", fg="#27ae60" if has_healthcheck else "#c0392b", padx=8, pady=4, font=("Arial", 9, "bold")).pack(anchor=tk.E, pady=2)
            tk.Label(status_frame, text="✓ 支持 Webhook" if has_webhook else "✗ 无 Webhook", bg="#d4edda" if has_webhook else "#e2e3e5", fg="#27ae60" if has_webhook else "#383d41", padx=8, pady=4, font=("Arial", 9, "bold")).pack(anchor=tk.E, pady=2)

            # Bottom Actions
            action_frame = ttk.Frame(card)
            action_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=5)
            ttk.Button(action_frame, text="编辑 (Edit)", command=lambda n=name, c=config: self.edit_target(n, c)).pack(side=tk.RIGHT, padx=5)
            ttk.Button(action_frame, text="复制 (Duplicate)", command=lambda c=config: self.add_target(base_config=c)).pack(side=tk.RIGHT, padx=5)
            ttk.Button(action_frame, text="删除 (Delete)", command=lambda n=name: self.delete_target(n)).pack(side=tk.RIGHT, padx=5)

    def add_target(self, base_config=None):
        self.edit_target("", base_config or {})
        
    def delete_target(self, name):
        if messagebox.askyesno("确认删除", f"确定要删除 Target '{name}' 吗？"):
            if "targets" in self.config_data and name in self.config_data["targets"]:
                del self.config_data["targets"][name]
                self.save_config()
                self.refresh_targets()

    def edit_target(self, old_name, config):
        top = tk.Toplevel(self)
        top.title(f"编辑 Target (Edit Target) - {old_name}" if old_name else "新增 Target (New Target)")
        top.geometry("600x550")
        
        form = ttk.Frame(top)
        form.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        vars_dict = {}
        
        fields = [
            ("Target Name (唯一键)*", "name", old_name),
            ("Repo Full Name (例: owner/repo)*", "repo_full_name", config.get("repo_full_name", "")),
            ("Base Branch", "base_branch", config.get("base_branch", "main")),
            ("Local Repo Path*", "repo_path", config.get("repo_path", "")),
            ("Service Log File*", "service_log_file", config.get("service_log_file", "")),
            ("Healthcheck URL", "healthcheck_url", config.get("healthcheck_url", "")),
        ]
        
        for i, (label, key, val) in enumerate(fields):
            ttk.Label(form, text=label).grid(row=i, column=0, sticky=tk.W, pady=5)
            v = tk.StringVar(value=val)
            vars_dict[key] = v
            ttk.Entry(form, textvariable=v, width=40).grid(row=i, column=1, sticky=tk.W, padx=10, pady=5)
            
        ttk.Label(form, text="Test Commands (用逗号分隔):").grid(row=len(fields), column=0, sticky=tk.W, pady=5)
        test_cmds = config.get("test_commands", [])
        test_cmds_str = ",".join(test_cmds) if isinstance(test_cmds, list) else test_cmds
        tc_var = tk.StringVar(value=test_cmds_str)
        vars_dict["test_commands"] = tc_var
        ttk.Entry(form, textvariable=tc_var, width=40).grid(row=len(fields), column=1, sticky=tk.W, padx=10, pady=5)
        
        def save():
            new_name = vars_dict["name"].get().strip()
            if not new_name:
                messagebox.showerror("Error", "Target Name 不能为空")
                return
                
            new_config = {
                "repo_full_name": vars_dict["repo_full_name"].get().strip(),
                "base_branch": vars_dict["base_branch"].get().strip(),
                "repo_path": vars_dict["repo_path"].get().strip(),
                "service_log_file": vars_dict["service_log_file"].get().strip(),
            }
            
            hc = vars_dict["healthcheck_url"].get().strip()
            if hc: new_config["healthcheck_url"] = hc
            
            tc = vars_dict["test_commands"].get().strip()
            if tc: new_config["test_commands"] = [c.strip() for c in tc.split(",") if c.strip()]
            
            if "targets" not in self.config_data:
                self.config_data["targets"] = {}
                
            if old_name and old_name != new_name and old_name in self.config_data["targets"]:
                del self.config_data["targets"][old_name]
                
            self.config_data["targets"][new_name] = new_config
            self.save_config()
            self.refresh_targets()
            top.destroy()
            
        ttk.Button(form, text="保存 (Save)", command=save).grid(row=10, column=0, columnspan=2, pady=20)

    def create_system_frame(self):
        frame = ttk.Frame(self.right_frame)
        ttk.Label(frame, text="系统状态 (System)", font=("Arial", 18, "bold")).pack(pady=15, padx=20, anchor=tk.W)

        toolbar = ttk.Frame(frame)
        toolbar.pack(fill=tk.X, padx=20, pady=5)
        
        ttk.Button(toolbar, text="重新检测 (Run Doctor)", command=self.refresh_system_status).pack(side=tk.LEFT)

        canvas = tk.Canvas(frame, highlightthickness=0)
        scrollbar_y = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        scrollbar_x = ttk.Scrollbar(frame, orient="horizontal", command=canvas.xview)
        self.sys_container = ttk.Frame(canvas)
        
        self.sys_container.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.sys_container, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar_y.set, xscrollcommand=scrollbar_x.set)
        
        scrollbar_y.pack(side="right", fill="y")
        scrollbar_x.pack(side="bottom", fill="x")
        canvas.pack(side="left", fill="both", expand=True, padx=20, pady=10)
        
        self.refresh_system_status()
        return frame

    def refresh_system_status(self):
        for widget in self.sys_container.winfo_children():
            widget.destroy()
            
        data = self.load_config()
        
        # 1. 凭据状态 (Credentials)
        cred_frame = ttk.LabelFrame(self.sys_container, text="🔑 凭据状态 (Credentials Status)")
        cred_frame.pack(fill=tk.X, expand=True, padx=10, pady=10)
        
        creds = data.get("credentials", {})
        keys_to_check = [
            ("OpenAI API Key", creds.get("openai_api_key_env", "OPENAI_API_KEY")),
            ("GitHub Token", creds.get("github_token_env", "GITHUB_TOKEN")),
            ("Feishu Webhook", creds.get("feishu_webhook_env", "FEISHU_WEBHOOK")),
            ("Feishu Secret", creds.get("feishu_webhook_secret_env", "FEISHU_WEBHOOK_SECRET"))
        ]
        
        missing_creds = 0
        for i, (name, env_var) in enumerate(keys_to_check):
            val = os.getenv(env_var)
            is_ok = bool(val)
            if not is_ok: missing_creds += 1
            
            val_display = "***" if is_ok else "未配置 (Missing)"
            lbl_text = f"{name} ({env_var}): {val_display}"
            color = "#27ae60" if is_ok else "#c0392b"
            tk.Label(cred_frame, text=lbl_text, fg=color, font=("Arial", 10, "bold")).grid(row=i//2, column=i%2, sticky=tk.W, padx=20, pady=5)
            
        # 2. 模型配置 & Guardrails
        mg_frame = ttk.LabelFrame(self.sys_container, text="🧠 模型与防护 (Model & Guardrails)")
        mg_frame.pack(fill=tk.X, expand=True, padx=10, pady=10)
        models = data.get("models", {})
        gr = data.get("guardrails", {})
        ttk.Label(mg_frame, text=f"默认模型 (default_model): {models.get('default_model', 'N/A')}").grid(row=0, column=0, sticky=tk.W, padx=20, pady=5)
        ttk.Label(mg_frame, text=f"分析推理深度 (analysis_reasoning_effort): {models.get('analysis_reasoning_effort', 'N/A')}").grid(row=0, column=1, sticky=tk.W, padx=20, pady=5)
        ttk.Label(mg_frame, text=f"补丁推理深度 (patch_reasoning_effort): {models.get('patch_reasoning_effort', 'N/A')}").grid(row=1, column=0, sticky=tk.W, padx=20, pady=5)
        ttk.Label(mg_frame, text=f"最大修改文件 (max_changed_files): {gr.get('max_changed_files', 'N/A')}").grid(row=1, column=1, sticky=tk.W, padx=20, pady=5)
        ttk.Label(mg_frame, text=f"最大修改行数 (max_patch_lines): {gr.get('max_patch_lines', 'N/A')}").grid(row=2, column=0, sticky=tk.W, padx=20, pady=5)

        # 3. 运行环境 (Runtime Environment)
        env_frame = ttk.LabelFrame(self.sys_container, text="💻 运行环境 (Runtime Environment)")
        env_frame.pack(fill=tk.X, expand=True, padx=10, pady=10)
        
        py_version = sys.version.split()[0]
        ttk.Label(env_frame, text=f"Python 版本 (python_version): {py_version}").grid(row=0, column=0, sticky=tk.W, padx=20, pady=5)
        
        try:
            import agentfix
            agentfix_ok = True
        except ImportError:
            agentfix_ok = False
        
        lbl_text = "AgentFix 模块 (module): " + ("✓ 可用 (Available)" if agentfix_ok else "✗ 不可用 (Unavailable)")
        color = "#27ae60" if agentfix_ok else "#c0392b"
        tk.Label(env_frame, text=lbl_text, fg=color, font=("Arial", 10, "bold")).grid(row=0, column=1, sticky=tk.W, padx=20, pady=5)

        # 4. 服务状态 (Service Status)
        srv_frame = ttk.LabelFrame(self.sys_container, text="🚀 服务状态 (Service Status)")
        srv_frame.pack(fill=tk.X, expand=True, padx=10, pady=10)
        server = data.get("server", {})
        ttk.Label(srv_frame, text=f"主机 (host): {server.get('host', 'N/A')}").grid(row=0, column=0, sticky=tk.W, padx=20, pady=5)
        ttk.Label(srv_frame, text=f"端口 (port): {server.get('port', 'N/A')}").grid(row=0, column=1, sticky=tk.W, padx=20, pady=5)
        ttk.Label(srv_frame, text=f"监听模式 (watch): {server.get('watch', 'False')}").grid(row=1, column=0, sticky=tk.W, padx=20, pady=5)

        # 5. 配置健康度 (Config Health)
        cfg_frame = ttk.LabelFrame(self.sys_container, text="⚙️ 配置健康度 (Config Health)")
        cfg_frame.pack(fill=tk.X, expand=True, padx=10, pady=10)
        
        ttk.Label(cfg_frame, text=f"配置来源 (source): {os.path.abspath(self.config_file)}").grid(row=0, column=0, columnspan=2, sticky=tk.W, padx=20, pady=5)
        
        # Check invalid paths
        invalid_paths = 0
        paths_to_check = [
            data.get("artifacts_dir", ".agentfix-artifacts"),
            data.get("records_dir", "records")
        ]
        for t in data.get("targets", {}).values():
            if t.get("repo_path"):
                paths_to_check.append(t.get("repo_path"))
            
        for p in paths_to_check:
            if p and not os.path.exists(os.path.abspath(p)):
                invalid_paths += 1
                
        ttk.Label(cfg_frame, text=f"缺失凭据数量 (missing_credentials): {missing_creds}", foreground="#c0392b" if missing_creds > 0 else "#27ae60", font=("Arial", 10, "bold")).grid(row=1, column=0, sticky=tk.W, padx=20, pady=5)
        ttk.Label(cfg_frame, text=f"非法路径数量 (invalid_paths): {invalid_paths}", foreground="#c0392b" if invalid_paths > 0 else "#27ae60", font=("Arial", 10, "bold")).grid(row=1, column=1, sticky=tk.W, padx=20, pady=5)

    def create_run_frame(self):
        frame = ttk.Frame(self.right_frame)
        ttk.Label(frame, text="手动触发修复 (Manual Run)", font=("Arial", 18, "bold")).pack(pady=15, padx=20, anchor=tk.W)

        canvas = tk.Canvas(frame, highlightthickness=0)
        scrollbar_y = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        scrollbar_x = ttk.Scrollbar(frame, orient="horizontal", command=canvas.xview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar_y.set, xscrollcommand=scrollbar_x.set)

        scrollbar_y.pack(side="right", fill="y")
        scrollbar_x.pack(side="bottom", fill="x")
        canvas.pack(side="left", fill="both", expand=True)

        form_frame = ttk.Frame(scrollable_frame)
        form_frame.pack(fill=tk.X, padx=20, pady=10)

        repo_var = tk.StringVar()
        log_var = tk.StringVar()

        ttk.Label(form_frame, text="目标仓库路径 (Repository Address):").grid(row=0, column=0, sticky=tk.W, pady=5)
        ttk.Entry(form_frame, textvariable=repo_var, width=70).grid(row=0, column=1, padx=10, pady=5)
        ttk.Button(form_frame, text="浏览... (Browse...)", command=lambda: repo_var.set(filedialog.askdirectory() or repo_var.get())).grid(row=0, column=2, pady=5)

        ttk.Label(form_frame, text="异常日志路径 (Log File Address):").grid(row=1, column=0, sticky=tk.W, pady=5)
        ttk.Entry(form_frame, textvariable=log_var, width=70).grid(row=1, column=1, padx=10, pady=5)
        ttk.Button(form_frame, text="浏览... (Browse...)", command=lambda: log_var.set(filedialog.askopenfilename() or log_var.get())).grid(row=1, column=2, pady=5)

        text_frame = ttk.Frame(scrollable_frame)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        output_text = tk.Text(text_frame, height=20, bg="#f5f5f5", font=("Consolas", 10))
        output_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        text_scroll = ttk.Scrollbar(text_frame, command=output_text.yview)
        text_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        output_text.config(yscrollcommand=text_scroll.set)
        
        def append_text(text):
            output_text.insert(tk.END, text)
            output_text.see(tk.END)

        def run_fix():
            repo = repo_var.get().strip()
            log = log_var.get().strip()
            if not repo or not log:
                messagebox.showerror("Error", "请同时选择目标仓库路径和异常日志路径 (Please select both Repository and Log File)")
                return
            
            run_btn.config(state=tk.DISABLED)
            output_text.delete(1.0, tk.END)
            append_text(f"开始运行 AgentFix... (Running AgentFix...)\n目标仓库 (Repo): {repo}\n异常日志 (Log): {log}\n\n")
            
            def task():
                try:
                    env = os.environ.copy()
                    src_path = os.path.abspath("src")
                    if "PYTHONPATH" in env:
                        env["PYTHONPATH"] = f"{src_path}{os.pathsep}{env['PYTHONPATH']}"
                    else:
                        env["PYTHONPATH"] = src_path
                        
                    process = subprocess.Popen(
                        [sys.executable, "-u", "-m", "agentfix", "run", "--repo", repo, "--log-file", log, "--no-pr"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        bufsize=1,
                        env=env
                    )
                    for line in process.stdout:
                        self.after(0, append_text, line)
                    process.wait()
                    self.after(0, append_text, f"\n运行结束，退出码为 (Process finished with exit code) {process.returncode}\n")
                except Exception as e:
                    self.after(0, append_text, f"\n错误 (Error): {e}\n")
                finally:
                    self.after(0, lambda: run_btn.config(state=tk.NORMAL))

            threading.Thread(target=task, daemon=True).start()

        run_btn = tk.Button(form_frame, text="▶ 运行修复 (Run AgentFix)", command=run_fix, bg="#4CAF50", fg="white", font=("Arial", 11, "bold"), relief=tk.FLAT, padx=10, pady=5)
        run_btn.grid(row=2, column=1, sticky=tk.W, pady=15)

        return frame

    def create_config_frame(self):
        frame = ttk.Frame(self.right_frame)
        
        header_frame = ttk.Frame(frame)
        header_frame.pack(fill=tk.X, padx=20, pady=15)
        ttk.Label(header_frame, text="配置中心 (Configuration)", font=("Arial", 18, "bold")).pack(side=tk.LEFT)
        save_btn = tk.Button(header_frame, text="保存配置 (Save Config)", command=self.save_config_action, bg="#2196F3", fg="white", font=("Arial", 11, "bold"), relief=tk.FLAT, padx=15)
        save_btn.pack(side=tk.RIGHT)

        notebook = ttk.Notebook(frame)
        notebook.pack(fill=tk.BOTH, expand=True, padx=20, pady=5)

        self.config_vars = {}

        # 1. System Config
        sys_frame = ttk.Frame(notebook)
        notebook.add(sys_frame, text="系统配置 (System)")
        self.build_form(sys_frame, [
            ("服务主机名 (server.host)", "server", "host"),
            ("服务端口 (server.port)", "server", "port"),
            ("轮询间隔秒数 (server.poll_interval_seconds)", "server", "poll_interval_seconds"),
            ("状态存储路径 (server.state_path)", "server", "state_path"),
            ("验证用Python路径 (validation.python_executable)", "validation", "python_executable")
        ])

        # 2. Model & Inference
        model_frame = ttk.Frame(notebook)
        notebook.add(model_frame, text="模型与推理 (Model & Inference)")
        self.build_form(model_frame, [
            ("大模型名称 (openai.model)", "openai", "model"),
            ("API 接口地址 (openai.base_url)", "openai", "base_url"),
            ("传输协议 (openai.transport)", "openai", "transport"),
            ("分析推理消耗 (openai.analysis_reasoning_effort)", "openai", "analysis_reasoning_effort"),
            ("补丁推理消耗 (openai.patch_reasoning_effort)", "openai", "patch_reasoning_effort"),
            ("最大允许修改文件数 (guardrails.max_changed_files)", "guardrails", "max_changed_files"),
            ("最大允许补丁行数 (guardrails.max_patch_lines)", "guardrails", "max_patch_lines"),
            ("最低分析置信度 (guardrails.min_confidence)", "guardrails", "min_confidence"),
            ("最大尝试修复次数 (runtime.max_repair_attempts)", "runtime", "max_repair_attempts"),
            ("忽略分析的路径配置 (guardrails.ignored_paths)", "guardrails", "ignored_paths")
        ])

        # 3. Credentials
        cred_frame = ttk.Frame(notebook)
        notebook.add(cred_frame, text="凭据管理 (Credentials)")
        self.build_form(cred_frame, [
            ("OpenAI 环境变量名 (openai.api_key_env_var)", "openai", "api_key_env_var"),
            ("GitHub 环境变量名 (github.token_env_var)", "github", "token_env_var"),
            ("飞书 Webhook 环境变量名 (feishu.webhook_url_env_var)", "feishu", "webhook_url_env_var"),
            ("飞书 Webhook 密钥变量名 (feishu.webhook_secret_env_var)", "feishu", "webhook_secret_env_var"),
            ("OpenAI API Key 值 (openai.api_key)", "openai", "api_key", True),
            ("GitHub Token 值 (github.token)", "github", "token", True),
            ("飞书 Webhook URL (feishu.webhook_url)", "feishu", "webhook_url", True),
            ("飞书 Webhook Secret (feishu.webhook_secret)", "feishu", "webhook_secret", True)
        ])

        # 4. Runtime & Artifacts
        run_art_frame = ttk.Frame(notebook)
        notebook.add(run_art_frame, text="运行与产物 (Runtime)")
        self.build_form(run_art_frame, [
            ("产物存储根目录 (runtime.artifact_root)", "runtime", "artifact_root"),
            ("修复记录根目录 (records.root)", "records", "root"),
            ("是否自动提交记录 (records.auto_commit)", "records", "auto_commit")
        ])

        return frame

    def go_to_system_tab(self):
        self.menu_list.selection_clear(0, tk.END)
        for i in range(self.menu_list.size()):
            if "系统状态" in self.menu_list.get(i):
                self.menu_list.selection_set(i)
                self.on_menu_select(None)
                break

    def build_form(self, parent, fields):
        canvas = tk.Canvas(parent, highlightthickness=0)
        scrollbar_y = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scrollbar_x = ttk.Scrollbar(parent, orient="horizontal", command=canvas.xview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(
                scrollregion=canvas.bbox("all")
            )
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar_y.set, xscrollcommand=scrollbar_x.set)

        scrollbar_y.pack(side="right", fill="y")
        scrollbar_x.pack(side="bottom", fill="x")
        canvas.pack(side="left", fill="both", expand=True, padx=10, pady=10)

        for i, item in enumerate(fields):
            label_text = item[0]
            sec = item[1]
            key = item[2]
            is_secret = item[3] if len(item) > 3 else False

            ttk.Label(scrollable_frame, text=label_text + ":", font=("Arial", 10)).grid(row=i, column=0, sticky=tk.W, padx=10, pady=8)
            
            if is_secret:
                val = self.local_config_data.get(sec, {}).get(key, "")
            else:
                val = self.config_data.get(sec, {}).get(key, "")
            
            if isinstance(val, list):
                val = ", ".join(str(v) for v in val)
                
            var = tk.StringVar(value=str(val))
            self.config_vars[(sec, key)] = (var, is_secret)
            
            entry = ttk.Entry(scrollable_frame, textvariable=var, width=50, font=("Arial", 10))
            if is_secret:
                entry.config(show="*")
            entry.grid(row=i, column=1, padx=10, pady=8, sticky=tk.W)
            
            # Source Badge
            source = "未配置"
            color = "gray"
            if val:
                source = "local.yaml" if is_secret else "agentfix.yaml"
                color = "#27ae60"
            else:
                if is_secret:
                    env_key = f"{key}_env_var"
                    env_name = self.config_data.get(sec, {}).get(env_key, "")
                    if env_name and os.getenv(env_name):
                        source = f"环境变量 ({env_name})"
                        color = "#2980b9"
                elif not is_secret and key in ("host", "port", "model"):
                    source = "系统默认"
                    color = "#f39c12"

            ttk.Label(scrollable_frame, text=f"[{source}]", foreground=color, font=("Arial", 9, "bold")).grid(row=i, column=2, sticky=tk.W, padx=5)

            if is_secret:
                def toggle_show(e=entry):
                    if e.cget("show") == "*":
                        e.config(show="")
                    else:
                        e.config(show="*")
                ttk.Button(scrollable_frame, text="👁", width=3, command=toggle_show).grid(row=i, column=3, padx=5)

    def save_config_action(self):
        for (sec, key), (var, is_secret) in self.config_vars.items():
            target_dict = self.local_config_data if is_secret else self.config_data
            
            if sec not in target_dict:
                target_dict[sec] = {}
            val = var.get().strip()
            
            if val:
                if key == "ignored_paths":
                    val = [v.strip() for v in val.split(",") if v.strip()]
                elif val.lower() == "true":
                    val = True
                elif val.lower() == "false":
                    val = False
                elif val.isdigit():
                    val = int(val)
                else:
                    try:
                        val = float(val)
                    except ValueError:
                        pass
                        
                target_dict[sec][key] = val
            else:
                if key in target_dict.get(sec, {}):
                    del target_dict[sec][key]
                    
        self.save_config()
        self.refresh_system_status()

    def create_incidents_frame(self):
        frame = ttk.Frame(self.right_frame)
        ttk.Label(frame, text="事故列表 (Incidents)", font=("Arial", 18, "bold")).pack(pady=15, padx=20, anchor=tk.W)

        # Filter Frame
        filter_frame = ttk.Frame(frame)
        filter_frame.pack(fill=tk.X, padx=20, pady=5)

        # Row 1 for Filters
        ttk.Label(filter_frame, text="状态 (Status):").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        self.filter_status = ttk.Combobox(filter_frame, values=["全部 (All)", "pr_created", "validated", "needs_manual_intervention", "failed"], width=15)
        self.filter_status.current(0)
        self.filter_status.grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(filter_frame, text="目标 (Target):").grid(row=0, column=2, padx=5, pady=5, sticky=tk.W)
        self.filter_target = ttk.Combobox(filter_frame, values=["全部 (All)"] + list(self.config_data.get("targets", {}).keys()), width=15)
        self.filter_target.current(0)
        self.filter_target.grid(row=0, column=3, padx=5, pady=5)

        ttk.Label(filter_frame, text="来源 (Source):").grid(row=0, column=4, padx=5, pady=5, sticky=tk.W)
        self.filter_source = ttk.Combobox(filter_frame, values=["全部 (All)", "incident_webhook", "manual", "cli"], width=15)
        self.filter_source.current(0)
        self.filter_source.grid(row=0, column=5, padx=5, pady=5)

        # Row 2 for Checkbox and Button to prevent crowding
        self.filter_has_pr = tk.BooleanVar()
        ttk.Checkbutton(filter_frame, text="仅看有 PR (Has PR)", variable=self.filter_has_pr).grid(row=1, column=0, columnspan=2, padx=5, pady=5, sticky=tk.W)

        ttk.Button(filter_frame, text="搜索 / 刷新 (Search)", command=self.load_incidents_data).grid(row=1, column=5, padx=5, pady=5, sticky=tk.E)

        # Table Frame
        table_frame = ttk.Frame(frame)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

        columns = ("incident_id", "target", "source", "status", "created_at", "root_cause_summary", "pr_url")
        self.incidents_tree = ttk.Treeview(table_frame, columns=columns, show="headings")
        self.incidents_tree.heading("incident_id", text="事故 ID (ID)")
        self.incidents_tree.heading("target", text="目标 (Target)")
        self.incidents_tree.heading("source", text="来源 (Source)")
        self.incidents_tree.heading("status", text="状态 (Status)")
        self.incidents_tree.heading("created_at", text="时间 (Created At)")
        self.incidents_tree.heading("root_cause_summary", text="根因摘要 (Root Cause)")
        self.incidents_tree.heading("pr_url", text="PR 链接 (PR URL)")

        # Set minwidth to ensure horizontal scrolling works as expected
        self.incidents_tree.column("incident_id", width=150, minwidth=150)
        self.incidents_tree.column("target", width=120, minwidth=120)
        self.incidents_tree.column("source", width=120, minwidth=120)
        self.incidents_tree.column("status", width=120, minwidth=120)
        self.incidents_tree.column("created_at", width=140, minwidth=140)
        self.incidents_tree.column("root_cause_summary", width=600, minwidth=600)
        self.incidents_tree.column("pr_url", width=400, minwidth=400)

        scrollbar_y = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.incidents_tree.yview)
        scrollbar_x = ttk.Scrollbar(table_frame, orient=tk.HORIZONTAL, command=self.incidents_tree.xview)
        self.incidents_tree.configure(yscroll=scrollbar_y.set, xscroll=scrollbar_x.set)
        
        scrollbar_y.pack(side=tk.RIGHT, fill=tk.Y)
        scrollbar_x.pack(side=tk.BOTTOM, fill=tk.X)
        self.incidents_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.incidents_tree.bind("<Double-1>", self.on_incident_double_click)
        self.incidents_tree.bind("<Button-3>", self.on_incident_right_click)

        # Initial load
        self.after(200, self.load_incidents_data)

        return frame

    def load_incidents_data(self):
        import json
        import glob
        from datetime import datetime

        for row in self.incidents_tree.get_children():
            self.incidents_tree.delete(row)

        records_root = self.config_data.get("records", {}).get("root", "records")
        records_path = os.path.abspath(records_root)

        filter_status_val = self.filter_status.get().split(" ")[0]
        filter_target_val = self.filter_target.get().split(" ")[0]
        filter_source_val = self.filter_source.get().split(" ")[0]
        filter_has_pr_val = self.filter_has_pr.get()

        if not os.path.exists(records_path):
            return

        records_list = []
        for file_path in glob.glob(os.path.join(records_path, "*.json")):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    
                    status = data.get("status", "")
                    target = data.get("target", "")
                    source = data.get("source", "")
                    pr_url = data.get("pr_url", "")
                    
                    if filter_status_val != "全部" and status != filter_status_val:
                        continue
                    if filter_target_val != "全部" and target != filter_target_val:
                        continue
                    if filter_source_val != "全部" and source != filter_source_val:
                        continue
                    if filter_has_pr_val and not pr_url:
                        continue

                    mod_time = os.path.getmtime(file_path)
                    created_at = datetime.fromtimestamp(mod_time).strftime("%Y-%m-%d %H:%M:%S")
                    
                    root_cause = data.get("repair_result", {}).get("root_cause_summary", "")
                    if not root_cause:
                        root_cause = data.get("analysis", {}).get("root_cause_summary", "")
                        
                    records_list.append({
                        "incident_id": data.get("incident_id", ""),
                        "target": target,
                        "source": source,
                        "status": status,
                        "created_at": created_at,
                        "root_cause_summary": root_cause,
                        "pr_url": pr_url,
                        "time": mod_time,
                        "raw_data": data
                    })
            except Exception:
                pass

        records_list.sort(key=lambda x: x["time"], reverse=True)
        
        if not hasattr(self, "current_incidents_data"):
            self.current_incidents_data = {}
            
        for r in records_list:
            iid = r["incident_id"]
            self.current_incidents_data[iid] = r["raw_data"]
            self.incidents_tree.insert("", tk.END, values=(
                iid, r["target"], r["source"], r["status"], r["created_at"], r["root_cause_summary"], r["pr_url"]
            ))

    def on_incident_double_click(self, event):
        selection = self.incidents_tree.selection()
        if not selection:
            return
        item = self.incidents_tree.item(selection[0])
        incident_id = item['values'][0]
        raw_data = self.current_incidents_data.get(incident_id)
        if raw_data:
            self.show_incident_detail(incident_id, raw_data)

    def show_incident_detail(self, incident_id, data):
        top = tk.Toplevel(self)
        top.title(f"事故详情 (Incident Detail) - {incident_id}")
        top.geometry("1100x750")

        notebook = ttk.Notebook(top)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # 1. 概览 (Overview)
        overview_frame = ttk.Frame(notebook)
        notebook.add(overview_frame, text="概览 (Overview)")
        self.build_overview_tab(overview_frame, data)

        # 2. 日志 (Log)
        log_frame = ttk.Frame(notebook)
        notebook.add(log_frame, text="日志 (Log)")
        self.build_log_tab(log_frame, data)

        # 3. 分析 (Analysis)
        analysis_frame = ttk.Frame(notebook)
        notebook.add(analysis_frame, text="分析 (Analysis)")
        self.build_analysis_tab(analysis_frame, data)

        # 4. 补丁 (Patch)
        patch_frame = ttk.Frame(notebook)
        notebook.add(patch_frame, text="补丁 (Patch)")
        self.build_patch_tab(patch_frame, data)

        # 5. 验证 (Validation)
        val_frame = ttk.Frame(notebook)
        notebook.add(val_frame, text="验证 (Validation)")
        self.build_validation_tab(val_frame, data)

        # 6. 产物 (Artifacts)
        art_frame = ttk.Frame(notebook)
        notebook.add(art_frame, text="产物 (Artifacts)")
        self.build_artifacts_tab(art_frame, data)

    def build_overview_tab(self, parent, data):
        canvas = tk.Canvas(parent, highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True, padx=10, pady=10)
        scrollbar.pack(side="right", fill="y")

        rr = data.get("repair_result") or data
        fields = [
            ("事故 ID (Incident ID)", data.get("incident_id")),
            ("目标服务 (Target)", data.get("target")),
            ("来源 (Source)", data.get("source")),
            ("状态 (Status)", data.get("status")),
            ("根因摘要 (Root Cause)", rr.get("root_cause_summary")),
            ("PR 链接 (PR URL)", data.get("pr_url") or rr.get("pr_url")),
            ("产物目录 (Artifact Dir)", rr.get("artifact_dir")),
            ("JSON 记录 (Record JSON)", data.get("record_json_path")),
            ("Markdown 记录 (Record MD)", data.get("record_markdown_path"))
        ]
        
        for i, (label, val) in enumerate(fields):
            ttk.Label(scrollable_frame, text=label + ":", font=("Arial", 10, "bold")).grid(row=i, column=0, sticky=tk.NW, padx=5, pady=8)
            text_val = tk.Text(scrollable_frame, height=4 if "Root Cause" in label else 1, width=100, bg="#f8f9fa", relief=tk.FLAT, font=("Arial", 10))
            text_val.insert(tk.END, str(val) if val is not None else "N/A")
            text_val.config(state=tk.DISABLED)
            text_val.grid(row=i, column=1, sticky=tk.W, padx=5, pady=8)

        tags_frame = ttk.Frame(scrollable_frame)
        tags_frame.grid(row=len(fields), column=0, columnspan=2, sticky=tk.W, padx=5, pady=10)
        
        is_validated = False
        if hasattr(val, "get"):
            is_validated = val.get("tests_passed", False)
        is_validated = is_validated or data.get("status") == "validated" or rr.get("status") == "validated"
        
        if is_validated:
            tk.Label(tags_frame, text="✓ 验证通过 (Validated)", bg="#d4edda", fg="#27ae60", padx=8, pady=4, font=("Arial", 10, "bold")).pack(side=tk.LEFT, padx=5)
        if data.get("generated_test") or rr.get("generated_test"):
            tk.Label(tags_frame, text="✓ 已生成测试 (Generated Test)", bg="#d1ecf1", fg="#0c5460", padx=8, pady=4, font=("Arial", 10, "bold")).pack(side=tk.LEFT, padx=5)
        if data.get("feishu_notified"):
            tk.Label(tags_frame, text="✓ 已通知飞书 (Notified)", bg="#cce5ff", fg="#004085", padx=8, pady=4, font=("Arial", 10, "bold")).pack(side=tk.LEFT, padx=5)

    def build_log_tab(self, parent, data):
        text = tk.Text(parent, wrap=tk.WORD, font=("Consolas", 10), bg="#2b2b2b", fg="#f8f8f2")
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        
        text.tag_config("error", foreground="#ff6b6b", font=("Consolas", 10, "bold"))
        log_content = data.get("message", "No log data available.")
        text.insert(tk.END, log_content)
        
        for keyword in ["Traceback", "Error", "Exception", "panic", "KeyError", "AttributeError", "TypeError"]:
            start = "1.0"
            while True:
                pos = text.search(keyword, start, stopindex=tk.END, nocase=True)
                if not pos:
                    break
                end = f"{pos}+{len(keyword)}c"
                text.tag_add("error", pos, end)
                start = end
                
        text.config(state=tk.DISABLED)

    def build_analysis_tab(self, parent, data):
        analysis = data.get("repair_result", {}).get("analysis") or data.get("analysis", {})
        
        canvas = tk.Canvas(parent, highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        scrollbar.pack(side="right", fill="y")

        ttk.Label(scrollable_frame, text="根因摘要 (Root Cause)", font=("Arial", 12, "bold")).pack(anchor=tk.W, padx=10, pady=(10, 5))
        rc_text = tk.Text(scrollable_frame, height=3, wrap=tk.WORD, font=("Arial", 10), bg="#f8f9fa", relief=tk.FLAT)
        rc_text.pack(fill=tk.X, padx=10)
        rc_text.insert(tk.END, analysis.get('root_cause_summary', 'N/A'))
        rc_text.config(state=tk.DISABLED)

        ttk.Label(scrollable_frame, text=f"置信度 (Confidence): {analysis.get('confidence', 'N/A')}", font=("Arial", 11, "bold")).pack(anchor=tk.W, padx=10, pady=10)
        
        ttk.Label(scrollable_frame, text="修复计划 (Repair Plan)", font=("Arial", 12, "bold")).pack(anchor=tk.W, padx=10, pady=(10, 5))
        for i, step in enumerate(analysis.get('repair_plan', [])):
            ttk.Label(scrollable_frame, text=f"{i+1}. {step}", font=("Arial", 10), wraplength=800).pack(anchor=tk.W, padx=20, pady=2)
            
        ttk.Label(scrollable_frame, text="验证重点 (Validation Focus)", font=("Arial", 12, "bold")).pack(anchor=tk.W, padx=10, pady=(15, 5))
        for i, focus in enumerate(analysis.get('validation_focus', [])):
            ttk.Label(scrollable_frame, text=f"• {focus}", font=("Arial", 10), wraplength=800).pack(anchor=tk.W, padx=20, pady=2)
            
        ttk.Label(scrollable_frame, text="候选文件 (Candidate Targets)", font=("Arial", 12, "bold")).pack(anchor=tk.W, padx=10, pady=(15, 5))
        for t in analysis.get('candidate_targets', []):
            lf = ttk.LabelFrame(scrollable_frame, text=f"File: {t.get('path')}")
            lf.pack(fill=tk.X, expand=True, padx=10, pady=5)
            ttk.Label(lf, text=f"Confidence: {t.get('confidence')}", font=("Arial", 9, "bold")).pack(anchor=tk.W, padx=5, pady=2)
            ttk.Label(lf, text=f"Rationale: {t.get('rationale')}", wraplength=750).pack(anchor=tk.W, padx=5, pady=2)

    def build_patch_tab(self, parent, data):
        rr = data.get("repair_result") or data
        
        changed_files = rr.get("changed_files", [])
        if changed_files:
            files_text = "\n".join([f"- {f}" for f in changed_files])
            ttk.Label(parent, text=f"修改文件 (Changed Files):\n{files_text}", justify=tk.LEFT, font=("Arial", 10, "bold")).pack(anchor=tk.W, padx=5, pady=10)
        
        diff = rr.get("diff_summary", "No patch available.")
        text = tk.Text(parent, wrap=tk.NONE, font=("Consolas", 10), bg="#2b2b2b", fg="#a6e22e")
        scrollbar_y = ttk.Scrollbar(parent, orient="vertical", command=text.yview)
        scrollbar_x = ttk.Scrollbar(parent, orient="horizontal", command=text.xview)
        text.configure(yscrollcommand=scrollbar_y.set, xscrollcommand=scrollbar_x.set)
        scrollbar_y.pack(side="right", fill="y")
        scrollbar_x.pack(side="bottom", fill="x")
        text.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        
        text.insert(tk.END, diff)
        text.config(state=tk.DISABLED)

    def build_validation_tab(self, parent, data):
        val = data.get("repair_result", {}).get("validation") or data.get("validation", {})
        
        canvas = tk.Canvas(parent, highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        scrollbar.pack(side="right", fill="y")

        # Validation Summary
        summary_frame = ttk.LabelFrame(scrollable_frame, text="验证结果 (Validation Summary)")
        summary_frame.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Label(summary_frame, text=f"语法检查 (Syntax Check): {val.get('syntax_check')}", font=("Arial", 10, "bold")).grid(row=0, column=0, padx=10, pady=5, sticky=tk.W)
        ttk.Label(summary_frame, text=f"测试是否执行 (Tests Executed): {val.get('tests_executed')}", font=("Arial", 10, "bold")).grid(row=0, column=1, padx=10, pady=5, sticky=tk.W)
        ttk.Label(summary_frame, text=f"测试是否通过 (Tests Passed): {val.get('tests_passed')}", font=("Arial", 10, "bold")).grid(row=0, column=2, padx=10, pady=5, sticky=tk.W)
        
        skip_reason = val.get("tests_skipped_reason")
        if skip_reason:
            ttk.Label(summary_frame, text=f"跳过原因 (Skip Reason): {skip_reason}", foreground="#c0392b").grid(row=1, column=0, columnspan=3, padx=10, pady=5, sticky=tk.W)

        # Commands List
        ttk.Label(scrollable_frame, text="执行命令记录 (Commands):", font=("Arial", 12, "bold")).pack(anchor=tk.W, padx=10, pady=(15, 5))
        
        for i, cmd in enumerate(val.get("commands", [])):
            lf = ttk.LabelFrame(scrollable_frame, text=f"Step {i+1}: {cmd.get('command')}")
            lf.pack(fill=tk.X, expand=True, padx=10, pady=5)
            
            rc = cmd.get('returncode')
            rc_color = "#27ae60" if rc == 0 else "#c0392b"
            tk.Label(lf, text=f"Return Code: {rc}", font=("Arial", 10, "bold"), fg=rc_color).pack(anchor=tk.W, padx=5, pady=2)
            
            if cmd.get('stdout'):
                st = tk.Text(lf, height=4, bg="#2b2b2b", fg="#f8f8f2", font=("Consolas", 9))
                st.pack(fill=tk.X, padx=5, pady=2)
                st.insert(tk.END, cmd.get('stdout'))
                st.config(state=tk.DISABLED)
            if cmd.get('stderr'):
                se = tk.Text(lf, height=4, bg="#2b2b2b", fg="#ff6b6b", font=("Consolas", 9))
                se.pack(fill=tk.X, padx=5, pady=2)
                se.insert(tk.END, cmd.get('stderr'))
                se.config(state=tk.DISABLED)

    def build_artifacts_tab(self, parent, data):
        rr = data.get("repair_result") or data
        fields = [
            ("JSON 记录 (Record JSON)", data.get("record_json_path")),
            ("Markdown 记录 (Record MD)", data.get("record_markdown_path")),
            ("产物目录 (Artifact Dir)", rr.get("artifact_dir")),
            ("PR 链接 (PR URL)", data.get("pr_url") or rr.get("pr_url")),
        ]
        
        for i, (label, val) in enumerate(fields):
            ttk.Label(parent, text=label + ":", font=("Arial", 10, "bold")).grid(row=i, column=0, sticky=tk.W, padx=10, pady=10)
            
            val_str = str(val) if val else "N/A"
            entry = ttk.Entry(parent, width=70, font=("Arial", 10))
            entry.insert(0, val_str)
            entry.config(state="readonly")
            entry.grid(row=i, column=1, sticky=tk.W, padx=10, pady=10)
            
            if val and str(val).startswith("http"):
                import webbrowser
                btn = ttk.Button(parent, text="打开 PR (Open PR)", command=lambda url=val_str: webbrowser.open(url))
                btn.grid(row=i, column=2, padx=5, pady=10)
            elif val:
                def copy_val(v=val_str):
                    self.clipboard_clear()
                    self.clipboard_append(v)
                    messagebox.showinfo("已复制", "路径已复制到剪贴板！")
                    
                def open_dir(v=val_str):
                    if os.path.isfile(v):
                        v = os.path.dirname(v)
                    if os.path.isdir(v):
                        os.startfile(v)
                    else:
                        messagebox.showerror("错误", "该路径不存在或无法打开")
                        
                btn_copy = ttk.Button(parent, text="复制路径 (Copy)", command=copy_val)
                btn_copy.grid(row=i, column=2, padx=5, pady=10)
                
                btn_open = ttk.Button(parent, text="在文件夹中打开 (Open Dir)", command=open_dir)
                btn_open.grid(row=i, column=3, padx=5, pady=10)

    def on_incident_right_click(self, event):
        item = self.incidents_tree.identify_row(event.y)
        if item:
            self.incidents_tree.selection_set(item)
            menu = tk.Menu(self, tearoff=0)
            values = self.incidents_tree.item(item, "values")
            incident_id = values[0]
            pr_url = values[6]
            
            menu.add_command(label="复制事故 ID (Copy Incident ID)", command=lambda: self.clipboard_clear() or self.clipboard_append(str(incident_id)))
            
            if pr_url and str(pr_url).startswith("http"):
                import webbrowser
                menu.add_command(label="打开 PR 链接 (Open PR URL)", command=lambda: webbrowser.open(str(pr_url)))
            
            menu.tk_popup(event.x_root, event.y_root)

if __name__ == "__main__":
    app = AgentFixGUI()
    app.mainloop()