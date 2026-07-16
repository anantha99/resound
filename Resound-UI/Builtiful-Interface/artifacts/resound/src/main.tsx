import { createRoot } from "react-dom/client";
import { setBaseUrl, setOrganization } from "@workspace/api-client-react";
import App from "./App";
import "./index.css";

setBaseUrl(import.meta.env.VITE_API_BASE_URL || null);
setOrganization(import.meta.env.VITE_RESOUND_ORGANIZATION || null);

createRoot(document.getElementById("root")!).render(<App />);
