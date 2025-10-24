import google.generativeai as genai
from typing import Optional
from app.config import settings


class GeminiService:
    """Google Gemini API連携サービス"""

    def __init__(self, api_key: Optional[str] = None):
        """
        Args:
            api_key: Gemini APIキー（指定しない場合は設定ファイルから取得）
        """
        self.api_key = api_key or settings.GEMINI_API_KEY
        # APIキーが未設定の場合はデモモード
        self.demo_mode = not self.api_key or self.api_key.strip() == ""
        if not self.demo_mode:
            genai.configure(api_key=self.api_key)

    async def execute_prompt(
        self,
        prompt: str,
        model: str = "gemini-1.5-pro",
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
                "tokens": int   # 使用トークン数（概算）
            }
        """
        # モデル名のマッピング（2.5-proは1.5-proにフォールバック）
        model_mapping = {
            "gemini-pro": "gemini-pro",
            "gemini-2.5-pro": "gemini-1.5-pro",
            "gemini-2.5-pro-deep-think": "gemini-1.5-pro",
        }

        model_name = model_mapping.get(model, model)

        # デモモードの場合はダミーレスポンスを返す
        if self.demo_mode:
            return {
                "output": f"【デモモード】\n\nGemini APIキーが設定されていないため、実際のAI応答は生成されません。\n\nこれはテスト用のダミーレスポンスです。\n\n実際に使用するには、.envファイルにGEMINI_API_KEYを設定してください。\n\n入力されたプロンプトの最初の100文字:\n{prompt[:100]}...",
                "model": f"{model_name} (demo)",
                "tokens": 100
            }

        try:
            generation_config = {
                "temperature": temperature,
                "max_output_tokens": max_tokens,
            }

            model_instance = genai.GenerativeModel(
                model_name=model_name,
                generation_config=generation_config
            )

            response = await model_instance.generate_content_async(prompt)

            output = response.text

            # Gemini APIはトークン数を直接返さないので、概算
            # 1トークン ≈ 4文字として計算
            estimated_tokens = (len(prompt) + len(output)) // 4

            return {
                "output": output,
                "model": model_name,
                "tokens": estimated_tokens
            }

        except Exception as e:
            raise Exception(f"Gemini API実行エラー: {str(e)}")

    async def execute_streaming(
        self,
        prompt: str,
        model: str = "gemini-1.5-pro",
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
        # モデル名のマッピング
        model_mapping = {
            "gemini-pro": "gemini-pro",
            "gemini-2.5-pro": "gemini-1.5-pro",
            "gemini-2.5-pro-deep-think": "gemini-1.5-pro",
        }

        model_name = model_mapping.get(model, model)

        try:
            generation_config = {
                "temperature": temperature,
                "max_output_tokens": max_tokens,
            }

            model_instance = genai.GenerativeModel(
                model_name=model_name,
                generation_config=generation_config
            )

            response = await model_instance.generate_content_async(
                prompt,
                stream=True
            )

            async for chunk in response:
                if chunk.text:
                    yield chunk.text

        except Exception as e:
            raise Exception(f"Gemini API実行エラー: {str(e)}")


# シングルトンインスタンス
gemini_service = GeminiService()

