from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from app.config import settings
from app.database import get_db
from app.models import Account, AccountType
from app.schemas import TokenData

# パスワードハッシュ化
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# OAuth2スキーム
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """パスワードの検証"""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """パスワードのハッシュ化"""
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    JWTアクセストークンの作成

    Args:
        data: トークンに含めるデータ
        expires_delta: 有効期限

    Returns:
        JWTトークン
    """
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def authenticate_user(db: Session, username: str, password: str) -> Optional[Account]:
    """
    ユーザー認証

    Args:
        db: データベースセッション
        username: ユーザー名
        password: パスワード

    Returns:
        認証成功時はAccountオブジェクト、失敗時はNone
    """
    account = db.query(Account).filter(Account.username == username).first()

    if not account:
        return None

    if not verify_password(password, account.hashed_password):
        return None

    if not account.is_active:
        return None

    return account


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> Account:
    """
    現在のユーザーを取得（JWT検証）

    Args:
        token: JWTトークン
        db: データベースセッション

    Returns:
        Accountオブジェクト

    Raises:
        HTTPException: 認証失敗時
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="認証情報を確認できませんでした",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        username: str = payload.get("sub")

        if username is None:
            raise credentials_exception

        token_data = TokenData(username=username)
    except JWTError:
        raise credentials_exception

    account = db.query(Account).filter(Account.username == token_data.username).first()

    if account is None:
        raise credentials_exception

    if not account.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="アカウントが無効化されています"
        )

    return account


async def get_current_active_parent(
    current_user: Account = Depends(get_current_user)
) -> Account:
    """
    現在のユーザーが親アカウント（管理者）であることを確認

    Args:
        current_user: 現在のユーザー

    Returns:
        Accountオブジェクト

    Raises:
        HTTPException: 親アカウントでない場合
    """
    if str(current_user.account_type) != AccountType.PARENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="管理者権限が必要です"
        )

    return current_user


async def get_current_active_child(
    current_user: Account = Depends(get_current_user)
) -> Account:
    """
    現在のユーザーが子アカウントであることを確認

    Args:
        current_user: 現在のユーザー

    Returns:
        Accountオブジェクト

    Raises:
        HTTPException: 子アカウントでない場合
    """
    if str(current_user.account_type) != AccountType.CHILD:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="この機能は子アカウント専用です"
        )

    return current_user

