"""
トークン料金計算ユーティリティ
"""


def calculate_token_cost(model_type: str, tokens: int) -> float:
    """
    モデルタイプとトークン数から料金を計算（USD単位）

    注意: 料金は2024年時点の概算値です。実際の料金は各プロバイダーの最新情報を参照してください。

    Args:
        model_type: モデルタイプ（例: "gpt-4", "gemini-2.5-pro"）
        tokens: 使用トークン数

    Returns:
        料金（USD、float）
    """
    if not tokens or tokens <= 0:
        return 0.0

    # モデル名を正規化（-deep-thinkサフィックスを削除）
    model = model_type.replace("-deep-think", "") if model_type else ""

    # OpenAIモデルの料金（1MトークンあたりのUSD）
    # 入力と出力で料金が異なる場合、平均値を使用
    openai_pricing = {
        "gpt-5.4": 8.25,
        "gpt-5.4-mini": 1.6,
        "gpt-5.4-pro": 35.0,
        "gpt-5.4-thinking": 38.0,
        "gpt-5.2": 28.0,
        "gpt-5.2-pro": 32.0,
        "gpt-5.2-thinking": 35.0,
        "o4-mini": 2.75,           # 推論/コード コスパ
    }

    # Geminiモデルの料金（1MトークンあたりのUSD）
    gemini_pricing = {
        "gemini-3.1-pro-preview": 7.0,
        "gemini-3-pro-preview": 1.5,
        "gemini-2.5-pro": 1.25,        # 推論/コード強い
        "gemini-2.5-flash": 0.15,
    }

    # Claudeモデルの料金（1MトークンあたりのUSD）
    claude_pricing = {
        "claude-opus-4-6": 22.5,
        "claude-opus-4-6-thinking": 27.0,     # Thinking追加コスト
        "claude-sonnet-4-6": 9.0,
        "claude-sonnet-4-6-thinking": 12.0,   # Thinking追加コスト
        "claude-haiku-4-5": 1.25,
    }

    # モデルタイプに応じた料金を取得
    if model in openai_pricing:
        price_per_million = openai_pricing[model]
    elif model in gemini_pricing:
        price_per_million = gemini_pricing[model]
    elif model in claude_pricing:
        price_per_million = claude_pricing[model]
    else:
        # デフォルト値（不明なモデルの場合）
        price_per_million = 1.0

    # トークン数を100万で割って料金を計算
    cost = (tokens / 1_000_000) * price_per_million
    return cost

