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
        self.geometry("950x650")
        
        # Configure styles
        style = ttk.Style(self)
        if 'clam' in style.theme_names():
            style.theme_use('clam')
        
        # Load config
        self.config_file = "agentfix.yaml"
        self.config_data = self.load_config()

        # Layout: Left Menu and Right Content
        self.paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        self.paned.pack(fill=tk.BOTH, expand=True)

        self.left_frame = tk.Frame(self.paned, width=220, bg="#2c3e50")
        self.right_frame = ttk.Frame(self.paned)
        self.paned.add(self.left_frame, weight=0)
        self.paned.add(self.right_frame, weight=1)

        # Left Menu
        tk.Label(self.left_frame, text="AgentFix\n控制台", font=("Arial", 16, "bold"), bg="#2c3e50", fg="white", pady=20).pack(fill=tk.X)
        
        self.menu_list = tk.Listbox(self.left_frame, font=("Arial", 12), bg="#2c3e50", fg="#bdc3c7", selectbackground="#34495e", selectforeground="white", relief=tk.FLAT, borderwidth=0, highlightthickness=0)
        self.menu_list.pack(fill=tk.BOTH, expand=True, padx=0, pady=5)
        
        menu_items = ["配置中心 (Configuration)", "运行看板 (Dashboard)"]
        for item in menu_items:
            self.menu_list.insert(tk.END, "  " + item)
            
        self.menu_list.bind("<<ListboxSelect>>", self.on_menu_select)
        
        # Right Content Frames
        self.frames = {}
        self.frames["  配置中心 (Configuration)"] = self.create_config_frame()
        self.frames["  运行看板 (Dashboard)"] = self.create_run_frame()

        # Show default (Configuration is first)
        self.menu_list.selection_set(0)
        self.on_menu_select(None)

    def load_config(self):
        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            messagebox.showwarning("警告 (Warning)", f"无法加载配置 {self.config_file}: {e}")
            return {}

    def save_config(self):
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                yaml.dump(self.config_data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
            messagebox.showinfo("成功 (Success)", "配置保存成功！(Configuration saved successfully!)")
        except Exception as e:
            messagebox.showerror("错误 (Error)", f"无法保存配置 {self.config_file}: {e}")

    def on_menu_select(self, event):
        selection = self.menu_list.curselection()
        if not selection:
            return
        selected_item = self.menu_list.get(selection[0])
        
        for frame in self.frames.values():
            frame.pack_forget()
            
        self.frames[selected_item].pack(fill=tk.BOTH, expand=True)

    def create_run_frame(self):
        frame = ttk.Frame(self.right_frame)
        ttk.Label(frame, text="运行看板 (Dashboard)", font=("Arial", 18, "bold")).pack(pady=15, padx=20, anchor=tk.W)
        
        form_frame = ttk.Frame(frame)
        form_frame.pack(fill=tk.X, padx=20, pady=10)

        repo_var = tk.StringVar()
        log_var = tk.StringVar()

        ttk.Label(form_frame, text="目标仓库路径 (Repository Address):").grid(row=0, column=0, sticky=tk.W, pady=5)
        ttk.Entry(form_frame, textvariable=repo_var, width=55).grid(row=0, column=1, padx=10, pady=5)
        ttk.Button(form_frame, text="浏览... (Browse...)", command=lambda: repo_var.set(filedialog.askdirectory() or repo_var.get())).grid(row=0, column=2, pady=5)

        ttk.Label(form_frame, text="异常日志路径 (Log File Address):").grid(row=1, column=0, sticky=tk.W, pady=5)
        ttk.Entry(form_frame, textvariable=log_var, width=55).grid(row=1, column=1, padx=10, pady=5)
        ttk.Button(form_frame, text="浏览... (Browse...)", command=lambda: log_var.set(filedialog.askopenfilename() or log_var.get())).grid(row=1, column=2, pady=5)

        text_frame = ttk.Frame(frame)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        output_text = tk.Text(text_frame, height=20, bg="#f5f5f5", font=("Consolas", 10))
        output_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(text_frame, command=output_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        output_text.config(yscrollcommand=scrollbar.set)
        
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
            ("飞书 Webhook 密钥变量名 (feishu.webhook_secret_env_var)", "feishu", "webhook_secret_env_var")
        ])

        # 4. Targets
        target_frame = ttk.Frame(notebook)
        notebook.add(target_frame, text="Targets配置 (Targets)")
        ttk.Label(target_frame, text="目标服务列表 (Targets List)", font=("Arial", 14, "bold")).pack(pady=10, padx=10, anchor=tk.W)
        
        targets_listbox = tk.Listbox(target_frame, font=("Arial", 11), height=10)
        targets_listbox.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        for target_name in self.config_data.get("targets", {}):
            targets_listbox.insert(tk.END, target_name)
            
        ttk.Label(target_frame, text="* UI 端复杂 Targets 编辑功能即将上线，目前请直接编辑 agentfix.yaml", foreground="gray").pack(pady=10, anchor=tk.W, padx=10)

        # 5. Runtime & Artifacts
        run_art_frame = ttk.Frame(notebook)
        notebook.add(run_art_frame, text="运行与产物 (Runtime)")
        self.build_form(run_art_frame, [
            ("产物存储根目录 (runtime.artifact_root)", "runtime", "artifact_root"),
            ("修复记录根目录 (records.root)", "records", "root"),
            ("是否自动提交记录 (records.auto_commit)", "records", "auto_commit")
        ])

        return frame

    def build_form(self, parent, fields):
        canvas = tk.Canvas(parent, highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(
                scrollregion=canvas.bbox("all")
            )
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True, padx=10, pady=10)
        scrollbar.pack(side="right", fill="y")

        for i, (label_text, sec, key) in enumerate(fields):
            ttk.Label(scrollable_frame, text=label_text + ":", font=("Arial", 10)).grid(row=i, column=0, sticky=tk.W, padx=10, pady=8)
            
            val = self.config_data.get(sec, {}).get(key, "")
            
            if isinstance(val, list):
                val = ", ".join(str(v) for v in val)
                
            var = tk.StringVar(value=str(val))
            self.config_vars[(sec, key)] = var
            
            entry = ttk.Entry(scrollable_frame, textvariable=var, width=50, font=("Arial", 10))
            entry.grid(row=i, column=1, padx=10, pady=8, sticky=tk.W)

    def save_config_action(self):
        for (sec, key), var in self.config_vars.items():
            if sec not in self.config_data:
                self.config_data[sec] = {}
            val = var.get().strip()
            
            # Type casting logic
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
                    
            self.config_data[sec][key] = val
        self.save_config()

if __name__ == "__main__":
    app = AgentFixGUI()
    app.mainloop()