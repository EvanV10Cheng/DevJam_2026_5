# 三個必知重點（README §8）：
#   1. host 必須是 0.0.0.0，用 127.0.0.1 會讓 Cloud Run 連不進來
#   2. port 讀 $PORT，Cloud Run 注入 8080 並期待你監聽它
#   3. exec 讓 uvicorn 成為 PID 1，才收得到 SIGTERM
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}
