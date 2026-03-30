from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, Enum as SQLEnum, Numeric, Date
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import enum


class AccountType(str, enum.Enum):
    """アカウントタイプ"""
    PARENT = "PARENT"  # 親アカウント（管理者）
    CHILD = "CHILD"    # 子アカウント（外部ユーザー）


class ExecutionMode(str, enum.Enum):
    """実行モード"""
    SERVER = "server"              # サーバー実行（従来）
    LOCAL_PROXY = "local_proxy"    # ローカルワーカー → サーバー代理 LLM 実行
    LOCAL_DIRECT = "local_direct"  # ローカルワーカー → 直接 LLM 実行


class ModelType(str, enum.Enum):
    """AIモデルタイプ"""
    GPT4 = "gpt-4"
    GPT4_TURBO = "gpt-4-turbo-preview"
    GPT5_PRO = "gpt-5-pro"
    GPT5 = "gpt-5"
    GPT5_1 = "gpt-5.1"
    GPT5_1_THINKING = "gpt-5.1-thinking"
    GPT5_2 = "gpt-5.2"
    GPT5_2_PRO = "gpt-5.2-pro"
    GPT5_2_THINKING = "gpt-5.2-thinking"
    GEMINI_PRO = "gemini-pro"
    GEMINI_3_PRO = "gemini-3-pro-preview"
    GEMINI_3_PRO_DEEP_THINK = "gemini-3-pro-preview-deep-think"
    GEMINI_2_5_PRO = "gemini-2.5-pro"
    GEMINI_2_5_PRO_DEEP_THINK = "gemini-2.5-pro-deep-think"


class Account(Base):
    """アカウントテーブル"""
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    account_type = Column(String(20), nullable=False, default=AccountType.CHILD)
    is_active = Column(Boolean, default=True, nullable=False)
    total_tokens = Column(Integer, default=0, nullable=False)
    total_cost = Column(Numeric(12, 6), default=0.0, nullable=False)
    total_executions = Column(Integer, default=0, nullable=False)
    tokens_this_month = Column(Integer, default=0, nullable=False)
    cost_this_month = Column(Numeric(12, 6), default=0.0, nullable=False)
    executions_this_month = Column(Integer, default=0, nullable=False)
    last_month_reset = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # リレーション
    skills_created = relationship("Skill", back_populates="creator", foreign_keys="Skill.created_by")
    account_skills = relationship("AccountSkill", back_populates="account", cascade="all, delete-orphan")
    executions = relationship("Execution", back_populates="account", cascade="all, delete-orphan")
    api_config = relationship("APIConfig", back_populates="account", uselist=False, cascade="all, delete-orphan")
    daily_execution_counts = relationship("DailyExecutionCount", back_populates="account", cascade="all, delete-orphan")


class Skill(Base):
    """スキルテーブル（暗号化保存）"""
    __tablename__ = "skills"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    description = Column(Text)
    encrypted_content = Column(Text, nullable=False)  # 暗号化されたスキル内容
    model_type = Column(String(100), nullable=False)
    input_schema = Column(Text)  # JSON形式で入力フィールドの定義を保存
    is_active = Column(Boolean, default=True, nullable=False)
    allows_file_output = Column(Boolean, default=False, nullable=False)
    enable_deep_think = Column(Boolean, default=True, nullable=False)
    enable_web_search = Column(Boolean, default=False, nullable=False)
    enable_code_interpreter = Column(Boolean, default=False, nullable=False)
    enable_file_search = Column(Boolean, default=False, nullable=False)
    created_by = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    # リレーション
    creator = relationship("Account", back_populates="skills_created", foreign_keys=[created_by])
    account_skills = relationship("AccountSkill", back_populates="skill", cascade="all, delete-orphan")
    executions = relationship("Execution", back_populates="skill", cascade="all, delete-orphan")


class Workflow(Base):
    """ワークフローテーブル"""
    __tablename__ = "workflows"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    description = Column(Text)
    input_schema = Column(Text, nullable=True)  # ワークフロー共通入力スキーマ（JSON形式）
    is_active = Column(Boolean, default=True, nullable=False)
    created_by = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    # 親スキル (Parent Skill) — ワークフローに直接埋め込み
    encrypted_parent_content = Column(Text, nullable=True)
    parent_model_type = Column(String(100), nullable=True, default="gpt-4o")
    parent_enable_deep_think = Column(Boolean, default=True, nullable=False)
    parent_enable_web_search = Column(Boolean, default=False, nullable=False)
    parent_enable_code_interpreter = Column(Boolean, default=False, nullable=False)
    parent_enable_file_search = Column(Boolean, default=False, nullable=False)

    # リレーション
    creator = relationship("Account")
    groups = relationship("WorkflowGroup", back_populates="workflow", cascade="all, delete-orphan", order_by="WorkflowGroup.group_order")
    skills = relationship("WorkflowSkill", back_populates="workflow", cascade="all, delete-orphan")


class WorkflowGroup(Base):
    """ワークフロー内のグループ（直列/並列の実行単位）"""
    __tablename__ = "workflow_groups"

    id = Column(Integer, primary_key=True, index=True)
    workflow_id = Column(Integer, ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True)
    group_order = Column(Integer, nullable=False)
    group_name = Column(String(255), nullable=True)
    execution_type = Column(String(20), nullable=False, default="serial")  # 'serial' | 'parallel'
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # リレーション
    workflow = relationship("Workflow", back_populates="groups")
    skills = relationship("WorkflowSkill", back_populates="group", cascade="all, delete-orphan", order_by="WorkflowSkill.order_in_group")


class WorkflowSkill(Base):
    """ワークフロー内のスキル"""
    __tablename__ = "workflow_skills"

    id = Column(Integer, primary_key=True, index=True)
    workflow_id = Column(Integer, ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True)
    skill_id = Column(Integer, ForeignKey("skills.id", ondelete="CASCADE"), nullable=False, index=True)
    skill_order = Column(Integer, nullable=False)  # 全体での順序
    skill_name = Column(String(255))
    config_json = Column(Text)
    depends_on = Column(Text, nullable=True)

    # グループ所属
    group_id = Column(Integer, ForeignKey("workflow_groups.id", ondelete="CASCADE"), nullable=True, index=True)
    order_in_group = Column(Integer, nullable=True)

    # リレーション
    workflow = relationship("Workflow", back_populates="skills")
    skill = relationship("Skill")
    group = relationship("WorkflowGroup", back_populates="skills")


class WorkflowExecution(Base):
    """ワークフロー実行テーブル"""
    __tablename__ = "workflow_executions"

    id = Column(Integer, primary_key=True, index=True)
    workflow_id = Column(Integer, ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(50), nullable=False, default="pending")
    current_step = Column(Integer, nullable=True)
    total_steps = Column(Integer, nullable=False)
    global_input_data = Column(Text)
    per_skill_input_data = Column(Text)  # JSON: {workflow_skill_id: {field: value}}
    error_message = Column(Text)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # リレーション
    workflow = relationship("Workflow")
    account = relationship("Account")
    executions = relationship("Execution", back_populates="workflow_execution", order_by="Execution.skill_order")


class AccountSkill(Base):
    """アカウントとスキルの紐付けテーブル"""
    __tablename__ = "account_skills"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    skill_id = Column(Integer, ForeignKey("skills.id", ondelete="CASCADE"), nullable=False)
    assigned_at = Column(DateTime(timezone=True), server_default=func.now())

    # リレーション
    account = relationship("Account", back_populates="account_skills")
    skill = relationship("Skill", back_populates="account_skills")


class Execution(Base):
    """実行ログテーブル"""
    __tablename__ = "executions"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    skill_id = Column(Integer, ForeignKey("skills.id", ondelete="SET NULL"), nullable=True)
    workflow_execution_id = Column(Integer, ForeignKey("workflow_executions.id", ondelete="SET NULL"), nullable=True, index=True)
    workflow_skill_id = Column(Integer, ForeignKey("workflow_skills.id", ondelete="SET NULL"), nullable=True)
    skill_order = Column(Integer, nullable=True)  # ワークフロー内のスキル順序
    input_data = Column(Text)
    output_data = Column(Text)
    model_used = Column(String(100))
    tokens_used = Column(Integer)
    cost = Column(Numeric(10, 6), nullable=True)
    execution_time = Column(Integer)  # ミリ秒
    status = Column(String(50))  # success, error, timeout, pending, processing, pending_local, cancelled
    error_message = Column(Text)
    enable_deep_think = Column(Boolean, nullable=True)
    output_format = Column(String(10), nullable=True, default="txt")
    dispatch_mode = Column(String(30), nullable=False, default="server")
    lease_token_hash = Column(String(128), nullable=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    executed_at = Column(DateTime(timezone=True), server_default=func.now())

    # リレーション
    account = relationship("Account", back_populates="executions")
    skill = relationship("Skill", back_populates="executions")
    workflow_execution = relationship("WorkflowExecution", back_populates="executions")
    workflow_skill = relationship("WorkflowSkill")


class APIConfig(Base):
    """子アカウントのAPI設定テーブル"""
    __tablename__ = "api_configs"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), unique=True, nullable=False)
    openai_api_key = Column(Text)  # Fernet暗号化後は長くなるためText
    gemini_api_key = Column(Text)  # Fernet暗号化後は長くなるためText
    anthropic_api_key = Column(Text)  # Fernet暗号化後は長くなるためText
    rate_limit_per_hour = Column(Integer, default=100)
    rate_limit_per_day = Column(Integer, default=1000)
    is_enabled = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # リレーション
    account = relationship("Account", back_populates="api_config")


class DailyExecutionCount(Base):
    """日ごとの実行回数テーブル"""
    __tablename__ = "daily_execution_counts"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    count = Column(Integer, nullable=False, server_default="0")

    # リレーション
    account = relationship("Account", back_populates="daily_execution_counts")


class WorkerAPIKey(Base):
    """ローカルワーカー認証用APIキーテーブル"""
    __tablename__ = "worker_api_keys"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    key_hash = Column(String(128), nullable=False, unique=True)
    name = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_used_at = Column(DateTime(timezone=True), nullable=True)

    # リレーション
    account = relationship("Account")
