import "./Navbar.css";
import { Link } from "react-router-dom";

function Navbar() {
  return (
    <nav className="navbar">

      {/* Logo */}
      <div className="logo">

        <div className="logo-icon">
          T
        </div>

        <Link to="/" className="logo-text">
          Tradict AI
        </Link>

      </div>

      {/* Navigation Links */}
      <ul className="nav-links">

        <li>
          <Link to="/">Home</Link>
        </li>

        <li>
          <Link to="/public">Trading Bots</Link>
        </li>

        <li>
          <Link to="/api">API Access</Link>
        </li>

        <li>
          <Link to="/docs">Documentation</Link>
        </li>

      </ul>

      {/* Buttons */}
      <div className="nav-buttons">

        <button className="login-btn">
          Login
        </button>

        <button className="start-btn">
          Start Trading
        </button>

      </div>

    </nav>
  );
}

export default Navbar;
