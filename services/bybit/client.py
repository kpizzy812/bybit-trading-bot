import logging
from typing import Dict
from pybit.unified_trading import HTTP
import config

logger = logging.getLogger(__name__)


class BybitError(Exception):
    """Custom exception for Bybit API errors"""
    pass


class BaseBybitClient:
    """
    Базовый клиент для Bybit API V5 (Unified Trading)
    Поддерживает testnet/live режимы
    """

    def __init__(self, testnet: bool = True):
        self.testnet = testnet

        # Используем функцию get_bybit_keys для получения ключей
        api_key, api_secret = config.get_bybit_keys(testnet)

        if not api_key or not api_secret:
            raise ValueError(
                f"Bybit API credentials not found for {'testnet' if testnet else 'live'} mode. "
                "Please set them in .env file."
            )

        self.client = HTTP(
            testnet=testnet,
            api_key=api_key,
            api_secret=api_secret
        )

        logger.info(f"Bybit client initialized ({'testnet' if testnet else 'live'} mode)")

    def _handle_response(self, response: Dict) -> Dict:
        """Обработка ответа от Bybit API"""
        ret_code = response.get('retCode', -1)
        ret_msg = response.get('retMsg', 'Unknown error')

        if ret_code != 0:
            # Типичные ошибки
            error_lower = ret_msg.lower()

            if "insufficient" in error_lower or "balance" in error_lower:
                raise BybitError("💸 Insufficient balance")
            elif "duplicate" in error_lower or "exists" in error_lower:
                raise BybitError("⚠️ Order already placed")
            elif "invalid" in error_lower:
                raise BybitError(f"❌ Invalid parameters: {ret_msg}")
            else:
                raise BybitError(f"❌ Bybit API error: {ret_msg}")

        return response.get('result', {})
