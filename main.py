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
    # --- Configuration Loading ---
    config = configparser.ConfigParser()
    config.read('config.ini')

    mt5_creds = config['mt5_credentials']
    trade_params = config['trading_parameters']
    strategy_params = config['strategy_ma_crossover']

    # --- Initialization of Components ---
    log.info("Starting Python Expert Advisor")
    connector = MT5Connector(
        login=int(mt5_creds['account']),
        password=mt5_creds['password'],
        server=mt5_creds['server']
    )

    if not connector.connect():
        log.error("Failed to connect to MT5. Exiting.")
        return

    # Initialize components with values from config
    symbol = trade_params['symbol']
    magic_number = int(trade_params['magic_number'])

    strategy = MACrossoverStrategy(
        fast_ma_period=int(strategy_params['fast_ma_period']),
        slow_ma_period=int(strategy_params['slow_ma_period'])
    )

    risk_manager = RiskManager(
        symbol=symbol,
        stop_loss_pips=int(trade_params['stop_loss_pips']),
        risk_reward_ratio=float(trade_params['risk_reward_ratio'])
    )

    # --- Main Trading Loop ---
    try:
        while True:
            log.info("-------------------- New Tick --------------------")

            # Check for open positions for this EA's symbol and magic number
            open_positions = connector.get_open_positions(symbol=symbol, magic_number=magic_number)

            # Fetch data and generate signal
            historical_data = connector.get_historical_data(symbol, trade_params['timeframe'],
                                                            strategy.slow_ma_period + 5)
            signal = strategy.get_signal(historical_data)
            log.info(f"Strategy Signal for {symbol}: {signal}")

            # --- Decision Logic ---
            if not open_positions:
                # No open positions, look for a new entry
                if signal in ["BUY", "SELL"]:
                    entry_price = mt5.symbol_info_tick(symbol).ask if signal == "BUY" else mt5.symbol_info_tick(
                        symbol).bid
                    sl_price, tp_price = risk_manager.calculate_sl_tp(signal, entry_price)
                    log.info(f"Calculated SL: {sl_price}, TP: {tp_price}")

                    connector.place_order(
                        symbol=symbol,
                        order_type=signal,
                        volume=float(trade_params['volume']),
                        sl_price=sl_price,
                        tp_price=tp_price,
                        magic_number=magic_number
                    )
            else:
                # Position is already open, check if we need to close it due to opposite signal
                current_pos = open_positions[0]  # Assuming one position per symbol
                pos_type = "BUY" if current_pos.type == mt5.ORDER_TYPE_BUY else "SELL"

                if (signal == "BUY" and pos_type == "SELL") or \
                        (signal == "SELL" and pos_type == "BUY"):
                    log.info(f"Opposite signal detected. Closing position #{current_pos.ticket}.")
                    connector.close_position(current_pos, comment="Closed due to opposite signal")
                else:
                    log.info(f"Holding current {pos_type} position. No action needed.")

            # Wait for the next cycle
            sleep_duration = int(trade_params['main_loop_sleep_seconds'])
            log.info(f"Sleeping for {sleep_duration} seconds...")
            time.sleep(sleep_duration)

    except KeyboardInterrupt:
        log.info("EA stopped by user (KeyboardInterrupt).")
    except Exception as e:
        log.error(f"An unexpected error occurred in the main loop: {e}", exc_info=True)
    finally:
        # --- Cleanup ---
        connector.disconnect()
        log.info("Python Expert Advisor has been shut down.")


if __name__ == "__main__":
    run()