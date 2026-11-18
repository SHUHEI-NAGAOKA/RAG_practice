# RAG API（FastAPI ＋ 画面）のイメージ
# ビルド: runtime/compose.yaml から（ビルドの範囲は runtime/。runtime の外は参照しない）
# 版はすべて固定する（同じ環境を再現するため）。ベースイメージはダイジェストまで固定
FROM python:3.12.16-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

WORKDIR /app

# torch は CPU 版を先に入れる（GPU 用ライブラリを入れずイメージを小さくする）
RUN pip install --no-cache-dir torch==2.15.0 \
    --index-url https://download.pytorch.org/whl/cpu

COPY rag_api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Qdrant の約束（コレクション名・Embedding などは config.py がここから読む）
COPY contract/ ./contract/
# アプリ本体（app/）と画面（static/）
COPY rag_api/app/ ./app/
COPY rag_api/static/ ./static/

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
