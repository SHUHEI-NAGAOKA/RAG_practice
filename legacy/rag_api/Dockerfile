FROM python:3.12-slim

WORKDIR /app

# torch は CPU版を先に入れる（GPU用ライブラリを入れずイメージを小さくする）
RUN pip install --no-cache-dir torch \
    --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .

RUN pip install --no-cache-dir \
    -r requirements.txt

COPY main.py .
COPY static/ ./static/

EXPOSE 8000

CMD ["uvicorn", "main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000"]
