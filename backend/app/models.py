from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, Enum as SQLEnum, Numeric
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
    GPT5_PRO = "gpt-5-pro"  # 最上位モデル
    GPT5 = "gpt-5"
    GPT5_1 = "gpt-5.1"  # 最新モデル
    GPT5_1_THINKING = "gpt-5.1-thinking"  # GPT-5.1 Thinking（思考時間自動調整モデル）
    GEMINI_PRO = "gemini-pro"
    GEMINI_3_PRO = "gemini-3-pro-preview"  # Gemini 3.0 Pro（最新モデル）
    GEMINI_3_PRO_DEEP_THINK = "gemini-3-pro-preview-deep-think" # Deep Think対応
    GEMINI_2_5_PRO = "gemini-2.5-pro"
    GEMINI_2_5_PRO_DEEP_THINK = "gemini-2.5-pro-deep-think" # Deep Think対応


class Account(Base):
    """アカウントテーブル"""
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    account_type = Column(String(20), nullable=False, default=AccountType.CHILD)
    is_active = Column(Boolean, default=True, nullable=False)
    total_tokens = Column(Integer, default=0, nullable=False)  # 総トークン数（全期間）
    total_cost = Column(Numeric(12, 6), default=0.0, nullable=False)  # 総料金（USD、全期間）
    total_executions = Column(Integer, default=0, nullable=False)  # 総実行回数（全期間）
    tokens_this_month = Column(Integer, default=0, nullable=False)  # 今月のトークン数
    cost_this_month = Column(Numeric(12, 6), default=0.0, nullable=False)  # 今月の料金（USD）
    executions_this_month = Column(Integer, default=0, nullable=False)  # 今月の実行回数
    last_month_reset = Column(DateTime(timezone=True), nullable=True)  # 最後に月リセットした日時
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
    enable_deep_think = Column(Boolean, default=True, nullable=False)  # Deep Think機能を有効にするか（Gemini 2.5/3系のみ）
    created_by = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    deleted_at = Column(DateTime(timezone=True), nullable=True)  # 論理削除用（削除日時）

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
    cost = Column(Numeric(10, 6), nullable=True)  # トークン料金（USD、小数点以下6桁まで）
    execution_time = Column(Integer)  # 実行時間（ミリ秒）
    status = Column(String(50))  # success, error, timeout
    error_message = Column(Text)  # エラーメッセージ
    enable_deep_think = Column(Boolean, nullable=True)  # 実行時にDeep Thinkが有効だったか（実行時点の状態を保存）
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

