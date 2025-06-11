# risk_manager.py

from logger_setup import log


class RiskManager:
    """
    Manages risk-related calculations for trades.

    This class is now spread-aware, making it suitable for high-frequency scalping
    where broker rules around stop levels and spread are critical.
    """

    def __init__(self, symbol: str, stop_loss_pips: int, risk_reward_ratio: float, point: float, stops_level: int):
        """
        Initializes the RiskManager with parameters for a specific symbol.

        Args:
            symbol (str): The trading symbol (e.g., 'EURUSD').
            stop_loss_pips (int): The desired distance of the stop loss from the entry price, in pips.
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
        if 'e' in str(self.point).lower():
            self.price_decimals = int(str(self.point).split('-')[-1])
        else:
            self.price_decimals = len(str(self.point).split('.')[-1])

    def calculate_sl_tp(self, order_type: str, current_ask: float, current_bid: float) -> tuple[
        float | None, float | None]:
        """
        Calculates SL/TP, ensuring they respect broker limits including the current spread.

        Args:
            order_type (str): The type of the order, must be either 'BUY' or 'SELL'.
            current_ask (float): The current ask price from the market tick.
            current_bid (float): The current bid price from the market tick.

        Returns:
            A tuple containing (stop_loss_price, take_profit_price), or (None, None) if inputs are invalid.
        """
        if not all([order_type, current_ask, current_bid]):
            log.error("RiskManager received invalid inputs for SL/TP calculation.")
            return None, None

        spread_in_points = (current_ask - current_bid) / self.point

        # The broker's minimum distance from the current price (in points)
        min_stop_level_in_points = self.stops_level

        # The true required distance for our SL must account for the spread and the broker's minimum stop level.
        # For a BUY, SL must be below BID. For a SELL, SL must be above ASK. The distance check is what matters.
        required_sl_distance_in_points = spread_in_points + min_stop_level_in_points

        sl_in_points = self.stop_loss_pips

        # Check if the configured stop loss is too tight for the current market conditions.
        if sl_in_points < required_sl_distance_in_points:
            original_sl_pips = self.stop_loss_pips
            # Adjust the stop loss to the minimum valid distance.
            sl_in_points = required_sl_distance_in_points

            log.warning(
                f"Configured SL for {self.symbol} is too tight for current spread({spread_in_points:.1f}) + stops_level({min_stop_level_in_points}). "
                f"Original: {original_sl_pips} pips, Required: {sl_in_points:.1f} pips. "
                f"SL automatically adjusted."
            )

        # Convert the final, validated stop loss from points to price.
        sl_in_price = sl_in_points * self.point
        tp_in_price = sl_in_price * self.risk_reward_ratio

        if order_type.upper() == "BUY":
            entry_price = current_ask
            sl_price = entry_price - sl_in_price
            tp_price = entry_price + tp_in_price
        elif order_type.upper() == "SELL":
            entry_price = current_bid
            sl_price = entry_price + sl_in_price
            tp_price = entry_price - tp_in_price
        else:
            log.error(f"Invalid order_type '{order_type}' received in RiskManager.")
            return None, None

        # Round the final prices to the correct number of decimal places for the symbol.
        return round(sl_price, self.price_decimals), round(tp_price, self.price_decimals)