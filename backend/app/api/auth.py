from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from app.database import get_db
from app.auth import authenticate_user, create_access_token
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

