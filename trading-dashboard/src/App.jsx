import Navbar from "./components/Navbar/Navbar";
import Footer from "./components/Footer/Footer";

import Home from "./pages/Home/Home";
import Connect from "./pages/Connect/connect.jsx";
import Dashboard from "./pages/Dashboard/Dashboard";
import Docs from "./pages/Docs/Docs";
import PublicData from "./pages/Livedata/PublicData";

import { BrowserRouter, Routes, Route } from "react-router-dom";

function App() {
  return (
    <BrowserRouter>

      <Navbar />

      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/connect" element={<Connect />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/docs" element={<Docs />} />
        <Route path="/public" element={<PublicData/>} />
      </Routes>

      <Footer />

    </BrowserRouter>
  );
}

export default App;
