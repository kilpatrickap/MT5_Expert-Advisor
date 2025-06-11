# backtest.py

import configparser
import pandas as pd
from datetime import datetime
from tqdm import tqdm  # For a progress bar (pip install tqdm)
import MetaTrader5 as mt5

# Import our custom modules
from logger_setup import log
from mt5_connector import MT5Connector
from risk_manager import RiskManager
from trading_strategy import MACrossoverStrategy


def run_backtest():
    """
    Main function to execute the backtesting process.
    It fetches data, simulates trading bar-by-bar, and reports performance.
    """
    # --- 1. Configuration and Setup ---
    log.info("--- Starting Backtest ---")
    config = configparser.ConfigParser()
    config.read('config.ini')

    # Load backtest-specific and general parameters
    try:
        backtest_params = config['backtest_parameters']
        mt5_creds = config['mt5_credentials']
        symbol = backtest_params['backtest_symbol']
        start_date = datetime.strptime(backtest_params['start_date'], '%Y-%m-%d')
        end_date = datetime.strptime(backtest_params['end_date'], '%Y-%m-%d')
    except KeyError as e:
        log.error(f"Configuration error: Missing section or key - {e}. Aborting.")
        return

    # Load parameters for the specific symbol being tested
    try:
        symbol_config = config[symbol]
    except KeyError:
        log.error(f"Configuration section for symbol '{symbol}' not found in config.ini. Aborting backtest.")
        return

    # --- 2. Data Fetching and Connection Handling ---
    log.info(f"Connecting to MT5 to fetch data for {symbol} from {start_date.date()} to {end_date.date()}...")

    # We use a temporary connector instance just for fetching data.
    connector = MT5Connector(login=int(mt5_creds['account']), password=mt5_creds['password'],
                             server=mt5_creds['server'])
    if not connector.connect():
        log.error("Could not connect to MT5. Aborting backtest.")
        return

    # --- CRITICAL: Fetch all required info from MT5 before disconnecting ---
    # Get the symbol's point value for pip calculations
    symbol_info = mt5.symbol_info(symbol)
    if not symbol_info:
        log.error(f"Could not retrieve info for symbol {symbol}. It may not be in Market Watch or is invalid.")
        connector.disconnect()
        return
    point = symbol_info.point

    # Get historical data. We fetch extra data before the start_date to ensure the initial MAs are calculated correctly.
    from dateutil.relativedelta import relativedelta
    ma_buffer_start_date = start_date - relativedelta(months=3)

    rates = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_H1, ma_buffer_start_date, end_date)

    # Now that we have all required live info (point and rates), we can disconnect.
    connector.disconnect()
    log.info("Disconnected from MT5. Proceeding with offline simulation.")

    if rates is None or len(rates) == 0:
        log.error("Failed to fetch historical data for the specified range.")
        return

    # Convert to DataFrame and prepare for simulation
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    # Filter out the buffer period so the backtest starts on the user-defined start_date
    df = df[df['time'] >= start_date].reset_index(drop=True)
    log.info(f"Successfully prepared {len(df)} data points for the simulation period.")

    # --- 3. Initialize Strategy, Risk Manager, and Simulation Variables ---
    strategy = MACrossoverStrategy(
        fast_ma_period=int(symbol_config['fast_ma_period']),
        slow_ma_period=int(symbol_config['slow_ma_period'])
    )
    risk_manager = RiskManager(
        symbol=symbol,
        stop_loss_pips=int(symbol_config['stop_loss_pips']),
        risk_reward_ratio=float(symbol_config['risk_reward_ratio']),
        point=point  # Pass the fetched point value
    )
    volume = float(symbol_config['volume'])

    # Simulation state variables
    current_trade = None
    completed_trades = []

    # --- 4. The Simulation Loop ---
    log.info("Starting simulation loop...")
    # We must start the loop at an index where there's enough preceding data for the slowest moving average.
    start_index = int(strategy.slow_ma_period)

    for i in tqdm(range(start_index, len(df)), desc=f"Backtesting {symbol}"):
        current_candle = df.iloc[i]

        # --- A. Check for SL/TP on an existing open trade ---
        if current_trade:
            exit_price = None

            if current_trade['type'] == 'BUY':
                if current_candle['low'] <= current_trade['sl']:
                    exit_price = current_trade['sl']
                elif current_candle['high'] >= current_trade['tp']:
                    exit_price = current_trade['tp']

            elif current_trade['type'] == 'SELL':
                if current_candle['high'] >= current_trade['sl']:
                    exit_price = current_trade['sl']
                elif current_candle['low'] <= current_trade['tp']:
                    exit_price = current_trade['tp']

            if exit_price:
                # Calculate PnL in pips
                if current_trade['type'] == 'BUY':
                    pnl = (exit_price - current_trade['entry_price']) / point
                else:  # SELL
                    pnl = (current_trade['entry_price'] - exit_price) / point

                # Record the closed trade and reset state
                current_trade['exit_price'] = exit_price
                current_trade['exit_time'] = current_candle['time']
                current_trade['pnl_pips'] = pnl
                current_trade['comment'] = 'SL/TP hit'
                completed_trades.append(current_trade)
                current_trade = None

        # --- B. Check for new trade signals ---
        # Pass the historical data up to the current candle to the strategy
        historical_slice = df.iloc[:i + 1]
        signal = strategy.get_signal(historical_slice)

        if not current_trade:  # If no trade is currently open
            if signal in ["BUY", "SELL"]:
                entry_price = current_candle['close']  # Enter on the close of the signal candle
                sl_price, tp_price = risk_manager.calculate_sl_tp(signal, entry_price)

                # Open a new simulated trade
                current_trade = {
                    'id': len(completed_trades) + 1,
                    'symbol': symbol,
                    'type': signal,
                    'entry_time': current_candle['time'],
                    'entry_price': entry_price,
                    'sl': sl_price,
                    'tp': tp_price,
                    'volume': volume,
                }

        elif current_trade:  # If a trade is already open, check for an exit signal
            if (signal == "BUY" and current_trade['type'] == "SELL") or \
                    (signal == "SELL" and current_trade['type'] == "BUY"):

                exit_price = current_candle['close']
                if current_trade['type'] == 'BUY':
                    pnl = (exit_price - current_trade['entry_price']) / point
                else:  # SELL
                    pnl = (current_trade['entry_price'] - exit_price) / point

                # Record the closed trade and reset state
                current_trade['exit_price'] = exit_price
                current_trade['exit_time'] = current_candle['time']
                current_trade['pnl_pips'] = pnl
                current_trade['comment'] = 'Closed by opposite signal'
                completed_trades.append(current_trade)
                current_trade = None

    # --- 5. Reporting ---
    log.info("Simulation complete. Generating report...")
    if not completed_trades:
        log.warning(
            "No trades were executed during the backtest period. Try adjusting strategy parameters or date range.")
        return

    results_df = pd.DataFrame(completed_trades)

    # Calculate performance metrics
    total_trades = len(results_df)
    winning_trades = results_df[results_df['pnl_pips'] > 0]
    losing_trades = results_df[results_df['pnl_pips'] <= 0]

    win_rate = (len(winning_trades) / total_trades) * 100 if total_trades > 0 else 0
    total_pnl_pips = results_df['pnl_pips'].sum()

    avg_win_pips = winning_trades['pnl_pips'].mean() if len(winning_trades) > 0 else 0
    avg_loss_pips = losing_trades['pnl_pips'].mean() if len(losing_trades) > 0 else 0

    gross_profit = winning_trades['pnl_pips'].sum()
    gross_loss = abs(losing_trades['pnl_pips'].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

    # --- Display Final Report in Console ---
    print("\n" + "=" * 50)
    print(f"{'BACKTEST REPORT':^50}")
    print("=" * 50)
    print(f" Symbol            : {symbol}")
    print(f" Period            : {start_date.date()} to {end_date.date()}")
    print(
        f" Strategy          : MA Crossover ({int(symbol_config['fast_ma_period'])}/{int(symbol_config['slow_ma_period'])})")
    print("-" * 50)
    print(f"{'PERFORMANCE METRICS':^50}")
    print("-" * 50)
    print(f" Total Net Profit  : {total_pnl_pips:.2f} pips")
    print(f" Profit Factor     : {profit_factor:.2f}")
    print(f" Total Trades      : {total_trades}")
    print(f" Win Rate          : {win_rate:.2f}%")
    print(f" Average Win       : {avg_win_pips:.2f} pips")
    print(f" Average Loss      : {avg_loss_pips:.2f} pips")
    print("=" * 50)

    # Save detailed trade log to a CSV file for further analysis
    results_filename = f"backtest_results_{symbol}_{start_date.date()}_to_{end_date.date()}.csv"
    results_df.to_csv(results_filename, index=False)
    log.info(f"Detailed trade log saved to '{results_filename}'")


if __name__ == "__main__":
    # This check ensures the backtest only runs when the script is executed directly
    run_backtest()