from os import path, remove
import pandas as pd
import datetime as dt
from strategies import LAA
from qtrade import Questrade

from credentials import QUANT_ACCOUNT_NUM, QUESTRADE_API_KEY, STANDARD_ACCOUNT_NUM

START_DATE = '2018-01-01'


class QuestradeBot:
    def __init__(self, acctNum):
        # Initialize Questrade Instance
        if path.exists("./access_token.yml"):
            try:
                self.qtrade = Questrade(token_yaml='./access_token.yml')
                self.qtrade.get_account_id()
            except:
                self.qtrade.refresh_access_token(from_yaml=True)
                try:
                    self.qtrade.get_account_id()
                except:
                    print("Get a new access code!")
                    remove("./access_token.yml")
                    self.qtrade = Questrade(access_code=QUESTRADE_API_KEY)
                
        else:
            self.qtrade = Questrade(access_code=QUESTRADE_API_KEY)
        
        self.acctNum = acctNum

    def get_acct_id(self):
        return self.qtrade.get_account_id()

    def get_ticker_info(self, symbol: str):
        return self.qtrade.ticker_information(symbol)

    def get_acct_positions(self):
        return self.qtrade.get_account_positions(self.acctNum)
    
    def _get_account_activities(self):
        return self.qtrade.get_account_activities(self.acctNum)

    def get_usd_total_equity(self):
        balance = self.get_account_balance_summary()
        return balance.loc['USD','Total_Equity']

    def get_usd_total_mv(self):
        balance = self.get_account_balance_summary()
        return balance.loc['USD', 'Market_Value']

    def get_cad_total_equity(self):
        balance = self.get_account_balance_summary()
        return balance.loc['CAD','Total_Equity']

    def get_cad_total_mv(self):
        balance = self.get_account_balance_summary()
        return balance.loc['CAD', 'Market_Value']

    def get_usd_total_cost(self):
        positions = self.get_acct_positions()
        total_cost = 0
        for pos in positions:
            curr_cost = pos['totalCost']
            total_cost += curr_cost
        return total_cost

    def get_account_balance_summary(self):
        bal = self.qtrade.get_account_balances(self.acctNum)

        data = {'Currency': [], 'Cash': [], 'Market_Value': [], 'Total_Equity': [], 'Cash (%)': [], 'Investment (%)': []}

        for x in bal['perCurrencyBalances']:
            data['Currency'].append(x['currency'])
            data['Cash'].append(x['cash'])
            data['Market_Value'].append(x['marketValue'])
            data['Total_Equity'].append(x['totalEquity'])
            if x['totalEquity'] != 0:
                data['Cash (%)'].append(round(100 * x['cash']/x['totalEquity'],2))
                data['Investment (%)'].append(round(100 * x['marketValue']/x['totalEquity'],2))
            else:
                data['Cash (%)'].append(0)
                data['Investment (%)'].append(0)

        df = pd.DataFrame(data)
        df.set_index('Currency', inplace=True)
        #print(tabulate(df, headers='keys'))
        return df

    def get_investment_summary(self):
        # p&l
        position_data = {
            'Symbol': [],
            'Description': [],
            'Currency': [],
            'Quantities': [],
            'Market Value': [],
            'Return (%)': [],
            'Portfolio (%)': []
        }
        total_market_value = self.get_usd_total_mv()
        total_costs = 0
        positions = self.qtrade.get_account_positions(self.acctNum)
        for position in positions:
            # handle daily execution for closeQuantity
            if position['openQuantity'] != 0:
                symbol = position['symbol']
                description = self.qtrade.ticker_information(symbol)['description']
                qty = position['openQuantity']
                cmv = position['currentMarketValue']
                currency = self.qtrade.ticker_information(symbol)['currency']
                cost = position['totalCost']
                change = round(100 * (cmv - cost) / cost, 2)

                total_costs = total_costs + cost
                position_data['Symbol'].append(symbol)
                position_data['Description'].append(description)
                position_data['Currency'].append(currency)
                position_data['Quantities'].append(qty)
                position_data['Market Value'].append(cmv)
                position_data['Return (%)'].append(change)
                position_data['Portfolio (%)'].append(round(100 * (cmv / total_market_value),2))

        portfolio = pd.DataFrame(position_data)
        portfolio.set_index('Symbol', inplace=True)
        #portfolio.index.name = None
        #print(tabulate(portfolio))
        return portfolio

    def get_historical_dividend_income(self):
        # identify the first date for creation
        endDate = dt.date.today().strftime("%Y-%m-%d")
        startDate = '2016-01-01'
        dtrange = pd.date_range(startDate, endDate, freq='d')
        months = pd.Series(dtrange.month)
        starts, ends = months.ne(months.shift(1)), months.ne(months.shift(-1))
        startEndDates = pd.DataFrame({
            'month_starting_date':
            dtrange[starts].strftime('%Y-%m-%d'),
            'month_ending_date':
            dtrange[ends].strftime('%Y-%m-%d')
        })
        dateList = startEndDates.values.tolist()

        output = {}
        total_div_earned = 0

        for date in dateList:
            start = date[0]
            end = date[1]
            activities = self.qtrade.get_account_activities(self.acctNum, start, end)
            monthly_div = 0
            for activity in activities:
                if activity['type'] == 'Dividends':
                    monthly_div = monthly_div + activity['netAmount']
            output[dt.datetime.strptime(start,"%Y-%m-%d").strftime("%Y-%m")] = monthly_div
            total_div_earned = total_div_earned + monthly_div

        monthly_div_df = pd.DataFrame.from_dict(output, orient='index', columns=['Monthly_Dividend_Income'])
             
        return monthly_div_df

    def calculate_account_return(self):
        # cagr, mdd, sharpe
        total_mv = self.get_usd_total_mv()
        total_cost = self.get_usd_total_cost()
        m1 = round(100 * (total_mv - total_cost) / total_cost, 2)
        investment = self.get_investment_summary()

        m2 = 0
        for symbol in investment.index:

            ret = investment.loc[symbol, 'Return (%)']
            port = investment.loc[symbol, 'Portfolio (%)'] / 100

            m2 += ret * port

        print(m1, m2)

    def strategy_allocation(self):
        # cash allocation
        # total equity - cash = allocatable amount
        total_equity = self.get_usd_total_equity()
        total_mv = self.get_usd_total_mv()
        curr_cash = total_equity - total_mv
        print(curr_cash)
        target_cash = total_equity * (self.cash_rate/100)
        
        if target_cash < curr_cash:
            # invest more from curr_cash
            invest_amount = curr_cash - target_cash
            print("invest more from curr_cash")

        else:
            # sell some from investment to increase curr_cash
            new_market_value = total_mv - (target_cash - curr_cash)
            print("sell some from investment to increase curr_cash")

if __name__ == "__main__":
    qb = QuestradeBot(QUANT_ACCOUNT_NUM)
    print(qb._get_account_activities())