import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./app/App";
import { BootstrapProvider } from "./app/bootstrap";
import "./styles.css";
import "./styles.day.css";
import "./styles.chat.css";
import "./styles.training.css";

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } } });

const root = document.getElementById("root");
if (root) {
  createRoot(root).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <BootstrapProvider fallback={<div className="boot-skeleton" aria-busy="true" />}>
          <App />
        </BootstrapProvider>
      </QueryClientProvider>
    </StrictMode>,
  );
}
