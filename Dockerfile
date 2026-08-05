# Octuplex Hugging Face Space Dockerfile
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-chi-sim \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖清单
COPY requirements.txt .

# 安装Python依赖
RUN pip install --no-cache-dir -r requirements.txt --break-system-packages

# 复制应用代码
COPY . .

# 创建运行时目录
RUN mkdir -p sandbox_workspace chroma_db logs uploads

# 暴露端口
EXPOSE 7860

# 启动命令
CMD ["python3", "app.py"]