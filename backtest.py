# backtest.py

import configparser
import pandas as pd
from datetime import datetime
from tqdm import tqdm
import MetaTrader5 as mt5

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

    try:
        backtest_params = config['backtest_parameters']
        mt5_creds = config['mt5_credentials']
        symbol = backtest_params['backtest_symbol']
        start_date = datetime.strptime(backtest_params['start_date'], '%Y-%m-%d')
        end_date = datetime.strptime(backtest_params['end_date'], '%Y-%m-%d')
    except KeyError as e:
        log.error(f"Configuration error: Missing section or key - {e}. Aborting.")
        return

    try:
        symbol_config = config[symbol]
    except KeyError:
        log.error(f"Configuration section for symbol '{symbol}' not found in config.ini. Aborting backtest.")
        return

    # --- 2. Data Fetching and Connection Handling ---
    log.info(f"Connecting to MT5 to fetch data for {symbol} from {start_date.date()} to {end_date.date()}...")

    connector = MT5Connector(login=int(mt5_creds['account']), password=mt5_creds['password'],
                             server=mt5_creds['server'])
    if not connector.connect():
        log.error("Could not connect to MT5. Aborting backtest.")
        return

    # Fetch all required symbol properties while connected
    symbol_info = mt5.symbol_info(symbol)
    if not symbol_info:
        log.error(f"Could not retrieve info for symbol {symbol}. It may not be in Market Watch or is invalid.")
        connector.disconnect()
        return
    point = symbol_info.point
    stops_level = symbol_info.trade_stops_level

    # Determine the correct MT5 timeframe constant from the config string
    timeframe_str = symbol_config['timeframe']
    timeframe_map = {
        'M1': mt5.TIMEFRAME_M1, 'M5': mt5.TIMEFRAME_M5, 'M15': mt5.TIMEFRAME_M15,
        'M30': mt5.TIMEFRAME_M30, 'H1': mt5.TIMEFRAME_H1, 'H4': mt5.TIMEFRAME_H4,
        'D1': mt5.TIMEFRAME_D1, 'W1': mt5.TIMEFRAME_W1, 'MN1': mt5.TIMEFRAME_MN1
    }
    mt5_timeframe = timeframe_map.get(timeframe_str.upper())
    if not mt5_timeframe:
        log.error(f"Invalid timeframe '{timeframe_str}' in config for {symbol}. Aborting.")
        connector.disconnect()
        return

    # Fetch historical data
    from dateutil.relativedelta import relativedelta
    ma_buffer_start_date = start_date - relativedelta(months=3)
    rates = mt5.copy_rates_range(symbol, mt5_timeframe, ma_buffer_start_date, end_date)

    connector.disconnect()
    log.info("Disconnected from MT5. Proceeding with offline simulation.")

    if rates is None or len(rates) == 0:
        log.error("Failed to fetch historical data for the specified range. Try a shorter date range.")
        return

    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    # Sort data chronologically and filter to the exact start date
    df = df.sort_values(by='time').reset_index(drop=True)
    df = df[df['time'] >= start_date].reset_index(drop=True)
    log.info(f"Successfully prepared {len(df)} data points for the simulation period.")

    # --- 3. Initialize Strategy and Risk Manager ---
    strategy = MACrossoverStrategy(
        fast_ma_period=int(symbol_config['fast_ma_period']),
        slow_ma_period=int(symbol_config['slow_ma_period'])
    )
    risk_manager = RiskManager(
        symbol=symbol,
        stop_loss_pips=int(symbol_config['stop_loss_pips']),
        risk_reward_ratio=float(symbol_config['risk_reward_ratio']),
        point=point,
        stops_level=stops_level
    )

    # --- 4. The Simulation Loop ---
    log.info("Starting simulation loop...")
    start_index = int(strategy.slow_ma_period)
    current_trade = None
    completed_trades = []

    for i in tqdm(range(start_index, len(df)), desc=f"Backtesting {symbol}"):
        current_candle = df.iloc[i]

        # Check for SL/TP on an open trade
        if current_trade:
            exit_price, pnl = None, 0
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
                pnl = (exit_price - current_trade['entry_price']) / point if current_trade['type'] == 'BUY' else (
                                                                                                                             current_trade[
                                                                                                                                 'entry_price'] - exit_price) / point
                current_trade.update({'exit_price': exit_price, 'exit_time': current_candle['time'], 'pnl_pips': pnl,
                                      'comment': 'SL/TP'})
                completed_trades.append(current_trade)
                current_trade = None

        # Check for new signals
        historical_slice = df.iloc[:i + 1]
        signal = strategy.get_signal(historical_slice)

        if not current_trade:
            if signal in ["BUY", "SELL"]:
                entry_price = current_candle['close']
                # Simulate spread-aware SL/TP calculation using candle close for both ask/bid
                sl_price, tp_price = risk_manager.calculate_sl_tp(order_type=signal, current_ask=entry_price,
                                                                  current_bid=entry_price)
                if sl_price and tp_price:
                    current_trade = {'id': len(completed_trades) + 1, 'symbol': symbol, 'type': signal,
                                     'entry_time': current_candle['time'], 'entry_price': entry_price, 'sl': sl_price,
                                     'tp': tp_price}
        elif current_trade:
            if (signal == "BUY" and current_trade['type'] == "SELL") or (
                    signal == "SELL" and current_trade['type'] == "BUY"):
                exit_price = current_candle['close']
                pnl = (exit_price - current_trade['entry_price']) / point if current_trade['type'] == 'BUY' else (
                                                                                                                             current_trade[
                                                                                                                                 'entry_price'] - exit_price) / point
                current_trade.update({'exit_price': exit_price, 'exit_time': current_candle['time'], 'pnl_pips': pnl,
                                      'comment': 'Opposite Signal'})
                completed_trades.append(current_trade)
                current_trade = None

    # --- 5. Reporting ---
    log.info("Simulation complete. Generating report...")
    if not completed_trades:
        log.warning("No trades were executed during the backtest period.")
        return

    results_df = pd.DataFrame(completed_trades)

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

    # Display Report
    print("\n" + "=" * 50)
    print(f"{'BACKTEST REPORT':^50}")
    print("=" * 50)
    print(f" Symbol            : {symbol} ({timeframe_str})")
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

    results_filename = f"backtest_results_{symbol}_{timeframe_str}_{start_date.date()}_to_{end_date.date()}.csv"
    results_df.to_csv(results_filename, index=False)
    log.info(f"Detailed trade log saved to '{results_filename}'")


if __name__ == "__main__":
    run_backtest()