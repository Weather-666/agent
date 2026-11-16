# Experts Agent Project

本项目包含 Experts 智能体平台的完整前后端与知识库构建模块：

## 目录结构

- **`backend/`**：基于 FastAPI 的后端控制面，负责用户、租户权限、计费、Expert 编排、会话与知识库同步管理。
- **`frontend/`**：基于 Next.js 的前端交互界面，提供专家聊天、控制台、知识库配置及用户管理等视图。
- **`lightrag-builder/`**：LightRAG Controller 与知识服务部署模块，支持独立 LightRAG 实例与 Docling 文档解析。
- **`study-notes/`**：迁移及学习笔记文档。
