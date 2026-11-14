# 印章工坊（SealDesk LAN）v0.1

一个独立开发的、用于局域网内 PDF 加盖普通章／骑缝章的 Web 工具。支持 Docker Compose，推荐运行于 PVE 的独立 Debian/Ubuntu 虚拟机，也可以放在 Docker 主机上。**不依赖 PDFQFZ 的源码**，借鉴的是普通章／骑缝章的工作流程。

> **定位**：日常办公使用的 PDF 可视化盖章工具，而不是 CA 可信电子签章平台。请只使用你有权使用的印章图像。

## 功能

- 浏览器（Mac、Windows、iPhone、iPad）访问；PDF 多页预览；拖动普通章调整位置
- 单份或多份 PDF 批处理：单份下载 PDF，多份下载 ZIP
- 普通章：多个印章、独立页码规则（全部、首页、末页、奇数、偶数、1,3-5）、直径/宽度、位置、旋转、不透明度
- 骑缝章：右／左／上／下、指定页范围、每组页数上限、分割位置、自动分段
- PNG、JPG、WebP 印章图；白底转透明
- 输入密码加密 PDF 读取、AES-256 输出 PDF 加密
- 保留 PDF 可选文本及绝大部分原始矢量内容，而非整页转图片
- 通过 HTTP Basic 保护，**不需要数据库、不留存上传文档、无第三方云 API、无外部 CDN**
- Docker 只读根文件系统、非 root 用户、限制 CPU/内存与权限

## ① 快速启动（Docker Compose）

安装 Docker Engine 及 Docker Compose Plugin 后：

```bash
unzip sealdesk-web.zip
cd sealdesk-web
cp .env.example .env
nano .env
```

把 `.env` 改成：

```ini
SEALDESK_BIND=192.168.123.20
SEALDESK_PORT=8765
SEALDESK_USER=admin
SEALDESK_PASSWORD=改成你自己生成的足够长的随机密码
```

建议用 `openssl rand -hex 24` 生成随机密码，然后填到 `.env` 的 `SEALDESK_PASSWORD` 字段。

其中 `192.168.123.20` **仅是例子**，必须替换成实际运行 Docker 的宿主机局域网 IPv4 地址。该地址必须存在于 Docker 宿主机网卡上。

```bash
docker compose up -d --build
docker compose ps
```

在同一局域网中打开：`http://192.168.123.20:8765`，输入 `.env` 中用户名／密码。

查看日志：`docker compose logs -f --tail=100`

停止／重启：`docker compose down` / `docker compose restart`

备份／升级：直接备份项目目录和 `.env`；不需要备份 PDF 数据库（无数据库）。

> 默认 `.env.example` 只监听 `127.0.0.1`，防止忘记配置安全策略就暴露到局域网。请不要将 `SEALDESK_BIND=0.0.0.0` 直接映射到公网。

## ② PVE 部署推荐

**首选：PVE 创建一台独立的 Debian 12 或 Ubuntu Server 虚拟机（VM）**。无需在 PVE 宿主机安装 Docker，避免和现有虚拟机（例如 FreePBX）产生管理、安全和升级风险。

建议资源（初期）：

- 1–2 vCPU
- 2 GB RAM（容器设定限制为 1 GB；处理复杂大 PDF 可能需提高）
- 10–16 GB 虚拟磁盘
- 1 张桥接局域网网卡，设置固定 IP 或 DHCP 静态租约
- Debian 12 / Ubuntu Server 24.04 LTS x86-64

在 VM 内安装 Docker Engine/Compose Plugin，复制 ZIP 到 VM，按照第①节完成部署。容器默认不持久化文档，VM 快照主要保护配置和应用。

也可在 PVE 的 LXC 中运行 Docker，但需要嵌套容器兼容性设置，配置更复杂；优先 VM。

**如果 PVE 里跑着重要电话服务，请不要将盖章服务和电话服务部署在同一个容器、同一个操作系统实例中。**

## ③ 运行于群晖或其他 Docker 主机

把整个项目目录上传到 Docker 宿主机，执行 `docker compose up -d --build`。如果宿主机的 Python 镜像无法拉取，先检查 Docker Hub 网络连通性，不建议直接更改为不明来源镜像。

## ④ 本机测试运行（无需 Docker）

需要 Python 3.12：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
SEALDESK_USER=admin SEALDESK_PASSWORD=local-test-password uvicorn app.main:app --host 127.0.0.1 --port 8765
```

然后访问 `http://127.0.0.1:8765`。Windows PowerShell 可用环境变量语法分别设置用户名密码。

自动测试：

```bash
pip install pytest httpx
python -m pytest -q
```

## ⑤ 数据保护说明

- 上传 PDF 的内容仅进入当前 Docker 服务的请求内存（框架在大文件上传时可能使用容器 `/tmp` 临时缓存；`tmpfs` 在内存中，非持久磁盘）。没有数据库、外部 API 或存储附件目录。
- **HTTP Basic 默认是明文 HTTP，不具备传输加密**。只建议在可信局域网使用；涉及敏感文件或跨 ZeroTier 访问时，建议在局域网反向代理（Caddy/Nginx）提供 HTTPS。由于浏览器会缓存 Basic 凭证，建议使用专用账号／只读设备网络。
- 不要直接开放到公网，不要使用公司印章原图分享给无权限人员。
- 输入输出 PDF 的密码只随当前请求提交；服务不写日志记录密码。
- 不能对已有数字签名保持无损；签名可能失效，已在界面提示并需要明确授权继续。
- 本版本 **不支持 PFX/CA 数字签名、操作审计、独立账号权限、服务端印章库、盖章审批和电子印章法律合规认证**。

## ⑥ 已知限制

- 目前没有 PDFQFZ 的某些高级功能：自定义分割比例、多章流水批次、数字证书签名、PDF 页面扫描化、复杂加印章合并模式等。
- 浏览器预览是 PDFium 渲染 PDF + HTML 叠加定位，导出使用 pypdf/ReportLab。少数异形 PDF（含复杂页面旋转、非标准 CropBox、特殊透明图像）预览坐标可能存在细小偏差，正式文件须检查导出结果。
- PDF 带有数字签名、复杂注释、交互表单或特殊透明度组时，修改 PDF 可能影响原有对象的表现；请使用原文件副本测试。
- 当前每个请求最多 12 份 PDF、12 张印章；每份 PDF 50 MB、每张图片 8 MB、最多 500 页。复杂文件会消耗较多内存，生产环境建议在可信环境先测试性能。
- 签章图片为普通 PDF 图像，**不是**国密电子签章，也无法证明盖章人身份。

## 演示文件

解压后可使用 `demo/demo-document.pdf` 和 `demo/demo-stamp.png` 测试页面预览与普通章／骑缝章功能；`demo/demo-result.pdf` 是预期效果示例。印章含 DEMO 字样，仅用于测试。

## ⑦ 更新或修改

目录结构：

```text
app/main.py             HTTP API、基本认证、文件收发、PDF / ZIP 响应
app/engine.py           PDF 盖章算法、页码处理、骑缝章分组、白底透明处理
app/static/index.html   中文界面
app/static/style.css    布局和视觉设计
app/static/app.js       浏览器交互、预览、拖动、批处理
Dockerfile              容器镜像
compose.yaml            Compose 配置和安全限制
.env.example            环境变量模板
tests/test_engine.py    自动回归测试
```

## 依赖与许可

本项目自编代码按 MIT License 许可（见 LICENSE），但并不代表第三方依赖遵循 MIT 许可。Python 依赖请遵循各自许可证；使用第三方软件、图片、印章素材和数字签名时须确认授权。

- [pypdf](https://pypdf.readthedocs.io/) — BSD-3-Clause
- [ReportLab](https://pypi.org/project/reportlab/) — BSD
- [pypdfium2 / PDFium](https://github.com/pypdfium2-team/pypdfium2) — Apache-2.0 / BSD-3-Clause 及其依赖许可证
- [Pillow](https://python-pillow.github.io/) — HPND
- [FastAPI](https://fastapi.tiangolo.com/) — MIT

此工具并非 `flytkgl/PDFQFZ` 的发行版或官方适配版本。

### 依赖安全与兼容性

`requirements.txt` 默认使用 `pypdf 6.21.4`（包含 2026-10 月份公开的恶意 PDF 导致无限循环等漏洞的修复；参见 [GitHub 安全公告](https://github.com/advisories/GHSA-mfr5-77xh-9j7h)）。由于本次离线测试容器中只安装了 `pypdf 5.9.0`，代码的六项自动化测试基于该版本通过；部署时的 `6.21.4` 需要联网构建后再次运行 `pytest` 验证，不应把离线测试视为新版本兼容性保证。

容器镜像**没有在本次交付环境中实际构建启动**（此环境未提供 Docker），因此首次在目标设备部署后请执行 `docker compose ps` 和完整测试，并先用非敏感 PDF 验证导出结果。
