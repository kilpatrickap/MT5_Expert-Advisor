# risk_manager.py

class RiskManager:
    """
    Manages risk-related calculations for trades.

    This class is responsible for determining the Stop Loss (SL) and Take Profit (TP)
    levels for a trade based on pre-configured parameters. It is designed to be
    independent of a live MetaTrader 5 connection, receiving all necessary market
    information (like the 'point' value) during its initialization.
    """

    def __init__(self, symbol: str, stop_loss_pips: int, risk_reward_ratio: float, point: float):
        """
        Initializes the RiskManager with parameters for a specific symbol.

        Args:
            symbol (str): The trading symbol (e.g., 'EURUSD').
            stop_loss_pips (int): The distance of the stop loss from the entry price, in pips.
            risk_reward_ratio (float): The ratio of potential profit to potential loss (e.g., 2.0 means TP is twice as far as SL).
            point (float): The smallest possible price change for the symbol. This is critical for converting pips to price values.
        """
        if not isinstance(stop_loss_pips, int) or stop_loss_pips <= 0:
            raise ValueError("stop_loss_pips must be a positive integer.")
        if not isinstance(risk_reward_ratio, (float, int)) or risk_reward_ratio <= 0:
            raise ValueError("risk_reward_ratio must be a positive number.")

        self.symbol = symbol
        self.stop_loss_pips = stop_loss_pips
        self.risk_reward_ratio = risk_reward_ratio
        self.point = point

        # Determine the number of decimal places for rounding from the point value.
        # Example: if point is 0.00001, decimals will be 5.
        self.price_decimals = str(point)[::-1].find('.') if '.' in str(point) else 0

    def calculate_sl_tp(self, order_type: str, entry_price: float) -> tuple[float, float]:
        """
        Calculates the exact Stop Loss and Take Profit price levels.

        Args:
            order_type (str): The type of the order, must be either 'BUY' or 'SELL'.
            entry_price (float): The price at which the trade will be entered.

        Returns:
            tuple[float, float]: A tuple containing the calculated (stop_loss_price, take_profit_price).
                                 Returns (None, None) if the order_type is invalid.
        """
        # Convert the Stop Loss from pips into the symbol's price scale
        sl_in_price = self.stop_loss_pips * self.point

        # Calculate the Take Profit distance based on the SL and the risk/reward ratio
        tp_in_price = sl_in_price * self.risk_reward_ratio

        if order_type.upper() == "BUY":
            sl_price = entry_price - sl_in_price
            tp_price = entry_price + tp_in_price
        elif order_type.upper() == "SELL":
            sl_price = entry_price + sl_in_price
            tp_price = entry_price - tp_in_price
        else:
            # If the order type is not 'BUY' or 'SELL', we cannot calculate SL/TP.
            return None, None

        # Round the final prices to the correct number of decimal places for the symbol
        return round(sl_price, self.price_decimals), round(tp_price, self.price_decimals)# risk_manager.py

class RiskManager:
    """
    Manages risk-related calculations for trades.

    This class is responsible for determining the Stop Loss (SL) and Take Profit (TP)
    levels for a trade based on pre-configured parameters. It is designed to be
    independent of a live MetaTrader 5 connection, receiving all necessary market
    information (like the 'point' value) during its initialization.
    """

    def __init__(self, symbol: str, stop_loss_pips: int, risk_reward_ratio: float, point: float):
        """
        Initializes the RiskManager with parameters for a specific symbol.

        Args:
            symbol (str): The trading symbol (e.g., 'EURUSD').
            stop_loss_pips (int): The distance of the stop loss from the entry price, in pips.
            risk_reward_ratio (float): The ratio of potential profit to potential loss (e.g., 2.0 means TP is twice as far as SL).
            point (float): The smallest possible price change for the symbol. This is critical for converting pips to price values.
        """
        if not isinstance(stop_loss_pips, int) or stop_loss_pips <= 0:
            raise ValueError("stop_loss_pips must be a positive integer.")
        if not isinstance(risk_reward_ratio, (float, int)) or risk_reward_ratio <= 0:
            raise ValueError("risk_reward_ratio must be a positive number.")

        self.symbol = symbol
        self.stop_loss_pips = stop_loss_pips
        self.risk_reward_ratio = risk_reward_ratio
        self.point = point

        # Determine the number of decimal places for rounding from the point value.
        # Example: if point is 0.00001, decimals will be 5.
        self.price_decimals = str(point)[::-1].find('.') if '.' in str(point) else 0

    def calculate_sl_tp(self, order_type: str, entry_price: float) -> tuple[float, float]:
        """
        Calculates the exact Stop Loss and Take Profit price levels.

        Args:
            order_type (str): The type of the order, must be either 'BUY' or 'SELL'.
            entry_price (float): The price at which the trade will be entered.

        Returns:
            tuple[float, float]: A tuple containing the calculated (stop_loss_price, take_profit_price).
                                 Returns (None, None) if the order_type is invalid.
        """
        # Convert the Stop Loss from pips into the symbol's price scale
        sl_in_price = self.stop_loss_pips * self.point

        # Calculate the Take Profit distance based on the SL and the risk/reward ratio
        tp_in_price = sl_in_price * self.risk_reward_ratio

        if order_type.upper() == "BUY":
            sl_price = entry_price - sl_in_price
            tp_price = entry_price + tp_in_price
        elif order_type.upper() == "SELL":
            sl_price = entry_price + sl_in_price
            tp_price = entry_price - tp_in_price
        else:
            # If the order type is not 'BUY' or 'SELL', we cannot calculate SL/TP.
            return None, None

        # Round the final prices to the correct number of decimal places for the symbol
        return round(sl_price, self.price_decimals), round(tp_price, self.price_decimals)