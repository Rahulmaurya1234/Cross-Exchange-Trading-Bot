export default function TradeCard({trade}){

  const long = trade.exchange_long.dynamic
  const short = trade.exchange_short.dynamic
  const combined = trade.combined.dynamic

  return(

    <div className="trade-card">

      <div className="trade-header">
        <span>{trade.symbol}</span>
        <span>{trade.status}</span>
      </div>

      <div className="trade-row">

        <div className="exchange">
          <h4>LONG</h4>
          <div>Mark: {long.mark_price}</div>
          <div>PnL: {long.unrealized_pnl}</div>
        </div>

        <div className="exchange">
          <h4>SHORT</h4>
          <div>Mark: {short.mark_price}</div>
          <div>PnL: {short.unrealized_pnl}</div>
        </div>

      </div>

      <div className="combined">

        <div>Total PnL: {combined.total_unrealized_pnl}</div>

        <div>Divergence: {combined.current_divergence_percent}</div>

      </div>

    </div>

  )

}
