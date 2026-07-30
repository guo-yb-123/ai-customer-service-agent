"""
AI 智能客服 — Streamlit 对话页面
"""
import streamlit as st
import requests
import json
import time
import uuid

# ===== 配置 =====
API_BASE = "http://127.0.0.1:8000"

NODE_LABEL = {
    "extract_intent": "🔍 识别意图",
    "check_slots": "📋 校验参数",
    "prompt_slot": "❓ 追问补充",
    "execute_skill": "⚙️ 执行业务",
    "check_sensitive": "🔒 安全检查",
    "approval": "⏳ 等待审批",
    "generate_reply": "💬 生成回复",
    "reflect": "🪞 反思自检",
    "finalize": "✅ 完成",
}

# ===== 页面设置 =====
st.set_page_config(
    page_title="AI 智能客服",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ===== 样式 =====
st.markdown("""
<style>
    .stChatMessage { padding: 1rem; }
    .node-progress {
        font-size: 0.85rem;
        color: #888;
        padding: 0.3rem 0.6rem;
        border-radius: 6px;
        display: inline-block;
        margin: 2px;
        background: #f0f0f0;
    }
    .node-progress.active {
        background: #e3f2fd;
        color: #1565c0;
        font-weight: 600;
    }
    .reply-warning {
        background: #fff3e0;
        border-left: 4px solid #ff9800;
        padding: 0.8rem;
        border-radius: 8px;
    }
</style>
""", unsafe_allow_html=True)


# ===== 初始化 session_state =====
def init_session():
    defaults = {
        "messages": [],
        "session_id": f"web_{uuid.uuid4().hex[:12]}",
        "user_id": "u001",
        "awaiting_approval": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


init_session()

# ===== 侧边栏 =====
with st.sidebar:
    st.title("🤖 AI 智能客服")

    st.markdown("---")

    st.subheader("👤 用户身份")
    user_id = st.selectbox(
        "选择测试用户",
        ["u001", "u002", "u003"],
        index=["u001", "u002", "u003"].index(st.session_state.user_id)
        if st.session_state.user_id in ["u001", "u002", "u003"]
        else 0,
    )
    if user_id != st.session_state.user_id:
        st.session_state.user_id = user_id
        st.session_state.messages = []
        st.session_state.session_id = f"web_{uuid.uuid4().hex[:12]}"
        st.rerun()

    st.markdown("---")

    st.subheader("📋 会话")
    st.code(st.session_state.session_id, language=None)

    col1, col2 = st.columns(2)
    with col1:
        if st.button("🆕 新会话", use_container_width=True):
            st.session_state.messages = []
            st.session_state.session_id = f"web_{uuid.uuid4().hex[:12]}"
            st.session_state.awaiting_approval = False
            st.rerun()
    with col2:
        if st.button("🗑️ 清空记录", use_container_width=True):
            st.session_state.messages = []
            st.rerun()

    st.markdown("---")

    st.subheader("💡 试试这些")
    examples = [
        "我的手机屏幕碎了，怎么办？",
        "帮我查一下我的订单",
        "我要申请售后",
        "物流到哪了？",
        "有什么手机推荐？",
    ]
    for ex in examples:
        if st.button(ex, use_container_width=True):
            st.session_state.pending_input = ex
            st.rerun()

    st.markdown("---")
    st.caption(f"API: {API_BASE}")


# ===== 主内容区 =====
st.title("💬 AI 智能客服")

# 消息列表
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# 输入框
user_input = st.chat_input("输入您的问题...")

# 处理侧边栏示例点击
if "pending_input" in st.session_state and st.session_state.pending_input:
    user_input = st.session_state.pending_input
    del st.session_state.pending_input


def send_message_stream(user_id: str, session_id: str, question: str):
    """通过流式接口发送消息，返回 (reply_text, nodes_seen)"""
    payload = {
        "session_id": session_id,
        "user_id": user_id,
        "question": question,
    }
    nodes_seen = []
    reply_text = None

    try:
        resp = requests.post(
            f"{API_BASE}/api/v1/chat/graph/stream",
            json=payload,
            stream=True,
            timeout=120,
        )

        if resp.status_code != 200:
            # 降级到同步接口
            sync_resp = requests.post(
                f"{API_BASE}/api/v1/chat/graph",
                json=payload,
                timeout=60,
            )
            data = sync_resp.json()
            reply_text = data.get("reply", "服务异常，请稍后重试")
            return reply_text, nodes_seen

        for line in resp.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: "):
                continue

            data_str = line[6:]
            try:
                event = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            event_type = event.get("type", "")

            if event_type == "node":
                node = event.get("node", "")
                if node and node not in nodes_seen:
                    nodes_seen.append(node)

            elif event_type == "reply":
                reply_text = event.get("content", "")

            elif event_type == "interrupt":
                st.session_state.awaiting_approval = True
                reply_text = "⏳ 此操作需要管理员审批，请稍候..."

            elif event_type == "error":
                reply_text = f"❌ 服务异常: {event.get('message', '未知错误')}"

        return reply_text or "服务暂时无响应，请稍后重试", nodes_seen

    except requests.exceptions.ConnectionError:
        return "❌ 无法连接服务器，请确认服务已启动", nodes_seen
    except Exception as e:
        return f"❌ 请求异常: {str(e)}", nodes_seen


if user_input:
    # 添加用户消息
    st.session_state.messages.append({"role": "user", "content": user_input})

    with st.chat_message("user"):
        st.markdown(user_input)

    # 调用 API
    with st.chat_message("assistant"):
        placeholder = st.empty()
        status_container = st.empty()

        with st.spinner("处理中..."):
            reply, nodes = send_message_stream(
                st.session_state.user_id,
                st.session_state.session_id,
                user_input,
            )

        # 画节点进度条
        if nodes:
            labels = []
            for i, node in enumerate(nodes):
                label = NODE_LABEL.get(node, node)
                labels.append(label)
            status_container.markdown(
                " → ".join([f"`{l}`" for l in labels])
            )

        # 显示回复
        if reply.startswith("❌") or reply.startswith("⏳"):
            placeholder.warning(reply)
        else:
            placeholder.markdown(reply)

        st.session_state.messages.append({"role": "assistant", "content": reply})
