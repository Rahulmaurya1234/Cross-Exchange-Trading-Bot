import { useEffect, useState } from "react";
import "./Dashboard.css";

export default function Dashboard(){

  const [data,setData] = useState({
    balances:{},
    active_trades:[],
    closed_trades:[],
    opportunities:[],
    metrics:{},
    runtime_config:{},
    entry_allowed:false
  });

  const [health,setHealth] = useState({});


/* ---------------- WEBSOCKET ---------------- */

useEffect(()=>{

  const ws = new WebSocket(
    (window.location.protocol === "https:" ? "wss://" : "ws://") +
    window.location.hostname +
    ":8000/ws"
  );

  ws.onopen = ()=>{
    console.log("WS CONNECTED");
  };

  ws.onmessage = (event)=>{

    try{

      const snapshot = JSON.parse(event.data);

      console.log("WS DATA",snapshot);

      setData(snapshot);

    }catch(err){

      console.log("WS PARSE ERROR",err);

    }

  };

  ws.onerror = (err)=>{
    console.log("WS ERROR",err);
  };

  ws.onclose = ()=>{
    console.log("WS CLOSED");
  };

  return ()=>ws.close();

},[]);



/* ---------------- HEALTH API ---------------- */

useEffect(()=>{

  async function fetchHealth(){

    try{

      const res = await fetch("http://localhost:8000/health");

      const h = await res.json();

      setHealth(h);

    }catch(e){

      console.log("health error",e);

    }

  }

  fetchHealth();

  const interval = setInterval(fetchHealth,4000);

  return ()=>clearInterval(interval);

},[]);



/* ---------------- ENTRY TOGGLE ---------------- */

async function toggleEntry(){

  try{

    const newState = !data.entry_allowed;

    const res = await fetch("http://localhost:8000/toggle-entry",{
      method:"POST",
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({allowed:newState})
    });

    const result = await res.json();

    console.log("toggle result",result);

  }catch(err){

    console.log("toggle error",err);

  }

}



/* ---------------- KILL ALL ---------------- */

async function killAll(){

  if(!window.confirm("Kill all trades?")) return;

  try{

    const res = await fetch("http://localhost:8000/kill-all",{
      method:"POST"
    });

    const result = await res.json();

    console.log("kill result",result);

  }catch(err){

    console.log("kill error",err);

  }

}



/* ---------------- UI ---------------- */

return(

<div className="wrap">


{/* HEADER */}

<header>

<h1>🚀 Trading Control Center</h1>

<div className="controls">

<div className={`status-pill ${data.entry_allowed ? "status-enabled":"status-disabled"}`}>

{data.entry_allowed ? "ENABLED":"DISABLED"}

</div>

<button className="btn toggle" onClick={toggleEntry}>
Toggle Entry
</button>

<button className="btn secondary"
onClick={()=>window.location.href="/settings"}>
⚙ Settings
</button>

<button className="btn critical" onClick={killAll}>
🚨 Kill All
</button>

</div>

</header>



{/* METRICS */}

<div className="metrics">

<div className="metric">
<div className="label">Bybit Balance</div>
<div className="value">
{data.balances?.bybit?.available_balance ?? "-"}
</div>
</div>

<div className="metric">
<div className="label">Kucoin Balance</div>
<div className="value">
{data.balances?.kucoin?.available_balance ?? "-"}
</div>
</div>

<div className="metric">
<div className="label">Funding Edge</div>
<div className="value">
{data.metrics?.total_edge ?? "-"}
</div>
</div>

<div className="metric">
<div className="label">Avg Interval</div>
<div className="value">
{data.metrics?.avg_interval ?? "-"}
</div>
</div>

</div>



{/* SYSTEM HEALTH */}

<div className="section">

<h2>🩺 System Health</h2>

<div className="metrics">

<div className="metric">
<div className="label">Server</div>
<div className="value">
{health.ok ? "OK":"DOWN"}
</div>
</div>

<div className="metric">
<div className="label">Live Data</div>
<div className="value">
{health.live_data_available ? "YES":"NO"}
</div>
</div>

<div className="metric">
<div className="label">Active Trades</div>
<div className="value">
{health.active_trades_count ?? 0}
</div>
</div>

<div className="metric">
<div className="label">Closed Trades</div>
<div className="value">
{health.closed_trades_count ?? 0}
</div>
</div>

<div className="metric">
<div className="label">Entry Allowed</div>
<div className="value">
{health.entry_allowed ? "YES":"NO"}
</div>
</div>

</div>

</div>



{/* ACTIVE TRADES */}

<section className="section">

<h2>🔥 Active Trades ({data.active_trades.length})</h2>

<div className="trades-grid">

{data.active_trades.map((t,i)=>(

<div key={i} className="trade-card">

<div className="trade-header">

<div className="trade-symbol">{t.symbol}</div>

<div className="meta-small">{t.status}</div>

</div>


<div className="exchange-row">

<div className="exchange-box">

<div className="title">
LONG ({t.exchange_long?.exchange})
</div>

<div className="kv">
<span>Entry</span>
<span>{t.exchange_long?.static?.entry_price}</span>
</div>

<div className="kv">
<span>Mark</span>
<span>{t.exchange_long?.dynamic?.mark_price}</span>
</div>

</div>


<div className="exchange-box">

<div className="title">
SHORT ({t.exchange_short?.exchange})
</div>

<div className="kv">
<span>Entry</span>
<span>{t.exchange_short?.static?.entry_price}</span>
</div>

<div className="kv">
<span>Mark</span>
<span>{t.exchange_short?.dynamic?.mark_price}</span>
</div>

</div>

</div>


<div className="combined-box">

<div className="kv">

<span>Total PnL</span>

<span>
{t.combined?.dynamic?.total_unrealized_pnl}
</span>

</div>

</div>

</div>

))}

</div>

</section>



{/* CLOSED TRADES */}

<section className="section">

<h2>✅ Closed Trades ({data.closed_trades.length})</h2>

<table className="mini-table">

<thead>

<tr>
<th>Symbol</th>
<th>PnL</th>
<th>Fees</th>
<th>Exit</th>
</tr>

</thead>

<tbody>

{[...data.closed_trades].reverse().map((t,i)=>(

<tr key={i}>

<td>{t.symbol}</td>
<td>{t.realized_pnl}</td>
<td>{t.total_fees}</td>
<td>{t.exit_reason}</td>

</tr>

))}

</tbody>

</table>

</section>



{/* OPPORTUNITIES */}

<section className="section">

<h2>📊 Opportunities ({data.opportunities.length})</h2>

<table className="mini-table">

<thead>

<tr>
<th>Symbol</th>
<th>Funding Diff</th>
<th>Ku Mark</th>
<th>Bb Mark</th>
</tr>

</thead>

<tbody>

{data.opportunities.slice(0,50).map((o,i)=>(

<tr key={i}>

<td>{o.symbol}</td>
<td>{o.funding_diff}</td>
<td>{o.ku_mark}</td>
<td>{o.bb_mark}</td>

</tr>

))}

</tbody>

</table>

</section>

</div>

);

}
