# risk_manager.py
import MetaTrader5 as mt5

class RiskManager:
    def __init__(self, symbol, stop_loss_pips, risk_reward_ratio):
        self.symbol = symbol
        self.stop_loss_pips = stop_loss_pips
        self.risk_reward_ratio = risk_reward_ratio
        self.point = mt5.symbol_info(self.symbol).point

    def calculate_sl_tp(self, order_type, entry_price):
        """Calculates Stop Loss and Take Profit prices."""
        sl_pips = self.stop_loss_pips * self.point
        tp_pips = self.stop_loss_pips * self.risk_reward_ratio * self.point

        if order_type == "BUY":
            sl_price = entry_price - sl_pips
            tp_price = entry_price + tp_pips
        elif order_type == "SELL":
            sl_price = entry_price + sl_pips
            tp_price = entry_price - tp_pips
        else:
            return None, None

        return round(sl_price, 5), round(tp_price, 5)