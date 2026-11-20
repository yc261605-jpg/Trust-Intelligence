"""QR token 小工具。"""
import secrets


def new_qr_token() -> str:
    """每張工單專屬 QR 裡放的隨機字串，別人猜不到。"""
    return secrets.token_urlsafe(16)
