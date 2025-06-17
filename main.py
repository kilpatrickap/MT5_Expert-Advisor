# main.py
import configparser
import time
import MetaTrader5 as mt5

from logger_setup import log
from mt5_connector import MT5Connector
from risk_manager import RiskManager
from trading_strategy import RegimeMomentumStrategy


def run():
    """Main execution function for the Expert Advisor."""
    # --- 1. Configuration Loading ---
    config = configparser.ConfigParser()
    config.read('config.ini')

    try:
        mt5_creds = config['mt5_credentials']
        trade_params = config['trading_parameters']
    except KeyError as e:
        log.error(f"Configuration error: Missing section or key - {e}. Aborting.")
        return

    # --- 2. Initialization of Main Components ---
    log.info("Starting Python Multi-Symbol Expert Advisor")
    connector = MT5Connector(
        login=int(mt5_creds['account']),
        password=mt5_creds['password'],
        server=mt5_creds['server']
    )

    if not connector.connect():
        log.error("Failed to connect to MT5. Exiting.")
        return

    try:
        symbols_to_trade = [s.strip() for s in trade_params['symbols'].split(',')]
        magic_number = int(trade_params['magic_number'])
    except KeyError as e:
        log.error(f"Trading parameter '{e}' is missing in config.ini. Exiting.")
        connector.disconnect()
        return

    # --- 3. Pre-Loop Initialization of Strategies and Risk Managers ---
    strategies = {}
    risk_managers = {}
    log.info("Initializing strategies and risk managers for each symbol...")
    for symbol in symbols_to_trade:
        try:
            # ... (Strategy initialization remains the same)
            symbol_config = config[symbol]
            strategies[symbol] = RegimeMomentumStrategy(
                fast_ema_period=int(symbol_config['fast_ema_period']),
                slow_ema_period=int(symbol_config['slow_ema_period']),
                adx_period=int(symbol_config['adx_period']),
                adx_threshold=int(symbol_config['adx_threshold']),
                stoch_k_period=int(symbol_config['stoch_k_period']),
                stoch_d_period=int(symbol_config['stoch_d_period']),
                stoch_slowing=int(symbol_config['stoch_slowing']),
                stoch_oversold=int(symbol_config['stoch_oversold']),
                stoch_overbought=int(symbol_config['stoch_overbought'])
            )
            symbol_info = mt5.symbol_info(symbol)
            if not symbol_info:
                log.error(f"Could not get info for {symbol}. It will be skipped.")
                continue
            risk_managers[symbol] = RiskManager(
                symbol=symbol,
                stop_loss_pips=int(symbol_config['stop_loss_pips']),
                risk_reward_ratio=float(symbol_config['risk_reward_ratio']),
                point=symbol_info.point,
                stops_level=symbol_info.trade_stops_level
            )
        except KeyError as e:
            log.error(f"Configuration error for symbol '{symbol}': Missing key {e}. This symbol will be skipped.")
            if symbol in strategies: del strategies[symbol]
            if symbol in risk_managers: del risk_managers[symbol]
            continue
    log.info(f"EA configured to trade symbols: {list(strategies.keys())}")

    # --- 4. Main Trading Loop ---
    try:
        while True:
            log.info("-------------------- New Trading Cycle --------------------")
            for symbol in strategies.keys():
                log.info(f"--- Processing symbol: {symbol} ---")
                try:
                    strategy = strategies[symbol]
                    risk_manager = risk_managers[symbol]
                    symbol_config = config[symbol]
                    timeframe_str = symbol_config['timeframe']

                    # NEW: Get risk percent from config
                    risk_percent = float(symbol_config.get('risk_per_trade_percent', 1.0))

                    historical_data = connector.get_historical_data(symbol, timeframe_str, strategy.min_bars + 5)
                    if historical_data is None or historical_data.empty:
                        log.warning(f"Could not fetch historical data for {symbol}. Skipping cycle.")
                        continue

                    open_positions = connector.get_open_positions(symbol=symbol, magic_number=magic_number)

                    if open_positions:
                        # ... (Exit logic remains the same)
                        current_pos = open_positions[0]
                        pos_type = "BUY" if current_pos.type == mt5.ORDER_TYPE_BUY else "SELL"
                        if strategy.get_exit_signal(historical_data, pos_type):
                            log.info(f"Protective exit signal for {symbol}. Closing position #{current_pos.ticket}.")
                            connector.close_position(current_pos, comment="Closed due to trend failure")
                        else:
                            log.info(f"Holding current {pos_type} position for {symbol}.")
                    else:
                        entry_signal = strategy.get_entry_signal(historical_data)
                        log.info(f"Strategy Entry Signal for {symbol} on {timeframe_str}: {entry_signal}")

                        if entry_signal in ["BUY", "SELL"]:
                            tick = mt5.symbol_info_tick(symbol)
                            if not tick:
                                log.warning(f"Could not get tick for {symbol}. Skipping trade.")
                                continue

                            # --- DYNAMIC SIZING LOGIC ---
                            # 1. Calculate SL/TP and the actual SL distance in pips
                            sl_price, tp_price, sl_pips = risk_manager.calculate_sl_tp(
                                order_type=entry_signal,
                                current_ask=tick.ask,
                                current_bid=tick.bid
                            )

                            if sl_price and tp_price and sl_pips:
                                # 2. Get account balance
                                account_info = mt5.account_info()
                                if not account_info:
                                    log.error("Could not get account info. Skipping trade.")
                                    continue
                                account_balance = account_info.balance

                                # 3. Calculate volume based on risk
                                volume = risk_manager.calculate_volume(
                                    account_balance=account_balance,
                                    risk_percent=risk_percent,
                                    stop_loss_pips=sl_pips
                                )

                                # 4. Place order if volume is valid
                                if volume:
                                    log.info(
                                        f"Placing {entry_signal} order for {symbol} | Vol: {volume}, SL: {sl_price}, TP: {tp_price}")
                                    connector.place_order(
                                        symbol=symbol,
                                        order_type=entry_signal,
                                        volume=volume,
                                        sl_price=sl_price,
                                        tp_price=tp_price,
                                        magic_number=magic_number
                                    )

                except Exception as e:
                    log.error(f"Unexpected error processing {symbol}: {e}", exc_info=True)
                    continue

            sleep_duration = int(trade_params['main_loop_sleep_seconds'])
            log.info(f"Cycle complete. Sleeping for {sleep_duration} seconds...")
            time.sleep(sleep_duration)

    except KeyboardInterrupt:
        log.info("EA stopped by user.")
    except Exception as e:
        log.error(f"A critical error occurred in the main loop: {e}", exc_info=True)
    finally:
        connector.disconnect()
        log.info("Python Expert Advisor has been shut down.")


if __name__ == "__main__":
    run()
