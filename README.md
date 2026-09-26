# yifileDownloader 使用说明

yifile.com（翼存网盘）批量下载工具。把分享链接写进清单，程序自动完成：
解析文件页 → 免费下载预检（freedl）→ 等待站点 30 秒倒计时 → 识别验证码换取直链 → 分块下载 → 完成后自动改名。
下载任务记录在本地 SQLite 数据库中，已完成的文件重新运行时自动跳过。

## 快速开始

1. 把要下载的 yifile 分享链接逐行写入 `yilist.txt`
   - 支持 `/f/` 短链和 `/file/` 长链两种格式
   - **必须保留链接 `#` 后面的 16 位片段**（如 `/f/xxxxxx#FHwrR-0g4qs-_pij`），
     它是防盗链 key，缺失会导致下载被服务器拒绝（403）
2. 双击运行 `yifileDownloader.exe`（或在本目录命令行执行）
3. 文件会下载到 `downloads/` 目录，完成后在数据库中标记，下次运行自动跳过已完成任务

## 下载流程与耗时

每个文件下载前需要（站点 2024+ 新版流程，程序自动处理）：

1. freedl 预检（在服务端登记本次下载会话）
2. 等待站点强制的 30 秒倒计时（免费用户限制，无法跳过）
3. 验证码识别换取直链（失败自动换图重试，最多 10 次）
4. 开始下载（每块 64KB、块间 0.05s 温和限速）

因此每个文件从启动到开始下载约有 40-60 秒延迟，属正常现象。

## 目录结构

```
release/
├── yifileDownloader.exe   主程序（单文件，免安装）
├── main.ini               配置文件（必须与 exe 同目录运行）
├── yilist.txt             下载链接清单
├── db/data.sqlite3        任务数据库（首次运行自动创建）
└── downloads/             下载目录（首次运行自动创建）
```

## 配置说明（main.ini）

```ini
[yifiletool]
yifilelist=yilist.txt          # 链接清单文件路径
downloadpath=./downloads       # 下载保存目录
datasource=./db/data.sqlite3   # 任务数据库路径
```

三个路径都支持相对路径（相对于运行时的工作目录）与绝对路径。

## 链接清单格式（yilist.txt）

- 每行一个链接，取每行第一列（Tab 分隔时只读第一列，可直接粘贴带说明的表格行）
- 以 `#` 开头的行会被忽略（注释）
- 链接形如：
  - `https://www.yifile.com/f/xxxxxxxx#AAAAAAAAAAAAAAAA`（短链 + 防盗链片段，推荐直接从浏览器复制完整地址）
  - `https://www.yifile.com/file/xxxxxxxx`（旧式长链）

## 断点续传（重要变更）

新版下载服务器**不支持 HTTP Range 断点续传**（请求会返回 403 "range not allowed"）。

- 下载中的文件以 `文件名.downloading` 临时保存
- 若程序中断，再次运行时会**从头重新下载**该文件（自动覆盖旧的 .downloading 临时文件）
- 只有完整下载的文件才会改回正式文件名；已完成的任务不会重复下载

## 常见问题

- **窗口一闪而过**：本版本结束时不会自动关窗，会显示"按回车键退出"，
  可查看完整输出定位问题
- **验证码识别**：内置模板匹配 OCR（无需安装 Tesseract），单次识别失败会自动换一张
  验证码重试（每文件最多 10 次）；若某文件始终失败，多为链接失效，跳过即可
- **下载速度**：实测约 64KB/s（站点对免费用户的每连接限速，浏览器下载同样如此；
  服务端不允许并发/Range，无法绕过）。3.11GB 约需 14 小时，请耐心挂着
- **链接失效 / 403**：清单中的死链会被跳过并打印提示，不影响其余任务；
  下载直链 403 多为清单中丢失了 `#` 防盗链片段
- **freedl 预检未通过**：可能达到当日免费下载次数限制，次日再试
- **重复文件**：目标目录已存在同名文件时，新文件自动加时间戳前缀

## 源码与重建

源码位于 `penn945-yifileDownloader-f74925e/`：

- `Main.py` 入口（配置、任务库、调度）
- `yifile.py` 核心下载类（页面解析、freedl 预检、验证码换直链、下载）
- `captcha_ocr.py` 验证码识别（内嵌模板库，纯 numpy+PIL）
- `captcha_templates.py` 自动生成的模板数据（勿手改）

重建 exe：

```bash
pip install pillow pyinstaller
pyinstaller --onefile --name yifileDownloader Main.py
```

模板库重建（需要 `_build/` 下的标注样本与脚本）：

```bash
python _build/build_templates.py
```
