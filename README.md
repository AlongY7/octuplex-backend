# Octuplex 后端服务

目标驱动型自主执行AI智能系统后端服务。

## 一键部署到 Render

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://dashboard.render.com/select-repo?type=web)

点击上方按钮，然后：
1. 用 GitHub 登录 Render
2. 选择 `AlongY7/octuplex-backend` 仓库
3. Render 会自动读取 `render.yaml` 配置
4. 设置环境变量 `LLM_API_KEY`（你的 DeepSeek API Key）
5. 点击 **Deploy**

部署完成后，后端地址为 `https://octuplex-backend.onrender.com`

## 功能

- 自然语言目标指令解析
- 智能任务拆解与执行
- Python代码沙盒执行
- 联网实时资料检索
- 多格式文档解析
- GitHub仓库操作
- 定时任务调度
- 长期记忆与RAG知识库

## 配置

在 Render Dashboard 的 Environment 中设置：
- `LLM_API_KEY`: 大模型API密钥（**必填**）
- `LLM_BASE_URL`: 大模型API地址（默认 `https://api.deepseek.com/v1`）
- `LLM_MODEL_NAME`: 模型名称（默认 `deepseek-chat`）
- `CORS_ORIGINS`: 前端域名白名单