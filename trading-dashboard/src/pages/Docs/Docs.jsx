import "./Docs.css";

function Docs() {
  return (
    <div className="docs">

      <div className="docs-container">

        <h1 className="docs-title">
          Tradict AI Documentation
        </h1>

        <p className="docs-subtitle">
          Tradict AI is an automated trading system designed to capture 
          funding fee opportunities and build cross-exchange hedge positions.
        </p>

        {/* Platform Overview */}

        <section className="docs-section">

          <h2>Platform Overview</h2>

          <p>
            Tradict AI connects multiple exchanges and automatically builds 
            hedge positions between them. The system focuses on capturing 
            funding fee opportunities while minimizing market risk through 
            cross-exchange hedging strategies.
          </p>

        </section>

        {/* Exchanges */}

        <section className="docs-section">

          <h2>Supported Exchanges</h2>

          <div className="docs-cards">

            <div className="doc-card">
              <h3>KuCoin</h3>
              <p>
                Tradict AI connects with your KuCoin account using secure API keys
                to execute hedging positions.
              </p>
            </div>

            <div className="doc-card">
              <h3>Bybit</h3>
              <p>
                Bybit is used as the second exchange to create cross-exchange hedge
                strategies and funding fee capture.
              </p>
            </div>

          </div>

        </section>

        {/* Strategy */}

        <section className="docs-section">

          <h2>Hedging Strategy</h2>

          <p>
            Tradict AI monitors funding rates and market conditions in real time. 
            When an opportunity appears, the system automatically creates hedge 
            positions across exchanges to reduce directional risk.
          </p>

          <ul className="docs-list">
            <li>Detect funding fee opportunities</li>
            <li>Create cross-exchange hedge positions</li>
            <li>Reduce directional market risk</li>
            <li>Protect capital before generating profit</li>
          </ul>

        </section>

        {/* Live Data */}

        <section className="docs-section">

          <h2>Live Market Data</h2>

          <p>
            The platform tracks live market data through WebSocket connections.
            This allows the system to monitor price movements, funding rates,
            and order book updates in real time.
          </p>

          <div className="code-block">
<pre>
{`ws://localhost:8000/ws

const ws = new WebSocket("ws://localhost:8000/ws")

ws.onmessage = (event) => {
 console.log(event.data)
}`}
</pre>
          </div>

        </section>

        {/* Account Setup */}

        <section className="docs-section">

          <h2>Account Setup</h2>

          <p>
            To start using Tradict AI you need to connect your exchange accounts
            using private API keys.
          </p>

          <ul className="docs-list">
            <li>Create API keys on KuCoin and Bybit</li>
            <li>Add both API keys to the Tradict AI dashboard</li>
            <li>Enable trading permissions for the keys</li>
            <li>Activate the trading bot from the dashboard</li>
          </ul>

        </section>

        {/* Trading Process */}

        <section className="docs-section">

          <h2>Trading Process</h2>

          <p>
            Once both exchange accounts are connected and the trading bot is 
            enabled, Tradict AI begins monitoring the market continuously.
          </p>

          <ul className="docs-list">
            <li>Live market data is streamed using WebSocket</li>
            <li>The system detects funding rate opportunities</li>
            <li>Hedge positions are created automatically</li>
            <li>Risk is reduced before profit generation</li>
          </ul>

        </section>

      </div>

    </div>
  );
}

export default Docs;