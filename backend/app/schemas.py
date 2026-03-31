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
    anthropic_api_key: Optional[str] = None
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
    anthropic_api_key: Optional[str] = None
    rate_limit_per_hour: Optional[int] = None
    rate_limit_per_day: Optional[int] = None
    api_config_enabled: Optional[bool] = None


class AccountResponse(AccountBase):
    id: int
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


# ==================== スキル ====================
class SkillBase(BaseModel):
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


class SkillCreate(SkillBase):
    content: str  # 暗号化前のスキル内容


class SkillUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    content: Optional[str] = None  # 暗号化前のスキル内容
    model_type: Optional[str] = None
    input_schema: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None
    allows_file_output: Optional[bool] = None  # ファイル出力を許可するか
    enable_deep_think: Optional[bool] = None  # Deep Think機能を有効にするか（Gemini 2.5/3系のみ）
    # 外部ツール利用可否フラグ（エージェント側のオーケストレーション用メタデータ）
    enable_web_search: Optional[bool] = None
    enable_code_interpreter: Optional[bool] = None
    enable_file_search: Optional[bool] = None


class SkillResponse(SkillBase):
    id: int
    is_active: bool
    created_by: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    # 注意: encrypted_contentは含めない（セキュリティ）

    class Config:
        from_attributes = True


class SkillListResponse(BaseModel):
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


# ==================== アカウント-スキル紐付け ====================
class AccountSkillAssign(BaseModel):
    account_id: int
    skill_id: int


class AccountSkillResponse(BaseModel):
    id: int
    account_id: int
    skill_id: int
    assigned_at: datetime

    class Config:
        from_attributes = True


# ==================== スキル実行 ====================
class AttachmentFile(BaseModel):
    """添付ファイル"""
    filename: str
    content: str  # Base64エンコードされたファイル内容、またはテキスト内容


class ExecuteSkillRequest(BaseModel):
    skill_id: int
    input_data: Dict[str, Any]  # スキルのinput_schemaに従った入力
    output_format: Optional[str] = "txt"  # 出力形式: csv, pdf, docx, md, txt
    attachments: Optional[List[AttachmentFile]] = None  # 添付ファイル（オプション）
    enable_deep_think: Optional[bool] = None  # Deep Think機能の有効/無効（Gemini 2.5/3系のみ、Noneの場合は自動判定）


class ExecuteSkillResponse(BaseModel):
    execution_id: int
    status: str
    output: Optional[str] = None
    model_used: Optional[str] = None
    tokens_used: Optional[int] = None
    execution_time: Optional[int] = None  # ミリ秒
    file_output: Optional[Dict[str, Any]] = None  # ファイル出力情報（output_formatが指定された場合）
    job_token: Optional[str] = None  # ローカル実行時のみ返却


# ==================== 実行ログ ====================
class ExecutionResponse(BaseModel):
    id: int
    account_id: int
    skill_id: Optional[int]
    skill_name: Optional[str] = None
    # ワークフロー関連フィールド（ワークフロー実行時のみ値が入る）
    workflow_execution_id: Optional[int] = None
    workflow_skill_id: Optional[int] = None
    workflow_id: Optional[int] = None
    skill_order: Optional[int] = None
    # 表示用のワークフロー名・ステップ名
    workflow_name: Optional[str] = None
    skill_display_name: Optional[str] = None
    input_data: str
    output_data: Optional[str] = None
    model_used: str
    tokens_used: Optional[int] = None
    execution_time: Optional[int] = None
    status: str
    error_message: Optional[str] = None
    output_format: Optional[str] = "txt"  # 出力形式（csv, pdf, docx, md, txt）
    execution_role: Optional[str] = None  # null | "quality_gate" | "supervisor" | "debate_judge"
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
    anthropic_api_key: Optional[str] = None


class APIConfigUpdate(BaseModel):
    openai_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
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
    total_skills: int
    total_executions: int


class UserDashboardStats(BaseModel):
    available_skills: int  # 利用可能なスキル数
    executions_this_month: int  # 今月の実行回数
    total_tokens_this_month: int  # 今月の総トークン数
    total_cost_this_month: float  # 今月の総トークン料金（USD）


class AccountWithSkillCount(BaseModel):
    id: int
    username: str
    email: str
    account_type: AccountType
    is_active: bool
    skill_count: int
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


# ==================== ワークフロー（グループベース） ====================

class WorkflowGroupSkillItem(BaseModel):
    """グループ内のスキル"""
    id: Optional[int] = None
    skill_id: int
    skill_name: Optional[str] = None
    model_type: Optional[str] = None
    order_in_group: int = 1
    skill_display_name: Optional[str] = None
    workflow_skill_id: Optional[int] = None
    skill_order: Optional[int] = None
    # エラーリカバリ
    on_error: str = "stop"  # "stop" | "skip" | "retry"
    max_retries: int = 0
    retry_delay_seconds: int = 5
    # 明示的データマッピング
    input_mapping: Optional[Dict[str, str]] = None  # {"target_field": "steps.<key>.output"}
    output_key: Optional[str] = None
    # 品質ゲート (Reflection)
    quality_gate_type: str = "disabled"  # "disabled" | "regex" | "json_schema" | "llm"
    quality_gate_prompt: Optional[str] = None
    quality_gate_model: Optional[str] = None
    max_reflection_loops: int = 0
    # ハンドオフ
    handoff_rules: Optional[List[Dict[str, Any]]] = None


class WorkflowGroupItem(BaseModel):
    """ワークフロー内のグループ"""
    id: Optional[int] = None
    group_order: int = 1
    group_name: Optional[str] = None
    execution_type: str = "serial"  # "serial" | "parallel"
    condition_expression: Optional[Dict[str, Any]] = None  # 条件分岐式
    skip_on_condition_fail: bool = True
    # スーパーバイザー
    supervisor_prompt: Optional[str] = None
    supervisor_model: Optional[str] = None
    # 動的モード
    dynamic_mode: str = "static"  # "static" | "dynamic"
    # ジャッジ (並列合議)
    judge_prompt: Optional[str] = None
    judge_model: Optional[str] = None
    skills: List[WorkflowGroupSkillItem] = []


class WorkflowCreate(BaseModel):
    """ワークフロー作成（親スキル埋め込み + グループ構造）"""
    name: str
    description: Optional[str] = None
    input_schema: Optional[Dict[str, Any]] = None
    is_active: bool = True
    # 親スキル
    parent_skill_content: str = ""  # 暗号化前のスキル本文
    parent_model_type: str = "gpt-4o"
    parent_enable_deep_think: bool = True
    parent_enable_web_search: bool = False
    parent_enable_code_interpreter: bool = False
    parent_enable_file_search: bool = False
    parent_skill_mode: str = "required"  # "required" | "optional" | "disabled"
    supervisor_mode: str = "disabled"  # "disabled" | "after_each_group" | "after_marked_groups"
    # グループ構造
    groups: List[WorkflowGroupItem] = []


class WorkflowUpdate(BaseModel):
    """ワークフロー更新"""
    name: Optional[str] = None
    description: Optional[str] = None
    input_schema: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None
    parent_skill_content: Optional[str] = None
    parent_model_type: Optional[str] = None
    parent_enable_deep_think: Optional[bool] = None
    parent_enable_web_search: Optional[bool] = None
    parent_enable_code_interpreter: Optional[bool] = None
    parent_enable_file_search: Optional[bool] = None
    parent_skill_mode: Optional[str] = None
    supervisor_mode: Optional[str] = None
    groups: Optional[List[WorkflowGroupItem]] = None


class WorkflowResponse(BaseModel):
    """ワークフロー詳細レスポンス"""
    id: int
    name: str
    description: Optional[str] = None
    input_schema: Optional[Dict[str, Any]] = None
    is_active: bool
    # 親スキル
    parent_skill_content: Optional[str] = None  # 管理者のみ復号済みで返す
    parent_model_type: Optional[str] = None
    parent_enable_deep_think: bool = True
    parent_enable_web_search: bool = False
    parent_enable_code_interpreter: bool = False
    parent_enable_file_search: bool = False
    parent_skill_mode: str = "required"
    supervisor_mode: str = "disabled"
    # メタ
    created_by: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    # グループ構造
    groups: List[WorkflowGroupItem] = []
    # 後方互換（フラットなスキル一覧）
    skills: List[Any] = []


class WorkflowListItem(BaseModel):
    """一覧用のサマリー"""
    id: int
    name: str
    description: Optional[str] = None
    is_active: bool
    parent_model_type: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    groups: List[WorkflowGroupItem] = []

    class Config:
        from_attributes = True


# 後方互換スキーマ（既存コードが参照）
class WorkflowSkillItem(BaseModel):
    id: Optional[int] = None
    skill_order: int = 0
    skill_name: Optional[str] = None
    skill_id: int = 0
    skill_display_name: Optional[str] = None


class WorkflowSkillUpdateItem(BaseModel):
    skill_id: int
    skill_order: int = 0
    skill_name: Optional[str] = None
    config_json: Optional[dict] = None


class WorkflowSkillsUpdateRequest(BaseModel):
    skills: List[WorkflowSkillUpdateItem]


class ParentSkillData(BaseModel):
    """親スキルデータ"""
    name: str = ""
    description: Optional[str] = None
    content: str = ""
    model_type: str = "gpt-4o"
    input_schema: Optional[Dict[str, Any]] = None
    enable_deep_think: bool = True
    enable_web_search: bool = False
    enable_code_interpreter: bool = False
    enable_file_search: bool = False


class WorkflowCreateWithParentSkill(BaseModel):
    """親スキル付きワークフロー作成"""
    name: str
    description: Optional[str] = None
    input_schema: Optional[Dict[str, Any]] = None
    is_active: bool = True
    parent_skill: ParentSkillData
    parent_skill_mode: str = "required"  # "required" | "optional" | "disabled"
    supervisor_mode: str = "disabled"  # "disabled" | "after_each_group" | "after_marked_groups"
    skills: List[WorkflowSkillUpdateItem] = []
    groups: Optional[List[WorkflowGroupItem]] = None


class UserWorkflowSummary(BaseModel):
    """ユーザー用ワークフロー一覧の1件"""

    workflow: WorkflowListItem
    skills: List[SkillListResponse]


class UserWorkflowDetailSkill(BaseModel):
    """ユーザー用ワークフロー詳細の1ステップ"""

    workflow_skill_id: int
    skill_order: int
    skill_name: Optional[str] = None
    skill_id: int
    skill_display_name: str


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
    job_token: Optional[str] = None  # ローカル実行時のみ
