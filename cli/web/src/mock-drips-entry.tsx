import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import "./index.css";
import { I18nProvider } from "./i18n";
import { ThemeProvider } from "./themes";
import { RealEstateDripsPage } from "./pages/real-estate-hub/drips";

const theme = new URLSearchParams(window.location.search).get("theme") || "dark";
document.documentElement.setAttribute("data-app-theme", theme);

createRoot(document.getElementById("root")!).render(
  <BrowserRouter>
    <I18nProvider>
      <ThemeProvider>
        <div className="min-h-screen bg-background text-foreground">
          <RealEstateDripsPage />
        </div>
      </ThemeProvider>
    </I18nProvider>
  </BrowserRouter>,
);
