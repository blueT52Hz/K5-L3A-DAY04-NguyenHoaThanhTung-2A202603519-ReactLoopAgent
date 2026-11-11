"""Nạp biến môi trường từ file .env ở thư mục project (chỉ dùng standard library).

Ưu tiên: giá trị trong .env GHI ĐÈ biến đã đặt ở terminal. Nếu .env không có
biến đó, để trống, là placeholder (YOUR_..., <...>) hoặc không có file .env,
giữ nguyên giá trị đặt ở terminal.

Hỗ trợ các dòng dạng:  KEY=value · export KEY=value · KEY="value" · # comment
"""
import os
from pathlib import Path

DEFAULT_ENV_PATH = Path(__file__).resolve().parent / '.env'


def _parse_line(line):
    """Trả (key, value) hoặc None nếu dòng trống/comment/không hợp lệ."""
    line = line.strip()
    if not line or line.startswith('#'):
        return None
    if line.startswith('export '):
        line = line[len('export '):].strip()
    key, sep, value = line.partition('=')
    key, value = key.strip(), value.strip()
    if not sep or not key:
        return None
    # Bỏ cặp nháy bao quanh: KEY="abc" hoặc KEY='abc'.
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        value = value[1:-1]
    return key, value


def load_env_file(path=DEFAULT_ENV_PATH):
    """Đọc .env và ghi vào os.environ. Trả danh sách tên biến đã nạp (không trả giá trị)."""
    path = Path(path)
    if not path.is_file():
        return []
    loaded = []
    try:
        lines = path.read_text(encoding='utf-8-sig').splitlines()  # utf-8-sig: bỏ BOM nếu có
    except OSError:
        return []
    for line in lines:
        parsed = _parse_line(line)
        if not parsed:
            continue
        key, value = parsed
        if value == '' or value.startswith(('YOUR_', '<')):
            continue  # rỗng hoặc placeholder (YOUR_KEY, <api-key>): không ghi đè giá trị ở terminal
        os.environ[key] = value
        loaded.append(key)
    return loaded
