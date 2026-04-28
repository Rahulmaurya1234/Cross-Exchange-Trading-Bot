export default function Header({entry}){

  return(

    <header>

      <h1>🚀 Trading Control Center</h1>

      <div className="controls">

        <div className={entry ? "status enabled" : "status disabled"}>
          {entry ? "ENABLED" : "DISABLED"}
        </div>

        <button className="btn">Toggle Entry</button>

        <button className="btn secondary">Settings</button>

        <button className="btn danger">Kill All</button>

      </div>

    </header>

  )

}
