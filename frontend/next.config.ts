import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  cacheComponents: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  // NOTE: no rewrites() proxy on purpose. The Next dev rewrite proxy kills
  // upstream requests slower than ~30s with HTTP 500, which broke Full GDD
  // (~50s) and sometimes image generation. The browser calls the backend
  // directly (see .env.local) and FastAPI CORS covers localhost:3000.
};

export default nextConfig;
