import { Switch, Route, Router as WouterRouter } from "wouter";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "@/components/ui/toaster";
import { TooltipProvider } from "@/components/ui/tooltip";
import { BrandProvider } from "@/context/BrandContext";
import NotFound from "@/pages/not-found";
import DashboardPage from "@/pages/dashboard";
import SignalsPage from "@/pages/signals";
import SignalDetailPage from "@/pages/signal-detail";
import MemoryPage from "@/pages/memory";
import PatternsPage from "@/pages/patterns";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
      refetchOnWindowFocus: false,
    },
  },
});

function Router() {
  return (
    <Switch>
      <Route path="/" component={DashboardPage} />
      <Route path="/signals" component={SignalsPage} />
      <Route path="/signals/:signalId" component={SignalDetailPage} />
      <Route path="/memory" component={MemoryPage} />
      <Route path="/patterns" component={PatternsPage} />
      <Route component={NotFound} />
    </Switch>
  );
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <BrandProvider>
          <WouterRouter base={import.meta.env.BASE_URL.replace(/\/$/, "")}>
            <Router />
          </WouterRouter>
        </BrandProvider>
        <Toaster />
      </TooltipProvider>
    </QueryClientProvider>
  );
}

export default App;
