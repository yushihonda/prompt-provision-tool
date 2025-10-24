from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pathlib import Path
from app.config import settings
from app.api import auth, admin, user, execute
import logging

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# FastAPIアプリケーションの作成
app = FastAPI(
    title="Prompt Provision Tool",
    description="GPT及びGeminiのプロンプトを外部に漏らさず、実行機能のみを提供するツール",
    version="1.0.0"
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
        <title>Prompt Provision Tool</title>
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
            <h1>🔐 Prompt Provision Tool</h1>
            <p style="text-align: center; color: #666;">
                プロンプトを保護しながらAI機能を提供するツール
            </p>
            <div class="links">
                <a href="/static/admin/login.html" class="link-button admin">管理者ログイン</a>
                <a href="/static/user/login.html" class="link-button">ユーザーログイン</a>
                <a href="/docs" class="link-button docs">API ドキュメント</a>
            </div>
        </div>
    </body>
    </html>
    """


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

