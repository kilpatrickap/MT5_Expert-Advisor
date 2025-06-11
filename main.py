# main.py
import configparser
import time
import MetaTrader5 as mt5

from logger_setup import log
from mt5_connector import MT5Connector
from risk_manager import RiskManager
from trading_strategy import MACrossoverStrategy


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

    # Get the list of symbols from the config file
    try:
        symbols_to_trade = [s.strip() for s in trade_params['symbols'].split(',')]
        magic_number = int(trade_params['magic_number'])
    except KeyError as e:
        log.error(f"Trading parameter '{e}' is missing in config.ini. Exiting.")
        connector.disconnect()
        return

    log.info(f"EA configured to trade symbols: {symbols_to_trade}")

    # --- 3. Main Trading Loop ---
    try:
        while True:
            log.info("-------------------- New Trading Cycle --------------------")

            # Iterate over each symbol to trade
            for symbol in symbols_to_trade:
                log.info(f"--- Processing symbol: {symbol} ---")

                try:
                    # Load symbol-specific parameters from its config section
                    symbol_config = config[symbol]

                    # --- THE FIX: Fetch all required symbol properties at once ---
                    symbol_info = mt5.symbol_info(symbol)
                    if not symbol_info:
                        log.warning(
                            f"Could not get info for {symbol}, skipping this cycle. Ensure it's in Market Watch.")
                        continue

                    point = symbol_info.point
                    stops_level = symbol_info.stops_level
                    log.debug(f"{symbol} | Point: {point} | Stops Level: {stops_level} points")
                    # --- END FIX ---

                    # Initialize components with symbol-specific values
                    strategy = MACrossoverStrategy(
                        fast_ma_period=int(symbol_config['fast_ma_period']),
                        slow_ma_period=int(symbol_config['slow_ma_period'])
                    )

                    # --- THE FIX: Pass all required info to the RiskManager ---
                    risk_manager = RiskManager(
                        symbol=symbol,
                        stop_loss_pips=int(symbol_config['stop_loss_pips']),
                        risk_reward_ratio=float(symbol_config['risk_reward_ratio']),
                        point=point,
                        stops_level=stops_level  # Pass the broker's minimum stop distance
                    )

                    # Check for open positions for THIS EA's symbol and magic number
                    open_positions = connector.get_open_positions(symbol=symbol, magic_number=magic_number)

                    # Fetch data and generate signal
                    timeframe_str = symbol_config['timeframe']
                    historical_data = connector.get_historical_data(timeframe_str, strategy.slow_ma_period + 5)
                    signal = strategy.get_signal(historical_data)
                    log.info(f"Strategy Signal for {symbol} on {timeframe_str}: {signal}")

                    # --- Decision Logic ---
                    if not open_positions:
                        if signal in ["BUY", "SELL"]:
                            entry_price = mt5.symbol_info_tick(symbol).ask if signal == "BUY" else mt5.symbol_info_tick(
                                symbol).bid
                            sl_price, tp_price = risk_manager.calculate_sl_tp(signal, entry_price)
                            log.info(f"Calculated SL: {sl_price}, TP: {tp_price} for {symbol}")

                            connector.place_order(
                                symbol=symbol,
                                order_type=signal,
                                volume=float(symbol_config['volume']),
                                sl_price=sl_price,
                                tp_price=tp_price,
                                magic_number=magic_number
                            )
                    else:
                        current_pos = open_positions[0]  # Assuming one position per symbol
                        pos_type = "BUY" if current_pos.type == mt5.ORDER_TYPE_BUY else "SELL"

                        if (signal == "BUY" and pos_type == "SELL") or \
                                (signal == "SELL" and pos_type == "BUY"):
                            log.info(f"Opposite signal for {symbol}. Closing position #{current_pos.ticket}.")
                            connector.close_position(current_pos, comment="Closed due to opposite signal")
                        else:
                            log.info(f"Holding current {pos_type} position for {symbol}. No action needed.")

                except KeyError as e:
                    log.warning(
                        f"Configuration section or key '{e}' for symbol '{symbol}' not found in config.ini. Skipping.")
                    continue
                except Exception as e:
                    log.error(f"An unexpected error occurred while processing {symbol}: {e}", exc_info=True)
                    continue  # Move to the next symbol

            # Wait for the next cycle
            sleep_duration = int(trade_params['main_loop_sleep_seconds'])
            log.info(f"Cycle complete. Sleeping for {sleep_duration} seconds...")
            time.sleep(sleep_duration)

    except KeyboardInterrupt:
        log.info("EA stopped by user (KeyboardInterrupt).")
    except Exception as e:
        log.error(f"A critical error occurred in the main loop: {e}", exc_info=True)
    finally:
        # --- Cleanup ---
        connector.disconnect()
        log.info("Python Expert Advisor has been shut down.")


if __name__ == "__main__":
    run()