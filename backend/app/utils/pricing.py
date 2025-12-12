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
        "gpt-4": 30.0,  # 入力$30 + 出力$60の平均
        "gpt-4-turbo-preview": 10.0,  # 入力$10 + 出力$30の平均
        "gpt-5": 15.0,  # 仮の値
        "gpt-5-pro": 20.0,  # 仮の値
        "gpt-5.1": 25.0,  # 仮の値
        "gpt-5.1-thinking": 30.0,  # 仮の値（思考時間自動調整モデル）
        "gpt-5.2": 28.0,  # 仮の値
        "gpt-5.2-pro": 32.0,  # 仮の値
        "gpt-5.2-thinking": 35.0,  # 仮の値（思考時間自動調整モデル）
    }

    # Geminiモデルの料金（1MトークンあたりのUSD）
    gemini_pricing = {
        "gemini-pro": 0.5,  # 入力$0.25 + 出力$0.5の平均
        "gemini-2.0-flash": 0.15,  # 入力$0.075 + 出力$0.3の平均
        "gemini-2.5-flash": 0.15,  # 入力$0.075 + 出力$0.3の平均
        "gemini-2.5-pro": 1.25,  # 入力$1.25 + 出力$5.0の平均
        "gemini-3-pro-preview": 1.5,  # 入力$1.5 + 出力$6.0の平均
    }

    # モデルタイプに応じた料金を取得
    if model in openai_pricing:
        price_per_million = openai_pricing[model]
    elif model in gemini_pricing:
        price_per_million = gemini_pricing[model]
    else:
        # デフォルト値（不明なモデルの場合）
        price_per_million = 1.0

    # トークン数を100万で割って料金を計算
    cost = (tokens / 1_000_000) * price_per_million
    return cost

