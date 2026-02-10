"""
プロンプト関連のユーティリティ関数
"""
import re
import difflib


def replace_placeholders(prompt_template: str, input_data: dict) -> str:
    """
    プロンプトテンプレート内のプレースホルダーを入力データで置き換える

    プレースホルダーの形式: {variable_name}
    オプショナルフィールドが空の場合、その行を削除する

    Args:
        prompt_template: プロンプトテンプレート
        input_data: 入力データ

    Returns:
        置き換え後のプロンプト
    """
    import logging
    logger = logging.getLogger(__name__)

    logger.info(f"replace_placeholders called with input_data keys: {list(input_data.keys())}")
    logger.info(f"Prompt template length: {len(prompt_template)}")
    logger.info(f"Prompt template (first 500 chars): {prompt_template[:500]}")

    result = prompt_template
    for key, value in input_data.items():
        placeholder = f"{{{key}}}"
        logger.info(f"Processing placeholder: {placeholder}, value type: {type(value)}, value length: {len(str(value)) if value else 0}")

        # 値がNone、空文字列、または空白のみの場合は空文字列に置換
        if value is None or (isinstance(value, str) and value.strip() == ""):
            # オプショナルフィールドの行全体を削除（行末まで）
            # プレースホルダーを含む行を削除（オプション表記がある場合）
            pattern = rf".*{re.escape(placeholder)}.*\n?"
            result = re.sub(pattern, "", result)
            logger.info(f"Removed placeholder {placeholder} (empty value)")
        else:
            # プレースホルダーがテンプレートに存在するか確認
            if placeholder in result:
                result = result.replace(placeholder, str(value))
                logger.info(f"Replaced placeholder {placeholder} with value (length: {len(str(value))})")
            else:
                logger.warning(f"⚠️ Placeholder {placeholder} not found in template! Available placeholders in template: {re.findall(r'\{([^}]+)\}', prompt_template)}")

    # 連続する空行を1つにまとめる
    result = re.sub(r'\n\s*\n\s*\n+', '\n\n', result)
    logger.info(f"Final prompt length: {len(result)}")
    logger.info(f"Final prompt (first 500 chars): {result[:500]}")

    # プレースホルダーが残っていないか確認
    remaining_placeholders = re.findall(r'\{([^}]+)\}', result)
    if remaining_placeholders:
        logger.warning(f"⚠️ Remaining placeholders in final prompt: {remaining_placeholders}")

    return result


def sanitize_output(
    output_text: str,
    template_text: str,
    min_match_len: int,
    similarity_threshold: float
) -> str:
    """
    出力がテンプレート本文に過度に類似/一致する場合に赤抜きする。
    - 長い連続一致(>= min_match_len)がある場合: その部分を[REDACTED]に置換
    - 全体類似度が高い場合(ratio>=threshold): 最長一致部分を[REDACTED]
    """
    if not output_text or not template_text:
        return output_text

    matcher = difflib.SequenceMatcher(None, output_text, template_text)
    ratio = matcher.quick_ratio()
    if ratio < similarity_threshold:
        ratio = matcher.ratio()

    longest = matcher.find_longest_match(0, len(output_text), 0, len(template_text))

    should_redact = longest.size >= min_match_len or ratio >= similarity_threshold
    if not should_redact:
        return output_text

    # 一度だけ最長一致を赤抜き（必要なら将来複数回に拡張）
    start = longest.a
    end = longest.a + longest.size
    redacted = output_text[:start] + "[REDACTED]" + output_text[end:]
    return redacted

