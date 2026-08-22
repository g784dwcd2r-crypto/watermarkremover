"use client";

import { TooltipProvider } from "@artrestore/ui";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import * as React from "react";

import { ApiError } from "@/lib/api";

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = React.useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 20_000,
            refetchOnWindowFocus: false,
            retry: (failureCount, error) => {
              // Never retry an auth or validation failure; it will not improve.
              if (error instanceof ApiError && error.status < 500) return false;
              return failureCount < 2;
            },
          },
          mutations: { retry: false },
        },
      }),
  );

  return (
    <QueryClientProvider client={client}>
      <TooltipProvider delayDuration={250}>{children}</TooltipProvider>
    </QueryClientProvider>
  );
}
