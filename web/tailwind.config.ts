import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        paper: "#F7F5EF",
        surface: "#FFFFFF",
        ink: "#1C1B18",
        subtle: "#6E6A61",
        faint: "#9A958A",
        hairline: "#E9E5DC",
        accent: { DEFAULT: "#0F7A66", ink: "#0B5C4B", soft: "#E6F1EC" },
        live: { DEFAULT: "#B26A09", soft: "#FBF0DC" },
        danger: { DEFAULT: "#B23A3A", soft: "#F8E9E6" },
      },
      fontFamily: {
        serif: ['"Fraunces"', "ui-serif", "Georgia", "serif"],
        sans: ['"Hanken Grotesk"', "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        mono: ['"IBM Plex Mono"', "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      boxShadow: {
        soft: "0 1px 2px rgba(28,27,24,0.05)",
        card: "0 1px 2px rgba(28,27,24,0.04), 0 18px 40px -28px rgba(28,27,24,0.22)",
        pop: "0 12px 32px -14px rgba(28,27,24,0.28)",
      },
      keyframes: {
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(6px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: { "fade-up": "fade-up 0.4s cubic-bezier(0.2,0.7,0.2,1) both" },
    },
  },
  plugins: [],
};

export default config;
