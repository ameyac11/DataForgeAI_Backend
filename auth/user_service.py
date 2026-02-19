import uuid
from typing import Optional, Tuple
from sqlalchemy.orm import Session
from database.models import User, AuthProviderModel
from database.enums import AuthProvider


def get_user_by_email(db: Session, email: str) -> Optional[User]:
    return db.query(User).filter(User.email == email.lower()).first()


def get_user_by_provider(db: Session, provider: AuthProvider, provider_user_id: str) -> Optional[User]:
    auth = db.query(AuthProviderModel).filter(
        AuthProviderModel.provider == provider,
        AuthProviderModel.provider_user_id == provider_user_id,
    ).first()
    return auth.user if auth else None


def get_or_create_user_by_email(
    db: Session, email: str, provider: AuthProvider, provider_user_id: str
) -> Tuple[User, bool]:
    """Unified user identity — match by email across all providers."""
    email = email.lower().strip()

    # check if this exact provider link exists
    existing_auth = db.query(AuthProviderModel).filter(
        AuthProviderModel.provider == provider,
        AuthProviderModel.provider_user_id == provider_user_id,
    ).first()
    if existing_auth:
        return (existing_auth.user, False)

    # check if user with this email exists (linked via different provider)
    user = get_user_by_email(db, email)
    is_new = False

    if not user:
        user = User(id=uuid.uuid4(), email=email)
        db.add(user)
        db.flush()
        is_new = True

    # link this provider to the user
    link_auth_provider(db, user, provider, provider_user_id)
    db.commit()
    db.refresh(user)
    return (user, is_new)


def link_auth_provider(db: Session, user: User, provider: AuthProvider, provider_user_id: str) -> AuthProviderModel:
    existing = db.query(AuthProviderModel).filter(
        AuthProviderModel.user_id == user.id,
        AuthProviderModel.provider == provider,
    ).first()
    if existing:
        return existing

    auth_provider = AuthProviderModel(
        id=uuid.uuid4(),
        user_id=user.id,
        provider=provider,
        provider_user_id=provider_user_id,
    )
    db.add(auth_provider)
    db.flush()
    return auth_provider


def get_user_providers(db: Session, user_id: uuid.UUID) -> list:
    providers = db.query(AuthProviderModel).filter(AuthProviderModel.user_id == user_id).all()
    return [p.provider.value for p in providers]
