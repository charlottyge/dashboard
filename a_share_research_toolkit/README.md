# A Share Research Toolkit

本工具是本地前端壳，用来统一运行两套能力：

- 盘中 checkpoint 扫描与策略包扫描
- 周末板块轮动、估值、季节性和事件研究报告

它不依赖 Codex skill 运行。盘中脚本已经内置在 `vendor/intraday_decision/scripts/`，周末报告直接调用相邻目录 `../a_share_rotation_research/`。

## 启动

```bash
cd "/Users/char/Desktop/04 investment/a_share_research_toolkit"
./start.sh
```

然后打开：

```text
http://127.0.0.1:8765
```

## 安装依赖

```bash
./install.sh
```

`install.sh` 会为相邻的 `tool/` 和 `a_share_rotation_research/` 检查虚拟环境并安装依赖。

## 页面功能

- 盘中决策：运行 09:25、09:45、10:30、11:20、13:30、14:30、15:10 扫描。
- 策略包扫描：运行 `scan_strategy.py`，默认保留前四个策略和 5 亿流通股上限。
- 周末板块轮动：运行 `a_share_rotation_research/src/weekly_runner.py`。
- 报告中心：预览最近生成的 Markdown、CSV 和 JSON。
- 迁移与配置：查看当前项目路径，使用备份/恢复脚本。

## 分享给朋友

如果只想让朋友打开网页查看最近结果，可以生成静态分享版：

```bash
cd "/Users/char/Desktop/04 investment"
python3 a_share_research_toolkit/scripts/publish_static_site.py
```

生成内容位于：

```text
public/
```

这个目录不需要 Python 后端，可以直接托管到 GitHub Pages。朋友看到的是只读结果页，包含最近盘中扫描、策略包候选、周度板块轮动报告和最近导出文件列表。

本地预览：

```bash
cd "/Users/char/Desktop/04 investment/public"
python3 -m http.server 8787
```

打开：

```text
http://127.0.0.1:8787
```

GitHub Pages 推荐设置：

- 建一个 GitHub 仓库，只提交 `public/` 里的文件。
- 在仓库 Settings -> Pages 里选择 `main` 分支和根目录。
- 每次本地生成新扫描或周报后，重新运行 `publish_static_site.py` 并推送。

## 备份和换电脑

在旧电脑：

```bash
./scripts/backup.sh
```

把生成的 `backup_*.tar.gz` 和整个工作目录复制到新电脑。

在新电脑：

```bash
./scripts/restore.sh /path/to/backup_*.tar.gz
./install.sh
./start.sh
```

如果新电脑路径不同，编辑：

```text
toolkit_config.json
```

重点检查：

- `intraday_export_root`
- `rotation_project_dir`
- `rotation_python`
- `investment_dir`

## 运行边界

本工具是研究辅助系统，不是投资建议。所有扫描和周报仍然遵守原始项目的数据规则：东方财富优先，失败后 fallback；无法验证的数据保留但标记；输出观察池而不是买卖建议。
