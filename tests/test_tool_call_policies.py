"""Test offline cho chính sách tool (bonus): ngân sách retry 429, Retry-After, thu gọn context."""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent import run_agent
from bonus.tools import BonusTools
from test_lab import FakeProvider, tool_call, final
from tool_call_policies import RateLimitBudget, compact_for_context, retry_after_seconds


class RateLimitBudgetTests(unittest.TestCase):
    def test_persistent_429_is_blocked_after_three_real_calls(self):
        tools = BonusTools(scenario='rate_limit_always')
        calls = [tool_call(f'c{i}', 'get_vercel_status', {}) for i in range(5)]
        provider = FakeProvider(calls + [final('Không biết trạng thái Vercel.')])
        result = run_agent('Kiểm tra Vercel', provider, tools, max_steps=8)
        self.assertEqual(result['status'], 'completed')
        real = [e for e in result['trace'] if e['event'] == 'tool']
        blocked = [e for e in result['trace'] if e['event'] == 'tool_blocked']
        self.assertEqual(len(real), 3)  # tool chỉ thực sự được gọi 3 lần
        self.assertEqual(len(blocked), 2)
        self.assertEqual(blocked[0]['result']['error'], 'RETRY_BUDGET_EXHAUSTED')
        self.assertEqual(tools.calls[('get_vercel_status', 'vercel')], 3)

    def test_budget_is_per_tool_and_provider(self):
        budget = RateLimitBudget(max_attempts=1, max_wait=0)
        budget.record('get_incident_details', {'provider': 'vercel'}, {'error': 'RATE_LIMITED'})
        self.assertIsNotNone(budget.blocked_result('get_incident_details', {'provider': 'vercel'}))
        self.assertIsNone(budget.blocked_result('get_incident_details', {'provider': 'npm'}))

    def test_retry_after_is_honored_with_cap(self):
        budget = RateLimitBudget(max_wait=5)
        with mock.patch('tool_call_policies.time.sleep') as sleep:
            waited = budget.record('get_vercel_status', {}, {'error': 'RATE_LIMITED', 'retry_after': '30'})
        sleep.assert_called_once_with(5)
        self.assertEqual(waited, 5)

    def test_retry_after_parsing(self):
        self.assertEqual(retry_after_seconds({'retry_after': '2'}), 2.0)
        self.assertEqual(retry_after_seconds({'retry_after_seconds': 0}), 0.0)
        self.assertEqual(retry_after_seconds({'retry_after': 'not-a-date'}), 0.0)
        self.assertEqual(retry_after_seconds({}), 0.0)


class ContextCompactionTests(unittest.TestCase):
    def test_noisy_distractors_are_trimmed_in_context_not_trace(self):
        tools = BonusTools(scenario='noisy')
        provider = FakeProvider([tool_call('a', 'get_vercel_status', {}), final()])
        result = run_agent('Kiểm tra Vercel', provider, tools, max_steps=3)
        sent = json.loads(provider.histories[1][-1]['content'])
        self.assertEqual(len(sent['distractors']), 10)
        self.assertEqual(sent['distractors_omitted_count'], 150)
        self.assertEqual(len(result['trace'][1]['result']['distractors']), 160)

    def test_short_lists_unchanged(self):
        data = {'incidents': [1, 2, 3]}
        self.assertEqual(compact_for_context(data), data)


if __name__ == '__main__':
    unittest.main()
