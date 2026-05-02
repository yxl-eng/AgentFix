import tkinter as tk
from tkinter import filedialog, messagebox
import subprocess
import threading
import sys
import os

def browse_repo():
    path = filedialog.askdirectory(title="Select Repository Directory")
    if path:
        repo_var.set(path)

def browse_log():
    path = filedialog.askopenfilename(title="Select Log File")
    if path:
        log_var.set(path)

def run_fix():
    repo = repo_var.get().strip()
    log = log_var.get().strip()
    if not repo or not log:
        messagebox.showerror("Error", "Please select both Repository and Log File")
        return
    
    run_btn.config(state=tk.DISABLED)
    output_text.delete(1.0, tk.END)
    output_text.insert(tk.END, f"Running AgentFix...\nRepo: {repo}\nLog: {log}\n\n")
    
    def append_text(text):
        output_text.insert(tk.END, text)
        output_text.see(tk.END)
    
    def task():
        try:
            # Add src to PYTHONPATH so agentfix module can be found
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
                root.after(0, append_text, line)
            process.wait()
            root.after(0, append_text, f"\nProcess finished with exit code {process.returncode}\n")
        except Exception as e:
            root.after(0, append_text, f"\nError: {e}\n")
        finally:
            root.after(0, lambda: run_btn.config(state=tk.NORMAL))

    threading.Thread(target=task, daemon=True).start()

root = tk.Tk()
root.title("AgentFix GUI")
root.geometry("650x450")

repo_var = tk.StringVar()
log_var = tk.StringVar()

frame_top = tk.Frame(root)
frame_top.pack(fill=tk.X, padx=10, pady=10)

tk.Label(frame_top, text="Repository Address:").grid(row=0, column=0, sticky=tk.W, pady=5)
tk.Entry(frame_top, textvariable=repo_var, width=50).grid(row=0, column=1, padx=5, pady=5)
tk.Button(frame_top, text="Browse...", command=browse_repo).grid(row=0, column=2, pady=5)

tk.Label(frame_top, text="Log File Address:").grid(row=1, column=0, sticky=tk.W, pady=5)
tk.Entry(frame_top, textvariable=log_var, width=50).grid(row=1, column=1, padx=5, pady=5)
tk.Button(frame_top, text="Browse...", command=browse_log).grid(row=1, column=2, pady=5)

run_btn = tk.Button(root, text="Run AgentFix", command=run_fix, bg="#4CAF50", fg="white", font=("Arial", 12, "bold"))
run_btn.pack(pady=5)

output_text = tk.Text(root, height=15)
output_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

# Add a scrollbar to the text widget
scrollbar = tk.Scrollbar(output_text)
scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
output_text.config(yscrollcommand=scrollbar.set)
scrollbar.config(command=output_text.yview)

root.mainloop()
