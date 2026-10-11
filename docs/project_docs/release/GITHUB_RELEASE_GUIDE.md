# AstraCode GitHub 发布指南

## 独立公开源码包

在开发项目根目录运行 `python packaging/export_public.py`，或使用 `--output` 指定一个不存在的新目录。工具以允许列表保留应用、测试、Skill、技术文档、构建脚本和历史快照，排除个人运行数据和求职资料，生成源码清单及 ZIP。公开目录内 README 即 GitHub 首页说明。

不要将整个本机开发目录直接 `git add .`。推荐在导出的公开目录初始化仓库。`packaging/publish_github.ps1 -InspectOnly` 可通过已登录 Git 凭据检查账号和仓库；指定 `-Source` 后可发布到空公开仓库，已有历史会拒绝覆盖。

## 发布前必须确认

1. 仓库中不存在 `.env`、API Key、个人测试日志和用户工作目录内容。
2. `python -m pytest -q`、`npm run build`、`cargo check` 全部通过。
3. 本地运行 `packaging/build_windows.ps1`，安装生成的 Setup 并进行一次干净机器验收。
4. 更新产品设计、开发档案、版本号和 Release Notes。
5. 如果公开分发，补充开源许可证、贡献规则、隐私说明和安全问题反馈方式。

## 本地生成下载版

在项目根目录执行：

```powershell
.\packaging\build_windows.ps1
```

生成文件：

```text
release\AstraCode-Workbench-v0.8.1-Windows-x64-Setup.exe
release\AstraCode-Workbench-v0.8.1-Windows-x64-Setup.exe.sha256
```

安装包内包含 PyInstaller 冻结的 Python sidecar，因此使用者不需要另外安装 Python。WebView2 使用 Tauri 的下载引导模式；Windows 10/11 通常已包含运行时。

当前本机构建文件：

```text
SHA256 925f71f4c604703401580bf0efb3a1e5d64f176f5f2f145e9a2922d2eb650260
```

每次重新构建都会产生不同文件，应以同目录 `.sha256` 中的新值为准，不要长期复制上面的示例值。

## 上传 GitHub

1. 在 GitHub 新建空仓库，不要勾选自动生成 README。
2. 在本地项目根目录初始化 Git，检查 `.gitignore` 后提交源码。
3. 添加远程地址并推送主分支。
4. 创建版本标签，例如 `v0.8.1`，推送标签。
5. `.github/workflows/release-windows.yml` 会在 Windows Runner 构建无 Key 安装包，并自动附加到对应 GitHub Release。

建议在 GitHub Release 页面同时粘贴 [`RELEASE_NOTES_0.8.1.md`](RELEASE_NOTES_0.8.1.md)，上传 `.exe` 与 `.sha256`，并把没有代码签名这一边界写清楚。

示例命令：

```powershell
git init
git add .
git commit -m "release: AstraCode Workbench v0.8.1"
git branch -M main
git remote add origin https://github.com/<你的用户名>/<仓库名>.git
git push -u origin main
git tag v0.8.1
git push origin v0.8.1
```

## 用户第一次打开

- 点击顶栏“新手指南”了解项目、模式、权限、Todo、验证和文件预览。
- 打开设置，填写用户自己的 DeepSeek API Key。
- Key 保存到 `%LOCALAPPDATA%\AstraCode\config.env`，不随项目或安装包分发。
- 点击左侧 `+` 添加项目目录，然后创建项目对话。

## 正式公开前仍建议补齐

- 当前已经采用 MIT 并保留上游版权，第三方依赖各自遵守原许可证。
- 给 Windows 安装包购买代码签名证书，否则部分用户可能看到 SmartScreen 未知发布者提示。
- 在另一台没有开发环境的 Windows 10/11 电脑上做安装、升级、卸载测试。
- 当前已补齐 `SECURITY.md`、`CONTRIBUTING.md`、`PRIVACY.md`；可继续完善 Issue 模板和启用私密漏洞报告。
- 未来接入自动更新时，需要签名更新清单并妥善保存 updater 私钥。
