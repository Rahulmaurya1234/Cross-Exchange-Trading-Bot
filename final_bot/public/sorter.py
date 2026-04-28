import asyncio
import copy
import time
flag = True
i = 0
async def sorter_loop(live_dict, sorted_dict, interval=0.5):

    global flag
    global i 
    while True:

        try:
            candidates = []

            for symbol, data in live_dict.items():

                ku = data.get("kucoin")
                bb = data.get("bybit")

                if not ku or not bb:
                    continue

                ku_rate = ku["funding_rate_decimal"]["value"]
                bb_rate = bb["funding_rate_decimal"]["value"]
                interval_hr = ku["funding_interval_hr"]["value"]

                if ku_rate is None or bb_rate is None or interval_hr is None:
                    continue

                try:
                    ku_rate = float(ku_rate)
                    bb_rate = float(bb_rate)
                    interval_hr = int(interval_hr)
                except:
                    continue

                diff = ku_rate - bb_rate
                abs_diff = abs(diff)

                if abs_diff == 0:
                    continue

                candidates.append((
                    symbol,
                    interval_hr,
                    abs_diff
                ))

            # Sort:
            # 1) funding interval asc
            # 2) funding diff desc
            candidates.sort(
                key=lambda x: (
                    x[1],
                    -x[2]
                )
            )

            top = []

            for symbol, interval_hr, abs_diff in candidates:
                data = live_dict[symbol]
                ku = data["kucoin"]
                bb = data["bybit"]

                #-----spread filter -------
                try:
                    bid_ku = float(ku["best_bid_price"]["value"])
                    ask_ku = float(ku["best_ask_price"]["value"])
                    bid_bb = float(bb["best_bid_price"]["value"])
                    ask_bb = float(bb["best_ask_price"]["value"])
                except:
                    continue

                if ask_ku < bid_ku or ask_bb < bid_bb : 
                    continue

                if bid_ku <= 0 or bid_bb <= 0:
                    continue

                spread_ku = (ask_ku - bid_ku)/bid_ku
                spread_bb = (ask_bb - bid_bb)/bid_bb

                if spread_ku > 0.002 or spread_bb > 0.002:
                    continue

                top.append((symbol,interval_hr,abs_diff))

                if len(top) == 20: 
                    break

            sorted_dict.clear()

            for symbol, interval_hr, abs_diff in top:

                # Deep copy full LIVE_DATA symbol section
                new_entry = copy.deepcopy(live_dict[symbol])

                # Add extra field
                new_entry["funding_rate_difference_decimal"] = {
                    "value": abs_diff,
                    "ts": time.time()
                }

                sorted_dict[symbol] = new_entry
                # if sorted_dict:
                #     # print("\n sorted top udated")
                #     for sym, data in sorted_dict.items():
                #         i = i +1
                #         if i > 500:
                #             print("\n sorted top udated")
                #             print("first entry:",sym)
                #             print("structure:sorted_dict[sym]")
                #             print("entry of sorted_dict[sym]:\n",sorted_dict[sym])
                #             i = 0
                #             # flag = False
                #         break
        except Exception as e:
            print("sorter_loop_error : ",e)
        
        await asyncio.sleep(interval)
