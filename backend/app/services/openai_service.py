from openai import AsyncOpenAI
from typing import Optional
from app.config import settings


class OpenAIService:
    """OpenAI API連携サービス"""
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Args:
            api_key: OpenAI APIキー（指定しない場合は設定ファイルから取得）
        """
        self.api_key = api_key or settings.OPENAI_API_KEY
        # APIキーが未設定の場合はデモモード
        self.demo_mode = not self.api_key or self.api_key.strip() == ""
        if not self.demo_mode:
            self.client = AsyncOpenAI(api_key=self.api_key)
        else:
            self.client = None
    
    async def execute_prompt(
        self,
        prompt: str,
        model: str = "gpt-4-turbo-preview",
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> dict:
        """
        プロンプトを実行
        
        Args:
            prompt: 実行するプロンプト（ユーザー入力と結合済み）
            model: 使用するモデル
            temperature: 温度パラメータ
            max_tokens: 最大トークン数
            
        Returns:
            {
                "output": str,  # 生成されたテキスト
                "model": str,   # 使用されたモデル
                "tokens": int   # 使用トークン数
            }
        """
        # モデル名はそのまま使用（既に文字列として渡される）
        model_name = model
        
        # デモモードの場合はダミーレスポンスを返す
        if self.demo_mode:
            return {
                "output": f"【デモモード】\n\nOpenAI APIキーが設定されていないため、実際のAI応答は生成されません。\n\nこれはテスト用のダミーレスポンスです。\n\n実際に使用するには、.envファイルにOPENAI_API_KEYを設定してください。\n\n入力されたプロンプトの最初の100文字:\n{prompt[:100]}...",
                "model": f"{model_name} (demo)",
                "tokens": 100
            }
        
        try:
            response = await self.client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                temperature=temperature,
                max_tokens=max_tokens
            )
            
            output = response.choices[0].message.content
            tokens_used = response.usage.total_tokens
            
            return {
                "output": output,
                "model": model_name,
                "tokens": tokens_used
            }
        
        except Exception as e:
            raise Exception(f"OpenAI API実行エラー: {str(e)}")
    
    async def execute_streaming(
        self,
        prompt: str,
        model: str = "gpt-4-turbo-preview",
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ):
        """
        ストリーミングでプロンプトを実行
        
        Args:
            prompt: 実行するプロンプト
            model: 使用するモデル
            temperature: 温度パラメータ
            max_tokens: 最大トークン数
            
        Yields:
            生成されたテキストのチャンク
        """
        # モデル名はそのまま使用
        model_name = model
        
        try:
            stream = await self.client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True
            )
            
            async for chunk in stream:
                if chunk.choices[0].delta.content is not None:
                    yield chunk.choices[0].delta.content
        
        except Exception as e:
            raise Exception(f"OpenAI API実行エラー: {str(e)}")


# シングルトンインスタンス
openai_service = OpenAIService()

