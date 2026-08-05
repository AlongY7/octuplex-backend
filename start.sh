#!/bin/bash
# ============================================================
# Octuplex 后端服务启动脚本
# 用于 Hugging Face Space 部署
# ============================================================

set -e

echo "=========================================="
echo "  Octuplex 后端服务启动中..."
echo "=========================================="

# 检查Python版本
echo "[1/5] 检查Python环境..."
python3 --version

# 安装依赖
echo "[2/5] 安装Python依赖..."
pip install -r requirements.txt --break-system-packages --quiet

# 创建必要目录
echo "[3/5] 创建运行时目录..."
mkdir -p sandbox_workspace
mkdir -p chroma_db
mkdir -p logs
mkdir -p uploads

# 检查环境变量
echo "[4/5] 检查环境变量配置..."
if [ -z "$LLM_API_KEY" ]; then
    echo "  ⚠️ 警告: LLM_API_KEY 未设置，请检查.env配置"
else
    echo "  ✅ LLM_API_KEY 已配置"
fi

if [ -z "$CORS_ORIGINS" ]; then
    echo "  ⚠️ 警告: CORS_ORIGINS 未设置，使用默认值"
    export CORS_ORIGINS="*"
fi

# 启动服务
echo "[5/5] 启动FastAPI服务 (端口: ${SERVER_PORT:-7860})..."
echo "=========================================="
echo "  Octuplex 服务已启动！"
echo "  API文档: http://0.0.0.0:${SERVER_PORT:-7860}/docs"
echo "  健康检查: http://0.0.0.0:${SERVER_PORT:-7860}/health"
echo "=========================================="

exec python3 app.py