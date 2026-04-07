from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pathlib import Path
from app.config import settings
from app.api import auth, admin, user, execute, worker
from app.database import engine
from app.models import Base
import logging

# 起動時に未作成のテーブルを作成 (coordinator 拡張テーブル群を含む)
try:
    Base.metadata.create_all(bind=engine)
except Exception as _e:
    logging.getLogger(__name__).warning(f"create_all failed: {_e}")

# 既定の coordinator アダプターを seed (idempotent)
try:
    from app.database import SessionLocal
    from app.services.coordinator_extensions import seed_default_adapters
    _db = SessionLocal()
    try:
        seed_default_adapters(_db)
    finally:
        _db.close()
except Exception as _e:
    logging.getLogger(__name__).warning(f"adapter seed failed: {_e}")


# ログ設定（環境に応じてログレベルを変更）
log_level = logging.DEBUG if settings.is_debug_mode else logging.INFO
logging.basicConfig(
    level=log_level,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# 本番環境では詳細なログを抑制
if settings.is_production:
    # SQLAlchemyのログを抑制
    logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)
    # その他の詳細ログを抑制
    logging.getLogger('uvicorn.access').setLevel(logging.WARNING)

# FastAPIアプリケーションの作成（本番はドキュメント無効化）
if settings.ENVIRONMENT == "production":
    app = FastAPI(
        title="NexMAGI",
        description="次世代AIオーケストレーションデスクトップアプリ — マルチエージェントワークフローを実行・管理",
        version="3.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
else:
    app = FastAPI(
        title="NexMAGI",
        description="次世代AIオーケストレーションデスクトップアプリ — マルチエージェントワークフローを実行・管理",
        version="3.0.0"
    )

# CORS設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# APIルーターの登録
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(user.router)
app.include_router(execute.router)
app.include_router(worker.router)

# 静的ファイルの提供（フロントエンド）
frontend_path = Path(__file__).parent.parent.parent / "frontend"
if frontend_path.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_path)), name="static")

# ルートエンドポイント
@app.get("/", response_class=HTMLResponse)
async def root():
    """ルートページ"""
    return """
    <!DOCTYPE html>
    <html lang="ja">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>NexMAGI</title>
        <style>
            body {
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                max-width: 800px;
                margin: 50px auto;
                padding: 20px;
                background-color: #f5f5f5;
            }
            .container {
                background: white;
                padding: 40px;
                border-radius: 10px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            }
            h1 {
                color: #333;
                text-align: center;
            }
            .links {
                display: flex;
                flex-direction: column;
                gap: 15px;
                margin-top: 30px;
            }
            .link-button {
                display: block;
                padding: 15px;
                background: #007bff;
                color: white;
                text-decoration: none;
                border-radius: 5px;
                text-align: center;
                transition: background 0.3s;
            }
            .link-button:hover {
                background: #0056b3;
            }
            .link-button.admin {
                background: #28a745;
            }
            .link-button.admin:hover {
                background: #218838;
            }
            .link-button.docs {
                background: #6c757d;
            }
            .link-button.docs:hover {
                background: #5a6268;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>NexMAGI</h1>
            <p style="text-align: center; color: #666;">
                次世代AIオーケストレーションデスクトップアプリ
            </p>
            <div class="links">
                <a href="/static/admin/login.html" class="link-button admin">管理者ログイン</a>
                <a href="/static/user/login.html" class="link-button">ユーザーログイン</a>

                <!-- 本番ではAPIドキュメントを非表示 -->
                %s
            </div>
        </div>
    </body>
    </html>
    """ % (
        '<a href="/docs" class="link-button docs">API ドキュメント</a>'
        if settings.ENVIRONMENT != "production" else ""
    )


@app.get("/health")
async def health_check():
    """ヘルスチェック"""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=settings.ENVIRONMENT == "development"
    )

