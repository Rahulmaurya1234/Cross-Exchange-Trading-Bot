import "./Home.css";
import { useNavigate } from "react-router-dom";

export default function Home() {

  const navigate = useNavigate();

  return (
    <div className="home">

      {/* HERO SECTION */}
      <section className="hero">

        <h1>Tradict AI</h1>

        <p>
          Automated cross-exchange hedge trading platform
          designed to capture funding fee opportunities
          while minimizing market risk.
        </p>

        <div className="hero-buttons">

          <button
            className="start-btn"
            onClick={() => navigate("/connect")}
          >
            Connect Exchanges
          </button>

          <button
            className="dashboard-btn"
            onClick={() => navigate("/dashboard")}
          >
            Open Dashboard
          </button>

        </div>

      </section>


      {/* FEATURES */}
      <section className="features">

        <h2>Platform Features</h2>

        <div className="feature-grid">

          <div className="feature-card">
            <h3>Funding Fee Strategy</h3>
            <p>
              Automatically capture funding rate opportunities
              across exchanges.
            </p>
          </div>

          <div className="feature-card">
            <h3>Cross Exchange Hedge</h3>
            <p>
              Hedge positions between KuCoin and Bybit to
              reduce market risk.
            </p>
          </div>

          <div className="feature-card">
            <h3>Live Market Tracking</h3>
            <p>
              Monitor live market data through WebSocket
              streams.
            </p>
          </div>

          <div className="feature-card">
            <h3>Automated Bot</h3>
            <p>
              The trading bot automatically detects funding
              opportunities and opens hedge positions.
            </p>
          </div>

        </div>

      </section>


      {/* HOW IT WORKS */}
      <section className="how">

        <h2>How It Works</h2>

        <div className="steps">

          <div className="step">
            <div className="step-number">1</div>
            <h3>Connect Exchanges</h3>
            <p>Add KuCoin and Bybit API keys.</p>
          </div>

          <div className="step">
            <div className="step-number">2</div>
            <h3>Start Trading Bot</h3>
            <p>The system monitors funding rates automatically.</p>
          </div>

          <div className="step">
            <div className="step-number">3</div>
            <h3>Hedge Positions</h3>
            <p>Bot creates cross-exchange hedge positions.</p>
          </div>

          <div className="step">
            <div className="step-number">4</div>
            <h3>Earn Funding Fees</h3>
            <p>Profit from funding rate differences.</p>
          </div>

        </div>

      </section>

    </div>
  );
}
