/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // The design-system package ships TypeScript source rather than a build step.
  transpilePackages: ["@artrestore/ui", "@artrestore/types"],
  poweredByHeader: false,
  typescript: { ignoreBuildErrors: false },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Frame-Options", value: "DENY" },
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=(), interest-cohort=()",
          },
        ],
      },
    ];
  },
};

export default nextConfig;
