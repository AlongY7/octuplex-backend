---
title: Octuplex Backend
emoji: ⚡
colorFrom: blue
colorTo: purple
sdk: docker
pinned: false
license: mit
---

# Octuplex 后端服务

目标驱动型自主执行AI智能系统后端服务。

## 功能

- 自然语言目标指令解析
- 智能任务拆解与执行
- Python代码沙盒执行
- 联网实时资料检索
- 多格式文档解析
- GitHub仓库操作
- 定时任务调度
- 长期记忆与RAG知识库

## 部署

此Space为Octuplex后端服务，前端页面部署在GitHub Pages。

## 配置

在Space Settings中设置以下Secret环境变量：
- `LLM_API_KEY`: 大模型API密钥（必填）
- `LLM_BASE_URL`: 大模型API地址
- `LLM_MODEL_NAME`: 模型名称
- `CORS_ORIGINS`: 前端域名白名单