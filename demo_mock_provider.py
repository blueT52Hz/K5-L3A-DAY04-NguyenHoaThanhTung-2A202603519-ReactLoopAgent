"""Provider giả lập cho demo Streamlit: không cần API key.

MockProvider có cùng interface với providers.Provider:
    complete(messages, schemas) -> {message, calls, finish, usage}
Nó trả response theo kịch bản cố định, nhưng vẫn chạy qua run_agent THẬT và StatusTools THẬT
(snapshot), nên trace, tool result và cách xử lý lỗi đều là hành vi thật của agent.
Câu trả lời cuối được ghép từ tool result đã quan sát, không hard-code incident ID.
"""
import json

# key -> (nhãn hiển thị, câu hỏi gợi ý, tools có giả lập timeout không)
SCENARIOS = {
    'multi_step': ('Nhiều bước: status -> incident details',
                   'GitHub Actions hiện có sự cố không? Hãy kiểm tra incident gần đây.', False),
    'parallel_calls': ('Hai tool call trong một response',
                       'So sánh trạng thái GitHub và Cloudflare hiện tại.', False),
    'invalid_json': ('Lỗi JSON arguments -> model tự sửa',
                     'GitHub Actions có sự cố không?', False),
    'unknown_tool': ('Gọi tool không tồn tại',
                     'Thời tiết Hà Nội hôm nay thế nào?', False),
    'tool_timeout': ('Tool timeout (partial failure)',
                     'Cloudflare có đang gặp sự cố không?', True),
    'length_cut': ("Output bị cắt (finish='length')",
                   'Tóm tắt toàn bộ incident GitHub tháng này.', False),
    'provider_error': ('Lỗi provider (HTTP 401)',
                       'GitHub có sự cố không?', False),
    'max_steps': ('Lặp tool đến hết max_steps',
                  'Kiểm tra liên tục GitHub Actions.', False),
}


def _tool_call(call_id, name, arguments):
    """Tạo một call theo format adapter trả về; arguments là JSON string (có thể hỏng)."""
    raw = arguments if isinstance(arguments, str) else json.dumps(arguments, ensure_ascii=False)
    return {'id': call_id, 'name': name, 'arguments': raw}


def _assistant_with_calls(calls):
    """Assistant message kiểu Chat Completions chứa tool_calls (agent append nguyên vẹn)."""
    return {'role': 'assistant', 'content': None, 'tool_calls': [
        {'id': c['id'], 'type': 'function', 'function': {'name': c['name'], 'arguments': c['arguments']}}
        for c in calls]}


def _respond_calls(calls):
    return {'message': _assistant_with_calls(calls), 'calls': calls, 'finish': 'tool_calls',
            'usage': {'mock': True}}


def _respond_text(text, finish='stop'):
    return {'message': {'role': 'assistant', 'content': text}, 'calls': [], 'finish': finish,
            'usage': {'mock': True}}


def _tool_results(messages):
    """Danh sách tool result (đã parse) theo thứ tự, lấy từ lịch sử messages."""
    out = []
    for m in messages:
        if m.get('role') == 'tool':
            try:
                out.append(json.loads(m.get('content') or '{}'))
            except json.JSONDecodeError:
                out.append({})
    return out


def _summarize_observations(results):
    """Ghép câu trả lời cuối từ dữ liệu tool thật; nêu nguồn và giới hạn."""
    lines = []
    for r in results:
        if r.get('ok') is False:
            lines.append(f"- Không kiểm tra được: `{r.get('error')}`: {r.get('message', '')}")
        elif 'overall' in r:
            overall = r['overall'] or {}
            names = ', '.join(i['name'] for i in r.get('incidents', [])[:3]) or 'không thấy incident khớp'
            lines.append(f"- **{r['provider']}** (snapshot {r.get('captured_at', '?')}): "
                         f"{overall.get('description', overall)}. Incident gần đây: {names}. Nguồn: {r.get('source')}")
        elif r.get('ok') and 'updates' in r:
            lines.append(f"- Chi tiết incident **{r['name']}** ({r['status']}, cập nhật {r['updated_at']}), "
                         f"{len(r['updates'])}/{r['updates_total']} update được trả về. Nguồn: {r['url']}")
    lines.append('\n_Giới hạn: tool chỉ tìm trong 50 incident gần nhất; không tìm thấy không chứng minh không có sự cố._')
    return '\n'.join(lines)


class MockProvider:
    """Provider kịch bản. Step được suy ra từ số assistant message đã có trong messages."""

    name = 'mock'

    def __init__(self, scenario):
        if scenario not in SCENARIOS:
            raise ValueError(f'Kịch bản không hợp lệ: {scenario}')
        self.scenario = scenario
        self.model = f'mock/{scenario}'

    def complete(self, messages, schemas):
        step = 1 + sum(1 for m in messages if m.get('role') == 'assistant')
        results = _tool_results(messages)
        handler = getattr(self, f'_{self.scenario}')
        return handler(step, results)

    # --- Các kịch bản -------------------------------------------------------
    def _multi_step(self, step, results):
        if step == 1:
            return _respond_calls([_tool_call('call_1', 'get_status', {'provider': 'github', 'component': 'Actions'})])
        if step == 2:
            incidents = (results[-1] or {}).get('incidents') or []
            if incidents:  # thấy incident liên quan -> gọi tiếp để đọc timeline
                return _respond_calls([_tool_call('call_2', 'get_incident_details',
                                                  {'provider': 'github', 'incident_id': incidents[0]['id']})])
        return _respond_text('Kết quả điều tra GitHub Actions:\n' + _summarize_observations(results))

    def _parallel_calls(self, step, results):
        if step == 1:
            return _respond_calls([_tool_call('call_gh', 'get_status', {'provider': 'github'}),
                                   _tool_call('call_cf', 'get_status', {'provider': 'cloudflare'})])
        return _respond_text('So sánh trạng thái hai dịch vụ:\n' + _summarize_observations(results))

    def _invalid_json(self, step, results):
        if step == 1:  # JSON thiếu dấu đóng -> agent phải trả INVALID_ARGUMENTS cho model
            return _respond_calls([_tool_call('call_bad', 'get_status', '{"provider": "github", "component": ')])
        if step == 2:
            return _respond_calls([_tool_call('call_fix', 'get_status', {'provider': 'github', 'component': 'Actions'})])
        return _respond_text('Đã sửa tham số và gọi lại thành công:\n' + _summarize_observations(results[1:]))

    def _unknown_tool(self, step, results):
        if step == 1:
            return _respond_calls([_tool_call('call_w', 'get_weather', {'city': 'Hà Nội'})])
        return _respond_text('Tôi không có công cụ tra thời tiết; tôi chỉ kiểm tra được trạng thái GitHub và '
                             'Cloudflare.\n' + _summarize_observations(results))

    def _tool_timeout(self, step, results):
        if step == 1:
            return _respond_calls([_tool_call('call_cf', 'get_status', {'provider': 'cloudflare'})])
        return _respond_text('Tool bị timeout nên **không đủ dữ liệu** để kết luận. Timeout của tool không có '
                             'nghĩa là Cloudflare đang sự cố.\n' + _summarize_observations(results))

    def _length_cut(self, step, results):
        return _respond_text('Tháng này GitHub có các incident sau: 1) Actions bị chậm do', finish='length')

    def _provider_error(self, step, results):
        # HTTP 401 là lỗi cấu hình -> agent không retry, kết thúc run với status=error.
        raise RuntimeError('HTTP 401: Unauthorized (API key giả lập không hợp lệ)')

    def _max_steps(self, step, results):
        return _respond_calls([_tool_call(f'call_{step}', 'get_status', {'provider': 'github', 'component': 'Actions'})])
