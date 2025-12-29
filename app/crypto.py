import base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

def _derive_key(raw: str) -> bytes:
    # Accept urlsafe base64-ish strings or plain text.
    b = raw.encode("utf-8")
    # Make a 32-byte key deterministically: if already 32+ bytes, truncate; else pad.
    if len(b) >= 32:
        return b[:32]
    return (b + b"\0" * 32)[:32]

class Crypto:
    def __init__(self, key_str: str):
        if not key_str:
            raise RuntimeError("APP_ENCRYPTION_KEY secret is required")
        self.key = _derive_key(key_str)
        self.aes = AESGCM(self.key)

    def encrypt(self, plaintext: str | None) -> str:
        if plaintext is None:
            return ""
        pt = plaintext.encode("utf-8")
        nonce = AESGCM.generate_key(bit_length=96)[:12]  # 12 bytes nonce
        ct = self.aes.encrypt(nonce, pt, None)
        blob = nonce + ct
        return base64.urlsafe_b64encode(blob).decode("utf-8")

    def decrypt(self, token: str | None) -> str:
        if not token:
            return ""
        blob = base64.urlsafe_b64decode(token.encode("utf-8"))
        nonce, ct = blob[:12], blob[12:]
        pt = self.aes.decrypt(nonce, ct, None)
        return pt.decode("utf-8")
