import uuid
import json
import re
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from database.session import get_db
from database.models import Chat, Message, DeletedChat
from database.enums import MessageRole
from core.dependencies import require_auth_cookie
from core.responses import success_response, error_response
from generator.engine import generate_dataset
from generator.prompts import CHAT_SYSTEM, CHAT_ROW_REMINDER
from llm.router import stream_chat, DEFAULT_CHAT_MODEL, MODEL_REGISTRY
from rate_limit.limiter import record_usage, check_rate_limit

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])

HISTORY_LIMIT = 12  # max messages to include as context


class SendRequest(BaseModel):
    chat_id: Optional[str] = None
    message: str
    model: Optional[str] = None
    data_format: Optional[str] = "JSON"
    data_mode: Optional[str] = "Synthetic"
    images: Optional[list[str]] = None  # list of base64-encoded images
    web_search: bool = False  # whether to use web search


class DownloadFromChatRequest(BaseModel):
    format: str = "json"
    rows: int = 100
    source: str = "AI"
    model_id: Optional[str] = None
    data_mode: str = "synthetic"
    dataset_name: Optional[str] = None


class RenameRequest(BaseModel):
    title: str


@router.post("/send")
async def send_message(req: SendRequest, user_id: str = Depends(require_auth_cookie), db: Session = Depends(get_db)):
    """Send message and get SSE streamed response. Every response includes a 5-row table."""
    model_id = req.model or DEFAULT_CHAT_MODEL

    # rate limit
    if not check_rate_limit(model_id, user_id):
        return error_response("Rate limit exceeded", 429)

    # get or create chat
    chat = None
    if req.chat_id:
        chat = db.query(Chat).filter(Chat.id == req.chat_id, Chat.user_id == user_id).first()

    if not chat:
        chat = Chat(
            id=uuid.uuid4(),
            user_id=user_id,
            title=req.message[:50].strip() or "New Chat",
            model=model_id,
            data_format=req.data_format,
            data_mode=req.data_mode,
        )
        db.add(chat)
        db.commit()

    # save user message
    user_msg = Message(id=uuid.uuid4(), chat_id=chat.id, role=MessageRole.user, content=req.message)
    db.add(user_msg)
    db.commit()

    # load history
    history = db.query(Message).filter(Message.chat_id == chat.id).order_by(Message.created_at).all()
    history = history[-HISTORY_LIMIT:]

    # build messages for LLM
    # Include data mode instruction in the system prompt
    mode_suffix = ""
    if req.data_mode:
        mode_key = req.data_mode.lower()
        # Map legacy "real-time" to "realistic"
        if mode_key == "real-time":
            mode_key = "realistic"
        mode_map = {
            "synthetic": "\n\nDATA MODE: Synthetic — Generate completely fictional/synthetic data in your example tables. Use made-up names, addresses, emails. Data should look plausible but NOT be real.",
            "realistic": "\n\nDATA MODE: Realistic — Generate data mimicking real-world patterns in your example tables. Use realistic names, real city names, properly formatted emails, realistic salary ranges. Data should appear believable but is not sourced from the internet.",
            "hybrid": "\n\nDATA MODE: Hybrid — Mix realistic formatting with synthetic values in your example tables. Use real city/country names and realistic distributions, but use fictional names and identifiers.",
            "live-data": "\n\nDATA MODE: Live Data — Generate data that mirrors real-world patterns in your example tables. Use realistic names, real city names, properly formatted data. The full dataset with live web data will be extracted during download using built-in web search tools.",
        }
        mode_suffix = mode_map.get(mode_key, "")

    llm_messages = [{"role": "system", "content": CHAT_SYSTEM + mode_suffix}]
    for msg in history:
        llm_messages.append({"role": msg.role.value, "content": msg.content})

    # Inject 5-row / 10-column reminder before final user message
    if len(llm_messages) >= 2:
        llm_messages.insert(-1, {"role": "system", "content": CHAT_ROW_REMINDER})

    # Web search tools are NEVER used during chat — only during dataset download
    # This applies to all modes including Compound models

    # If images are provided and the model supports vision, build multimodal user message
    model_info = MODEL_REGISTRY.get(model_id, {})
    if req.images and model_info.get("vision"):
        # Replace the last user message with multimodal content
        content_parts = [{"type": "text", "text": req.message}]
        for img_b64 in req.images[:4]:  # limit to 4 images
            # Auto-detect image type or default to jpeg
            if img_b64.startswith("data:"):
                # Already has data URI prefix
                image_url = img_b64
            else:
                image_url = f"data:image/jpeg;base64,{img_b64}"
            content_parts.append({
                "type": "image_url",
                "image_url": {"url": image_url},
            })
        # Replace last message (which is the current user message) with multimodal
        if llm_messages and llm_messages[-1]["role"] == "user":
            llm_messages[-1]["content"] = content_parts

    async def event_stream():
        full_response = ""
        try:
            async for chunk in stream_chat(llm_messages, model_id):
                full_response += chunk
                yield f"data: {json.dumps({'type': 'chunk', 'content': chunk})}\n\n"

            # check if response has a markdown table
            has_table = bool(re.search(r"\|.*\|.*\|", full_response))

            # save assistant message
            assistant_msg = Message(
                id=uuid.uuid4(),
                chat_id=chat.id,
                role=MessageRole.assistant,
                content=full_response,
                show_download=has_table,
            )
            db.add(assistant_msg)

            # update chat timestamp
            chat.model = model_id
            chat.data_format = req.data_format
            chat.data_mode = req.data_mode
            db.commit()

            record_usage(model_id, user_id)

            # send done event with metadata
            yield f"data: {json.dumps({'type': 'done', 'chat_id': str(chat.id), 'show_download': has_table})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)[:200]})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/{chat_id}/download")
def download_from_chat(
    chat_id: str,
    req: DownloadFromChatRequest,
    user_id: str = Depends(require_auth_cookie),
    db: Session = Depends(get_db),
):
    """Generate dataset from chat context. Extracts schema from last assistant table."""
    chat = db.query(Chat).filter(Chat.id == chat_id, Chat.user_id == user_id).first()
    if not chat:
        return error_response("Chat not found", 404)

    messages = db.query(Message).filter(Message.chat_id == chat.id).order_by(Message.created_at).all()
    if not messages:
        return error_response("No messages in chat")

    # extract columns from last assistant response with a table
    columns = _extract_columns_from_chat(messages)
    if not columns:
        return error_response("Could not extract dataset schema from chat")

    # build context from chat history
    context = _build_chat_context(messages)

    # Determine web search usage — ONLY for compound models in live-data mode
    data_mode = req.data_mode or (chat.data_mode or "synthetic").lower()
    # Map legacy "real-time" to "realistic"
    if data_mode == "real-time":
        data_mode = "realistic"
    model_id_for_gen = req.model_id or chat.model
    model_info = MODEL_REGISTRY.get(model_id_for_gen, {})
    # Web search ONLY for compound/compound-mini models
    is_compound = model_id_for_gen in ("compound", "compound-mini")
    use_web_search = is_compound and model_info.get("web_search", False)
    # Force live-data mode for compound models
    if is_compound:
        data_mode = "live-data"

    result = generate_dataset(
        columns=columns,
        rows=req.rows,
        fmt=req.format,
        source=req.source,
        context=context,
        model_id=model_id_for_gen,
        user_id=user_id,
        data_mode=data_mode,
        use_web_search=use_web_search,
    )

    # Auto-save dataset
    from api.datasets import auto_save_dataset
    dataset_name = req.dataset_name or chat.title or "Chat Dataset"
    save_result = auto_save_dataset(
        user_id=user_id,
        data=result["data"],
        fmt=result["format"],
        dataset_name=dataset_name,
        model_id=model_id_for_gen or "unknown",
        data_mode=data_mode,
        db=db,
    )

    # Flatten: put formatted content directly in "data", metadata at top level
    return {
        "success": True,
        "data": result["data"],
        "format": result["format"],
        "rows_generated": result["rows_generated"],
        "error": None,
        **save_result,
    }


@router.post("")
def create_chat(user_id: str = Depends(require_auth_cookie), db: Session = Depends(get_db)):
    chat = Chat(id=uuid.uuid4(), user_id=user_id, title="New Chat")
    db.add(chat)
    db.commit()
    return success_response({"id": str(chat.id), "title": chat.title})


@router.get("/history")
def get_history(user_id: str = Depends(require_auth_cookie), db: Session = Depends(get_db)):
    chats = db.query(Chat).filter(Chat.user_id == user_id).order_by(Chat.updated_at.desc()).all()
    return success_response([
        {
            "id": str(c.id),
            "title": c.title,
            "starred": c.starred,
            "pinned": c.pinned,
            "updatedAt": c.updated_at.isoformat() if c.updated_at else c.created_at.isoformat(),
        }
        for c in chats
    ])


@router.get("/{chat_id}/messages")
def get_messages(chat_id: str, user_id: str = Depends(require_auth_cookie), db: Session = Depends(get_db)):
    chat = db.query(Chat).filter(Chat.id == chat_id, Chat.user_id == user_id).first()
    if not chat:
        return error_response("Chat not found", 404)

    messages = db.query(Message).filter(Message.chat_id == chat.id).order_by(Message.created_at).all()
    return success_response([
        {
            "id": str(m.id),
            "role": m.role.value,
            "content": m.content,
            "showDownload": m.show_download,
            "createdAt": m.created_at.isoformat(),
        }
        for m in messages
    ])


@router.put("/{chat_id}/rename")
def rename_chat(chat_id: str, req: RenameRequest, user_id: str = Depends(require_auth_cookie), db: Session = Depends(get_db)):
    chat = db.query(Chat).filter(Chat.id == chat_id, Chat.user_id == user_id).first()
    if not chat:
        return error_response("Chat not found", 404)
    chat.title = req.title
    db.commit()
    return success_response({"message": "Renamed"})


@router.put("/{chat_id}/star")
def toggle_star(chat_id: str, user_id: str = Depends(require_auth_cookie), db: Session = Depends(get_db)):
    chat = db.query(Chat).filter(Chat.id == chat_id, Chat.user_id == user_id).first()
    if not chat:
        return error_response("Chat not found", 404)
    chat.starred = not chat.starred
    db.commit()
    return success_response({"starred": chat.starred})


@router.put("/{chat_id}/pin")
def toggle_pin(chat_id: str, user_id: str = Depends(require_auth_cookie), db: Session = Depends(get_db)):
    chat = db.query(Chat).filter(Chat.id == chat_id, Chat.user_id == user_id).first()
    if not chat:
        return error_response("Chat not found", 404)
    chat.pinned = not chat.pinned
    db.commit()
    return success_response({"pinned": chat.pinned})


@router.delete("/{chat_id}")
def delete_chat(chat_id: str, user_id: str = Depends(require_auth_cookie), db: Session = Depends(get_db)):
    chat = db.query(Chat).filter(Chat.id == chat_id, Chat.user_id == user_id).first()
    if not chat:
        return error_response("Chat not found", 404)

    # soft delete — archive to deleted_chats
    messages = db.query(Message).filter(Message.chat_id == chat.id).order_by(Message.created_at).all()
    messages_data = [{"role": m.role.value, "content": m.content, "show_download": m.show_download} for m in messages]

    deleted = DeletedChat(
        id=chat.id,
        user_id=chat.user_id,
        title=chat.title,
        starred=chat.starred,
        pinned=chat.pinned,
        created_at=chat.created_at,
        updated_at=chat.updated_at,
        messages_data=messages_data,
    )
    db.add(deleted)
    db.delete(chat)
    db.commit()

    return success_response({"message": "Chat deleted"})


# --- helpers ---

def _extract_columns_from_chat(messages: list) -> list:
    """Find last assistant message with a markdown table, extract column headers."""
    for msg in reversed(messages):
        if msg.role != MessageRole.assistant:
            continue
        # find markdown table
        lines = msg.content.split("\n")
        for i, line in enumerate(lines):
            if "|" in line and i + 1 < len(lines) and re.match(r"^\s*\|[\s\-|]+\|\s*$", lines[i + 1]):
                # this is a table header
                headers = [h.strip() for h in line.split("|") if h.strip()]
                if headers:
                    # infer types from data rows
                    columns = []
                    data_rows = []
                    for j in range(i + 2, min(i + 7, len(lines))):
                        if "|" not in lines[j]:
                            break
                        cells = [c.strip() for c in lines[j].split("|") if c.strip()]
                        data_rows.append(cells)

                    for idx, header in enumerate(headers):
                        col_type = _infer_type(header, [r[idx] if idx < len(r) else "" for r in data_rows])
                        columns.append({"name": header, "type": col_type})
                    return columns
    return []


def _infer_type(header: str, sample_values: list) -> str:
    """Guess column type from header name and sample values."""
    h = header.lower()

    # name-based heuristics
    if "id" == h or h.endswith("_id"):
        return "Number"
    if "email" in h:
        return "Email"
    if "phone" in h:
        return "Phone Number"
    if "date" in h or "birth" in h:
        return "Date"
    if "age" in h:
        return "Number"
    if "price" in h or "cost" in h or "salary" in h or "amount" in h or "revenue" in h:
        return "Currency"
    if "city" in h:
        return "City"
    if "country" in h:
        return "Country"
    if "state" in h:
        return "State"
    if "address" in h:
        return "Address"
    if "name" in h:
        return "Name"
    if "url" in h or "website" in h:
        return "URL"
    if "company" in h:
        return "Company Name"
    if "department" in h or "dept" in h:
        return "Department"
    if "title" in h or "job" in h or "position" in h:
        return "Job Title"
    if "bool" in h or "active" in h or "status" in h:
        return "Boolean"
    if "gender" in h:
        return "Gender"

    # value-based heuristics
    if sample_values:
        val = sample_values[0]
        if val:
            try:
                int(str(val).replace(",", ""))
                return "Number"
            except ValueError:
                pass
            try:
                float(str(val).replace(",", "").replace("$", ""))
                return "Currency"
            except ValueError:
                pass
            if "@" in str(val):
                return "Email"

    return "String"


def _build_chat_context(messages: list) -> str:
    """Summarize chat history into a context string for dataset generation."""
    parts = []
    for msg in messages[-6:]:  # last 6 messages
        role = "User" if msg.role == MessageRole.user else "Assistant"
        parts.append(f"{role}: {msg.content[:200]}")
    return "\n".join(parts)
