"""Hiển thị kết quả run_agent trong Streamlit: answer, tool calls, trace, lỗi, usage.

Dùng chung cho chế độ Mock, Live và Replay eval (cùng format {status, answer, trace, usage, error}).
"""
import json

import streamlit as st

STATUS_STYLE = {  # status -> (biểu tượng, màu markdown, mô tả)
    'completed': ('✅', 'green', 'Hoàn thành'),
    'max_steps': ('⏱️', 'orange', 'Hết max_steps'),
    'error': ('❌', 'red', 'Lỗi, không hoàn thành'),
}

# Event trace không phải tool/model: event cảnh báo (vàng) và event lỗi (đỏ).
WARNING_EVENTS = {'provider_retry', 'validation_missing_source'}
ERROR_EVENTS = {'provider_error'}


def _show_json(value, expanded=True):
    """Trình xem JSON dạng cây, thu gọn/mở từng nhánh (như JSON preview của tool).

    expanded: True/False hoặc số int = độ sâu mở sẵn (vd 1: chỉ mở cấp ngoài cùng).
    String không phải JSON (vd arguments hỏng) hiển thị nguyên văn để thấy rõ lỗi.
    """
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            st.code(value or '(rỗng)', language='text')
            return
    if isinstance(value, (dict, list)):
        st.json(value, expanded=expanded)
    else:
        st.code(repr(value), language='text')


def _is_tool_error(result):
    return isinstance(result, dict) and result.get('ok') is False


def _total_tokens(usage):
    """Cộng total_tokens nếu provider có cung cấp; None nếu không có (vd mock)."""
    totals = [u.get('total_tokens') for u in usage or [] if isinstance(u, dict) and u.get('total_tokens')]
    return sum(totals) if totals else None


def render_status_line(result):
    icon, color, label = STATUS_STYLE.get(result.get('status'), ('❔', 'gray', 'Không rõ'))
    trace = result.get('trace') or []
    steps = sum(1 for e in trace if e.get('event') == 'model')
    tools = [e for e in trace if e.get('event') == 'tool']
    errors = sum(1 for e in tools if _is_tool_error(e.get('result')))
    tokens = _total_tokens(result.get('usage'))
    parts = [f"{icon} :{color}[**{result.get('status')}**] · {label}",
             f'{steps} model call', f'{len(tools)} tool call']
    if errors:
        parts.append(f':red[{errors} tool lỗi]')
    parts.append(f'{tokens} tokens' if tokens else 'tokens: n/a')
    st.caption(' · '.join(parts))


def _args_preview(arguments, limit=60):
    """Tóm tắt arguments một dòng cho tiêu đề expander, vd provider=github, component=Actions."""
    if isinstance(arguments, dict):
        text = ', '.join(f'{k}={v}' for k, v in arguments.items())
    else:
        text = str(arguments)
    return text if len(text) <= limit else text[:limit] + '…'


def render_tool_calls(trace):
    """Mỗi tool call một expander riêng (thu gọn được); bên trong là JSON tree của arguments và result.

    Tool lỗi mở sẵn để thấy ngay mã lỗi; tool thành công thu gọn để khung chat gọn.
    """
    tools = [e for e in trace or [] if e.get('event') == 'tool']
    if not tools:
        return
    st.markdown(f'**🔧 Tool đã gọi ({len(tools)})**')
    for e in tools:
        result = e.get('result')
        failed = _is_tool_error(result)
        title = (f"{'🔴' if failed else '🟢'} Step {e.get('step')} · {e.get('name')}"
                 f"({_args_preview(e.get('arguments'))})")
        if failed:
            title += f" · {result.get('error')}"
        with st.expander(title, expanded=failed):
            st.caption('Arguments')
            _show_json(e.get('arguments'), expanded=True)
            st.caption('Result (observation trả lại model) · bấm ▸ để mở nhánh')
            _show_json(result, expanded=True if failed else 1)


def _event_line(e):
    """Một dòng mô tả event trace theo loại."""
    kind, step = e.get('event'), e.get('step', '-')
    if kind == 'model':
        return f"🧠 Step {step} · model call · finish=`{e.get('finish')}` · {e.get('tool_calls', 0)} tool call"
    if kind == 'tool':
        mark = '🔴 lỗi' if _is_tool_error(e.get('result')) else '🟢 ok'
        return f"🔧 Step {step} · tool `{e.get('name')}` · {mark}"
    if kind == 'final':
        return f'🏁 Step {step} · final answer'
    extra = {k: v for k, v in e.items() if k not in ('event', 'step')}
    return f"⚠️ Step {step} · `{kind}` · {json.dumps(extra, ensure_ascii=False)[:300]}"


def render_trace(result):
    """Timeline trace + khối lỗi của run; kèm JSON thô để đối chiếu khi demo."""
    trace = result.get('trace') or []
    with st.expander(f'🧭 Trace ({len(trace)} event)', expanded=result.get('status') != 'completed'):
        for e in trace:
            line = _event_line(e)
            if e.get('event') in ERROR_EVENTS:
                st.error(line)
            elif e.get('event') in WARNING_EVENTS or (e.get('event') == 'tool' and _is_tool_error(e.get('result'))):
                st.warning(line)
            else:
                st.markdown(line)
        if result.get('error'):
            st.error(f"Run kết thúc với lỗi: {result['error']}")
        st.caption('Trace JSON thô · bấm ▸ để mở từng event')
        _show_json(trace, expanded=False)


def render_agent_result(result):
    """Toàn bộ khung trả lời của assistant trong chat."""
    render_status_line(result)
    answer = result.get('answer') or ''
    if answer:
        st.markdown(answer)
    elif result.get('status') != 'completed':
        st.markdown('_Agent không đưa ra câu trả lời hoàn chỉnh._')
    if result.get('status') == 'error' and answer:
        st.warning('Câu trả lời trên **không được coi là hoàn thành** (bị cắt hoặc dừng bất thường).')
    render_tool_calls(result.get('trace'))
    render_trace(result)


def render_grade(case):
    """Panel chấm điểm của một case trong file eval (chế độ Replay)."""
    grade = case.get('grade') or {}
    score = grade.get('score')
    with st.expander(f"📝 Chấm điểm · {score if score is not None else 'unscored'}/100", expanded=True):
        st.markdown(f"**Expected:** {case.get('expected', '')}")
        if grade.get('reason'):
            st.markdown(f"**Judge reason:** {grade['reason']}")
        if grade.get('improvement'):
            st.markdown(f"**Gợi ý cải tiến:** {grade['improvement']}")
        if grade.get('mechanical'):
            st.caption('Kiểm tra bằng code (grade.mechanical)')
            _show_json(grade['mechanical'], expanded=1)
