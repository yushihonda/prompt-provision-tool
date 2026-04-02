from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from app.database import get_db
from app.auth import authenticate_user, create_access_token
from app.models import Account, AccountType
from app.schemas import Token
from app.config import settings
import logging

# ロガーの設定
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["認証"])


@router.post("/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """
    ログイン

    ユーザー名とパスワードで認証し、JWTトークンを返す
    """
    try:
        logger.info(f"Login attempt for user: {form_data.username}")

        account = authenticate_user(db, form_data.username, form_data.password)

        if not account:
            logger.warning(f"Failed login attempt for user: {form_data.username}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="ユーザー名またはパスワードが正しくありません",
                headers={"WWW-Authenticate": "Bearer"},
            )

        access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={"sub": account.username, "type": str(account.account_type)},
            expires_delta=access_token_expires
        )

        logger.info(f"Successful login for user: {form_data.username}")
        return {"access_token": access_token, "token_type": "bearer"}

    except HTTPException:
        # HTTPExceptionはそのまま再送出
        raise
    except Exception as e:
        # その他のエラーはログに記録して500エラーを返す
        logger.error(f"Login error for user {form_data.username}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"サーバー内部エラーが発生しました: {str(e)}"
        )


@router.get("/dev-login")
async def dev_login(
    role: str = Query("admin", pattern="^(admin|user)$"),
    db: Session = Depends(get_db),
):
    """
    開発環境専用: ログインをスキップしてトークンを取得する。
    本番環境では無効化される。

    Args:
        role: "admin" (親アカウント) or "user" (子アカウント)
    """
    if settings.ENVIRONMENT == "production":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not found",
        )

    # 対応するアカウントを取得（最初に見つかったものを使用）
    if role == "admin":
        account = (
            db.query(Account)
            .filter(Account.account_type == AccountType.PARENT, Account.is_active == True)
            .first()
        )
    else:
        account = (
            db.query(Account)
            .filter(Account.account_type == AccountType.CHILD, Account.is_active == True)
            .first()
        )

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{role} アカウントが見つかりません。先にアカウントを作成してください。",
        )

    access_token = create_access_token(
        data={"sub": account.username, "type": str(account.account_type)},
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )

    logger.info(f"Dev auto-login: {account.username} (role={role})")
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "username": account.username,
        "account_type": str(account.account_type),
    }

