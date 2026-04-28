import { useEffect, useState, useMemo, useRef } from "react";
import "./PublicData.css";

const PAGE_SIZE = 20;

export default function PublicData(){

  const [data,setData] = useState({});
  const [page,setPage] = useState(1);
  const [selected,setSelected] = useState(null);

  const canvasRef = useRef(null);
  const historyRef = useRef({});

  // ---------------- websocket ----------------

  useEffect(()=>{

    const ws = new WebSocket("ws://localhost:8000/ws/public");

    ws.onopen = ()=> console.log("WS connected");

    ws.onmessage = (event)=>{

      const live = JSON.parse(event.data);
      setData(live);

      Object.entries(live).forEach(([symbol,info])=>{

        const bb = info?.bybit;
        const ku = info?.kucoin;

        if(!bb || !ku) return;

        const bb_mark = bb?.mark_price?.value;
        const ku_mark = ku?.mark_price?.value;

        if(!bb_mark || !ku_mark) return;

        const price = (bb_mark + ku_mark) / 2;

        if(!historyRef.current[symbol]){
          historyRef.current[symbol] = [];
        }

        historyRef.current[symbol].push(price);

        if(historyRef.current[symbol].length > 200){
          historyRef.current[symbol].shift();
        }

      });

    };

    return ()=> ws.close();

  },[]);

  // ---------------- processed list ----------------

  const processed = useMemo(()=>{

    const rows = [];

    Object.entries(data).forEach(([symbol,info])=>{

      const bb = info?.bybit;
      const ku = info?.kucoin;

      if(!bb || !ku) return;

      const bb_mark = bb?.mark_price?.value;
      const ku_mark = ku?.mark_price?.value;

      const bb_funding = bb?.funding_rate_decimal?.value;
      const ku_funding = ku?.funding_rate_decimal?.value;

      const diff = Math.abs((bb_funding||0)-(ku_funding||0));

      const divergence =
        (bb_mark && ku_mark)
        ? Math.abs(bb_mark-ku_mark)/((bb_mark+ku_mark)/2)
        : 0;

      rows.push({
        symbol,
        bb_mark,
        ku_mark,
        diff,
        divergence
      });

    });

    rows.sort((a,b)=> b.diff-a.diff);

    return rows;

  },[data]);

  // ---------------- pagination ----------------

  const totalPages = Math.ceil(processed.length / PAGE_SIZE);

  const pageRows = processed.slice(
    (page-1)*PAGE_SIZE,
    page*PAGE_SIZE
  );

  // ---------------- draw chart ----------------

  useEffect(()=>{

  if(!selected) return;

  const canvas = canvasRef.current;
  if(!canvas) return;

  const ctx = canvas.getContext("2d");

  const prices = historyRef.current[selected] || [];

  ctx.clearRect(0,0,canvas.width,canvas.height);

  if(prices.length === 0) return;

  const max = Math.max(...prices);
  const min = Math.min(...prices);

  const stepX = canvas.width / prices.length;

  ctx.beginPath();
  ctx.strokeStyle = "#22c55e";
  ctx.lineWidth = 2;

  prices.forEach((price,i)=>{

    const x = i * stepX;

    const y =
      canvas.height -
      ((price-min)/(max-min || 1)) * canvas.height;

    if(i===0){
      ctx.moveTo(x,y);
    }else{
      ctx.lineTo(x,y);
    }

  });

  ctx.stroke();

},[selected,data]);


  return(

    <div className="public-wrap">

      <h1>Public Market Dashboard</h1>

      <div className="stats">
        <div>Total Symbols: {Object.keys(data).length}</div>
        <div>Valid Symbols: {processed.length}</div>
        <div>Page: {page}/{totalPages}</div>
      </div>

      <table className="market-table">

        <thead>
          <tr>
            <th>Symbol</th>
            <th>Bybit</th>
            <th>Kucoin</th>
            <th>Funding Diff</th>
            <th>Divergence</th>
          </tr>
        </thead>

        <tbody>

          {pageRows.map(row=>(
            <tr
              key={row.symbol}
              onClick={()=>setSelected(row.symbol)}
            >
              <td>{row.symbol}</td>
              <td>{row.bb_mark?.toFixed(2)}</td>
              <td>{row.ku_mark?.toFixed(2)}</td>
              <td>{row.diff.toFixed(6)}</td>
              <td>{row.divergence.toFixed(6)}</td>
            </tr>
          ))}

        </tbody>

      </table>

      <div className="pagination">

        <button
          disabled={page===1}
          onClick={()=>setPage(p=>p-1)}
        >
          Prev
        </button>

        <button
          disabled={page===totalPages}
          onClick={()=>setPage(p=>p+1)}
        >
          Next
        </button>

      </div>

      {selected && (

        <div className="chart-panel">

          <h2>{selected} Chart</h2>

          <canvas
            ref={canvasRef}
            width="900"
            height="400"
            className="chart-container"
          />

        </div>

      )}

    </div>

  );

}
