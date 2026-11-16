# Amazon Experts 源码迁移报告

服务器 182，经 76 跳转进行只读检查和流式传输。

## backend

- 服务器路径 `/usr/local/amazon/amazon-experts-backend-dev`
- 本地路径 `D:\Rag\work-agent\backend`
- 服务器分支 `dev`，提交 `ecc978083c1e36af8abda05e83ad0f815ec5d5ae`
- SSH 流式 Git bundle，保留服务器本地分支、标签和可达提交历史。核对提交与文件数，共 200 个跟踪文件。
- 服务器无已跟踪文件改动。 两个未跟踪运行日志已排除。

## frontend

- 服务器路径 `/usr/local/amazon/amazon-experts-fronted-main`
- 本地路径 `D:\Rag\work-agent\frontend`
- 服务器分支 `dev`，提交 `283d4e544dfd2b8ff7bbe45ca567360c2648dcc5`
- SSH 流式 Git archive，保留指定提交的源码快照。核对提交与文件数，共 201 个跟踪文件。
- 服务器无已跟踪文件改动。 两个未跟踪运行日志已排除。

## lightrag-builder

- 服务器路径 `/usr/local/amazon/lightrag-builder`
- 本地路径 `D:\Rag\work-agent\lightrag-builder`
- 服务器分支 `main`，提交 `10aaeedba5ef00f7fb3a81ee7ba83c9c3713ff19`
- SSH 流式 Git bundle，保留服务器本地分支、标签和可达提交历史。核对提交与文件数，共 17 个跟踪文件。
- 服务器无已跟踪文件改动。 工作树干净。

## 排除和验证范围

真实环境文件、运行日志、依赖、缓存、运行数据和凭据不在迁移范围。通过历史路径检查和常见凭据模式扫描筛查传输内容。没有安装依赖或启动服务。

前端历史含旧 .bak 文件，因此前端只交付当前提交源码，历史和分支信息记录在本报告。后端和前端远程仓库未通过非交互访问检查。LightRAG Builder 的远程 main 与服务器 HEAD 一致。
