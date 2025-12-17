"""
State manager for EV group state persistence.
"""
import logging
from typing import Optional, List
from datetime import datetime, timedelta

from sqlalchemy import select, update, delete
from sqlalchemy.dialects.postgresql import insert

from database.engine import get_session
from database.models import EVGroupState
from .models import EVGroupKey, EVGroupStats

logger = logging.getLogger(__name__)


class EVStateManager:
    """Управление персистентным состоянием групп."""

    async def get_state(self, group_key: str) -> Optional[EVGroupState]:
        """Получить состояние группы."""
        async for session in get_session():
            try:
                result = await session.execute(
                    select(EVGroupState).where(EVGroupState.group_key == group_key)
                )
                return result.scalar_one_or_none()
            except Exception as e:
                logger.error(f"Error getting EV state for {group_key}: {e}")
                return None

    async def is_disabled(self, group_key: str) -> bool:
        """Проверить отключена ли группа."""
        state = await self.get_state(group_key)
        if not state:
            return False

        # Check manual override
        if state.manual_override:
            if state.override_until and datetime.utcnow() < state.override_until:
                return False  # Override active - not disabled
            # Override expired - check actual state

        # Check disabled_until
        if state.disabled_until and datetime.utcnow() >= state.disabled_until:
            return False  # Temporary disable expired

        return state.is_disabled

    async def upsert_state(
        self,
        group_key: str,
        level: str,
        stats: EVGroupStats,
        is_disabled: bool = False,
        disable_reason: Optional[str] = None,
    ) -> bool:
        """
        Создать или обновить состояние группы.

        Args:
            group_key: Ключ группы
            level: Уровень (L1, L2, L3)
            stats: Текущая статистика
            is_disabled: Флаг отключения
            disable_reason: Причина отключения
        """
        async for session in get_session():
            try:
                stmt = insert(EVGroupState).values(
                    group_key=group_key,
                    level=level,
                    is_disabled=is_disabled,
                    disable_reason=disable_reason,
                    last_eval_at=datetime.utcnow(),
                    last_real_ev=stats.real_ev,
                    last_rolling_ev=stats.rolling_ev,
                    last_sample_size=stats.sample_size,
                    last_winrate=stats.winrate,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                ).on_conflict_do_update(
                    index_elements=['group_key'],
                    set_={
                        'is_disabled': is_disabled,
                        'disable_reason': disable_reason,
                        'last_eval_at': datetime.utcnow(),
                        'last_real_ev': stats.real_ev,
                        'last_rolling_ev': stats.rolling_ev,
                        'last_sample_size': stats.sample_size,
                        'last_winrate': stats.winrate,
                        'updated_at': datetime.utcnow(),
                    }
                )
                await session.execute(stmt)
                await session.commit()
                return True
            except Exception as e:
                logger.error(f"Error upserting EV state for {group_key}: {e}")
                return False

    async def set_manual_override(
        self,
        group_key: str,
        user_id: int,
        duration_hours: Optional[int] = None,
        reason: Optional[str] = None,
    ) -> bool:
        """
        Установить manual override для группы.

        Args:
            group_key: Ключ группы
            user_id: ID пользователя
            duration_hours: Длительность override в часах (None = permanent)
            reason: Причина override
        """
        async for session in get_session():
            try:
                override_until = None
                if duration_hours:
                    override_until = datetime.utcnow() + timedelta(hours=duration_hours)

                stmt = update(EVGroupState).where(
                    EVGroupState.group_key == group_key
                ).values(
                    manual_override=True,
                    override_by=user_id,
                    override_until=override_until,
                    override_reason=reason,
                    updated_at=datetime.utcnow(),
                )
                result = await session.execute(stmt)
                await session.commit()
                return result.rowcount > 0
            except Exception as e:
                logger.error(f"Error setting manual override for {group_key}: {e}")
                return False

    async def clear_manual_override(self, group_key: str) -> bool:
        """Снять manual override."""
        async for session in get_session():
            try:
                stmt = update(EVGroupState).where(
                    EVGroupState.group_key == group_key
                ).values(
                    manual_override=False,
                    override_by=None,
                    override_until=None,
                    override_reason=None,
                    updated_at=datetime.utcnow(),
                )
                result = await session.execute(stmt)
                await session.commit()
                return result.rowcount > 0
            except Exception as e:
                logger.error(f"Error clearing manual override for {group_key}: {e}")
                return False

    async def set_disabled(
        self,
        group_key: str,
        reason: str,
        duration_hours: Optional[int] = None,
    ) -> bool:
        """
        Отключить группу.

        Args:
            group_key: Ключ группы
            reason: Причина (auto_disabled, manual_disabled)
            duration_hours: Длительность бана (None = permanent)
        """
        async for session in get_session():
            try:
                disabled_until = None
                if duration_hours:
                    disabled_until = datetime.utcnow() + timedelta(hours=duration_hours)

                stmt = update(EVGroupState).where(
                    EVGroupState.group_key == group_key
                ).values(
                    is_disabled=True,
                    disable_reason=reason,
                    disabled_until=disabled_until,
                    updated_at=datetime.utcnow(),
                )
                result = await session.execute(stmt)
                await session.commit()
                return result.rowcount > 0
            except Exception as e:
                logger.error(f"Error setting disabled for {group_key}: {e}")
                return False

    async def set_enabled(self, group_key: str) -> bool:
        """Включить группу."""
        async for session in get_session():
            try:
                stmt = update(EVGroupState).where(
                    EVGroupState.group_key == group_key
                ).values(
                    is_disabled=False,
                    disable_reason=None,
                    disabled_until=None,
                    updated_at=datetime.utcnow(),
                )
                result = await session.execute(stmt)
                await session.commit()
                return result.rowcount > 0
            except Exception as e:
                logger.error(f"Error enabling {group_key}: {e}")
                return False

    async def get_all_disabled(self) -> List[EVGroupState]:
        """Получить все отключённые группы."""
        async for session in get_session():
            try:
                result = await session.execute(
                    select(EVGroupState).where(EVGroupState.is_disabled == True)
                )
                return list(result.scalars().all())
            except Exception as e:
                logger.error(f"Error getting disabled groups: {e}")
                return []

    async def get_all_states(self) -> List[EVGroupState]:
        """Получить все состояния."""
        async for session in get_session():
            try:
                result = await session.execute(select(EVGroupState))
                return list(result.scalars().all())
            except Exception as e:
                logger.error(f"Error getting all states: {e}")
                return []

    async def disable_group(
        self,
        group_key: str,
        reason: str,
        duration_hours: Optional[int] = None,
    ) -> bool:
        """Alias for set_disabled."""
        return await self.set_disabled(group_key, reason, duration_hours)
