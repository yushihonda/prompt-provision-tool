FROM python:3.10-slim

WORKDIR /app

# 必要なパッケージのインストール (MySQLクライアントなど)
RUN apt-get update && apt-get install -y \
    pkg-config \
    default-libmysqlclient-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ローカル環境用なので、コード自体はボリュームマウントで読み込む想定ですが
# 一応コピーしておきます
COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
