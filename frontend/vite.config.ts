import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Le proxy /api → back-end évite toute configuration CORS en développement.
//
// Le défaut vise `localhost` : c'est le cas du développement hors conteneur,
// et un défaut qui échoue en silence coûte plus cher qu'un défaut explicite.
// L'ancien défaut `http://api:8000` était le nom du service compose : hors
// Docker ce nom ne résout pas, chaque appel /api échouait et l'interface
// restait vide sans rien dire. La pile compose passe désormais `API_URL`
// explicitement (voir docker-compose.yml), donc les deux chemins sont câblés.
const API_URL = process.env.API_URL ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: Number(process.env.WEB_PORT ?? 5173),
    proxy: { "/api": { target: API_URL, changeOrigin: true } },
  },
});
