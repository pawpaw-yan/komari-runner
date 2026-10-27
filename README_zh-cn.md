# Komari 运行时引导（Runtime-only bootstrap）

本仓库已精简为最小运行时引导，用于把 Komari（https://github.com/komari-monitor/komari）
部署到只提供「构建命令 + 运行命令」的容器平台（如 infrlo / dash.infrlo.com）。

仓库内**不包含**上游 Go 源码，也不编译 Go 项目；上游源码请见原仓库。

## 工作原理

1. 启动时从 `komari-monitor/komari` 的 GitHub Releases 下载最新预编译二进制
   （可用 `KOMARI_VERSION` 固定版本；GitHub API 不可用时回退到 `1.5.0-fix1`）；
2. 把 komari 绑定到回环地址，并在所有常见平台网关端口
   （`$PORT` + 3000/5000/8000/8080/8888，IPv4+IPv6 双栈）上做原始 TCP 转发，
   网关拨任何端口都能连上（WebSocket 原样透传）。

运行入口：`python app.py`（Debian 系环境用 `python3 app.py`）。

可选 `--download-only` 参数：只下载二进制后退出，用于构建期预下载：

```
pip install -r requirements.txt && (python3 app.py --download-only || true)
```

运行命令：`python3 app.py || python app.py`

## 环境变量

| 变量 | 说明 | 默认值 |
|---|---|---|
| `PORT` | komari 主端口（自动加入转发列表） | `8080` |
| `KOMARI_EXTRA_PORTS` | 额外转发端口，逗号分隔 | `3000,5000,8000,8080,8888` |
| `KOMARI_LISTEN` | komari 绑定地址 | `127.0.0.1:$PORT` |
| `KOMARI_VERSION` | 固定版本号，如 `1.5.0-fix1`；留空或 `latest` = 最新 release | 最新 |
| `KOMARI_DOWNLOAD_URL` | 直接指定二进制下载地址（可填镜像加速） | GitHub 官方地址 |
| `KOMARI_DATABASE` | SQLite 数据库路径 | `./data/komari.db` |
| `KOMARI_ARGS` | 附加给 `komari server` 的参数（空格分隔） | 空 |

infrlo 平台的部署细节（构建/运行命令、数据持久化、WebSocket 注意事项）
见 [doc/deploy-infrlo.md](doc/deploy-infrlo.md)。

## 精简后的文件清单

以下文件全部保留，其余上游 Komari 源码已在
"Remove upstream Komari sources, keep runtime-only bootstrap" 提交中删除：

| 文件 | 作用 |
|---|---|
| `app.py` | 引导脚本：下载二进制 → exec 启动 komari |
| `requirements.txt` | 空依赖占位，兼容平台默认构建命令 `pip install -r requirements.txt` |
| `doc/deploy-infrlo.md` | infrlo 部署指南 |
| `README.md` / `README_zh-cn.md` | 本文档 |
| `NOTICE` / `LICENSE` | 保留上游署名与 MIT 许可证 |

## 许可证

Komari 采用 MIT 许可证；本引导仓库保留上游 `LICENSE` 与 `NOTICE` 以满足署名要求。
