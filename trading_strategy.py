# trading_strategy.py
import pandas as pd


class MACrossoverStrategy:
    def __init__(self, fast_ma_period, slow_ma_period):
        self.fast_ma_period = fast_ma_period
        self.slow_ma_period = slow_ma_period

    def get_signal(self, historical_data: pd.DataFrame):
        """
        Analyzes historical data and returns a trading signal.
        Returns: 'BUY', 'SELL', or 'HOLD'.
        """
        if historical_data is None or len(historical_data) < self.slow_ma_period:
            return "HOLD"  # Not enough data

        # Calculate MAs
        df = historical_data.copy()
        df['fast_ma'] = df['close'].rolling(window=self.fast_ma_period).mean()
        df['slow_ma'] = df['close'].rolling(window=self.slow_ma_period).mean()

        # Get the last two completed candles' values
        last_candle = df.iloc[-2]
        prev_candle = df.iloc[-3]

        # Crossover logic
        # Buy signal: Fast MA crosses above Slow MA
        if last_candle['fast_ma'] > last_candle['slow_ma'] and prev_candle['fast_ma'] <= prev_candle['slow_ma']:
            return "BUY"

        # Sell signal: Fast MA crosses below Slow MA
        if last_candle['fast_ma'] < last_candle['slow_ma'] and prev_candle['fast_ma'] >= prev_candle['slow_ma']:
            return "SELL"

        return "HOLD"