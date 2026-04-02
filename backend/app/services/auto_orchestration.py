"""
自動オーケストレーション — ワークフロー構造からランタイムデフォルトを推論

ユーザーが手動設定しなくても、agent_profile やグループ構造から
品質ゲート・エラー時・出力キー・ジャッジを自動適用する。

ルール:
  1. エラー時: 全ステップで retry(1回) → 失敗なら skip
  2. 出力キー: agent_profile から自動生成 (explore_result, plan_result, ...)
  3. 品質ゲート: verification プロファイルのみ regex で VERDICT 行チェック
  4. ジャッジ: 並列グループで自動生成（ワークフロー名・目的からプロンプト構築）
  5. SV: 自動化しない（差し戻しリスクが高い）
"""
import logging
from collections import Counter
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# VERDICT 行の正規表現（agent_profiles.py の検証契約と一致）
VERDICT_REGEX = r"VERDICT\s*:\s*(PASS|FAIL|PARTIAL)"


def compute_orchestration_overrides(
    workflow,
    groups: list,
    all_workflow_skills: list,
    all_skills: dict,
) -> Dict[str, Dict[int, Dict[str, Any]]]:
    """
    ワークフロー構造からランタイムオーバーライドを計算する。

    Returns:
        {
            "workflow_skills": {
                ws_id: {"output_key": ..., "on_error": ..., "max_retries": ..., ...},
            },
            "groups": {
                group_id: {"judge_prompt": ..., "judge_model": ...},
            },
        }
    """
    overrides: Dict[str, Dict[int, Dict[str, Any]]] = {
        "workflow_skills": {},
        "groups": {},
    }

    # profile ごとの出現カウント（サフィックス用）
    profile_counter: Counter = Counter()

    for ws in all_workflow_skills:
        ws_id = ws.id
        skill = all_skills.get(ws.skill_id) if hasattr(ws, "skill_id") else None
        ws_overrides: Dict[str, Any] = {}

        # --- agent_profile を取得 ---
        profile = (
            getattr(ws, "agent_profile", None)
            or (getattr(skill, "default_agent_profile", None) if skill else None)
            or "default"
        )
        profile = profile.strip().lower()

        # --- Rule 1: エラー時 → retry(1) ---
        current_on_error = getattr(ws, "on_error", "stop") or "stop"
        current_max_retries = getattr(ws, "max_retries", 0) or 0
        if current_on_error == "stop" and current_max_retries == 0:
            ws_overrides["on_error"] = "retry"
            ws_overrides["max_retries"] = 1

        # --- Rule 2: 出力キー → profile ベース ---
        current_output_key = getattr(ws, "output_key", None)
        if not current_output_key:
            profile_counter[profile] += 1
            count = profile_counter[profile]
            base_key = f"{profile}_result"
            ws_overrides["output_key"] = base_key if count == 1 else f"{base_key}_{count}"

        # --- Rule 3: 品質ゲート → verification のみ regex ---
        current_gate_type = getattr(ws, "quality_gate_type", "disabled") or "disabled"
        current_max_loops = getattr(ws, "max_reflection_loops", 0) or 0
        if profile == "verification" and current_gate_type == "disabled" and current_max_loops == 0:
            ws_overrides["quality_gate_type"] = "regex"
            ws_overrides["quality_gate_prompt"] = VERDICT_REGEX
            ws_overrides["max_reflection_loops"] = 1

        if ws_overrides:
            overrides["workflow_skills"][ws_id] = ws_overrides

    # --- Rule 4: ジャッジ → 並列グループ ---
    wf_name = getattr(workflow, "name", "") or ""
    wf_desc = getattr(workflow, "description", "") or ""
    parent_model = getattr(workflow, "parent_model_type", None) or "gpt-5.1"

    for group in groups:
        group_id = group.id
        exec_type = getattr(group, "execution_type", "serial") or "serial"
        current_judge = getattr(group, "judge_prompt", None)

        if exec_type == "parallel" and not current_judge:
            group_name = getattr(group, "group_name", "") or f"Group {getattr(group, 'group_order', '?')}"
            # グループ内のスキル名を収集
            group_skill_names = []
            for ws in all_workflow_skills:
                if getattr(ws, "group_id", None) == group_id:
                    name = getattr(ws, "skill_name", None)
                    if not name:
                        sk = all_skills.get(ws.skill_id) if hasattr(ws, "skill_id") else None
                        name = getattr(sk, "name", None) if sk else None
                    if name:
                        group_skill_names.append(name)

            judge_prompt = _build_judge_prompt(wf_name, wf_desc, group_name, group_skill_names)
            overrides["groups"][group_id] = {
                "judge_prompt": judge_prompt,
                "judge_model": parent_model,
            }

    # ログ出力
    ws_count = len(overrides["workflow_skills"])
    grp_count = len(overrides["groups"])
    if ws_count or grp_count:
        logger.info(
            f"Auto-orchestration: {ws_count} skill overrides, {grp_count} group overrides applied"
        )

    return overrides


def get_effective(obj, field: str, overrides: Dict, obj_id: int, section: str):
    """オーバーライド値があればそれを返し、なければDB値を返す。"""
    section_overrides = overrides.get(section, {}).get(obj_id, {})
    if field in section_overrides:
        return section_overrides[field]
    return getattr(obj, field, None)


def _build_judge_prompt(
    wf_name: str, wf_desc: str, group_name: str, skill_names: List[str]
) -> str:
    skills_list = "\n".join(f"- {name}" for name in skill_names) if skill_names else "(不明)"
    return f"""あなたは並列実行グループ「{group_name}」の出力を評価するジャッジです。

ワークフロー: {wf_name}
目的: {wf_desc or '(未設定)'}

並列で実行されたスキル:
{skills_list}

各スキルの出力を比較し、以下を判定してください:
1. 最も品質の高い出力はどれか
2. 各出力の長所・短所
3. 最終的な統合結果

以下のJSON形式で回答してください:
{{"best": "最良スキル名", "reasoning": "選定理由", "merged_output": "統合された最終出力"}}
"""


def generate_leader_prompt(workflow_name: str, workflow_description: str) -> str:
    """ワークフロー名・説明からリーダースキルのプロンプトを自動生成する。"""
    return f"""あなたは「{workflow_name}」ワークフローの統合エージェントです。

目的: {workflow_description or '(未設定)'}

全ステップの出力結果があなたの入力として渡されています。
これらを統合し、ワークフローの目的に最も適した最終成果物を作成してください。

出力に含めるべき内容:
1. エグゼクティブサマリー（結論を先に）
2. 各ステップの要点と重要な発見
3. 最終成果物（目的に応じた具体的なアウトプット）
4. 今後の推奨アクション

各ステップの出力をそのまま繰り返すのではなく、統合・整理して価値のある最終レポートにまとめてください。
"""
