import json
import unittest
from types import SimpleNamespace
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.agent_profiles import extract_verdict, AGENT_PROFILE_PROMPTS
from app.services.completion_service import _persist_workflow_metadata


class VerificationPromptTests(unittest.TestCase):
    """Verification プロンプトに証跡フォーマットと adversarial probe が含まれること"""

    def test_prompt_contains_evidence_format_check(self):
        prompt = AGENT_PROFILE_PROMPTS["verification"]
        self.assertIn("### Check:", prompt)

    def test_prompt_contains_evidence_format_command_run(self):
        prompt = AGENT_PROFILE_PROMPTS["verification"]
        self.assertIn("**Command run:**", prompt)

    def test_prompt_contains_evidence_format_output_observed(self):
        prompt = AGENT_PROFILE_PROMPTS["verification"]
        self.assertIn("**Output observed:**", prompt)

    def test_prompt_contains_evidence_format_result(self):
        prompt = AGENT_PROFILE_PROMPTS["verification"]
        self.assertIn("**Result:** PASS|FAIL", prompt)

    def test_prompt_contains_content_evidence_format(self):
        prompt = AGENT_PROFILE_PROMPTS["verification"]
        self.assertIn("**根拠:**", prompt)

    def test_prompt_requires_adversarial_probe(self):
        prompt = AGENT_PROFILE_PROMPTS["verification"]
        self.assertIn("Adversarial Probe", prompt)
        self.assertIn("壊しテスト", prompt)

    def test_prompt_requires_verdict_line(self):
        prompt = AGENT_PROFILE_PROMPTS["verification"]
        self.assertIn("VERDICT: PASS", prompt)
        self.assertIn("VERDICT: FAIL", prompt)
        self.assertIn("VERDICT: PARTIAL", prompt)


class ExtractVerdictTests(unittest.TestCase):
    def test_extracts_verdict_from_json_payload(self):
        self.assertEqual(extract_verdict('{"verdict":"PASS"}'), "PASS")

    def test_extracts_verdict_from_explicit_final_line(self):
        self.assertEqual(
            extract_verdict("## 5. Final Verdict\nVERDICT: FAIL"),
            "FAIL",
        )

    def test_extracts_verdict_from_text_body_with_regex_fallback(self):
        self.assertEqual(
            extract_verdict("Verification Summary\nsome text VERDICT: PARTIAL more text"),
            "PARTIAL",
        )

    def test_returns_none_when_verdict_cannot_be_extracted(self):
        self.assertIsNone(extract_verdict("verification output without canonical verdict"))

    def test_extracts_verdict_case_insensitive(self):
        self.assertEqual(extract_verdict("verdict: pass"), "PASS")
        self.assertEqual(extract_verdict("Verdict: Fail"), "FAIL")

    def test_extracts_verdict_with_extra_whitespace(self):
        self.assertEqual(extract_verdict("VERDICT:  PASS  "), "PASS")
        self.assertEqual(extract_verdict("  VERDICT: FAIL"), "FAIL")

    def test_extracts_first_verdict_when_multiple(self):
        text = "VERDICT: PARTIAL\nsome text\nVERDICT: PASS"
        self.assertEqual(extract_verdict(text), "PARTIAL")

    def test_returns_none_for_empty_and_none(self):
        self.assertIsNone(extract_verdict(None))
        self.assertIsNone(extract_verdict(""))

    def test_extracts_verdict_from_json_case_insensitive(self):
        self.assertEqual(extract_verdict('{"verdict":"partial"}'), "PARTIAL")


class ExtractStructuredEnvelopeTests(unittest.TestCase):
    """_extract_structured_envelope のテスト"""

    def test_extracts_from_top_level_json(self):
        from app.services.completion_service import _extract_structured_envelope
        output = '{"summary": "短い要約", "key_points": ["要点1"]}'
        result = _extract_structured_envelope(output)
        self.assertIsNotNone(result)
        self.assertEqual(result["summary"], "短い要約")

    def test_extracts_from_trailing_json_block(self):
        from app.services.completion_service import _extract_structured_envelope
        output = '本文テキスト\n\n```json\n{"summary": "末尾の要約", "key_points": ["a"]}\n```'
        result = _extract_structured_envelope(output)
        self.assertIsNotNone(result)
        self.assertEqual(result["summary"], "末尾の要約")

    def test_returns_none_for_no_envelope(self):
        from app.services.completion_service import _extract_structured_envelope
        self.assertIsNone(_extract_structured_envelope("普通のテキスト出力"))
        self.assertIsNone(_extract_structured_envelope(None))
        self.assertIsNone(_extract_structured_envelope(""))

    def test_returns_none_for_json_without_summary(self):
        from app.services.completion_service import _extract_structured_envelope
        self.assertIsNone(_extract_structured_envelope('{"key": "value"}'))

    def test_handles_malformed_json(self):
        from app.services.completion_service import _extract_structured_envelope
        self.assertIsNone(_extract_structured_envelope('```json\n{broken json}\n```'))


class AppendSynthesisEventTests(unittest.TestCase):
    """append_synthesis_event のテスト"""

    def test_appends_event_with_timestamp(self):
        from app.services.completion_service import append_synthesis_event
        wf_exec = SimpleNamespace(synthesis_log=None)
        append_synthesis_event(wf_exec, {"event_type": "step_complete", "summary": "テスト"})
        events = json.loads(wf_exec.synthesis_log)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "step_complete")
        self.assertIn("timestamp", events[0])

    def test_appends_to_existing_events(self):
        from app.services.completion_service import append_synthesis_event
        wf_exec = SimpleNamespace(synthesis_log='[{"event_type": "first"}]')
        append_synthesis_event(wf_exec, {"event_type": "second"})
        events = json.loads(wf_exec.synthesis_log)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[1]["event_type"], "second")

    def test_limits_to_100_events(self):
        from app.services.completion_service import append_synthesis_event
        existing = [{"event_type": f"ev_{i}"} for i in range(100)]
        wf_exec = SimpleNamespace(synthesis_log=json.dumps(existing))
        append_synthesis_event(wf_exec, {"event_type": "overflow"})
        events = json.loads(wf_exec.synthesis_log)
        self.assertEqual(len(events), 100)
        self.assertEqual(events[-1]["event_type"], "overflow")
        self.assertEqual(events[0]["event_type"], "ev_1")  # ev_0 dropped

    def test_handles_corrupted_log(self):
        from app.services.completion_service import append_synthesis_event
        wf_exec = SimpleNamespace(synthesis_log="not valid json")
        append_synthesis_event(wf_exec, {"event_type": "recovery"})
        events = json.loads(wf_exec.synthesis_log)
        self.assertEqual(len(events), 1)


class PersistWorkflowMetadataTests(unittest.TestCase):
    class _FakeQuery:
        def __init__(self, wf_exec):
            self._wf_exec = wf_exec

        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return self._wf_exec

    class _FakeSession:
        def __init__(self, wf_exec):
            self._wf_exec = wf_exec
            self.commit_count = 0

        def query(self, model):
            return PersistWorkflowMetadataTests._FakeQuery(self._wf_exec)

        def commit(self):
            self.commit_count += 1

    def test_verification_without_extractable_verdict_falls_back_to_fail(self):
        wf_exec = SimpleNamespace(
            id=1,
            current_stage=None,
            final_verdict=None,
            blackboard_data='{"plan.summary":"x"}',
            handoff_summary=None,
            synthesis_log=None,
        )
        execution = SimpleNamespace(
            id=10,
            workflow_execution_id=1,
            agent_profile="verification",
            status="success",
            output_data="verification output without canonical verdict",
            error_message=None,
            input_data='{"_nexmagi_handoff_refs":["plan.summary"]}',
            execution_role=None,
            skill_name=None,
            skill_order=1,
            workflow_skill_id=10,
            reflection_loop=0,
        )
        db = self._FakeSession(wf_exec)

        _persist_workflow_metadata(db, execution)

        self.assertEqual(wf_exec.current_stage, "verification")
        self.assertEqual(wf_exec.final_verdict, "FAIL")
        self.assertIn('"schema_version": 1', wf_exec.handoff_summary)
        self.assertEqual(db.commit_count, 1)

    def test_handoff_summary_contains_required_fields(self):
        """handoff_summary が必須フィールドを全て含むこと"""
        wf_exec = SimpleNamespace(
            id=2,
            current_stage=None,
            final_verdict=None,
            blackboard_data='{}',
            handoff_summary=None,
            synthesis_log=None,
        )
        execution = SimpleNamespace(
            id=20,
            workflow_execution_id=2,
            agent_profile="plan",
            status="success",
            output_data="計画を策定しました。",
            error_message=None,
            input_data='{"_nexmagi_handoff_refs":["explore.output"]}',
            execution_role=None,
            skill_name="戦略設計",
            skill_order=2,
            workflow_skill_id=20,
            reflection_loop=0,
        )
        db = self._FakeSession(wf_exec)
        _persist_workflow_metadata(db, execution)

        handoff = json.loads(wf_exec.handoff_summary)
        self.assertEqual(handoff["schema_version"], 1)
        self.assertEqual(handoff["from_profile"], "plan")
        self.assertIn("to_profile", handoff)
        self.assertIn("source_execution_id", handoff)
        self.assertIn("summary", handoff)
        self.assertIn("blackboard_refs", handoff)
        self.assertIn("important_counts", handoff)
        self.assertIn("display_verdict", handoff)

    def test_success_execution_does_not_set_fail_verdict(self):
        """verification 以外のプロファイルでは verdict を設定しないこと"""
        wf_exec = SimpleNamespace(
            id=3,
            current_stage=None,
            final_verdict=None,
            blackboard_data='{}',
            handoff_summary=None,
            synthesis_log=None,
        )
        execution = SimpleNamespace(
            id=30,
            workflow_execution_id=3,
            agent_profile="implement",
            status="success",
            output_data="実装完了。",
            error_message=None,
            input_data='{}',
            execution_role=None,
            skill_name="コンテンツ生成",
            skill_order=3,
            workflow_skill_id=30,
            reflection_loop=0,
        )
        db = self._FakeSession(wf_exec)
        _persist_workflow_metadata(db, execution)

        self.assertEqual(wf_exec.current_stage, "implement")
        self.assertIsNone(wf_exec.final_verdict)


if __name__ == "__main__":
    unittest.main()
