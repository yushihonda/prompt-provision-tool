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
        # サポートするプレースホルダー形式:
        # - {key}
        # - {{key}}  （既存プロンプトとの互換性のため）
        placeholder_single = f"{{{key}}}"
        placeholder_double = f"{{{{{key}}}}}"
        logger.info(
            f"Processing placeholder: single={placeholder_single}, double={placeholder_double}, "
            f"value type: {type(value)}, value length: {len(str(value)) if value else 0}"
        )

        # 値がNone、空文字列、または空白のみの場合は空文字列に置換
        if value is None or (isinstance(value, str) and value.strip() == ""):
            # オプショナルフィールドの行全体を削除（行末まで）
            # プレースホルダーを含む行を削除（オプション表記がある場合）
            # 単一波括弧/二重波括弧のどちらにも対応
            pattern_single = rf".*{re.escape(placeholder_single)}.*\n?"
            pattern_double = rf".*{re.escape(placeholder_double)}.*\n?"
            before_len = len(result)
            result = re.sub(pattern_single, "", result)
            result = re.sub(pattern_double, "", result)
            logger.info(
                f"Removed placeholder {placeholder_single}/{placeholder_double} (empty value), "
                f"length {before_len} -> {len(result)}"
            )
        else:
            # プレースホルダーがテンプレートに存在するか確認
            replaced_any = False
            if placeholder_single in result:
                result = result.replace(placeholder_single, str(value))
                replaced_any = True
                logger.info(
                    f"Replaced placeholder {placeholder_single} with value "
                    f"(length: {len(str(value))})"
                )
            if placeholder_double in result:
                result = result.replace(placeholder_double, str(value))
                replaced_any = True
                logger.info(
                    f"Replaced placeholder {placeholder_double} with value "
                    f"(length: {len(str(value))})"
                )

            if not replaced_any:
                logger.warning(
                    f"⚠️ Placeholders {placeholder_single}/{placeholder_double} not found in template! "
                    f"Available single-brace placeholders in template: "
                    f"{re.findall(r'\\{([^}]+)\\}', prompt_template)}"
                )

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

