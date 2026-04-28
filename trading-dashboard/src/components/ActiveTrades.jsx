import TradeCard from "./TradeCard";

export default function ActiveTrades({trades}){

  return(

    <section className="section">

      <h2>🔥 Active Trades</h2>

      <div className="trades-grid">

        {trades.map(t=>(
          <TradeCard key={t.trade_id} trade={t}/>
        ))}

      </div>

    </section>

  )

}
