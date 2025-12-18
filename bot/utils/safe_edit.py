"""
Safe message editing utility.
Handles media messages by deleting and sending new message.
"""
from aiogram.types import Message, InlineKeyboardMarkup
from typing import Optional


async def safe_edit_text(
    message: Message,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    **kwargs
) -> Message:
    """
    Безопасное редактирование сообщения.
    Если сообщение с медиа (фото/видео) - удаляет и отправляет новое.

    Args:
        message: Сообщение для редактирования
        text: Новый текст
        reply_markup: Клавиатура
        **kwargs: Дополнительные параметры для edit_text/answer

    Returns:
        Отредактированное или новое сообщение
    """
    try:
        return await message.edit_text(text, reply_markup=reply_markup, **kwargs)
    except Exception:
        # Сообщение с медиа - удаляем и отправляем новое
        try:
            await message.delete()
        except Exception:
            pass
        return await message.answer(text, reply_markup=reply_markup, **kwargs)
