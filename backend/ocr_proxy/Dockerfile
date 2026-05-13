# syntax=docker/dockerfile:1
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv

# 先に requirements だけコピーしてレイヤキャッシュを効かせる
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY app ./app

# Cloud Run は PORT 環境変数を渡す。既定は 8080。
ENV PORT=8080
EXPOSE 8080

# Issue #29 §1: defense-in-depth として runtime のみ非 root で実行。
# Cloud Run のサンドボックスで blast radius は元々小さいが、コンテナ脱出系の
# 仮想的攻撃に対する追加保護。COPY は root のままで、CMD のみ app ユーザーで起動。
RUN adduser --system --no-create-home app
USER app

# 単一ワーカーで起動（Cloud Run のスケーリング任せ）。concurrency は Cloud Run 側で設定。
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
