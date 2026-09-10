import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactCompiler: true,

  // This app lives inside a larger project directory, and there is an unrelated
  // package-lock.json further up the tree. Pin the workspace root so Turbopack
  // does not go looking for it.
  turbopack: { root: path.resolve(__dirname) },

  images: {
    remotePatterns: [{ protocol: "https", hostname: "*.supabase.co" }],
  },
};

export default nextConfig;
