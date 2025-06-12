# trading_strategy.py
import pandas as pd
import pandas_ta as ta

class RegimeMomentumStrategy:
    """
    A trading strategy that combines a regime filter (ADX) with a momentum
    entry (EMA trend + Stochastic pullback).

    The core idea is to only trade during strong trends and enter on temporary
    dips or pullbacks, aiming to improve the probability of success compared to a
    simple crossover system. It also includes a protective exit signal if the
    underlying trend fails.
    """

    def __init__(self, fast_ema_period: int, slow_ema_period: int, adx_period: int,
                 adx_threshold: int, stoch_k_period: int, stoch_d_period: int,
                 stoch_slowing: int, stoch_oversold: int, stoch_overbought: int):
        """
        Initializes the strategy with its various indicator parameters.
        """
        # EMA parameters for trend direction
        self.fast_ema_period = fast_ema_period
        self.slow_ema_period = slow_ema_period

        # ADX parameters for regime filter (trend strength)
        self.adx_period = adx_period
        self.adx_threshold = adx_threshold

        # Stochastic parameters for pullback entry trigger
        self.stoch_k = stoch_k_period
        self.stoch_d = stoch_d_period
        self.stoch_slowing = stoch_slowing
        self.stoch_oversold = stoch_oversold
        self.stoch_overbought = stoch_overbought

        # Determine the minimum number of bars required for all indicators to warm up
        self.min_bars = max(self.fast_ema_period, self.slow_ema_period, self.adx_period, self.stoch_k)

    def _calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """A helper method to calculate and append all required indicators."""
        # Calculate EMAs
        df.ta.ema(length=self.fast_ema_period, append=True)
        df.ta.ema(length=self.slow_ema_period, append=True)
        # Calculate ADX
        df.ta.adx(length=self.adx_period, append=True)
        # Calculate Stochastics
        df.ta.stoch(k=self.stoch_k, d=self.stoch_d, smooth_k=self.stoch_slowing, append=True)
        return df

    def get_entry_signal(self, historical_data: pd.DataFrame) -> str:
        """
        Analyzes data to find high-probability entry signals based on the strategy rules.

        Returns:
            str: 'BUY', 'SELL', or 'HOLD'.
        """
        if historical_data is None or len(historical_data) < self.min_bars + 3:
            return "HOLD"  # Not enough data for calculation

        df = historical_data.copy()
        df = self._calculate_indicators(df)

        # Rename columns for easier access (pandas-ta creates specific names)
        fast_ema_col = f'EMA_{self.fast_ema_period}'
        slow_ema_col = f'EMA_{self.slow_ema_period}'
        adx_col = f'ADX_{self.adx_period}'
        stoch_k_col = f'STOCHk_{self.stoch_k}_{self.stoch_d}_{self.stoch_slowing}'

        # Get the last two completed candles' values for crossover detection
        last = df.iloc[-2]
        prev = df.iloc[-3]

        # Check that indicator data is available for the candles we are checking
        if pd.isna(last[adx_col]) or pd.isna(last[stoch_k_col]) or pd.isna(last[slow_ema_col]):
            return "HOLD"  # Indicators have not fully warmed up

        # --- ENTRY LOGIC ---
        # Rule 1: Market must be trending
        is_trending = last[adx_col] > self.adx_threshold

        # Rule 2: Determine trend direction and check for pullback entry
        is_uptrend = last[fast_ema_col] > last[slow_ema_col]
        is_downtrend = last[fast_ema_col] < last[slow_ema_col]

        # BUY Signal: Strong uptrend (ADX) + Confirmed uptrend (EMAs) + Pullback is over (Stochastics crossover)
        stoch_crossed_up = last[stoch_k_col] > self.stoch_oversold and prev[stoch_k_col] <= self.stoch_oversold
        if is_trending and is_uptrend and stoch_crossed_up:
            return "BUY"

        # SELL Signal: Strong downtrend (ADX) + Confirmed downtrend (EMAs) + Pullback is over (Stochastics crossover)
        stoch_crossed_down = last[stoch_k_col] < self.stoch_overbought and prev[stoch_k_col] >= self.stoch_overbought
        if is_trending and is_downtrend and stoch_crossed_down:
            return "SELL"

        return "HOLD"

    def get_exit_signal(self, historical_data: pd.DataFrame, position_type: str) -> bool:
        """
        Checks for a protective exit condition, primarily if the core trend has failed.
        This is triggered by the EMAs crossing against the position.

        Args:
            historical_data (pd.DataFrame): The price data.
            position_type (str): The type of the open position ('BUY' or 'SELL').

        Returns:
            bool: True if an exit signal is found, False otherwise.
        """
        if historical_data is None or len(historical_data) < self.min_bars + 3:
            return False

        df = historical_data.copy()
        # Only need EMAs for the exit signal calculation
        df.ta.ema(length=self.fast_ema_period, append=True)
        df.ta.ema(length=self.slow_ema_period, append=True)

        fast_ema_col = f'EMA_{self.fast_ema_period}'
        slow_ema_col = f'EMA_{self.slow_ema_period}'

        last = df.iloc[-2]
        prev = df.iloc[-3]

        if pd.isna(last[slow_ema_col]) or pd.isna(prev[slow_ema_col]):
            return False  # Not enough data for a reliable signal

        # --- EXIT LOGIC ---
        # If in a BUY trade, exit if the trend reverses (fast EMA crosses below slow EMA)
        if position_type.upper() == "BUY":
            if last[fast_ema_col] < last[slow_ema_col] and prev[fast_ema_col] >= prev[slow_ema_col]:
                return True

        # If in a SELL trade, exit if the trend reverses (fast EMA crosses above slow EMA)
        elif position_type.upper() == "SELL":
            if last[fast_ema_col] > last[slow_ema_col] and prev[fast_ema_col] <= prev[slow_ema_col]:
                return True

        return False