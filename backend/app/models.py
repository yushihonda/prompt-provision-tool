from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import enum


class AccountType(str, enum.Enum):
    """アカウントタイプ"""
    PARENT = "PARENT"  # 親アカウント（管理者）
    CHILD = "CHILD"    # 子アカウント（外部ユーザー）


class ModelType(str, enum.Enum):
    """AIモデルタイプ"""
    GPT4 = "gpt-4"
    GPT4_TURBO = "gpt-4-turbo-preview"
    GPT5_PRO = "gpt-5-pro"  # 将来対応
    GPT5_THINKING = "gpt-5-thinking"
    GEMINI_PRO = "gemini-pro"
    GEMINI_2_5_PRO = "gemini-2.5-pro"
    GEMINI_DEEP_THINK = "gemini-2.5-pro-deep-think"


class Account(Base):
    """アカウントテーブル"""
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    account_type = Column(String(20), nullable=False, default=AccountType.CHILD)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # リレーション
    prompts_created = relationship("Prompt", back_populates="creator", foreign_keys="Prompt.created_by")
    account_prompts = relationship("AccountPrompt", back_populates="account", cascade="all, delete-orphan")
    executions = relationship("Execution", back_populates="account", cascade="all, delete-orphan")
    api_config = relationship("APIConfig", back_populates="account", uselist=False, cascade="all, delete-orphan")


class Prompt(Base):
    """プロンプトテーブル（暗号化保存）"""
    __tablename__ = "prompts"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    description = Column(Text)
    encrypted_content = Column(Text, nullable=False)  # 暗号化されたプロンプト
    model_type = Column(String(100), nullable=False)  # モデルタイプ（文字列として保存）
    input_schema = Column(Text)  # JSON形式で入力フィールドの定義を保存
    is_active = Column(Boolean, default=True, nullable=False)
    allows_file_output = Column(Boolean, default=False, nullable=False)  # ファイル出力を許可するか
    created_by = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # リレーション
    creator = relationship("Account", back_populates="prompts_created", foreign_keys=[created_by])
    account_prompts = relationship("AccountPrompt", back_populates="prompt", cascade="all, delete-orphan")
    executions = relationship("Execution", back_populates="prompt", cascade="all, delete-orphan")


class AccountPrompt(Base):
    """アカウントとプロンプトの紐付けテーブル"""
    __tablename__ = "account_prompts"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    prompt_id = Column(Integer, ForeignKey("prompts.id", ondelete="CASCADE"), nullable=False)
    assigned_at = Column(DateTime(timezone=True), server_default=func.now())

    # リレーション
    account = relationship("Account", back_populates="account_prompts")
    prompt = relationship("Prompt", back_populates="account_prompts")


class Execution(Base):
    """実行ログテーブル"""
    __tablename__ = "executions"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    prompt_id = Column(Integer, ForeignKey("prompts.id", ondelete="SET NULL"), nullable=True)
    input_data = Column(Text)  # ユーザーが入力したデータ
    output_data = Column(Text)  # AIの出力結果
    model_used = Column(String(100))  # 使用されたモデル
    tokens_used = Column(Integer)  # 使用トークン数
    execution_time = Column(Integer)  # 実行時間（ミリ秒）
    status = Column(String(50))  # success, error, timeout
    error_message = Column(Text)  # エラーメッセージ
    executed_at = Column(DateTime(timezone=True), server_default=func.now())

    # リレーション
    account = relationship("Account", back_populates="executions")
    prompt = relationship("Prompt", back_populates="executions")


class APIConfig(Base):
    """子アカウントのAPI設定テーブル"""
    __tablename__ = "api_configs"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), unique=True, nullable=False)
    openai_api_key = Column(String(255))  # 子アカウント独自のAPIキー（オプション）
    gemini_api_key = Column(String(255))  # 子アカウント独自のAPIキー（オプション）
    rate_limit_per_hour = Column(Integer, default=100)  # 1時間あたりの実行制限
    rate_limit_per_day = Column(Integer, default=1000)  # 1日あたりの実行制限
    is_enabled = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # リレーション
    account = relationship("Account", back_populates="api_config")

