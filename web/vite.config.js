import { defineConfig } from "vite";

export default defineConfig({
  base: "./",
  build: {
    target: "es2022", // main.js usa top-level await
  },
});
