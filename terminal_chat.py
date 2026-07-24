"""
AI 智能客服 - 终端对话 Demo
极简模式：只显示 Q&A，等待时显示进度节点
"""
import requests
import json
import sys

API_BASE = "http://127.0.0.1:8000"

NODE_LABEL = {
    "extract_intent": "识别意图",
    "check_slots": "校验参数",
    "prompt_slot": "追问",
    "execute_skill": "执行业务",
    "check_sensitive": "安全检查",
    "approval": "等待审批",
    "generate_reply": "生成回复",
    "reflect": "反思自检",
    "finalize": "完成",
}


def send_message(user_id: str, session_id: str, user_query: str):
    """通过 LangGraph 流式接口发送消息"""
    print(f"\n🧑 You: {user_query}")

    payload = {
        "session_id": session_id,
        "user_id": user_id,
        "question": user_query,
    }

    try:
        resp = requests.post(
            f"{API_BASE}/api/v1/chat/graph/stream",
            json=payload,
            stream=True,
            timeout=60,
        )

        if resp.status_code != 200:
            sync_resp = requests.post(
                f"{API_BASE}/api/v1/chat/graph",
                json=payload,
                timeout=30,
            )
            data = sync_resp.json()
            print(f"🤖 AI: {data.get('reply', '服务异常')}")
            return

        reply_text = None
        shown_nodes = set()

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
                if node and node not in shown_nodes:
                    shown_nodes.add(node)
                    label = NODE_LABEL.get(node, node)
                    sys.stdout.write(f"\r   {label}...")
                    sys.stdout.flush()

            elif event_type == "reply":
                reply_text = event.get("content", "")

            elif event_type == "interrupt":
                sys.stdout.write("\r")
                sys.stdout.flush()
                print("🤖 AI: 此操作已提交审核，请稍候...")
                return

        # 清除进度指示器，显示最终回复
        sys.stdout.write("\r")
        sys.stdout.flush()
        if reply_text:
            print(f"🤖 AI: {reply_text}")
        else:
            print("🤖 AI: 服务暂时异常，请稍后重试")

    except requests.exceptions.ConnectionError:
        print("❌ 无法连接服务器")
    except Exception as e:
        print(f"❌ {e}")


def main():
    print("=" * 44)
    print("  🤖 AI 智能客服 — 终端对话 Demo")
    print("=" * 44)
    print("  测试用户: u001 / u002 / u003")
    print("  输入 exit 退出\n")

    import time
    user_id = "u001"
    session_id = f"demo_{user_id}_{int(time.time())}"

    while True:
        try:
            user_input = input(f"  {user_id} > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 再见！")
            break

        if not user_input:
            continue

        if user_input.lower() == "exit":
            print("👋 再见！")
            break

        send_message(user_id, session_id, user_input)


if __name__ == "__main__":
    main()
