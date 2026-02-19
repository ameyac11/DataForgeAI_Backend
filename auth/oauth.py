import httpx
from config import get_settings

settings = get_settings()

# google oauth
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
GOOGLE_SCOPES = "email profile openid"

# github oauth
GITHUB_AUTH_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"
GITHUB_EMAILS_URL = "https://api.github.com/user/emails"
GITHUB_SCOPES = "user:email read:user"


def get_google_auth_url() -> str:
    redirect_uri = f"{settings.BACKEND_URL}/api/v1/auth/google/callback"
    return (
        f"{GOOGLE_AUTH_URL}?client_id={settings.GOOGLE_CLIENT_ID}"
        f"&redirect_uri={redirect_uri}&response_type=code"
        f"&scope={GOOGLE_SCOPES}&access_type=offline&prompt=consent"
    )


async def exchange_google_code(code: str) -> dict:
    """Exchange auth code for user info."""
    redirect_uri = f"{settings.BACKEND_URL}/api/v1/auth/google/callback"
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(GOOGLE_TOKEN_URL, data={
            "code": code,
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        })
        tokens = token_resp.json()
        access_token = tokens.get("access_token")
        if not access_token:
            raise ValueError(f"Google token exchange failed: {tokens}")

        user_resp = await client.get(GOOGLE_USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"})
        return user_resp.json()


def get_github_auth_url() -> str:
    redirect_uri = f"{settings.BACKEND_URL}/api/v1/auth/github/callback"
    return (
        f"{GITHUB_AUTH_URL}?client_id={settings.GITHUB_CLIENT_ID}"
        f"&redirect_uri={redirect_uri}&scope={GITHUB_SCOPES}"
    )


async def exchange_github_code(code: str) -> dict:
    """Exchange auth code for user info + primary email."""
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            GITHUB_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.GITHUB_CLIENT_ID,
                "client_secret": settings.GITHUB_CLIENT_SECRET,
            },
            headers={"Accept": "application/json"},
        )
        tokens = token_resp.json()
        access_token = tokens.get("access_token")
        if not access_token:
            raise ValueError(f"GitHub token exchange failed: {tokens}")

        headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}

        user_resp = await client.get(GITHUB_USER_URL, headers=headers)
        user_data = user_resp.json()

        # get primary verified email
        emails_resp = await client.get(GITHUB_EMAILS_URL, headers=headers)
        emails = emails_resp.json()
        primary_email = next((e["email"] for e in emails if e.get("primary") and e.get("verified")), None)
        if not primary_email and emails:
            primary_email = emails[0].get("email")

        user_data["email"] = primary_email or user_data.get("email")
        return user_data
