import os
import tkinter as tk
from collections import deque
from pathlib import Path
import subprocess

class MockGUI:
    def __init__(self):
        # Initialize a basic Tkinter root (not actually drawn)
        self.root = tk.Tk()
        
        # Mock variables just like in gui.py
        self.target_vars = {
            "repo_full_name": tk.StringVar(),
            "repo_path": tk.StringVar()
        }
        
        # We set our test workspace
        self.form_vars = {
            ("runtime", "workspace_root"): tk.StringVar(value="G:/test_workspace")
        }
        self.config_data = {}

    def auto_locate_repo(self) -> None:
        repo_input = self.target_vars["repo_full_name"].get().strip()
        if not repo_input:
            print("Warning: 请先填写远程仓库链接或名称")
            return
        
        workspace = ""
        if ("runtime", "workspace_root") in self.form_vars:
            workspace = self.form_vars[("runtime", "workspace_root")].get().strip()
            
        if not workspace or not Path(workspace).exists():
            print("Warning: 工作区无效")
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
            print(f"Success: 定位成功 -> {found_path}")
        else:
            print(f"Not Found: 在工作区内未找到 {repo_name}，触发 clone")
            self._clone_repo(repo_input, workspace_path / repo_name)

    def _clone_repo(self, repo_url_or_name: str, target_dir: Path) -> None:
        clone_url = repo_url_or_name
        if not clone_url.startswith("http") and not clone_url.startswith("git@"):
            clone_url = f"https://github.com/{repo_url_or_name}.git"
            
        print(f"Cloning {clone_url} to {target_dir}...")
        try:
            # For the test script, we wait for completion instead of using a background thread
            subprocess.run(["git", "clone", clone_url, str(target_dir)], capture_output=True, text=True, check=True)
            self.target_vars["repo_path"].set(str(target_dir))
            print(f"Clone Success: {target_dir}")
        except subprocess.CalledProcessError as e:
            print(f"Clone Failed: {e.stderr}")

def test():
    gui = MockGUI()
    
    # We will test cloning a small public repo
    test_repo = "octocat/Spoon-Knife"
    print(f"--- 测试: 自动 Clone {test_repo} ---")
    
    gui.target_vars["repo_full_name"].set(test_repo)
    gui.auto_locate_repo()
    
    print(f"\n最终填充的本地路径为: {gui.target_vars['repo_path'].get()}")

if __name__ == '__main__':
    test()
