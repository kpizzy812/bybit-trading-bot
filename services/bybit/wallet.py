import logging
from typing import Dict
from .client import BybitError

logger = logging.getLogger(__name__)


class WalletMixin:
    """Миксин для работы с кошельком"""

    async def get_wallet_balance(self) -> Dict:
        """
        Получить баланс кошелька

        Returns:
            {
                'totalEquity': '1000.00',
                'availableBalance': '950.00',
                'totalWalletBalance': '1000.00',
                ...
            }
        """
        try:
            response = self.client.get_wallet_balance(
                accountType="UNIFIED"  # V5 API uses UNIFIED account
            )
            result = self._handle_response(response)

            # Ищем USDT баланс
            for coin in result.get('list', [{}])[0].get('coin', []):
                if coin.get('coin') == 'USDT':
                    return coin

            raise BybitError("USDT balance not found")

        except Exception as e:
            logger.error(f"Error getting wallet balance: {e}")
            raise BybitError(f"Failed to get balance: {str(e)}")
