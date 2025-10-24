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


class AccountUpdate(BaseModel):
    email: Optional[EmailStr] = None
    password: Optional[str] = None
    is_active: Optional[bool] = None


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


class PromptCreate(PromptBase):
    content: str  # 暗号化前のプロンプト内容


class PromptUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    content: Optional[str] = None  # 暗号化前のプロンプト内容
    model_type: Optional[str] = None
    input_schema: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None


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
class ExecutePromptRequest(BaseModel):
    prompt_id: int
    input_data: Dict[str, Any]  # プロンプトのinput_schemaに従った入力


class ExecutePromptResponse(BaseModel):
    output: str
    model_used: str
    tokens_used: Optional[int] = None
    execution_time: int  # ミリ秒
    status: str


# ==================== 実行ログ ====================
class ExecutionResponse(BaseModel):
    id: int
    account_id: int
    prompt_id: Optional[int]
    prompt_name: Optional[str] = None
    input_data: str
    output_data: str
    model_used: str
    tokens_used: Optional[int]
    execution_time: int
    status: str
    error_message: Optional[str] = None
    executed_at: datetime
    
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
    executions_today: int
    executions_this_month: int


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

