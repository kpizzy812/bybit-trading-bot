from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Update
import config


class OwnerCheckMiddleware(BaseMiddleware):
    """
    Middleware для проверки Owner-only режима.

    Если OWNER_TELEGRAM_ID установлен (не 0), то только owner может использовать бота.
    Все апдейты от других пользователей игнорируются.
    """

    async def __call__(
        self,
        handler: Callable[[Update, Dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: Dict[str, Any]
    ) -> Any:
        # Если owner mode не активен (ID = 0), пропускаем всех
        if config.OWNER_TELEGRAM_ID == 0:
            return await handler(event, data)

        # Получаем user_id из события
        user_id = None

        if event.message:
            user_id = event.message.from_user.id
        elif event.callback_query:
            user_id = event.callback_query.from_user.id
        elif event.inline_query:
            user_id = event.inline_query.from_user.id

        # Если user_id не найден (странная ситуация), блокируем
        if user_id is None:
            return

        # Проверяем, является ли пользователь owner'ом
        if user_id != config.OWNER_TELEGRAM_ID:
            # Логируем попытку доступа
            username = getattr(event.message.from_user if event.message else event.callback_query.from_user, 'username', 'unknown')

            print(f"🔒 Access denied for user {user_id} (@{username}). Owner-only mode enabled.")

            # Отправляем сообщение о блокировке (опционально)
            if event.message:
                await event.message.answer(
                    "🔒 This bot is in owner-only mode.\n"
                    "Access denied."
                )

            # Блокируем дальнейшую обработку
            return

        # Пользователь является owner'ом, продолжаем обработку
        return await handler(event, data)
