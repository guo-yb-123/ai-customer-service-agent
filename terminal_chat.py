import requests
import time
import json

API_BASE = "http://127.0.0.1:8000"


def get_task_result(task_id, session_id, user_id):
    status_url = f"{API_BASE}/api/v1/task/status/{task_id}"

    raw_data = None

    print("   ⏳ 正在轮询后台任务状态...", end="", flush=True)
    for _ in range(15):
        try:
            r = requests.get(status_url)
            j = r.json()
            if j['status'] == 'pending':
                print(".", end="", flush=True)
                time.sleep(1.5)
                continue
            elif j['status'] == 'done':
                raw_data = j.get('raw_data', [])
                print(" ✅ 数据拉取完成！")
                break
            elif j['status'] == 'failed':
                print(" ❌ 任务失败")
                return "后台任务执行失败"
        except Exception as e:
            # 遇到乱码等解析错误时，不要直接崩溃，尝试重试
            print("x", end="", flush=True)
            time.sleep(1.5)
            continue

    # 如果轮询结束还没拿到数据（或数据为空）
    if not raw_data:
        return "查询超时，获取数据为空，请稍后重试。"

    print("   ✨ 正在请求大模型润色...", end="", flush=True)
    try:
        refine_resp = requests.post(
            f"{API_BASE}/api/v1/chat/refine",
            json={"session_id": session_id, "user_id": user_id, "raw_data": raw_data},
            timeout=10
        )
        refine_json = refine_resp.json()
        print(" ✅ 润色完成！")
        return refine_json.get("reply", "润色失败，未获取到有效回复")
    except Exception as e:
        return f"润色接口异常：{str(e)}"


def send_message(user_id, session_id, user_query):
    print(f"\n🧑 User ({user_id}): {user_query}")

    payload = {
        "session_id": session_id,
        "user_id": user_id,
        "question": user_query
    }

    # 第一次请求，触发工具
    resp = requests.post(f"{API_BASE}/api/v1/chat/local", json=payload)
    print(f"⚠️ 后端返回的 HTTP 状态码: {resp.status_code}")
    print(f"⚠️ 后端返回的原始内容: '{resp.text}'")
    data = resp.json()

    task_id = data.get("task_id")
    action = data.get("action")

    # 【关键修复】只有明确带有异步标记的任务才进入轮询
    if task_id and action == "async_task_pending":
        final_reply = get_task_result(task_id, session_id, user_id)
    else:
        # 普通回复或立刻返回的回复
        final_reply = data.get("reply", "服务异常")

    print(f"🤖 AI: {final_reply}\n")


def main():
    print("=" * 50)
    print("🤖 AI 智能客服控制台 (终端版)")
    print("=" * 50)
    print("内置测试用户: u001, u002, u008")
    print("直接输入问题即可（输入 'exit' 退出）\n")

    user_id = "u001"
    session_id = "terminal_session"

    while True:
        user_input = input(f"{user_id} > ")
        if user_input.strip().lower() == "exit":
            break
        if not user_input.strip():
            continue
        send_message(user_id, session_id, user_input)


if __name__ == "__main__":
    main()