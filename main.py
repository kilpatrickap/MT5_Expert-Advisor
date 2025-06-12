# main.py
import configparser
import time
import MetaTrader5 as mt5

from logger_setup import log
from mt5_connector import MT5Connector
from risk_manager import RiskManager
from trading_strategy import RegimeMomentumStrategy  # <-- IMPORT THE NEW STRATEGY


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
    # This is more efficient as we initialize objects once per symbol, not on every loop.
    strategies = {}
    risk_managers = {}

    log.info("Initializing strategies and risk managers for each symbol...")
    for symbol in symbols_to_trade:
        try:
            log.info(f"--- Loading config for {symbol} ---")
            symbol_config = config[symbol]

            # Initialize the new RegimeMomentumStrategy
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
                log.error(f"Could not get info for {symbol}. It will be skipped. Ensure it's in Market Watch.")
                continue

            # Initialize the Risk Manager
            risk_managers[symbol] = RiskManager(
                symbol=symbol,
                stop_loss_pips=int(symbol_config['stop_loss_pips']),
                risk_reward_ratio=float(symbol_config['risk_reward_ratio']),
                point=symbol_info.point,
                stops_level=symbol_info.trade_stops_level
            )

        except KeyError as e:
            log.error(f"Configuration error for symbol '{symbol}': Missing key {e}. This symbol will be skipped.")
            # Remove from list to avoid processing in the main loop
            if symbol in strategies: del strategies[symbol]
            if symbol in risk_managers: del risk_managers[symbol]
            continue

    log.info(f"EA configured to trade symbols: {list(strategies.keys())}")

    # --- 4. Main Trading Loop ---
    try:
        while True:
            log.info("-------------------- New Trading Cycle --------------------")

            for symbol in strategies.keys():  # Iterate only over successfully configured symbols
                log.info(f"--- Processing symbol: {symbol} ---")
                try:
                    strategy = strategies[symbol]
                    risk_manager = risk_managers[symbol]
                    symbol_config = config[symbol]
                    timeframe_str = symbol_config['timeframe']

                    # Fetch historical data needed for the strategy's indicators
                    historical_data = connector.get_historical_data(symbol, timeframe_str, strategy.min_bars + 5)
                    if historical_data is None or historical_data.empty:
                        log.warning(f"Could not fetch historical data for {symbol}. Skipping this cycle.")
                        continue

                    open_positions = connector.get_open_positions(symbol=symbol, magic_number=magic_number)

                    # --- Decision Logic ---
                    if open_positions:
                        # --- LOGIC FOR AN OPEN POSITION ---
                        current_pos = open_positions[0]
                        pos_type = "BUY" if current_pos.type == mt5.ORDER_TYPE_BUY else "SELL"

                        # Check for a protective exit signal from the strategy
                        should_exit = strategy.get_exit_signal(historical_data, pos_type)
                        if should_exit:
                            log.info(
                                f"Protective exit signal (trend failure) for {symbol}. Closing position #{current_pos.ticket}.")
                            connector.close_position(current_pos, comment="Closed due to trend failure (EMA cross)")
                        else:
                            log.info(f"Holding current {pos_type} position for {symbol}. No exit signal.")
                    else:
                        # --- LOGIC FOR NO OPEN POSITION ---
                        entry_signal = strategy.get_entry_signal(historical_data)
                        log.info(f"Strategy Entry Signal for {symbol} on {timeframe_str}: {entry_signal}")

                        if entry_signal in ["BUY", "SELL"]:
                            tick = mt5.symbol_info_tick(symbol)
                            if not tick:
                                log.warning(f"Could not retrieve current tick for {symbol}. Skipping trade attempt.")
                                continue

                            sl_price, tp_price = risk_manager.calculate_sl_tp(
                                order_type=entry_signal,
                                current_ask=tick.ask,
                                current_bid=tick.bid
                            )

                            if sl_price and tp_price:
                                log.info(f"Placing {entry_signal} order for {symbol}. SL: {sl_price}, TP: {tp_price}")
                                connector.place_order(
                                    symbol=symbol,
                                    order_type=entry_signal,
                                    volume=float(symbol_config['volume']),
                                    sl_price=sl_price,
                                    tp_price=tp_price,
                                    magic_number=magic_number
                                )

                except Exception as e:
                    log.error(f"An unexpected error occurred while processing {symbol}: {e}", exc_info=True)
                    continue

            sleep_duration = int(trade_params['main_loop_sleep_seconds'])
            log.info(f"Cycle complete. Sleeping for {sleep_duration} seconds...")
            time.sleep(sleep_duration)

    except KeyboardInterrupt:
        log.info("EA stopped by user (KeyboardInterrupt).")
    except Exception as e:
        log.error(f"A critical error occurred in the main loop: {e}", exc_info=True)
    finally:
        connector.disconnect()
        log.info("Python Expert Advisor has been shut down.")


if __name__ == "__main__":
    run()