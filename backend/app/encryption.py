from cryptography.fernet import Fernet
from app.config import settings
import base64


class EncryptionService:
    """プロンプト暗号化・復号化サービス"""

    def __init__(self):
        # 暗号化キーの準備
        key = settings.ENCRYPTION_KEY.encode()
        # 32バイトのキーをBase64エンコード
        if len(key) == 32:
            key = base64.urlsafe_b64encode(key)
        self.cipher = Fernet(key)

    def encrypt(self, plain_text: str) -> str:
        """
        プレーンテキストを暗号化

        Args:
            plain_text: 暗号化するテキスト

        Returns:
            暗号化されたテキスト（Base64エンコード済み）
        """
        if not plain_text:
            return ""

        encrypted_bytes = self.cipher.encrypt(plain_text.encode('utf-8'))
        return encrypted_bytes.decode('utf-8')

    def decrypt(self, encrypted_text: str) -> str:
        """
        暗号化されたテキストを復号化

        Args:
            encrypted_text: 暗号化されたテキスト

        Returns:
            復号化されたプレーンテキスト
        """
        if encrypted_text is None or not encrypted_text:
            return ""

        try:
            decrypted_bytes = self.cipher.decrypt(encrypted_text.encode('utf-8'))
            return decrypted_bytes.decode('utf-8')
        except Exception as e:
            raise ValueError(f"復号化に失敗しました: {str(e)}")


# シングルトンインスタンス
encryption_service = EncryptionService()

