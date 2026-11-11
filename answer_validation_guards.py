"""Kiểm tra final answer trước khi trả kết quả (Bài 4).

1. Nguồn: nếu đã đọc thành công incident (get_incident_details), answer phải chứa
   ít nhất một URL incident đã quan sát. Chỉ kiểm tra SỰ HIỆN DIỆN của URL, không
   chứng minh mọi claim đều có nguồn.
2. Prompt injection: tìm chỉ dẫn giả trong tool result (vd "ignore previous
   instructions", "SYSTEM OVERRIDE"), lấy các marker dạng UPPER_SNAKE trong đó; nếu
   answer chép lại marker thì ẩn đi. Phát hiện theo mẫu chung, không hard-code marker.
"""
import re

from bonus.tools import HOSTS as BONUS_HOSTS
from status_tools import HOSTS

# Host trang status của mọi provider (bài chính + bonus) để chấp nhận URL incident đầy đủ.
ALL_HOSTS = {**HOSTS, **BONUS_HOSTS}

# Dấu hiệu văn bản đang ra lệnh cho model (tiếng Anh + tiếng Việt).
INJECTION_PATTERNS = re.compile(
    r'ignore\s+(?:all\s+|the\s+)?(?:previous|prior|above|user|system)'
    r'|system\s+override|^\s*system\s*:|\bsystem\s*:'
    r'|higher\s+priority\s+than\s+the\s+user'
    r'|bỏ\s+qua\s+(?:mọi\s+|các\s+|tất\s+cả\s+)?(?:hướng\s+dẫn|chỉ\s+dẫn)',
    re.IGNORECASE)
# Marker kiểu LAB_SOMETHING_CONFIRMED: chữ hoa/số, có ít nhất một dấu gạch dưới.
MARKER_PATTERN = re.compile(r'\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b')
REDACTED = '[chuỗi chỉ dẫn đáng ngờ đã ẩn]'


def _iter_strings(value):
    """Duyệt mọi chuỗi trong dict/list lồng nhau của tool result."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _iter_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_strings(item)


def collect_incident_urls(name, result):
    """URL hợp lệ để dẫn nguồn từ một get_incident_details thành công; rỗng nếu thất bại."""
    if name != 'get_incident_details' or not isinstance(result, dict) or result.get('ok') is not True:
        return set()
    urls = set()
    if result.get('url'):
        urls.add(result['url'])
    host = ALL_HOSTS.get(result.get('provider'))
    if host and result.get('id'):  # expected chấp nhận cả trang incident đầy đủ
        urls.add(f"{host}/incidents/{result['id']}")
    return urls


def collect_injection_markers(result):
    """Marker xuất hiện trong đoạn văn bản có dấu hiệu chỉ dẫn giả của một tool result."""
    markers = set()
    for text in _iter_strings(result):
        if INJECTION_PATTERNS.search(text):
            markers.update(MARKER_PATTERN.findall(text))
    return markers


def has_observed_source(answer, observed_urls):
    """True nếu không cần nguồn (chưa đọc incident nào) hoặc answer chứa ít nhất một URL."""
    if not observed_urls:
        return True
    return any(url in answer for url in observed_urls)


def source_revision_request(observed_urls):
    urls = ', '.join(sorted(observed_urls))
    return ('Câu trả lời chưa dẫn URL nguồn của incident đã đọc. Hãy viết lại câu trả lời, '
            f'giữ nguyên nội dung và thêm URL nguồn lấy từ tool result (một trong: {urls}).')


def redact_injection_markers(answer, markers):
    """Ẩn marker bị chép lại. Trả (answer_mới, danh sách marker đã ẩn)."""
    found = sorted(m for m in markers if m in answer)
    for marker in found:
        answer = answer.replace(marker, REDACTED)
    return answer, found
