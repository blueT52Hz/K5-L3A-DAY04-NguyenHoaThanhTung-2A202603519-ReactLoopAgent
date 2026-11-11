"""Giao diện chat demo cho Status Agent (Day 04).

Chạy:  pip install streamlit  rồi  streamlit run demo_app.py
Ba chế độ:
  - Mock:   MockProvider theo kịch bản, không cần key; vẫn chạy run_agent + StatusTools thật.
  - Live:   gọi LLM thật qua providers.Provider (đọc PROVIDER/MODEL/key từ .env).
  - Replay: xem lại case trong eval_before.json / eval_after.json (answer, trace, chấm điểm).
File này chỉ để trình bày; không ảnh hưởng agent.py, tests hay evals.
"""
import json
import os
from pathlib import Path

import streamlit as st

from agent import run_agent
from demo_fault_injection import FAULTS, wrap_with_faults
from demo_mock_provider import SCENARIOS, MockProvider
from demo_trace_render import render_agent_result, render_grade
from env_file_loader import load_env_file
from status_tools import StatusTools

load_env_file()  # nạp .env trước sidebar để caption PROVIDER/MODEL hiển thị đúng ngay từ đầu (không in key)
ROOT = Path(__file__).resolve().parent
MODES = ('Mock (không cần key)', 'Live (gọi LLM thật)', 'Replay eval JSON')

st.set_page_config(page_title='Status Agent Demo', page_icon='🛰️', layout='centered')
st.markdown('<style>.block-container{max-width:860px;padding-top:2rem}</style>', unsafe_allow_html=True)


def _sidebar():
    """Cấu hình chạy; trả dict settings."""
    with st.sidebar:
        st.header('🛰️ Status Agent')
        mode = st.radio('Chế độ', MODES)
        settings = {'mode': mode, 'max_steps': st.slider('max_steps', 1, 12, 6)}
        if mode == MODES[0]:
            settings['scenario'] = st.selectbox('Kịch bản', list(SCENARIOS), format_func=lambda k: SCENARIOS[k][0])
            st.caption(f"Câu hỏi gợi ý: _{SCENARIOS[settings['scenario']][1]}_")
        elif mode == MODES[1]:
            settings['tool_mode'] = st.selectbox('Dữ liệu tool', ['snapshot', 'live'])
            settings['faults'] = st.multiselect(
                '💥 Chèn lỗi giả lập', list(FAULTS),
                format_func=lambda k: f"[{FAULTS[k][0]}] {FAULTS[k][1]}",
                help='Model thật vẫn chạy và phải tự xử lý lỗi. Lỗi [tool] trả về dạng observation; '
                     'lỗi [provider] đi qua logic retry và kết thúc run của agent.')
            # Chỉ hiển thị provider/model, KHÔNG bao giờ hiển thị key.
            st.caption(f"Provider: `{os.getenv('PROVIDER', '?')}` · Model: `{os.getenv('MODEL', '?')}`")
        if mode != MODES[2] and st.button('🗑️ Xóa hội thoại', use_container_width=True):
            st.session_state.messages = []
        st.divider()
        st.caption('Mỗi câu hỏi là một run độc lập của run_agent (agent không nhớ câu trước).')
    return settings


def _build_provider_and_tools(settings):
    """Tạo provider + tools theo chế độ. Ném ValueError/RuntimeError nếu cấu hình sai."""
    if settings['mode'] == MODES[0]:
        scenario = settings['scenario']
        return MockProvider(scenario), StatusTools('snapshot', fail=SCENARIOS[scenario][2])
    from providers import Provider  # import muộn: providers đọc .env khi import
    provider = Provider(os.getenv('PROVIDER', 'openai'), os.getenv('MODEL'))
    return wrap_with_faults(provider, StatusTools(settings['tool_mode']), settings.get('faults', []))


def _run_question(question, settings):
    try:
        provider, tools = _build_provider_and_tools(settings)
        # Lỗi 'max_steps_1' (Live): ép 1 lượt gọi model -> model gọi tool ở step 1 thì hết lượt.
        max_steps = 1 if 'max_steps_1' in (settings.get('faults') or []) else settings['max_steps']
        return run_agent(question, provider, tools, max_steps=max_steps)
    except Exception as exc:  # lỗi cấu hình (thiếu key/model): hiển thị như run lỗi, không crash UI
        return {'status': 'error', 'answer': '', 'trace': [], 'usage': [],
                'error': f'Cấu hình lỗi: {type(exc).__name__}: {str(exc)[:200]}'}


def _render_history():
    for msg in st.session_state.messages:
        with st.chat_message(msg['role'], avatar='🧑' if msg['role'] == 'user' else '🛰️'):
            if msg['role'] == 'user':
                st.markdown(msg['content'])
            else:
                if msg.get('label'):
                    st.caption(msg['label'])
                render_agent_result(msg['result'])


def chat_page(settings):
    st.title('Status Agent')
    st.caption('Điều tra sự cố GitHub / Cloudflare bằng ReAct loop: model → tool → observation → answer.')
    st.session_state.setdefault('messages', [])
    if not st.session_state.messages:
        st.info('Nhập câu hỏi bên dưới. Ở chế độ Mock, hãy chọn kịch bản ở sidebar và dùng câu hỏi gợi ý.')
    _render_history()

    question = st.chat_input('Hỏi về trạng thái GitHub hoặc Cloudflare...')
    if not question:
        return
    st.session_state.messages.append({'role': 'user', 'content': question})
    with st.chat_message('user', avatar='🧑'):
        st.markdown(question)
    with st.chat_message('assistant', avatar='🛰️'):
        with st.spinner('Agent đang chạy...'):
            result = _run_question(question, settings)
        if settings['mode'] == MODES[0]:
            label = f"Mock · {SCENARIOS[settings['scenario']][0]}"
        else:
            faults = settings.get('faults') or []
            label = 'Live' + (f" · 💥 lỗi giả lập: {', '.join(faults)}" if faults else '')
        st.caption(label)
        render_agent_result(result)
    st.session_state.messages.append({'role': 'assistant', 'result': result, 'label': label})


def _load_eval_report():
    """Chọn file eval có sẵn trong repo hoặc upload; trả (tên, report) hoặc (None, None)."""
    files = sorted(p.name for p in ROOT.glob('eval*.json'))
    uploaded = st.file_uploader('Hoặc upload file eval JSON', type='json')
    if uploaded is not None:
        return uploaded.name, json.load(uploaded)
    if not files:
        st.warning('Chưa có file eval*.json. Chạy `python evals/run_evals.py --output eval_before.json` trước.')
        return None, None
    name = st.selectbox('File eval', files)
    return name, json.loads((ROOT / name).read_text(encoding='utf-8'))


def replay_page():
    st.title('Replay eval')
    try:
        name, report = _load_eval_report()
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        st.error(f'File eval không đọc được: {exc}')
        return
    if not report:
        return
    summary, cases = report.get('summary') or {}, report.get('cases') or []
    col1, col2, col3 = st.columns(3)
    col1.metric('Điểm tổng', summary.get('score_0_100', 'null'))
    col2.metric('Số case', len(cases))
    col3.metric('Model', (report.get('config') or {}).get('model', '?'))
    with st.expander('Config (phải giống nhau giữa before/after)'):
        st.code(json.dumps(report.get('config'), ensure_ascii=False, indent=2), language='json')
    if not cases:
        return

    def case_label(c):
        score = (c.get('grade') or {}).get('score')
        return f"{c.get('id')} · {f'{score} điểm' if score is not None else 'chưa chấm (unscored)'}"

    case = st.selectbox('Case', cases, format_func=case_label)
    with st.chat_message('user', avatar='🧑'):
        st.markdown(case.get('question', ''))
    with st.chat_message('assistant', avatar='🛰️'):
        st.caption(f'Replay · {name} · {case.get("id")}')
        render_agent_result(case.get('result') or {})
    render_grade(case)


settings = _sidebar()
if settings['mode'] == MODES[2]:
    replay_page()
else:
    chat_page(settings)
