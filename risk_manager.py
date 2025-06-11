# risk_manager.py

from logger_setup import log


class RiskManager:
    """
    Manages risk-related calculations for trades.

    This class is responsible for determining the Stop Loss (SL) and Take Profit (TP)
    levels for a trade. It is designed to be independent of a live MetaTrader 5
    connection but aware of broker-specific rules like minimum stop distance.
    """

    def __init__(self, symbol: str, stop_loss_pips: int, risk_reward_ratio: float, point: float, stops_level: int):
        """
        Initializes the RiskManager with parameters for a specific symbol.

        Args:
            symbol (str): The trading symbol (e.g., 'EURUSD').
            stop_loss_pips (int): The distance of the stop loss from the entry price, in pips.
            risk_reward_ratio (float): The ratio of potential profit to potential loss.
            point (float): The smallest possible price change for the symbol.
            stops_level (int): The minimum distance from the current price for placing stops, in points, as required by the broker.
        """
        if not isinstance(stop_loss_pips, int) or stop_loss_pips <= 0:
            raise ValueError("stop_loss_pips must be a positive integer.")
        if not isinstance(risk_reward_ratio, (float, int)) or risk_reward_ratio <= 0:
            raise ValueError("risk_reward_ratio must be a positive number.")

        self.symbol = symbol
        self.stop_loss_pips = stop_loss_pips
        self.risk_reward_ratio = risk_reward_ratio
        self.point = point
        self.stops_level = stops_level

        # Robustly determine the number of decimal places for rounding from the point value.
        # This handles both standard floats (0.0001) and scientific notation (1e-05).
        if 'e' in str(self.point).lower():
            self.price_decimals = int(str(self.point).split('-')[-1])
        else:
            self.price_decimals = len(str(self.point).split('.')[-1])

    def calculate_sl_tp(self, order_type: str, entry_price: float) -> tuple[float, float]:
        """
        Calculates the exact Stop Loss and Take Profit price levels, ensuring they respect broker limits.

        Args:
            order_type (str): The type of the order, must be either 'BUY' or 'SELL'.
            entry_price (float): The price at which the trade will be entered.

        Returns:
            A tuple containing the (stop_loss_price, take_profit_price).
        """
        sl_in_price = self.stop_loss_pips * self.point

        # --- VALIDATION AGAINST BROKER'S MINIMUM STOP DISTANCE ---
        min_stop_distance = self.stops_level * self.point

        if sl_in_price < min_stop_distance:
            # The configured Stop Loss is too tight for the broker.
            original_sl_pips = self.stop_loss_pips

            # Adjust the stop loss to the minimum required distance.
            sl_in_price = min_stop_distance

            # Log a warning to inform the user of this automatic adjustment.
            log.warning(
                f"Configured SL of {original_sl_pips} pips for {self.symbol} is below broker's minimum of "
                f"{self.stops_level} points. SL has been automatically adjusted to the minimum."
            )

        # Calculate Take Profit based on the (potentially adjusted) Stop Loss to maintain the R:R ratio.
        tp_in_price = sl_in_price * self.risk_reward_ratio

        if order_type.upper() == "BUY":
            sl_price = entry_price - sl_in_price
            tp_price = entry_price + tp_in_price
        elif order_type.upper() == "SELL":
            sl_price = entry_price + sl_in_price
            tp_price = entry_price - tp_in_price
        else:
            log.error(f"Invalid order_type '{order_type}' received in RiskManager.")
            return None, None

        # Round the final prices to the correct number of decimal places for the symbol.
        return round(sl_price, self.price_decimals), round(tp_price, self.price_decimals)