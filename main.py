import asyncio
import json
import threading
import time
import websockets
from pythonosc import udp_client
from collections import deque

# ========== 配置 ==========
WS_URL       = "ws://localhost:3001"   # LLBot OneBot11 正向 WS 地址
OSC_HOST     = "127.0.0.1"            # VRChat OSC 地址
OSC_PORT     = 9000                   # VRChat OSC 端口
OSC_ADDRESS  = "/chatbox/input"       # VRChat Chatbox OSC 地址
DISPLAY_TIME = 8                      # 每条消息显示秒数
MAX_LENGTH   = 144                    # VRChat Chatbox 字符上限
DEBUG        = True

# 只转发来自这些群的消息，留空则转发所有群消息
ALLOWED_GROUPS: set[int] = set()      # 例如: {123456789, 987654321}
# 只转发来自这些用户的私聊，留空则转发所有私聊
ALLOWED_PRIVATE: set[int] = set()     # 例如: {123456789}

# ========== 全局状态 ==========
osc_client  = udp_client.SimpleUDPClient(OSC_HOST, OSC_PORT)
msg_queue   = deque()
queue_lock  = threading.Lock()

def debug_log(msg: str):
    if DEBUG:
        print(f"[DEBUG] {time.strftime('%H:%M:%S')} - {msg}")

# ========== 消息格式化 ==========
def format_message(sender: str, content: str) -> str:
    """格式化为 '用户名：内容'，超长自动截断"""
    text = f"{sender}：{content}"
    if len(text) > MAX_LENGTH:
        text = text[:MAX_LENGTH - 1] + "…"
    return text

# ========== OSC 发送线程 ==========
def osc_sender_loop():
    """依次发送队列里的消息，每条显示 DISPLAY_TIME 秒后清空"""
    debug_log("OSC 发送线程启动")
    while True:
        msg = None
        with queue_lock:
            if msg_queue:
                msg = msg_queue.popleft()

        if msg:
            debug_log(f"发送 OSC → {msg}")
            try:
                # True = 立即显示，不等玩家确认
                osc_client.send_message(OSC_ADDRESS, [msg, True])
            except Exception as e:
                debug_log(f"OSC 发送失败: {e}")
            time.sleep(DISPLAY_TIME)
            # 消息显示完毕后清空 Chatbox
            try:
                osc_client.send_message(OSC_ADDRESS, ["", True])
            except Exception:
                pass
        else:
            time.sleep(0.5)

# ========== 消息过滤与入队 ==========
def handle_event(event: dict):
    if event.get("post_type") != "message":
        return

    msg_type = event.get("message_type")
    sender   = event.get("sender", {})
    nickname = sender.get("card") or sender.get("nickname") or "未知"  # 群名片优先
    content  = event.get("raw_message", "").strip()

    if not content:
        return

    if msg_type == "group":
        group_id = event.get("group_id")
        if ALLOWED_GROUPS and group_id not in ALLOWED_GROUPS:
            debug_log(f"忽略群 {group_id} 的消息（不在白名单）")
            return
        source = f"群{group_id}"
        text = format_message(nickname, content)
        debug_log(f"[{source}] {nickname}: {content}")

    elif msg_type == "private":
        user_id = event.get("user_id")
        if ALLOWED_PRIVATE and user_id not in ALLOWED_PRIVATE:
            debug_log(f"忽略用户 {user_id} 的私聊（不在白名单）")
            return
        text = format_message(nickname, content)
        debug_log(f"[私聊] {nickname}: {content}")

    else:
        return

    with queue_lock:
        msg_queue.append(text)

# ========== WebSocket 接收循环 ==========
async def ws_receiver():
    debug_log(f"连接 LLBot WebSocket: {WS_URL}")
    while True:
        try:
            async with websockets.connect(WS_URL) as ws:
                print(f"✅ 已连接到 LLBot，监听消息中...")
                async for raw in ws:
                    try:
                        event = json.loads(raw)
                        handle_event(event)
                    except json.JSONDecodeError:
                        debug_log(f"JSON 解析失败: {raw[:100]}")
        except Exception as e:
            print(f"⚠️  连接断开: {e}，5 秒后重连...")
            await asyncio.sleep(5)

# ========== 主入口 ==========
if __name__ == "__main__":
    print(f"QQ → VRChat OSC 转发器")
    print(f"WebSocket : {WS_URL}")
    print(f"OSC       : {OSC_HOST}:{OSC_PORT}  →  {OSC_ADDRESS}")
    print(f"消息显示时长: {DISPLAY_TIME}s  |  字符上限: {MAX_LENGTH}\n")

    # OSC 发送线程（守护线程）
    threading.Thread(target=osc_sender_loop, daemon=True).start()

    # WebSocket 接收（主线程 asyncio 事件循环）
    try:
        asyncio.run(ws_receiver())
    except KeyboardInterrupt:
        print("\n程序已退出")
