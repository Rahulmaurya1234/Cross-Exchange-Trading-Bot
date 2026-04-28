export default function Metrics({data}){

  const bybit = data?.balances?.bybit?.available_balance
  const kucoin = data?.balances?.kucoin?.available_balance

  return(

    <div className="metrics">

      <div className="metric">
        <div className="label">Bybit Balance</div>
        <div className="value">{bybit ?? "—"}</div>
      </div>

      <div className="metric">
        <div className="label">Kucoin Balance</div>
        <div className="value">{kucoin ?? "—"}</div>
      </div>

      <div className="metric">
        <div className="label">Total Funding Edge</div>
        <div className="value">{data.metrics.total_edge}</div>
      </div>

      <div className="metric">
        <div className="label">Avg Interval</div>
        <div className="value">{data.metrics.avg_interval}</div>
      </div>

    </div>

  )

}
