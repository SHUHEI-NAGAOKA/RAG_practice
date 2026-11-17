# RAG API（FastAPI ＋ 画面）のイメージ
# ビルド: runtime/compose.yaml から（このフォルダがビルドの範囲。runtime の外は参照しない）
FROM python:3.12-slim

WORKDIR /app

# torch は CPU 版を先に入れる（GPU 用ライブラリを入れずイメージを小さくする）
RUN pip install --no-cache-dir torch \
    --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# アプリ本体（app/）と画面（static/）
COPY app/ ./app/
COPY static/ ./static/

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
