"""Initial schema - create all tables

Revision ID: 0001_initial_schema
Revises:
Create Date: 2024-12-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = '0001_initial_schema'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # market_contexts
    op.create_table(
        'market_contexts',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('analysis_id', sa.String(64), unique=True, index=True, nullable=False),
        sa.Column('symbol', sa.String(20), index=True, nullable=False),
        sa.Column('timeframe', sa.String(10), nullable=False),
        sa.Column('created_at', sa.DateTime, nullable=False),
        sa.Column('current_price', sa.Float, nullable=False),
        sa.Column('trend', sa.String(20), nullable=False),
        sa.Column('phase', sa.String(30), nullable=False),
        sa.Column('sentiment', sa.String(20), nullable=False),
        sa.Column('volatility', sa.String(20), nullable=False),
        sa.Column('bias', sa.String(10), nullable=False),
        sa.Column('strength', sa.Float, nullable=False),
        sa.Column('rsi', sa.Float, nullable=True),
        sa.Column('funding_rate_pct', sa.Float, nullable=True),
        sa.Column('long_short_ratio', sa.Float, nullable=True),
        sa.Column('key_levels', postgresql.JSON, nullable=True),
        sa.Column('data_quality_pct', sa.Integer, default=0),
    )
    op.create_index('ix_market_contexts_symbol_created', 'market_contexts', ['symbol', 'created_at'])

    # no_trade_signals
    op.create_table(
        'no_trade_signals',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('analysis_id', sa.String(64), sa.ForeignKey('market_contexts.analysis_id'), index=True, nullable=False),
        sa.Column('symbol', sa.String(20), index=True, nullable=False),
        sa.Column('timeframe', sa.String(10), nullable=False),
        sa.Column('created_at', sa.DateTime, nullable=False),
        sa.Column('should_not_trade', sa.Boolean, default=True),
        sa.Column('confidence', sa.Float, nullable=False),
        sa.Column('category', sa.String(50), nullable=False),
        sa.Column('reasons', postgresql.JSON, nullable=False),
        sa.Column('wait_for', postgresql.JSON, nullable=True),
        sa.Column('estimated_wait_hours', sa.Integer, nullable=True),
    )
    op.create_index('ix_no_trade_symbol_created', 'no_trade_signals', ['symbol', 'created_at'])

    # scenarios
    op.create_table(
        'scenarios',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('analysis_id', sa.String(64), sa.ForeignKey('market_contexts.analysis_id'), index=True, nullable=False),
        sa.Column('scenario_idx', sa.Integer, nullable=False),
        sa.Column('created_at', sa.DateTime, nullable=False),
        sa.Column('symbol', sa.String(20), index=True, nullable=False),
        sa.Column('timeframe', sa.String(10), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('bias', sa.String(10), nullable=False),
        sa.Column('confidence', sa.Float, nullable=False),
        sa.Column('confidence_raw', sa.Float, nullable=True),
        sa.Column('primary_archetype', sa.String(50), nullable=True),
        sa.Column('entry_price_min', sa.Float, nullable=False),
        sa.Column('entry_price_max', sa.Float, nullable=False),
        sa.Column('entry_type', sa.String(30), nullable=False),
        sa.Column('entry_plan', postgresql.JSON, nullable=True),
        sa.Column('stop_loss_conservative', sa.Float, nullable=False),
        sa.Column('stop_loss_aggressive', sa.Float, nullable=False),
        sa.Column('stop_loss_recommended', sa.Float, nullable=False),
        sa.Column('stop_loss_reason', sa.Text, nullable=True),
        sa.Column('stop_pct_of_entry', sa.Float, nullable=True),
        sa.Column('atr_multiple_stop', sa.Float, nullable=True),
        sa.Column('targets', postgresql.JSON, nullable=False),
        sa.Column('leverage_recommended', sa.String(20), nullable=False),
        sa.Column('leverage_max_safe', sa.String(20), nullable=False),
        sa.Column('leverage_volatility_adjusted', sa.Boolean, default=False),
        sa.Column('atr_pct', sa.Float, nullable=True),
        sa.Column('invalidation_price', sa.Float, nullable=False),
        sa.Column('invalidation_condition', sa.String(200), nullable=False),
        sa.Column('why_bullish', postgresql.JSON, nullable=True),
        sa.Column('why_bearish', postgresql.JSON, nullable=True),
        sa.Column('why_risks', postgresql.JSON, nullable=False),
        sa.Column('conditions', postgresql.JSON, nullable=False),
        sa.Column('no_trade_conditions', postgresql.JSON, nullable=True),
        sa.Column('time_valid_hours', sa.Integer, nullable=True),
        sa.Column('entry_trigger', sa.String(200), nullable=True),
        sa.Column('validation_status', sa.String(50), nullable=True),
        sa.Column('ev_r', sa.Float, nullable=True),
        sa.Column('ev_r_gross', sa.Float, nullable=True),
        sa.Column('ev_fees_r', sa.Float, nullable=True),
        sa.Column('ev_grade', sa.String(5), nullable=True),
        sa.Column('scenario_score', sa.Float, nullable=True),
        sa.Column('prob_sl', sa.Float, nullable=True),
        sa.Column('prob_tp1', sa.Float, nullable=True),
        sa.Column('prob_tp2', sa.Float, nullable=True),
        sa.Column('prob_tp3', sa.Float, nullable=True),
        sa.Column('prob_other', sa.Float, nullable=True),
        sa.Column('probs_source', sa.String(30), nullable=True),
        sa.Column('probs_sample_size', sa.Integer, nullable=True),
        sa.Column('class_key', sa.String(200), nullable=True),
        sa.Column('class_level', sa.String(10), nullable=True),
        sa.Column('class_sample_size', sa.Integer, nullable=True),
        sa.Column('class_winrate', sa.Float, nullable=True),
        sa.Column('class_avg_pnl_r', sa.Float, nullable=True),
        sa.Column('class_avg_ev_r', sa.Float, nullable=True),
        sa.Column('class_is_enabled', sa.Boolean, nullable=True),
        sa.Column('class_warning', sa.Text, nullable=True),
        sa.Column('learning_sl_atr_mult', sa.Float, nullable=True),
        sa.Column('learning_tp1_r', sa.Float, nullable=True),
        sa.Column('learning_tp2_r', sa.Float, nullable=True),
        sa.Column('learning_based_on_trades', sa.Integer, nullable=True),
        sa.Column('learning_confidence', sa.Float, nullable=True),
        sa.Column('raw_snapshot', postgresql.JSON, nullable=True),
    )
    op.create_index('ix_scenarios_symbol_created', 'scenarios', ['symbol', 'created_at'])
    op.create_index('ix_scenarios_archetype', 'scenarios', ['primary_archetype'])
    op.create_index('ix_scenarios_ev_grade', 'scenarios', ['ev_grade'])

    # trades
    op.create_table(
        'trades',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('trade_id', sa.String(64), unique=True, index=True, nullable=False),
        sa.Column('scenario_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('scenarios.id'), nullable=True),
        sa.Column('user_id', sa.Integer, index=True, nullable=False),
        sa.Column('created_at', sa.DateTime, nullable=False),
        sa.Column('opened_at', sa.DateTime, nullable=True),
        sa.Column('closed_at', sa.DateTime, nullable=True),
        sa.Column('symbol', sa.String(20), index=True, nullable=False),
        sa.Column('side', sa.String(10), nullable=False),
        sa.Column('timeframe', sa.String(10), nullable=True),
        sa.Column('entry_price', sa.Float, nullable=False),
        sa.Column('qty', sa.Float, nullable=False),
        sa.Column('leverage', sa.Integer, nullable=False),
        sa.Column('margin_mode', sa.String(20), default='Isolated'),
        sa.Column('margin_usd', sa.Float, nullable=False),
        sa.Column('entry_mode', sa.String(20), default='single'),
        sa.Column('stop_price', sa.Float, nullable=False),
        sa.Column('risk_usd', sa.Float, nullable=False),
        sa.Column('tp_price', sa.Float, nullable=True),
        sa.Column('rr_planned', sa.Float, nullable=True),
        sa.Column('exit_price', sa.Float, nullable=True),
        sa.Column('avg_exit_price', sa.Float, nullable=True),
        sa.Column('pnl_usd', sa.Float, nullable=True),
        sa.Column('pnl_percent', sa.Float, nullable=True),
        sa.Column('roe_percent', sa.Float, nullable=True),
        sa.Column('rr_actual', sa.Float, nullable=True),
        sa.Column('outcome', sa.String(20), nullable=True),
        sa.Column('exit_reason', sa.String(30), nullable=True),
        sa.Column('fills', postgresql.JSON, nullable=True),
        sa.Column('closed_qty', sa.Float, default=0.0),
        sa.Column('remaining_qty', sa.Float, nullable=True),
        sa.Column('entry_fee_usd', sa.Float, nullable=True),
        sa.Column('exit_fees_usd', sa.Float, nullable=True),
        sa.Column('funding_usd', sa.Float, nullable=True),
        sa.Column('total_fees_usd', sa.Float, nullable=True),
        sa.Column('min_price_seen', sa.Float, nullable=True),
        sa.Column('max_price_seen', sa.Float, nullable=True),
        sa.Column('mae_usd', sa.Float, nullable=True),
        sa.Column('mae_r', sa.Float, nullable=True),
        sa.Column('mfe_usd', sa.Float, nullable=True),
        sa.Column('mfe_r', sa.Float, nullable=True),
        sa.Column('r_result', sa.Float, nullable=True),
        sa.Column('market_regime', sa.String(50), nullable=True),
        sa.Column('status', sa.String(20), default='open'),
        sa.Column('testnet', sa.Boolean, default=False),
        sa.Column('scenario_source', sa.String(20), default='manual'),
        sa.Column('entry_reason', sa.Text, nullable=True),
        sa.Column('validation_status', sa.String(50), nullable=True),
        sa.Column('analysis_id', sa.String(64), nullable=True),
        sa.Column('scenario_confidence', sa.Float, nullable=True),
        sa.Column('scenario_bias', sa.String(10), nullable=True),
        sa.Column('scenario_archetype', sa.String(50), nullable=True),
        sa.Column('scenario_ev_r', sa.Float, nullable=True),
        sa.Column('scenario_ev_grade', sa.String(5), nullable=True),
        sa.Column('scenario_score', sa.Float, nullable=True),
        sa.Column('scenario_class_key', sa.String(200), nullable=True),
        sa.Column('scenario_class_winrate', sa.Float, nullable=True),
        sa.Column('scenario_class_warning', sa.Text, nullable=True),
        sa.Column('prob_sl', sa.Float, nullable=True),
        sa.Column('prob_tp1', sa.Float, nullable=True),
        sa.Column('probs_source', sa.String(30), nullable=True),
        sa.Column('scenario_snapshot', postgresql.JSON, nullable=True),
    )
    op.create_index('ix_trades_user_created', 'trades', ['user_id', 'created_at'])
    op.create_index('ix_trades_symbol_outcome', 'trades', ['symbol', 'outcome'])
    op.create_index('ix_trades_archetype_outcome', 'trades', ['scenario_archetype', 'outcome'])
    op.create_index('ix_trades_analysis_id', 'trades', ['analysis_id'])
    op.create_index('ix_trades_status_closed_at', 'trades', ['status', 'closed_at'])
    op.create_index('ix_trades_archetype_tf_closed', 'trades', ['scenario_archetype', 'timeframe', 'closed_at'])
    op.create_index('ix_trades_regime_closed', 'trades', ['market_regime', 'closed_at'])

    # user_settings
    op.create_table(
        'user_settings',
        sa.Column('user_id', sa.Integer, primary_key=True),
        sa.Column('created_at', sa.DateTime, nullable=False),
        sa.Column('updated_at', sa.DateTime, nullable=False),
        sa.Column('trading_capital_mode', sa.String(20), default='manual'),
        sa.Column('trading_capital_usd', sa.Float, nullable=True),
        sa.Column('default_risk_usd', sa.Float, default=5.0),
        sa.Column('default_leverage', sa.Integer, default=10),
        sa.Column('default_margin_mode', sa.String(20), default='Isolated'),
        sa.Column('default_tp_mode', sa.String(20), default='rr'),
        sa.Column('default_tp_rr', sa.Float, default=2.0),
        sa.Column('shorts_enabled', sa.Boolean, default=True),
        sa.Column('confirm_always', sa.Boolean, default=True),
        sa.Column('max_risk_per_trade', sa.Float, default=50.0),
        sa.Column('max_margin_per_trade', sa.Float, default=500.0),
        sa.Column('max_notional_per_trade', sa.Float, default=10000.0),
        sa.Column('testnet_mode', sa.Boolean, default=False),
        sa.Column('auto_breakeven_enabled', sa.Boolean, default=True),
        sa.Column('max_active_positions', sa.Integer, default=5),
        sa.Column('confidence_risk_scaling', sa.Boolean, default=True),
    )

    # ev_group_state
    op.create_table(
        'ev_group_state',
        sa.Column('group_key', sa.String(200), primary_key=True),
        sa.Column('level', sa.String(10), nullable=False),
        sa.Column('is_disabled', sa.Boolean, default=False),
        sa.Column('disabled_until', sa.DateTime, nullable=True),
        sa.Column('disable_reason', sa.String(50), nullable=True),
        sa.Column('last_eval_at', sa.DateTime, nullable=False),
        sa.Column('last_real_ev', sa.Float, nullable=True),
        sa.Column('last_rolling_ev', sa.Float, nullable=True),
        sa.Column('last_sample_size', sa.Integer, nullable=True),
        sa.Column('last_winrate', sa.Float, nullable=True),
        sa.Column('manual_override', sa.Boolean, default=False),
        sa.Column('override_by', sa.Integer, nullable=True),
        sa.Column('override_until', sa.DateTime, nullable=True),
        sa.Column('override_reason', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False),
        sa.Column('updated_at', sa.DateTime, nullable=False),
    )

    # ev_gate_log
    op.create_table(
        'ev_gate_log',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime, index=True, nullable=False),
        sa.Column('user_id', sa.Integer, index=True, nullable=False),
        sa.Column('archetype', sa.String(50), nullable=False),
        sa.Column('timeframe', sa.String(10), nullable=True),
        sa.Column('market_regime', sa.String(50), nullable=True),
        sa.Column('symbol', sa.String(20), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('selected_level', sa.String(10), nullable=True),
        sa.Column('selected_key', sa.String(200), nullable=True),
        sa.Column('real_ev', sa.Float, nullable=True),
        sa.Column('rolling_ev', sa.Float, nullable=True),
        sa.Column('sample_size', sa.Integer, nullable=True),
        sa.Column('user_action', sa.String(30), nullable=True),
    )
    op.create_index('ix_ev_gate_log_user_created', 'ev_gate_log', ['user_id', 'created_at'])
    op.create_index('ix_ev_gate_log_status', 'ev_gate_log', ['status'])


def downgrade() -> None:
    op.drop_table('ev_gate_log')
    op.drop_table('ev_group_state')
    op.drop_table('user_settings')
    op.drop_table('trades')
    op.drop_table('scenarios')
    op.drop_table('no_trade_signals')
    op.drop_table('market_contexts')
