from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from app.models import AccountType


# ==================== 認証 ====================
class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: Optional[str] = None
    account_type: Optional[str] = None


class LoginRequest(BaseModel):
    username: str
    password: str


# ==================== アカウント ====================
class AccountBase(BaseModel):
    username: str
    email: EmailStr
    account_type: AccountType


class AccountCreate(AccountBase):
    password: str
    # API設定（オプション）
    openai_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None
    rate_limit_per_hour: Optional[int] = 100
    rate_limit_per_day: Optional[int] = 1000
    api_config_enabled: Optional[bool] = True


class AccountUpdate(BaseModel):
    email: Optional[EmailStr] = None
    password: Optional[str] = None
    is_active: Optional[bool] = None
    # API設定（オプション）
    openai_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None
    rate_limit_per_hour: Optional[int] = None
    rate_limit_per_day: Optional[int] = None
    api_config_enabled: Optional[bool] = None


class AccountResponse(AccountBase):
    id: int
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


# ==================== プロンプト ====================
class PromptBase(BaseModel):
    name: str
    description: Optional[str] = None
    model_type: str
    input_schema: Optional[Dict[str, Any]] = None
    allows_file_output: bool = False  # ファイル出力を許可するか
    enable_deep_think: bool = True  # Deep Think機能を有効にするか（Gemini 2.5/3系のみ、デフォルト: True）
    # 外部ツール利用可否フラグ（エージェント側のオーケストレーション用メタデータ）
    enable_web_search: bool = False
    enable_code_interpreter: bool = False
    enable_file_search: bool = False


class PromptCreate(PromptBase):
    content: str  # 暗号化前のプロンプト内容


class PromptUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    content: Optional[str] = None  # 暗号化前のプロンプト内容
    model_type: Optional[str] = None
    input_schema: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None
    allows_file_output: Optional[bool] = None  # ファイル出力を許可するか
    enable_deep_think: Optional[bool] = None  # Deep Think機能を有効にするか（Gemini 2.5/3系のみ）
    # 外部ツール利用可否フラグ（エージェント側のオーケストレーション用メタデータ）
    enable_web_search: Optional[bool] = None
    enable_code_interpreter: Optional[bool] = None
    enable_file_search: Optional[bool] = None


class PromptResponse(PromptBase):
    id: int
    is_active: bool
    created_by: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    # 注意: encrypted_contentは含めない（セキュリティ）

    class Config:
        from_attributes = True


class PromptListResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    model_type: str
    allows_file_output: bool = False  # ファイル出力を許可するか
    enable_deep_think: bool = True  # Deep Think機能を有効にするか
    enable_web_search: bool = False
    enable_code_interpreter: bool = False
    enable_file_search: bool = False

    class Config:
        from_attributes = True


# ==================== アカウント-プロンプト紐付け ====================
class AccountPromptAssign(BaseModel):
    account_id: int
    prompt_id: int


class AccountPromptResponse(BaseModel):
    id: int
    account_id: int
    prompt_id: int
    assigned_at: datetime

    class Config:
        from_attributes = True


# ==================== プロンプト実行 ====================
class AttachmentFile(BaseModel):
    """添付ファイル"""
    filename: str
    content: str  # Base64エンコードされたファイル内容、またはテキスト内容


class ExecutePromptRequest(BaseModel):
    prompt_id: int
    input_data: Dict[str, Any]  # プロンプトのinput_schemaに従った入力
    output_format: Optional[str] = "txt"  # 出力形式: csv, pdf, docx, md, txt
    attachments: Optional[List[AttachmentFile]] = None  # 添付ファイル（オプション）
    enable_deep_think: Optional[bool] = None  # Deep Think機能の有効/無効（Gemini 2.5/3系のみ、Noneの場合は自動判定）


class ExecutePromptResponse(BaseModel):
    execution_id: int
    status: str
    output: Optional[str] = None
    model_used: Optional[str] = None
    tokens_used: Optional[int] = None
    execution_time: Optional[int] = None  # ミリ秒
    file_output: Optional[Dict[str, Any]] = None  # ファイル出力情報（output_formatが指定された場合）


# ==================== 実行ログ ====================
class ExecutionResponse(BaseModel):
    id: int
    account_id: int
    prompt_id: Optional[int]
    prompt_name: Optional[str] = None
    # ワークフロー関連フィールド（ワークフロー実行時のみ値が入る）
    workflow_execution_id: Optional[int] = None
    workflow_skill_id: Optional[int] = None
    step_order: Optional[int] = None
    # 表示用のワークフロー名・ステップ名
    workflow_name: Optional[str] = None
    step_name: Optional[str] = None
    input_data: str
    output_data: Optional[str] = None
    model_used: str
    tokens_used: Optional[int] = None
    execution_time: Optional[int] = None
    status: str
    error_message: Optional[str] = None
    output_format: Optional[str] = "txt"  # 出力形式（csv, pdf, docx, md, txt）
    executed_at: datetime
    # Deep Think有効フラグ（履歴詳細表示用）
    enable_deep_think: Optional[bool] = None

    class Config:
        from_attributes = True


# ==================== API設定 ====================
class APIConfigBase(BaseModel):
    rate_limit_per_hour: int = 100
    rate_limit_per_day: int = 1000
    is_enabled: bool = True


class APIConfigCreate(APIConfigBase):
    account_id: int
    openai_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None


class APIConfigUpdate(BaseModel):
    openai_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None
    rate_limit_per_hour: Optional[int] = None
    rate_limit_per_day: Optional[int] = None
    is_enabled: Optional[bool] = None


class APIConfigResponse(APIConfigBase):
    id: int
    account_id: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    # 注意: APIキーは含めない（セキュリティ）

    class Config:
        from_attributes = True


# ==================== 統計・ダッシュボード ====================
class DashboardStats(BaseModel):
    total_accounts: int
    total_prompts: int
    total_executions: int


class UserDashboardStats(BaseModel):
    available_prompts: int  # 利用可能なプロンプト数
    executions_this_month: int  # 今月の実行回数
    total_tokens_this_month: int  # 今月の総トークン数
    total_cost_this_month: float  # 今月の総トークン料金（USD）


class AccountWithPromptCount(BaseModel):
    id: int
    username: str
    email: str
    account_type: AccountType
    is_active: bool
    prompt_count: int
    execution_count: int

    class Config:
        from_attributes = True


# ==================== 監視機能 ====================
class CeleryWorkerInfo(BaseModel):
    """Celery Worker情報"""
    name: str
    status: str  # online, offline
    active_tasks: int  # 実行中タスク数
    reserved_tasks: int  # 待機中タスク数
    total_tasks_completed: Optional[int] = None  # 完了タスク数
    total_tasks_failed: Optional[int] = None  # 失敗タスク数


class CeleryWorkerStats(BaseModel):
    """Celery Worker統計情報"""
    workers: List[CeleryWorkerInfo]
    total_workers: int
    total_active_tasks: int
    total_reserved_tasks: int
    celery_available: bool


class RedisStats(BaseModel):
    """Redis統計情報"""
    connection_status: str  # connected, disconnected
    memory_used_mb: Optional[float] = None
    memory_max_mb: Optional[float] = None
    memory_usage_percent: Optional[float] = None
    stream_count: int
    active_streams: List[str]  # アクティブなStream一覧（最大10件）


class TaskStats(BaseModel):
    """タスク統計情報"""
    period_hours: int  # 集計期間（時間）
    total_executions: int
    successful: int
    failed: int
    cancelled: int
    success_rate: float  # 成功率（0.0-1.0）
    error_rate: float  # エラー率（0.0-1.0）
    average_execution_time_ms: Optional[float] = None
    max_execution_time_ms: Optional[int] = None


# ==================== ページネーション ====================
class PaginatedResponse(BaseModel):
    """ページネーション用のレスポンスモデル"""
    items: List[Any]
    total: int
    skip: int
    limit: int


# ==================== ワークフロー / Skill ====================


class WorkflowBase(BaseModel):
    name: str
    description: Optional[str] = None
    input_schema: Optional[Dict[str, Any]] = None
    is_active: bool = True
    # ワークフロー専用の統合プロンプト（リーダー）ID
    leader_prompt_id: Optional[int] = None


class WorkflowCreate(WorkflowBase):
    pass


class WorkflowUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    input_schema: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None
    leader_prompt_id: Optional[int] = None


class WorkflowSkillItem(BaseModel):
    """ワークフロー内の1ステップ（管理画面・ユーザー共通用の軽量表現）"""

    id: Optional[int] = None  # workflow_skill_id
    step_order: int
    step_name: Optional[str] = None
    prompt_id: int
    prompt_name: Optional[str] = None


class WorkflowResponse(WorkflowBase):
    id: int
    created_by: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    skills: List[WorkflowSkillItem] = []

    class Config:
        from_attributes = True


class WorkflowListItem(BaseModel):
    """一覧用のサマリー"""

    id: int
    name: str
    description: Optional[str] = None
    input_schema: Optional[Dict[str, Any]] = None
    is_active: bool
    leader_prompt_id: Optional[int] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class WorkflowSkillUpdateItem(BaseModel):
    """/api/admin/workflows/{id}/skills 用入力"""

    prompt_id: int
    step_order: int
    step_name: Optional[str] = None
    config_json: Optional[dict] = None


class WorkflowSkillsUpdateRequest(BaseModel):
    skills: List[WorkflowSkillUpdateItem]


class LeaderPromptData(BaseModel):
    """ワークフロー作成時の親プロンプトデータ"""
    name: str
    description: Optional[str] = None
    content: str  # プロンプト本文
    model_type: str = "gpt-5.1"
    input_schema: Optional[Dict[str, Any]] = None
    enable_deep_think: bool = True
    enable_web_search: bool = False
    enable_code_interpreter: bool = False
    enable_file_search: bool = False


class WorkflowCreateWithPrompt(BaseModel):
    """親プロンプトと子プロンプトを含むワークフロー作成リクエスト"""
    name: str
    description: Optional[str] = None
    input_schema: Optional[Dict[str, Any]] = None
    is_active: bool = True
    leader_prompt: LeaderPromptData
    skills: List[WorkflowSkillUpdateItem] = []  # 子プロンプト（Skills）のリスト


class UserWorkflowSummary(BaseModel):
    """ユーザー用ワークフロー一覧の1件"""

    workflow: WorkflowListItem
    skills: List[PromptListResponse]


class UserWorkflowDetailSkill(BaseModel):
    """ユーザー用ワークフロー詳細の1ステップ"""

    workflow_skill_id: int
    step_order: int
    step_name: Optional[str] = None
    prompt_id: int
    prompt_name: str


class UserWorkflowDetail(BaseModel):
    """ユーザー用ワークフロー詳細"""

    workflow: WorkflowListItem
    skills: List[UserWorkflowDetailSkill]
    input_schema: Optional[Dict[str, Any]] = None


class ExecuteWorkflowRequest(BaseModel):
    """ワークフロー実行リクエスト"""

    workflow_id: int
    global_input_data: Dict[str, Any]
    per_skill_input: Optional[Dict[int, Dict[str, Any]]] = None  # key: workflow_skill_id
    output_format: Optional[str] = "txt"


class ExecuteWorkflowResponse(BaseModel):
    workflow_id: int
    workflow_execution_id: int  # ワークフロー実行ID
    execution_ids: List[int]

