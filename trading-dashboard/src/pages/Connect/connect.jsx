import { useState } from "react"
import "./Connect.css"

export default function Connect(){

const [form,setForm] = useState({

kucoin_key:"",
kucoin_secret:"",
kucoin_passphrase:"",

bybit_key:"",
bybit_secret:""

})

function handleChange(e){

setForm({
...form,
[e.target.name]:e.target.value
})

}

async function handleSubmit(){

await fetch("http://localhost:8000/save-keys",{

method:"POST",

headers:{
"Content-Type":"application/json"
},

body:JSON.stringify(form)

})

alert("API Keys Saved")

}

return(

<div className="connect">

<h1>Connect Exchanges</h1>

<div className="form">

<h2>KuCoin</h2>

<input
name="kucoin_key"
placeholder="KuCoin API Key"
onChange={handleChange}
/>

<input
name="kucoin_secret"
placeholder="KuCoin API Secret"
onChange={handleChange}
/>

<input
name="kucoin_passphrase"
placeholder="KuCoin Passphrase"
onChange={handleChange}
/>

<h2>Bybit</h2>

<input
name="bybit_key"
placeholder="Bybit API Key"
onChange={handleChange}
/>

<input
name="bybit_secret"
placeholder="Bybit API Secret"
onChange={handleChange}
/>

<button onClick={handleSubmit}>
Save & Start Bot
</button>

</div>

</div>

)

}