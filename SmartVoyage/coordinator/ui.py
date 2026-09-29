from typing import Any


def build_thread_id(user_id: str, session_id: str) -> str:
    user_id = user_id.strip()
    session_id = session_id.strip()
    if not user_id:
        raise ValueError("用户 ID 不能为空")
    if not session_id:
        raise ValueError("会话 ID 不能为空")
    return f"{user_id}:{session_id}"


def _interrupt_value(interrupt_item: Any) -> dict | None:
    value = getattr(interrupt_item, "value", None)
    return value if isinstance(value, dict) else None


def interpret_graph_result(result: dict) -> dict:
    interrupts = result.get("__interrupt__") or ()
    pending = _interrupt_value(interrupts[0]) if interrupts else None
    return {
        "pending_confirmation": pending,
        "response": None if pending else result.get("final_answer", "任务已完成。"),
        "trace": result.get("trace", []),
    }


def format_confirmation(payload: dict) -> str:
    ticket = payload["ticket"]
    departure_time = str(ticket.get("departure_time", ""))
    return (
        "### 请确认预订\n\n"
        f"- 行程：{ticket.get('departure', '')} → {ticket.get('destination', '')}\n"
        f"- 班次：{ticket.get('number', '')}\n"
        f"- 出发时间：{departure_time.replace('T', ' ')}\n"
        f"- 舱位/座位：{ticket.get('seat_class', '')}\n"
        f"- 单价：{ticket.get('price', '')} 元\n"
        f"- 数量：{payload.get('quantity', 1)} 张"
    )


def trace_rows(trace: list) -> list[dict[str, str]]:
    rows = []
    for event in trace:
        if hasattr(event, "model_dump"):
            item = event.model_dump()
        elif isinstance(event, dict):
            item = event
        else:
            continue
        rows.append(
            {
                "节点": str(item.get("label", item.get("node", ""))),
                "状态": str(item.get("status", "")),
                "摘要": str(item.get("summary", "")),
            }
        )
    return rows
