# AgentFix 环境配置指南

## 第一步：安装 Python 虚拟环境

```bash
cd /path/to/Feishu_code_reviewer

# 创建虚拟环境
python3 -m venv .venv

# 激活虚拟环境（macOS）
source .venv/bin/activate
```

激活成功后，终端提示符前会出现 `(.venv)` 前缀。

```bash
# 安装项目依赖（包含 openai、pydantic、PyYAML + pytest）
pip install -e ".[dev]"
```

> `-e` 表示「可编辑模式」安装，修改 src 下的代码无需重新安装即可生效。
> **注意**: zsh 环境下方括号需要加引号：`pip install -e ".[dev]"`

---

## 第二步：配置文件

### 2.1 复制配置模板

```bash
cp agentfix.yaml.example agentfix.yaml
```

### 2.2 理解配置文件结构

打开 `agentfix.yaml`，核心关注这 **两个凭证相关字段**：

```yaml
openai:
  model: deepseek-v3-2-251201          # LLM 模型名
  api_key_env_var: ARK_API_KEY          # ⬅ 环境变量名（告诉程序去读哪个变量）
  base_url: https://ark.cn-beijing.volces.com/api/v3  # API 地址
  transport: rest_chat_completions       # 传输协议

github:
  token_env_var: GITHUB_TOKEN            # ⬅ 环境变量名
  api_base_url: https://api.github.com
```

**关键点**：`api_key_env_var` 和 `token_env_var` 只是**声明了环境变量的名字**，程序运行时会用这个名字去 `os.getenv()` 取值。

---

## 第三步：设置环境变量（3 种方式，任选其一）

### 方式 A：终端临时导出（最简单，推荐先这样试）

每次打开新终端都需要重新设置：

```bash
export ARK_API_KEY="你的火山方舟API Key"
export GITHUB_TOKEN="你的GitHub Token（如需自动创建PR）"
```

验证是否生效：
```bash
echo $ARK_API_KEY
echo $GITHUB_TOKEN
```

然后直接运行：
```bash
agentfix doctor        # 检查凭据是否识别到
agentfix run --repo /path/to/repo --log-file xxx.log
```

---

### 方式 B：写入 `agentfix.local.yaml`（推荐日常使用）

这个文件**已被 `.gitignore` 忽略**，不会提交到 Git，适合存放真实密钥：

创建 `agentfix.local.yaml`，内容如下：

```yaml
openai:
  api_key: "你的火山方舟API Key"    # 直接写死，不需要设环境变量

github:
  token: "你的GitHub Personal Access Token"   # 直接写死
```

**加载逻辑**（见 `config.py:93-101`）：
```
agentfix.yaml (基础配置) 
    ↓ _deep_merge 合并
agentfix.local.yaml (本地覆盖，优先级更高)
```

即：`local.yaml` 中的字段会覆盖 `agentfix.yaml` 的同名字段。

---

### 方式 C：写入 Shell 配置文件（永久生效）

把 export 写入 `~/.zshrc`（macOS 默认 shell）：

```bash
echo 'export ARK_API_KEY="你的Key"' >> ~/.zshrc
echo 'export GITHUB_TOKEN="你的Token"' >> ~/.zshrc
source ~/.zshrc
```

之后每次开终端自动生效。

---

## 第四步：验证环境是否配通

```bash
# 激活虚拟环境
source .venv/bin/activate

# 运行自检命令
agentfix doctor
```

`doctor` 会输出一份 JSON 报告，重点关注这两个字段：

```json
{
  "credentials": {
    "openai_api_key_present": true,    // ⬅ 必须是 true
    "github_token_present": true        // ⬅ 不建PR可为false
  },
  "command_requirements": {
    "analyze": "requires OpenAI API key",
    "run": "requires OpenAI API key and GitHub token unless --no-pr is used"
  }
}
```

- `openai_api_key_present: false` → 检查 `ARK_API_KEY` 是否正确导出，或 `agentfix.local.yaml` 中是否写了 `api_key`
- 如果只做 `validate` / `doctor` 命令，**不需要 API Key**

---

## 第五步：获取密钥的具体方法

### 火山方舟 API Key（ARK_API_KEY）

1. 打开 [火山引擎控制台](https://console.volcengine.com/ark/)
2. 进入「API Key 管理」→ 创建 Key
3. 确保 `base_url` 和 `model` 与你的方舟套餐匹配：
   - 默认配置：`base_url: https://ark.cn-beijing.volces.com/api/v3`
   - 默认模型：`deepseek-v3-2-251201`
4. 如果用的是其他兼容接口（如 OpenAI 官方），修改 `agentfix.yaml`：
   ```yaml
   openai:
     model: gpt-4o
     base_url: https://api.openai.com/v1
     transport: responses
     api_key_env_var: OPENAI_API_KEY
   ```

### GitHub Personal Access Token（GITHUB_TOKEN）

1. 打开 GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)
2. 勾选 `repo` 权限（用于创建分支和 Draft PR）
3. 生成 Token（以 `ghp_` 开头）

> **注意**：如果你使用 `--no-pr` 参数（不自动建 PR），则不需要 GITHUB_TOKEN。

---

## 常见问题排查

| 问题 | 排查方法 |
|------|----------|
| `ModuleNotFoundError: No module named 'agentfix'` | 未执行 `pip install -e .` 或未激活 venv |
| `Missing model API Key` | 检查 `agentfix doctor` 输出中 `openai_api_key_present` |
| API 调用报 401/403 | Key 过期或 `base_url` 不对 |
| `agentfix: command not found` | 需要先激活 venv：`source .venv/bin/activate` |
| `no matches found: .[dev]` | zsh 下方括号是特殊字符，加引号：`pip install -e ".[dev]"` |
| `setup.py not found` | pip 版本太旧，升级：`python3 -m pip install --upgrade pip` |
| `requires Python >=3.11` | 系统版本太低，需安装 Python 3.11+ 并用它创建 venv |
| `SSL: CERTIFICATE_VERIFY_FAILED` | python.org 版 Python 缺证书：`pip install certifi` + 设 `SSL_CERT_FILE` |

---

## 完整一键启动流程（汇总）

```bash
# === 终端中依次执行 ===

# 1. 进入项目目录
cd /path/to/Feishu_code_reviewer

# 2. 激活虚拟环境
source .venv/bin/activate

# 3. 设置环境变量（或提前写好 agentfix.local.yaml）
export ARK_API_KEY="your-key-here"
export GITHUB_TOKEN="your-token-here"

# 4. 自检
agentfix doctor

# 5. 执行修复（示例）
agentfix run --repo /path/to/target-repo --log-file ./tests/fixtures/some-error.log --base-branch main
```
