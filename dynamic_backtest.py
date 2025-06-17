# dynamic_backtest.py
import configparser
import pandas as pd
from datetime import datetime
from tqdm import tqdm
import MetaTrader5 as mt5
from dateutil.relativedelta import relativedelta
import itertools

from logger_setup import log
from mt5_connector import MT5Connector
from risk_manager import RiskManager
from trading_strategy import RegimeMomentumStrategy

# --- 1. OPTIMIZATION PARAMETER RANGES ---
# Define the different values you want to test for each parameter.
# Be careful: more values mean exponentially longer optimization times.
OPTIMIZATION_PARAMS = {
    'stop_loss_pips': [60, 80, 100],
    'risk_reward_ratio': [1.5, 1.8, 2.0],
    'adx_threshold': [22, 25, 28]
}


def run_single_backtest(df: pd.DataFrame, symbol_info: dict, params: dict):
    """
    Runs a single backtest for one combination of parameters.
    This is a modified, non-verbose version of the original run_backtest function.
    Returns the profit factor and total trades.
    """
    symbol = symbol_info['name']
    point = symbol_info['point']

    # --- Initialize Strategy and Risk Manager with current iteration's params ---
    strategy = RegimeMomentumStrategy(
        fast_ema_period=21,  # Keeping some parameters fixed for simplicity
        slow_ema_period=50,
        adx_period=14,
        adx_threshold=int(params['adx_threshold']),
        stoch_k_period=14,
        stoch_d_period=3,
        stoch_slowing=3,
        stoch_oversold=20,
        stoch_overbought=80
    )
    risk_manager = RiskManager(
        symbol=symbol,
        stop_loss_pips=int(params['stop_loss_pips']),
        risk_reward_ratio=float(params['risk_reward_ratio']),
        point=point,
        stops_level=symbol_info['trade_stops_level']
    )

    # --- Simulation Loop ---
    start_date = datetime.strptime(params['start_date'], '%Y-%m-%d')
    sim_start_index = df[df['time'] >= start_date].index[0]
    current_trade = None
    completed_trades = []

    for i in range(sim_start_index, len(df)):
        current_candle = df.iloc[i]
        historical_slice = df.iloc[:i + 1]

        if current_trade:
            exit_price, comment = None, ''
            if current_trade['type'] == 'BUY':
                if current_candle['low'] <= current_trade['sl']:
                    exit_price, comment = current_trade['sl'], 'SL Hit'
                elif current_candle['high'] >= current_trade['tp']:
                    exit_price, comment = current_trade['tp'], 'TP Hit'
            elif current_trade['type'] == 'SELL':
                if current_candle['high'] >= current_trade['sl']:
                    exit_price, comment = current_trade['sl'], 'SL Hit'
                elif current_candle['low'] <= current_trade['tp']:
                    exit_price, comment = current_trade['tp'], 'TP Hit'

            if not exit_price and strategy.get_exit_signal(historical_slice, current_trade['type']):
                exit_price, comment = current_candle['close'], 'Strategy Exit'

            if exit_price:
                pnl = (exit_price - current_trade['entry_price']) / point if current_trade['type'] == 'BUY' else (
                                                                                                                             current_trade[
                                                                                                                                 'entry_price'] - exit_price) / point
                current_trade.update({'exit_price': exit_price, 'exit_time': current_candle['time'], 'pnl_pips': pnl,
                                      'comment': comment})
                completed_trades.append(current_trade)
                current_trade = None

        if not current_trade:
            entry_signal = strategy.get_entry_signal(historical_slice)
            if entry_signal in ["BUY", "SELL"]:
                entry_price = current_candle['close']
                sl_price, tp_price, _ = risk_manager.calculate_sl_tp(order_type=entry_signal, current_ask=entry_price,
                                                                     current_bid=entry_price)
                if sl_price and tp_price:
                    current_trade = {'id': len(completed_trades) + 1, 'symbol': symbol, 'type': entry_signal,
                                     'entry_time': current_candle['time'], 'entry_price': entry_price, 'sl': sl_price,
                                     'tp': tp_price}

    # --- Calculate Results ---
    if not completed_trades:
        return 0, 0  # No trades, profit factor is 0

    results_df = pd.DataFrame(completed_trades)
    gross_profit = results_df[results_df['pnl_pips'] > 0]['pnl_pips'].sum()
    gross_loss = abs(results_df[results_df['pnl_pips'] <= 0]['pnl_pips'].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

    return profit_factor, len(results_df)


def run_dynamic_backtest():
    """
    Main function to execute the optimization process.
    """
    # --- Configuration and Data Fetching (same as before) ---
    log.info("--- Starting Dynamic Backtest (Optimization) ---")
    config = configparser.ConfigParser()
    config.read('config.ini')
    backtest_params = config['backtest_parameters']
    mt5_creds = config['mt5_credentials']
    symbol = backtest_params['backtest_symbol']
    start_date = backtest_params['start_date']
    end_date = backtest_params['end_date']
    timeframe_str = config[symbol]['timeframe']

    connector = MT5Connector(login=int(mt5_creds['account']), password=mt5_creds['password'],
                             server=mt5_creds['server'])
    if not connector.connect(): return

    symbol_info_obj = mt5.symbol_info(symbol)
    if not symbol_info_obj:
        log.error(f"Could not retrieve info for symbol {symbol}.")
        connector.disconnect()
        return

    # Convert symbol_info object to a dictionary for easier passing
    symbol_info = {
        'name': symbol_info_obj.name,
        'point': symbol_info_obj.point,
        'trade_stops_level': symbol_info_obj.trade_stops_level
    }

    timeframe_map = {'M15': mt5.TIMEFRAME_M15, 'H1': mt5.TIMEFRAME_H1}  # Add more if needed
    mt5_timeframe = timeframe_map.get(timeframe_str.upper())
    buffer_start_date = datetime.strptime(start_date, '%Y-%m-%d') - relativedelta(months=6)
    rates = mt5.copy_rates_range(symbol, mt5_timeframe, buffer_start_date, datetime.strptime(end_date, '%Y-%m-%d'))
    connector.disconnect()

    if rates is None or len(rates) == 0:
        log.error("Failed to fetch historical data.")
        return

    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df = df.sort_values(by='time').reset_index(drop=True)
    log.info(f"Data for {symbol} fetched successfully. Starting optimization...")

    # --- Optimization Loop ---
    # Create a list of all parameter combinations
    keys, values = zip(*OPTIMIZATION_PARAMS.items())
    param_combinations = [dict(zip(keys, v)) for v in itertools.product(*values)]

    all_results = []

    # Use tqdm for a progress bar
    for params in tqdm(param_combinations, desc=f"Optimizing {symbol}"):
        # Add static params for the backtest function
        params['start_date'] = start_date

        profit_factor, total_trades = run_single_backtest(df, symbol_info, params)

        result = params.copy()
        result['profit_factor'] = round(profit_factor, 2)
        result['total_trades'] = total_trades
        all_results.append(result)

    # --- Reporting ---
    if not all_results:
        log.warning("Optimization finished with no results.")
        return

    results_df = pd.DataFrame(all_results)
    # Sort by profit factor in descending order
    results_df = results_df.sort_values(by='profit_factor', ascending=False).reset_index(drop=True)

    profitable_results = results_df[results_df['profit_factor'] > 1.2]

    print("\n" + "=" * 80)
    print(f"{'OPTIMIZATION REPORT':^80}")
    print("=" * 80)
    print(f" Symbol: {symbol} ({timeframe_str}) | Period: {start_date} to {end_date}")
    print(f" Total Combinations Tested: {len(all_results)}")
    print("-" * 80)

    if profitable_results.empty:
        print("No profitable parameter combinations found with Profit Factor > 1.2.")
        print("Showing the Top 5 best results found:")
        print(results_df.head(5).to_string())
    else:
        print("Profitable Combinations Found (Profit Factor > 1.2):")
        print(profitable_results.to_string())

    best_params = results_df.iloc[0]
    print("-" * 80)
    print("BEST OVERALL PARAMETERS FOUND:")
    print(f"  - Stop Loss (pips): {best_params['stop_loss_pips']}")
    print(f"  - Risk/Reward Ratio: {best_params['risk_reward_ratio']}")
    print(f"  - ADX Threshold: {best_params['adx_threshold']}")
    print(f"  - Resulting Profit Factor: {best_params['profit_factor']}")
    print(f"  - Resulting Total Trades: {best_params['total_trades']}")
    print("=" * 80)


if __name__ == "__main__":
    run_dynamic_backtest()