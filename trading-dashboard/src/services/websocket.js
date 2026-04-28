import { useEffect, useState } from "react";

export default function useWebSocket(){

  const [data, setData] = useState({
    entry_allowed: false,
    active_trades: [],
    closed_trades: [],
    opportunities: [],
    balances: {},
    metrics: {},
    runtime_config: {}
  });

  useEffect(()=>{

    const ws = new WebSocket("ws://localhost:8000/ws");

    ws.onopen = () => {
      console.log("WebSocket connected");
    };

    ws.onmessage = (event)=>{
      const parsed = JSON.parse(event.data);
      setData(parsed);
    };

    ws.onerror = (err)=>{
      console.log("WebSocket error",err);
    };

    ws.onclose = ()=>{
      console.log("WebSocket closed");
    };

    return ()=> ws.close();

  },[]);

  return data;
}
