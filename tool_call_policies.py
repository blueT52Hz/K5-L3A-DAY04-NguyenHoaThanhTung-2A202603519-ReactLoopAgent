"""Chính sách quanh việc chạy tool (bonus): giới hạn retry khi tool trả 429, tôn trọng
Retry-After, và thu gọn danh sách quá dài trước khi đưa tool result vào context model.

Các chính sách này chung cho mọi tool, không hard-code provider, incident hay câu trả lời.
"""
import datetime
import email.utils
import time

MAX_RATE_LIMITED_ATTEMPTS = 3   # số lần 429 tối đa cho cùng (tool, provider); sau đó chặn gọi tiếp
MAX_RETRY_AFTER_SECONDS = 5     # chờ tối đa theo Retry-After để không vượt budget thời gian
MAX_LIST_ITEMS_IN_CONTEXT = 10  # danh sách dài hơn sẽ bị cắt khi đưa vào context


def _call_key(name, args):
    """Gom retry theo tool + provider (get_incident_details nhận provider trong args)."""
    provider = args.get('provider') if isinstance(args, dict) else None
    return name, provider


def _is_rate_limited(result):
    return isinstance(result, dict) and (result.get('error') == 'RATE_LIMITED'
                                         or result.get('http_status') == 429)


def retry_after_seconds(result):
    """Đọc Retry-After (số giây hoặc HTTP-date) từ tool result; 0 nếu không có/không hợp lệ."""
    value = result.get('retry_after_seconds', result.get('retry_after'))
    if value is None:
        return 0.0
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        pass
    try:
        when = email.utils.parsedate_to_datetime(str(value))
        return max(0.0, (when - datetime.datetime.now(datetime.timezone.utc)).total_seconds())
    except (TypeError, ValueError):
        return 0.0


class RateLimitBudget:
    """Đếm số lần 429 theo (tool, provider) trong một run và chặn khi vượt ngân sách."""

    def __init__(self, max_attempts=MAX_RATE_LIMITED_ATTEMPTS, max_wait=MAX_RETRY_AFTER_SECONDS):
        self.max_attempts, self.max_wait, self.hits = max_attempts, max_wait, {}

    def blocked_result(self, name, args):
        """Trả observation lỗi nếu (tool, provider) đã hết ngân sách retry; None nếu được gọi."""
        hits = self.hits.get(_call_key(name, args), 0)
        if hits < self.max_attempts:
            return None
        return {'ok': False, 'error': 'RETRY_BUDGET_EXHAUSTED', 'retriable': False,
                'message': (f'Đã gặp rate limit {hits} lần cho tool này; agent không gọi thêm. '
                            'Hãy báo rằng không kiểm tra được phần này và trả lời phần còn lại. '
                            'Rate limit không phải là outage của dịch vụ.')}

    def record(self, name, args, result):
        """Ghi nhận kết quả; nếu là 429 thì chờ theo Retry-After (có giới hạn). Trả số giây đã chờ."""
        if not _is_rate_limited(result):
            return 0.0
        key = _call_key(name, args)
        self.hits[key] = self.hits.get(key, 0) + 1
        wait = min(retry_after_seconds(result), self.max_wait)
        if wait > 0:
            time.sleep(wait)
        return wait


def compact_for_context(result, max_items=MAX_LIST_ITEMS_IN_CONTEXT):
    """Cắt các danh sách cấp cao nhất dài hơn max_items, ghi số mục bị bỏ để model biết dữ liệu chưa đủ."""
    if not isinstance(result, dict):
        return result
    compact = dict(result)
    for key, value in result.items():
        if isinstance(value, list) and len(value) > max_items:
            compact[key] = value[:max_items]
            compact[f'{key}_omitted_count'] = len(value) - max_items
    return compact
