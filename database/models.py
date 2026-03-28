import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy import Column, String, DateTime, ForeignKey, Text, Enum, UniqueConstraint, Index, Boolean, Integer
from sqlalchemy.dialects.postgresql import UUID, JSON
from sqlalchemy.orm import relationship

from database.base import Base
from database.enums import AuthProvider, MessageRole

IST = timezone(timedelta(hours=5, minutes=30))


def now_ist():
    return datetime.now(IST)


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=True)
    role = Column(String(50), nullable=True)
    purpose = Column(Text, nullable=True)
    onboarding_completed = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=now_ist, nullable=False)

    auth_providers = relationship("AuthProviderModel", back_populates="user", cascade="all, delete-orphan")
    chats = relationship("Chat", back_populates="user", cascade="all, delete-orphan")
    datasets = relationship("UserDataset", back_populates="user", cascade="all, delete-orphan")
    analytics_runs = relationship("AnalyticsRun", back_populates="user", cascade="all, delete-orphan")


class AuthProviderModel(Base):
    __tablename__ = "auth_providers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    provider = Column(Enum(AuthProvider), nullable=False)
    provider_user_id = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), default=now_ist, nullable=False)

    user = relationship("User", back_populates="auth_providers")

    __table_args__ = (
        UniqueConstraint("provider", "provider_user_id", name="uq_provider_user"),
        Index("idx_provider_user", "provider", "provider_user_id"),
    )


class Chat(Base):
    __tablename__ = "chats"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(255), nullable=False, default="New Chat")
    starred = Column(Boolean, default=False, nullable=False)
    pinned = Column(Boolean, default=False, nullable=False)
    model = Column(String(50), nullable=True)
    data_format = Column(String(10), nullable=True)
    data_mode = Column(String(20), nullable=True)
    created_at = Column(DateTime(timezone=True), default=now_ist, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=now_ist, onupdate=now_ist, nullable=True)

    user = relationship("User", back_populates="chats")
    messages = relationship("Message", back_populates="chat", cascade="all, delete-orphan", order_by="Message.created_at")


class DeletedChat(Base):
    __tablename__ = "deleted_chats"

    id = Column(UUID(as_uuid=True), primary_key=True)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    starred = Column(Boolean, default=False, nullable=False)
    pinned = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=True)
    deleted_at = Column(DateTime(timezone=True), default=now_ist, nullable=False)
    messages_data = Column(JSON, default=list, nullable=False)


class Message(Base):
    __tablename__ = "messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chat_id = Column(UUID(as_uuid=True), ForeignKey("chats.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(Enum(MessageRole), nullable=False)
    content = Column(Text, nullable=False)
    show_download = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=now_ist, nullable=False)

    chat = relationship("Chat", back_populates="messages")


class UserDataset(Base):
    __tablename__ = "user_datasets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    dataset_name = Column(Text, nullable=False)
    generation_mode = Column(Text, nullable=False)
    model_used = Column(Text, nullable=False)
    file_size_bytes = Column(Integer, nullable=False)
    file_path = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=now_ist, nullable=False)

    user = relationship("User", back_populates="datasets")


class AnalyticsRun(Base):
    __tablename__ = "analytics_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id = Column(String(64), unique=True, nullable=False, index=True)
    filename = Column(Text, nullable=False)
    file_size_bytes = Column(Integer, nullable=False)
    rows = Column(Integer, nullable=False)
    columns = Column(Integer, nullable=False)
    numeric_columns = Column(Integer, nullable=False, default=0)
    categorical_columns = Column(Integer, nullable=False, default=0)
    missing_pct = Column(String(32), nullable=False, default="0.0")
    memory_bytes = Column(Integer, nullable=False, default=0)
    state = Column(String(20), nullable=False, default="active")
    created_at = Column(DateTime(timezone=True), default=now_ist, nullable=False)
    last_accessed_at = Column(DateTime(timezone=True), default=now_ist, nullable=False)

    user = relationship("User", back_populates="analytics_runs")
