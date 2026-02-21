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
from generator.engine import generate_dataset_from_chat
from generator.prompt_builder import build_system_prompt
from llm.router import stream_chat
from models import MODEL_CONFIG, DEFAULT_CHAT_MODEL, is_compound
from rate_limit.limiter import check_and_record

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
    rows: int = 20  # default 20; overridden by what user said in chat
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

    # global rate limit (INCR-first, no user_id)
    rate_error = check_and_record(model_id)
    if rate_error:
        async def rate_limit_stream():
            yield f"data: {json.dumps({'type': 'error', 'content': rate_error['message']})}".encode() + b"\n\n"
        return StreamingResponse(rate_limit_stream(), media_type="text/event-stream", status_code=200)

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

    # normalize generation mode — compound forces live_data
    generation_mode = (req.data_mode or "synthetic").lower().replace("-", "_")
    if generation_mode == "real_time":
        generation_mode = "realistic"
    if is_compound(model_id):
        generation_mode = "live_data"

    # build system prompt via PromptBuilder (rebuilt every request, never stored)
    system_prompt = build_system_prompt("chat_preview", generation_mode, model_id)

    llm_messages = [{"role": "system", "content": system_prompt}]
    for msg in history:
        llm_messages.append({"role": msg.role.value, "content": msg.content})

    # multimodal: if images provided and model supports vision
    model_info = MODEL_CONFIG.get(model_id, {})
    if req.images and model_info.get("vision"):
        content_parts = [{"type": "text", "text": req.message}]
        for img_b64 in req.images[:4]:
            if img_b64.startswith("data:"):
                image_url = img_b64
            else:
                image_url = f"data:image/jpeg;base64,{img_b64}"
            content_parts.append({
                "type": "image_url",
                "image_url": {"url": image_url},
            })
        if llm_messages and llm_messages[-1]["role"] == "user":
            llm_messages[-1]["content"] = content_parts

    async def event_stream():
        full_response = ""
        try:
            async for chunk in stream_chat(llm_messages, model_id):
                full_response += chunk
                yield f"data: {json.dumps({'type': 'chunk', 'content': chunk})}\n\n"

            has_table = bool(re.search(r"\|.*\|.*\|", full_response))

            assistant_msg = Message(
                id=uuid.uuid4(),
                chat_id=chat.id,
                role=MessageRole.assistant,
                content=full_response,
                show_download=has_table,
            )
            db.add(assistant_msg)

            chat.model = model_id
            chat.data_format = req.data_format
            chat.data_mode = req.data_mode
            db.commit()

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
    """Generate dataset from chat context.
    Passes the FULL chat history to the LLM so it generates the exact
    rows and columns the user asked for in the conversation."""
    chat = db.query(Chat).filter(Chat.id == chat_id, Chat.user_id == user_id).first()
    if not chat:
        return error_response("Chat not found", 404)

    db_messages = db.query(Message).filter(Message.chat_id == chat.id).order_by(Message.created_at).all()
    if not db_messages:
        return error_response("No messages in chat")

    # Build chat history as plain dicts for the LLM
    chat_history = []
    for msg in db_messages:
        chat_history.append({"role": msg.role.value, "content": msg.content})

    # Determine data mode — compound forces live_data
    data_mode = req.data_mode or (chat.data_mode or "synthetic").lower()
    if data_mode == "real-time":
        data_mode = "realistic"
    model_id_for_gen = req.model_id or chat.model
    if is_compound(model_id_for_gen):
        data_mode = "live-data"

    # Build context string for table name derivation
    context = chat.title or ""

    # Pass full chat history to LLM — it decides rows/columns from conversation
    try:
        result = generate_dataset_from_chat(
            chat_messages=chat_history,
            fmt=req.format,
            model_id=model_id_for_gen,
            data_mode=data_mode,
            default_rows=req.rows,
            context=context,
        )
    except ValueError as exc:
        return error_response(str(exc))
    except Exception as exc:
        return error_response(f"Dataset generation failed: {str(exc)[:300]}")

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
