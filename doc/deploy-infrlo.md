# Komari 部署到 infrlo 容器

infrlo 容器只提供两个配置项：**Build Command** 和 **Run Command**（默认值分别为
`pip install -r requirements.txt` 和 `python app.py`）。

Komari 是 Go 预编译单二进制程序，**前端已内嵌**，运行时只依赖一个可写的工作目录，
因此采用「Python 引导脚本」方案：`app.py` 在构建期/运行期从 GitHub Releases 下载
对应架构的二进制，然后用 `execv` 把 `python app.py` 进程替换为 `./komari server`，
平台两条命令基本保持默认即可。

## 配置

| 配置项 | 填写内容 |
|---|---|
| Build Command | `pip install -r requirements.txt && (python3 app.py --download-only \|\| python app.py --download-only)` |
| Run Command | `python3 app.py \|\| python app.py` |
| 端口 | komari 默认监听 `0.0.0.0:25774`；若平台注入 `PORT` 环境变量则自动跟随 |

> **注意用 `python3`**：infrlo 的 Debian 系环境没有 `python` 命令（构建日志会报
> `/bin/sh: 1: python: not found`），`pip` 能用不代表 `python` 存在。
> 上面命令已做 `python3 → python` 双重兜底。

> 即使 Build Command 里的下载步骤失败也能部署（运行期会重试），
> 但建议构建期预下载，启动更快，也不依赖运行环境的外网连通性。

## 可选环境变量（在 infrlo 容器设置页添加）

| 变量 | 说明 | 默认值 |
|---|---|---|
| `PORT` | 监听端口（平台通常会自动注入） | `25774` |
| `KOMARI_VERSION` | 指定版本号，如 `1.5.0-fix1` | 自动取最新 release |
| `KOMARI_DOWNLOAD_URL` | 直接指定二进制下载地址，可填 ghproxy 等镜像加速 | GitHub 官方地址 |
| `KOMARI_LISTEN` | 监听地址，如 `0.0.0.0:8080` | `0.0.0.0:$PORT` |
| `KOMARI_DATABASE` | SQLite 文件路径 | `./data/komari.db` |
| `KOMARI_ARGS` | 附加给 `komari server` 的参数（空格分隔） | 空 |

## 排错

- **Logs 页完全空白（连 Error 都是 0）**：不代表程序没输出。先点 Refresh 等一两分钟；
  旧版引导脚本的 print 因 Python 管道块缓冲 + execvp 会被整体丢弃（已修复，需重新部署）。
  若重新部署后仍空白，说明进程压根没跑起来或立刻崩溃，转下一条。
- **平台显示 ONLINE / Deployment Successful 但打不开（502）**：只代表容器进程在跑，
  不代表 komari 已监听。去 Logs 页看真实日志；最常见原因是 `python: not found`
  （改用 `python3`）、下载二进制失败（设 `KOMARI_DOWNLOAD_URL` 走镜像）或
  首次下载 20MB+ 二进制尚未完成——默认构建命令不含预下载，首次启动可能要等 1-2 分钟。
  建议把 Build Command 改为含 `--download-only` 的预下载版本（见上文配置表）。
- **容器内完全没有 python3** 的兜底方案：不依赖 Python，直接在
  Build Command 用 curl/wget 拉二进制（x86 容器）：
  `curl -fsSL -o komari https://github.com/komari-monitor/komari/releases/download/1.5.0-fix1/komari-linux-amd64 && chmod +x komari`
  Run Command 改为：`./komari server --listen 0.0.0.0:${PORT:-25774}`

## 数据持久化

数据库默认写在容器工作目录 `./data/komari.db`。infrlo 这类容器重启/重新部署后
**文件系统通常是临时的**，面板数据（账号、探针列表、记录）会丢失：

- 若平台提供持久化存储/挂载目录，设置 `KOMARI_DATABASE=/持久化路径/komari.db`；
- 否则每次重新部署需重新执行首次安装向导（浏览器打开面板首页即可进入安装页）；
- 可用面板自带的备份/恢复功能在两次部署间迁移数据。

## 其他注意事项

- **WebSocket**：探针（agent）通过 WebSocket 连接面板，部署后需确认平台已开启
  WebSocket 支持，否则探针连不上。
- **架构自动适配**：`app.py` 会根据容器架构自动选择 `komari-linux-{amd64,arm64,386,loong64,riscv64}`。
- **下载失败**：若容器访问 GitHub 受限，设置 `KOMARI_DOWNLOAD_URL` 走镜像，
  例如 `https://ghproxy.net/https://github.com/komari-monitor/komari/releases/download/1.5.0-fix1/komari-linux-amd64`。
- **探针端**：部署好面板后，在面板后台复制 `install-komari.sh` 命令安装各节点探针，
  连接地址填 infrlo 分配的域名，WebSocket 端口与面板同端口。

## 文件说明

| 文件 | 作用 |
|---|---|
| `app.py` | Python 引导脚本：下载二进制 → exec 启动 komari |
| `requirements.txt` | 空依赖占位，兼容平台默认构建命令 |
