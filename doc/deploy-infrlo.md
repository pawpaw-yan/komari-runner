# Komari 部署到 infrlo 容器

infrlo 平台的 Python 应用默认提供两条命令：**Build Command**
（`pip install -r requirements.txt`）和 **Run Command**（`python app.py`）。

Komari 是 Go 预编译单二进制程序，前端已内嵌，运行时只依赖一个可写的工作目录。
`app.py` 在运行期从 GitHub Releases 下载对应架构的二进制（实测约 2 秒），
启动后把它绑在 `127.0.0.1:$PORT`，并在**所有常见网关端口**
（`$PORT` + 3000/5000/8000/8080/8888，IPv4+IPv6 双栈）上做原始 TCP 转发。

**两条命令保持平台默认即可，无需修改。**

## 实测记录（2026-10-27/28，komari 1.6.1）

- Run Command 用平台默认 `python app.py` 可用：运行环境有 `python` 命令
  （构建环境没有，见下文「构建日志里可以忽略的 ERR」）。
- 运行期下载 `komari-linux-amd64`（28.6MB）约 2 秒完成，无需构建期预下载。
- 平台**不注入 `PORT` 环境变量**；设了 `PORT=8080` 后 komari 正常监听
  `0.0.0.0:8080`，但边缘网关仍返回 Bad Gateway——网关拨的端口/协议栈
  与应用绑定的对不上，且从容器内无从得知网关的具体行为，于是改为
  多端口兜底转发方案（见下）。

## 端口与 Bad Gateway（关键）

`app.py` 现在自动兜底：komari 绑 `127.0.0.1:$PORT`（默认 8080），Python 进程
同时在 `$PORT` 和 3000/5000/8000/8080/8888 上监听并透传（含 WebSocket）。
网关拨哪个端口都能命中，一般**无需任何端口配置**。

补充说明：

- 想改主端口：环境变量 `PORT=<端口>`；想增减兜底端口：`KOMARI_EXTRA_PORTS=9000,9001`。
- `KOMARI_LISTEN` 可把 komari 直接绑到 `0.0.0.0`（此时不需要转发，但网关端口
  仍必须与 komari 绑定端口一致才能访问）。

## 域名与 404

- **Bad Gateway**：域名已路由到应用，但网关拨不上容器端口。多端口版部署后应消失。
- **`404 page not found`（纯文本）**：这是 infrlo 边缘网关自己的 Go 默认 404，
  说明该主机名**没有路由到任何应用**（komari 在根路径只返回安装向导，不会 404）。
  去 Overview 页找平台分配的 `*.infrlo.com` 访问域名，先用它验证，再绑自定义域名。

## 构建日志里可以忽略的 ERR

infrlo 的 buildpack 在构建期会探测 Python 框架，产生与本项目无关的报错。
**不影响构建与部署**（最终仍是 Build succeeded / Deployment Successful）：

- `from mango import create_asgi_app`、`ModuleNotFoundError: No module named 'quart'`
  ——平台默认模板（mango/quart）的探测。本项目不是 Python Web 应用，无需理会，
  也无法从仓库侧消除。
- `/bin/sh: 1: python: not found` ——构建环境没有 `python` 命令（只有 `python3`）。
  旧版文档建议的预下载构建命令会触发它；改用平台默认构建命令后即不再出现。

如仍想在构建期预下载（例如构建机网络更快），Build Command 可用：

```
pip install -r requirements.txt && (python3 app.py --download-only || true)
```

`|| true` 保证下载失败也不阻塞部署（运行期会重试）。

## 可选环境变量（在 infrlo 容器设置页添加）

| 变量 | 说明 | 默认值 |
|---|---|---|
| `PORT` | komari 主端口（自动加入转发列表） | `8080` |
| `KOMARI_EXTRA_PORTS` | 额外转发端口，逗号分隔；默认 3000/5000/8000/8080/8888 | 内置默认 |
| `KOMARI_VERSION` | 指定版本号，如 `1.6.1` | 自动取最新 release |
| `KOMARI_DOWNLOAD_URL` | 直接指定二进制下载地址，可填 ghproxy 等镜像加速 | GitHub 官方地址 |
| `KOMARI_LISTEN` | komari 绑定地址，如 `0.0.0.0:8080` | `127.0.0.1:$PORT` |
| `KOMARI_DATABASE` | SQLite 文件路径 | `./data/komari.db` |
| `KOMARI_ARGS` | 附加给 `komari server` 的参数（空格分隔） | 空 |

## 排错

- **Logs 页完全空白**：旧版引导脚本的 print 因 Python 管道块缓冲 + execvp 被
  整体丢弃（已修复）。重新部署后应能看到 `[komari] downloading ...` →
  `[komari] starting: ...` → komari 的 `[INFO/SERVER]` 日志。
- **Bad Gateway**：见上文「端口与 Bad Gateway」，最常见原因是端口没对齐。
- **下载失败**：设 `KOMARI_DOWNLOAD_URL` 走镜像，例如
  `https://ghproxy.net/https://github.com/komari-monitor/komari/releases/download/1.6.1/komari-linux-amd64`。
- **证书错误（ERR_CERT_AUTHORITY_INVALID）**：TLS 由 infrlo 边缘代理负责，与本仓库
  无关。多为平台尚未给该子域签发证书（等几分钟重试）或访问域名与平台分配的不一致；
  换网络（如手机流量）访问可排除本地代理拦截。
  **证书修复前不要点「高级 → 继续前往」登录面板**，否则密码明文暴露。

## 数据持久化

数据库默认写在容器工作目录 `./data/komari.db`。infrlo 这类容器重启/重新部署后
**文件系统通常是临时的**，面板数据（账号、探针列表、记录）会丢失：

- 若平台提供持久化存储/挂载目录，设置 `KOMARI_DATABASE=/持久化路径/komari.db`；
- 否则每次重新部署需重新执行首次安装向导（浏览器打开面板首页即可进入安装页）；
- 可用面板自带的备份/恢复功能在两次部署间迁移数据。

## 其他注意事项

- **WebSocket**：探针（agent）通过 WebSocket 连接面板，部署后需确认平台已开启
  WebSocket 支持，否则探针连不上。
- **架构自动适配**：`app.py` 会根据容器架构自动选择
  `komari-linux-{amd64,arm64,386,loong64,riscv64}`。
- **探针端**：部署好面板后，在面板后台复制安装命令安装各节点探针，
  连接地址填面板域名，WebSocket 端口与面板同端口。

## 文件说明

| 文件 | 作用 |
|---|---|
| `app.py` | Python 引导脚本：下载二进制 → exec 启动 komari |
| `requirements.txt` | 空依赖占位，兼容平台默认构建命令 |
